from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
import redis.asyncio as redis
from openai import AsyncOpenAI

from app.config import Settings

LOGGER = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.pg_pool: asyncpg.Pool | None = None
        self.redis: redis.Redis | None = None
        self.vector_enabled = False
        self.initialized = False

    async def connect(self) -> None:
        if self.initialized:
            return
        if not self.settings.memory_enabled:
            self.initialized = True
            LOGGER.info("Memory store disabled by MEMORY_ENABLED=false")
            return

        if self.settings.database_url:
            self.pg_pool = await asyncpg.create_pool(self.settings.database_url, min_size=1, max_size=5)
            await self._init_schema()

        if self.settings.redis_url:
            self.redis = redis.from_url(self.settings.redis_url, decode_responses=True)

        self.initialized = True
        LOGGER.info(
            "Memory store initialized: postgres=%s redis=%s vector=%s",
            bool(self.pg_pool),
            bool(self.redis),
            self.vector_enabled,
        )

    async def _init_schema(self) -> None:
        assert self.pg_pool is not None
        async with self.pg_pool.acquire() as conn:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                self.vector_enabled = True
            except Exception:
                self.vector_enabled = False
                LOGGER.warning("pgvector extension not available; semantic memory disabled")

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_turns (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            if self.vector_enabled:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_facts (
                        id BIGSERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        fact_text TEXT NOT NULL,
                        embedding vector(1536) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_facts_user_id
                    ON memory_facts(user_id);
                    """
                )

    async def remember_turn(self, user_id: int, role: str, content: str) -> None:
        if not self.settings.memory_enabled:
            return
        if not content.strip():
            return

        clipped = content.strip()[:2000]

        if self.redis:
            key = f"mem:recent:{user_id}"
            payload = json.dumps({"role": role, "content": clipped})
            await self.redis.lpush(key, payload)
            await self.redis.ltrim(key, 0, max(self.settings.memory_recent_turns - 1, 0))
            await self.redis.expire(key, 60 * 60 * 72)

        if self.pg_pool:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO memory_turns(user_id, role, content) VALUES($1, $2, $3)",
                    user_id,
                    role,
                    clipped,
                )

    async def remember_fact(self, user_id: int, fact_text: str) -> None:
        if not self.settings.memory_enabled or not self.vector_enabled or not self.pg_pool:
            return
        text = fact_text.strip()
        if len(text) < 20:
            return

        vector = await self._embed(text)
        if not vector:
            return

        async with self.pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO memory_facts(user_id, fact_text, embedding) VALUES($1, $2, $3::vector)",
                user_id,
                text[:2000],
                vector,
            )

    async def get_context(self, user_id: int, query: str) -> dict[str, list[str]]:
        recent: list[str] = []
        semantic: list[str] = []

        if self.redis:
            items = await self.redis.lrange(f"mem:recent:{user_id}", 0, self.settings.memory_recent_turns - 1)
            for raw in reversed(items):
                item = json.loads(raw)
                recent.append(f"{item.get('role', 'unknown')}: {item.get('content', '')}")
        elif self.pg_pool:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT role, content
                    FROM memory_turns
                    WHERE user_id = $1
                    ORDER BY id DESC
                    LIMIT $2
                    """,
                    user_id,
                    self.settings.memory_recent_turns,
                )
                for row in reversed(rows):
                    recent.append(f"{row['role']}: {row['content']}")

        if self.vector_enabled and self.pg_pool and query.strip():
            q_vector = await self._embed(query.strip()[:4000])
            if q_vector:
                async with self.pg_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT fact_text
                        FROM memory_facts
                        WHERE user_id = $1
                        ORDER BY embedding <=> $2::vector
                        LIMIT $3
                        """,
                        user_id,
                        q_vector,
                        self.settings.memory_semantic_k,
                    )
                    semantic = [row["fact_text"] for row in rows]

        return {"recent": recent, "semantic": semantic}

    async def _embed(self, text: str) -> str | None:
        try:
            response = await self.openai.embeddings.create(
                model=self.settings.memory_embed_model,
                input=text,
            )
            vector = response.data[0].embedding
            return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"
        except Exception as exc:
            LOGGER.warning("Embedding failed: %s", exc)
            return None

    @staticmethod
    def format_context(memory: dict[str, list[str]]) -> str:
        recent = memory.get("recent", [])
        semantic = memory.get("semantic", [])
        blocks: list[str] = []
        if recent:
            blocks.append("Краткая история диалога:\n" + "\n".join(f"- {x}" for x in recent[-12:]))
        if semantic:
            blocks.append("Долгосрочная релевантная память:\n" + "\n".join(f"- {x}" for x in semantic[:8]))
        return "\n\n".join(blocks)
