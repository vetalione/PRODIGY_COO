from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_id: int | None
    openai_api_key: str
    openai_model: str
    notion_token: str
    notion_parent_page_id: str
    notion_access_phrase: str | None
    notion_workspace_page_id: str | None
    notion_tasks_db_id: str | None
    notion_projects_db_id: str | None


def load_settings() -> Settings:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    notion_parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID", "").replace("-", "").strip()

    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    if not notion_token:
        raise ValueError("NOTION_TOKEN is required")
    if not notion_parent_page_id:
        raise ValueError("NOTION_PARENT_PAGE_ID is required")

    allowed_user_raw = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    allowed_user = int(allowed_user_raw) if allowed_user_raw else None

    return Settings(
        telegram_bot_token=telegram_bot_token,
        telegram_allowed_user_id=allowed_user,
        openai_api_key=openai_api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.3").strip(),
        notion_token=notion_token,
        notion_parent_page_id=notion_parent_page_id,
        notion_access_phrase=(os.getenv("NOTION_ACCESS_PHRASE", "").strip() or None),
        notion_workspace_page_id=(os.getenv("NOTION_WORKSPACE_PAGE_ID", "").replace("-", "").strip() or None),
        notion_tasks_db_id=(os.getenv("NOTION_TASKS_DB_ID", "").replace("-", "").strip() or None),
        notion_projects_db_id=(os.getenv("NOTION_PROJECTS_DB_ID", "").replace("-", "").strip() or None),
    )
