from __future__ import annotations

import logging
from typing import Any
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
        self.pending_actions: dict[int, dict[str, Any]] = {}
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
        app.add_handler(CommandHandler("myid", self.my_id))
        app.add_handler(CommandHandler("unlock", self.unlock))
        app.add_handler(CommandHandler("setup", self.setup))
        app.add_handler(CommandHandler("focus", self.focus))
        app.add_handler(CommandHandler("newtask", self.new_task))
        app.add_handler(CommandHandler("newproject", self.new_project))
        app.add_handler(CommandHandler("approve", self.approve))
        app.add_handler(CommandHandler("reject", self.reject))
        app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        return app

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        user_id = update.effective_user.id if update.effective_user else 0
        username = (update.effective_user.username or "") if update.effective_user else ""
        await update.message.reply_text(
            "COO агент активен.\n"
            f"Твой user_id: {user_id}\n"
            f"Твой username: @{username}\n"
            "Команды: /myid, /setup, /focus, /newtask <текст>, /newproject <название>, /approve, /reject."
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        await update.message.reply_text(
            "Я веду систему FOCUS LOCK.\n"
            "ID: /myid\n"
            "0) /unlock <секретная фраза> — открыть доступ к Notion\n"
            "1) /setup — создать рабочее пространство в Notion\n"
            "2) /newtask Текст — добавить задачу\n"
            "3) /newproject Название — добавить проект\n"
            "4) /focus — текущий срез по задачам и проектам\n"
            "5) Голосовое/текст — дам COO-ответ и предложу изменения в Notion\n"
            "6) /approve — применить предложенные изменения\n"
            "7) /reject — отклонить предложенные изменения"
        )

    async def my_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        user_id = update.effective_user.id if update.effective_user else 0
        username = (update.effective_user.username or "") if update.effective_user else ""
        await update.message.reply_text(
            f"Твой TELEGRAM_ALLOWED_USER_ID: {user_id}\n"
            f"Твой TELEGRAM_ALLOWED_USERNAME: @{username}"
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

        await self._process_user_input(update, text)

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not update.message or not update.message.voice:
            return

        await update.message.reply_text("Принял голосовое. Распознаю...")
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = bytes(await file.download_as_bytearray())
        transcript = await self.agent.transcribe_voice(audio_bytes, filename="voice.ogg")
        if not transcript:
            await update.message.reply_text("Не удалось распознать голосовое. Попробуй ещё раз.")
            return

        await update.message.reply_text(f"Распознал: {transcript[:800]}")
        await self._process_user_input(update, transcript)

    async def approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        if not await self._guard_notion_access(update):
            return

        user_id = update.effective_user.id if update.effective_user else 0
        pending = self.pending_actions.get(user_id)
        if not pending:
            await update.message.reply_text("Нет предложенных изменений для применения.")
            return

        action_logs: list[str] = []
        for action in pending.get("actions", []):
            if not isinstance(action, dict):
                continue
            try:
                result = await self.notion.execute_action(action)
                action_logs.append(result)
            except Exception as exc:
                LOGGER.exception("Failed Notion action on approve: %s", action)
                action_logs.append(f"Ошибка изменения Notion: {exc}")

        self.pending_actions.pop(user_id, None)
        if action_logs:
            await update.message.reply_text(
                "Применил изменения в Notion:\n" + "\n".join(f"- {x}" for x in action_logs[:12])
            )
        else:
            await update.message.reply_text("Изменений не применено.")

    async def reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard_user(update):
            return
        user_id = update.effective_user.id if update.effective_user else 0
        had_plan = user_id in self.pending_actions
        self.pending_actions.pop(user_id, None)
        if had_plan:
            await update.message.reply_text("Ок, изменения в Notion отклонены.")
        else:
            await update.message.reply_text("Нет активного плана для отклонения.")

    async def _process_user_input(self, update: Update, user_text: str) -> None:
        notion_allowed = not self.settings.notion_access_phrase or (
            update.effective_user and update.effective_user.id in self.notion_unlocked_users
        )

        if notion_allowed:
            snapshot = await self.notion.get_focus_snapshot()
        else:
            snapshot = "Notion недоступен: пользователь не прошёл /unlock."

        plan = await self.agent.reply_with_plan(
            user_text=user_text,
            notion_snapshot=snapshot,
            allow_notion_actions=notion_allowed,
        )

        answer = str(plan.get("reply", "")).strip() or "Не удалось сформировать ответ."
        actions = [a for a in plan.get("actions", []) if isinstance(a, dict)]
        user_id = update.effective_user.id if update.effective_user else 0

        if actions:
            self.pending_actions[user_id] = {"actions": actions, "reply": answer}
            actions_text = self._format_actions(actions)
            msg = (
                f"{answer}\n\n"
                "План изменений в Notion (ожидает подтверждения):\n"
                f"{actions_text}\n\n"
                "Подтверди /approve или отмени /reject"
            )
            await update.message.reply_text(msg[:4000])
            return

        await update.message.reply_text(answer[:4000])

    def _format_actions(self, actions: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, action in enumerate(actions, start=1):
            action_type = str(action.get("type", "unknown"))
            if action_type == "add_task":
                lines.append(
                    f"{idx}. add_task: {action.get('title', '')} | project={action.get('project', 'General')} | priority={action.get('priority', 'Medium')}"
                )
            elif action_type == "add_project":
                lines.append(
                    f"{idx}. add_project: {action.get('name', '')} | status={action.get('status', 'Experiment')}"
                )
            elif action_type == "update_task_status":
                lines.append(
                    f"{idx}. update_task_status: {action.get('title', '')} -> {action.get('status', 'Todo')}"
                )
            elif action_type == "update_project_status":
                lines.append(
                    f"{idx}. update_project_status: {action.get('name', '')} -> {action.get('status', 'Paused')}"
                )
            else:
                lines.append(f"{idx}. unknown_action: {action}")
        return "\n".join(lines)

    async def _guard_user(self, update: Update) -> bool:
        user_id = update.effective_user.id if update.effective_user else None
        username = (update.effective_user.username or "").lower() if update.effective_user else ""

        checks: list[bool] = []
        if self.settings.telegram_allowed_user_id is not None:
            checks.append(user_id == self.settings.telegram_allowed_user_id)
        if self.settings.telegram_allowed_username is not None:
            checks.append(username == self.settings.telegram_allowed_username)

        if checks and not any(checks):
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
