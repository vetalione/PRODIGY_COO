from __future__ import annotations

import logging
from typing import Final

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.agent import CoAgent
from app.config import Settings
from app.notion_service import NotionService

LOGGER: Final = logging.getLogger(__name__)


class TelegramCooBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.notion_unlocked_users: set[int] = set()
        self.notion = NotionService(
            token=settings.notion_token,
            parent_page_id=settings.notion_parent_page_id,
            workspace_page_id=settings.notion_workspace_page_id,
            tasks_db_id=settings.notion_tasks_db_id,
            projects_db_id=settings.notion_projects_db_id,
        )
        self.agent = CoAgent(api_key=settings.openai_api_key, model=settings.openai_model)

    def build_app(self) -> Application:
        app = Application.builder().token(self.settings.telegram_bot_token).build()

        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help))
        app.add_handler(CommandHandler("unlock", self.unlock))
        app.add_handler(CommandHandler("setup", self.setup))
        app.add_handler(CommandHandler("focus", self.focus))
        app.add_handler(CommandHandler("newtask", self.new_task))
        app.add_handler(CommandHandler("newproject", self.new_project))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        return app

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        await update.message.reply_text(
            "COO агент активен. Команды: /setup, /focus, /newtask <текст>, /newproject <название>."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        await update.message.reply_text(
            "Я веду систему FOCUS LOCK.\n"
            "0) /unlock <секретная фраза> — открыть доступ к Notion\n"
            "1) /setup — создать рабочее пространство в Notion\n"
            "2) /newtask Текст — добавить задачу\n"
            "3) /newproject Название — добавить проект\n"
            "4) /focus — текущий срез по задачам и проектам\n"
            "5) Просто напиши сообщение — дам структурное COO-решение"
        )

    async def unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        user_id = update.effective_user.id if update.effective_user else 0

        if not self.settings.notion_access_phrase:
            self.notion_unlocked_users.add(user_id)
            await update.message.reply_text("Доступ к Notion открыт (фраза не задана в env).")
            return

        phrase = " ".join(context.args).strip()
        if phrase and phrase == self.settings.notion_access_phrase:
            self.notion_unlocked_users.add(user_id)
            await update.message.reply_text("Доступ к Notion открыт.")
            return
        await update.message.reply_text("Неверная фраза.")

    async def setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not await self._guard_notion_access(update):
            return
        ids = await self.notion.ensure_workspace()
        await update.message.reply_text(
            "Готово. Workspace в Notion подготовлен.\n"
            f"WORKSPACE_PAGE_ID={ids.workspace_page_id}\n"
            f"TASKS_DB_ID={ids.tasks_db_id}\n"
            f"PROJECTS_DB_ID={ids.projects_db_id}"
        )

    async def focus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not await self._guard_notion_access(update):
            return
        snapshot = await self.notion.get_focus_snapshot()
        await update.message.reply_text(snapshot)

    async def new_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not await self._guard_notion_access(update):
            return
        text = " ".join(context.args).strip()
        if not text:
            await update.message.reply_text("Использование: /newtask <текст задачи>")
            return
        task_id = await self.notion.add_task(text=text)
        await update.message.reply_text(f"Задача добавлена в Notion. ID: {task_id}")

    async def new_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not await self._guard_notion_access(update):
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text("Использование: /newproject <название проекта>")
            return
        project_id = await self.notion.add_project(name=name)
        await update.message.reply_text(f"Проект добавлен в Notion. ID: {project_id}")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return

        text = (update.message.text or "").strip()

        if text.lower().startswith("задача:"):
            if not await self._guard_notion_access(update):
                return
            task_text = text.split(":", 1)[1].strip()
            if task_text:
                task_id = await self.notion.add_task(task_text)
                await update.message.reply_text(f"Сохранил задачу в Notion. ID: {task_id}")
                return

        if self.settings.notion_access_phrase and (update.effective_user.id not in self.notion_unlocked_users):
            snapshot = "Notion недоступен: пользователь не прошёл /unlock."
        else:
            snapshot = await self.notion.get_focus_snapshot()
        answer = await self.agent.reply(user_text=text, notion_snapshot=snapshot)
        await update.message.reply_text(answer[:4000])

    async def _guard_user(self, update: Update) -> bool:
        user_id = update.effective_user.id if update.effective_user else None
        if self.settings.telegram_allowed_user_id and user_id != self.settings.telegram_allowed_user_id:
            LOGGER.warning("Blocked user_id=%s", user_id)
            if update.message:
                await update.message.reply_text("Доступ запрещён.")
            return False
        return True

    async def _guard_notion_access(self, update: Update) -> bool:
        if not self.settings.notion_access_phrase:
            return True
        user_id = update.effective_user.id if update.effective_user else None
        if user_id in self.notion_unlocked_users:
            return True
        if update.message:
            await update.message.reply_text("Сначала /unlock <секретная фраза>.")
        return False
