from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_id: int | None
    telegram_allowed_username: str | None
    bot_timezone: str
    openai_api_key: str
    openai_model: str
    memory_embed_model: str
    database_url: str | None
    redis_url: str | None
    memory_enabled: bool
    memory_recent_turns: int
    memory_semantic_k: int
    notion_token: str
    notion_parent_page_id: str | None
    notion_source_db_ids: list[str]
    notion_access_phrase: str | None
    notion_workspace_page_id: str | None
    notion_tasks_db_id: str | None
    notion_projects_db_id: str | None


def load_settings() -> Settings:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    notion_parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID", "").replace("-", "").strip() or None

    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    if not notion_token:
        raise ValueError("NOTION_TOKEN is required")

    allowed_user_raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    allowed_user = int(allowed_user_raw) if allowed_user_raw else None
    allowed_username = os.getenv("TELEGRAM_ALLOWED_USERNAME", "").strip().lstrip("@").lower() or None
    source_db_ids_raw = os.getenv("NOTION_SOURCE_DB_IDS", "").strip()
    source_db_ids = [x.replace("-", "").strip() for x in source_db_ids_raw.split(",") if x.strip()]

    memory_enabled_raw = os.getenv("MEMORY_ENABLED", "true").strip().lower()
    memory_enabled = memory_enabled_raw in {"1", "true", "yes", "on"}

    return Settings(
        telegram_bot_token=telegram_bot_token,
        telegram_allowed_user_id=allowed_user,
        telegram_allowed_username=allowed_username,
        bot_timezone=os.getenv("BOT_TIMEZONE", "Europe/Moscow").strip(),
        openai_api_key=openai_api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.3").strip(),
        memory_embed_model=os.getenv("MEMORY_EMBED_MODEL", "text-embedding-3-small").strip(),
        database_url=(os.getenv("DATABASE_URL", "").strip() or None),
        redis_url=(os.getenv("REDIS_URL", "").strip() or None),
        memory_enabled=memory_enabled,
        memory_recent_turns=int(os.getenv("MEMORY_RECENT_TURNS", "10").strip()),
        memory_semantic_k=int(os.getenv("MEMORY_SEMANTIC_K", "6").strip()),
        notion_token=notion_token,
        notion_parent_page_id=notion_parent_page_id,
        notion_source_db_ids=source_db_ids,
        notion_access_phrase=(os.getenv("NOTION_ACCESS_PHRASE", "").strip() or None),
        notion_workspace_page_id=(os.getenv("NOTION_WORKSPACE_PAGE_ID", "").replace("-", "").strip() or None),
        notion_tasks_db_id=(os.getenv("NOTION_TASKS_DB_ID", "").replace("-", "").strip() or None),
        notion_projects_db_id=(os.getenv("NOTION_PROJECTS_DB_ID", "").replace("-", "").strip() or None),
    )
