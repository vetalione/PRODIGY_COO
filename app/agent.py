from __future__ import annotations

from openai import AsyncOpenAI

from app.prompts import SYSTEM_PROMPT


class CoAgent:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def reply(self, user_text: str, notion_snapshot: str) -> str:
        response = await self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "system",
                    "content": f"Контекст из Notion:\n{notion_snapshot}",
                },
                {"role": "user", "content": user_text},
            ],
            temperature=0.4,
        )
        return (response.output_text or "Не удалось сформировать ответ.").strip()
