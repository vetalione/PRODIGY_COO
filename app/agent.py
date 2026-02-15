from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI, BadRequestError

from app.prompts import SYSTEM_PROMPT


LOGGER = logging.getLogger(__name__)


def _normalize_model_name(model: str) -> str:
    value = (model or "").strip()
    if value in {"gpt-5.3", "gpt-5.3-codex"}:
        return "gpt-5"
    return value or "gpt-5"


class CoAgent:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = _normalize_model_name(model)

    async def _responses_create_with_retries(
        self,
        *,
        input_messages: list[dict[str, str]],
        temperature: float,
    ):
        candidate_models: list[str] = []
        for m in [self.model, "gpt-5", "gpt-4.1-mini"]:
            normalized = _normalize_model_name(m)
            if normalized not in candidate_models:
                candidate_models.append(normalized)

        for model in candidate_models:
            params: dict[str, Any] = {
                "model": model,
                "input": input_messages,
            }
            # Для GPT-5 семейства temperature может быть недоступен/ограничен.
            if not model.startswith("gpt-5"):
                params["temperature"] = temperature

            try:
                return await self.client.responses.create(**params)
            except BadRequestError as exc:
                LOGGER.warning(
                    "OpenAI bad request for model=%s: %s",
                    model,
                    getattr(exc, "message", str(exc)),
                )
                continue
            except Exception:
                LOGGER.exception("OpenAI responses.create failed for model=%s", model)
                continue

        raise RuntimeError("No compatible OpenAI model available for responses.create")

    async def reply(self, user_text: str, notion_snapshot: str) -> str:
        try:
            response = await self._responses_create_with_retries(
                input_messages=[
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
            LOGGER.exception("Primary reply generation failed")
            return "Не удалось сформировать ответ."

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
            "Если пользователь просит план (например на 7 дней), сформируй список конкретных действий и заполни actions несколькими задачами add_task. "
            "ВАЖНО: не пиши в reply, что изменения уже внесены в Notion. До фактического применения это только предложенный план. "
            f"Разрешение на изменения в Notion: {'yes' if allow_notion_actions else 'no'}; если no, actions=[]"
        )

        try:
            response = await self._responses_create_with_retries(
                input_messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": planning_prompt},
                    {"role": "system", "content": f"Контекст из Notion:\n{notion_snapshot}"},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.2,
            )
            raw = (response.output_text or "").strip()
        except Exception:
            LOGGER.exception("Planning response generation failed")
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
