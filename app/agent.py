from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.prompts import SYSTEM_PROMPT


class CoAgent:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def reply(self, user_text: str, notion_snapshot: str) -> str:
        try:
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
        except Exception:
            fallback = await self.client.responses.create(
                model="gpt-4.1-mini",
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
            return (fallback.output_text or "Не удалось сформировать ответ.").strip()

    async def transcribe_voice(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        transcript = await self.client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=(filename, audio_bytes),
        )
        text = getattr(transcript, "text", "") or ""
        return text.strip()

    async def reply_with_plan(
        self,
        user_text: str,
        notion_snapshot: str,
        allow_notion_actions: bool,
    ) -> dict[str, Any]:
        planning_prompt = (
            "Верни строго JSON без markdown. Формат:\n"
            "{\"reply\": string, \"actions\": Action[]}\n"
            "Action поддерживает только:\n"
            "1) {\"type\":\"add_task\",\"title\":string,\"project\":string,\"priority\":\"High\"|\"Medium\"|\"Low\"}\n"
            "2) {\"type\":\"add_project\",\"name\":string,\"status\":\"Main\"|\"Support\"|\"Experiment\"|\"Paused\"|\"Done\",\"kpi\":string}\n"
            "3) {\"type\":\"update_task_status\",\"title\":string,\"status\":\"Todo\"|\"Doing\"|\"Done\"|\"Paused\"}\n"
            "4) {\"type\":\"update_project_status\",\"name\":string,\"status\":\"Main\"|\"Support\"|\"Experiment\"|\"Paused\"|\"Done\"}\n"
            "Если изменений в Notion не нужно, actions=[]. "
            f"Разрешение на изменения в Notion: {'yes' if allow_notion_actions else 'no'}; если no, actions=[]"
        )

        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": planning_prompt},
                    {"role": "system", "content": f"Контекст из Notion:\n{notion_snapshot}"},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.2,
            )
            raw = (response.output_text or "").strip()
        except Exception:
            return {"reply": await self.reply(user_text, notion_snapshot), "actions": []}
        parsed = _safe_json(raw)
        if not isinstance(parsed, dict):
            return {"reply": await self.reply(user_text, notion_snapshot), "actions": []}

        reply_text = str(parsed.get("reply", "")).strip() or "Не удалось сформировать ответ."
        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        if not allow_notion_actions:
            actions = []
        return {"reply": reply_text, "actions": actions}


def _safe_json(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except Exception:
        pass

    if "```" in raw:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except Exception:
            return None
    return None
