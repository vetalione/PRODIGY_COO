from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_client import AsyncClient
from notion_client.errors import APIResponseError


@dataclass
class NotionIds:
    workspace_page_id: str
    tasks_db_id: str
    projects_db_id: str


class NotionService:
    def __init__(
        self,
        token: str,
        parent_page_id: str | None,
        workspace_page_id: str | None = None,
        tasks_db_id: str | None = None,
        projects_db_id: str | None = None,
    ) -> None:
        self.client = AsyncClient(auth=token)
        self.parent_page_id = parent_page_id
        self.cached_ids: NotionIds | None = None
        if workspace_page_id and tasks_db_id and projects_db_id:
            self.cached_ids = NotionIds(workspace_page_id, tasks_db_id, projects_db_id)

    async def ensure_workspace(self) -> NotionIds:
        if self.cached_ids:
            return self.cached_ids

        workspace_page_id = await self._find_page_id_by_title("COO Workspace")
        if not workspace_page_id:
            page = await self._create_workspace_page()
            workspace_page_id = page["id"]

        projects_db_id = await self._find_database_id_by_title("COO Projects")
        if not projects_db_id:
            db = await self.client.databases.create(
                parent={"type": "page_id", "page_id": workspace_page_id},
                title=[{"type": "text", "text": {"content": "COO Projects"}}],
                properties={
                    "Name": {"title": {}},
                    "Status": {
                        "select": {
                            "options": [
                                {"name": "Main"},
                                {"name": "Support"},
                                {"name": "Experiment"},
                                {"name": "Paused"},
                                {"name": "Done"},
                            ]
                        }
                    },
                    "KPI": {"rich_text": {}},
                    "Notes": {"rich_text": {}},
                },
            )
            projects_db_id = db["id"]

        tasks_db_id = await self._find_database_id_by_title("COO Tasks")
        if not tasks_db_id:
            db = await self.client.databases.create(
                parent={"type": "page_id", "page_id": workspace_page_id},
                title=[{"type": "text", "text": {"content": "COO Tasks"}}],
                properties={
                    "Name": {"title": {}},
                    "Status": {
                        "select": {
                            "options": [
                                {"name": "Todo"},
                                {"name": "Doing"},
                                {"name": "Done"},
                                {"name": "Paused"},
                            ]
                        }
                    },
                    "Priority": {
                        "select": {
                            "options": [
                                {"name": "High"},
                                {"name": "Medium"},
                                {"name": "Low"},
                            ]
                        }
                    },
                    "Project": {"rich_text": {}},
                    "Energy": {
                        "select": {
                            "options": [
                                {"name": "High"},
                                {"name": "Normal"},
                                {"name": "Low"},
                            ]
                        }
                    },
                },
            )
            tasks_db_id = db["id"]

        self.cached_ids = NotionIds(
            workspace_page_id=workspace_page_id,
            tasks_db_id=tasks_db_id,
            projects_db_id=projects_db_id,
        )
        return self.cached_ids

    async def add_task(self, text: str, project: str = "", priority: str = "Medium") -> str:
        ids = await self.ensure_workspace()
        page = await self.client.pages.create(
            parent={"database_id": ids.tasks_db_id},
            properties={
                "Name": {"title": [{"type": "text", "text": {"content": text[:2000]}}]},
                "Status": {"select": {"name": "Todo"}},
                "Priority": {"select": {"name": priority}},
                "Project": {
                    "rich_text": [{"type": "text", "text": {"content": project[:1000] or "General"}}]
                },
                "Energy": {"select": {"name": "Normal"}},
            },
        )
        return page["id"]

    async def add_project(self, name: str, status: str = "Experiment", kpi: str = "") -> str:
        ids = await self.ensure_workspace()
        page = await self.client.pages.create(
            parent={"database_id": ids.projects_db_id},
            properties={
                "Name": {"title": [{"type": "text", "text": {"content": name[:2000]}}]},
                "Status": {"select": {"name": status}},
                "KPI": {"rich_text": [{"type": "text", "text": {"content": kpi[:1000]}}]},
            },
        )
        return page["id"]

    async def get_focus_snapshot(self) -> str:
        ids = await self.ensure_workspace()

        projects = await self.client.databases.query(
            database_id=ids.projects_db_id,
            filter={"property": "Status", "select": {"does_not_equal": "Done"}},
            page_size=10,
        )
        tasks = await self.client.databases.query(
            database_id=ids.tasks_db_id,
            filter={"property": "Status", "select": {"does_not_equal": "Done"}},
            page_size=12,
        )

        project_lines = []
        for item in projects.get("results", []):
            props = item.get("properties", {})
            name = _extract_title(props.get("Name", {}))
            status = ((props.get("Status", {}) or {}).get("select") or {}).get("name", "Unknown")
            project_lines.append(f"- {name} [{status}]")

        task_lines = []
        for item in tasks.get("results", []):
            props = item.get("properties", {})
            name = _extract_title(props.get("Name", {}))
            status = ((props.get("Status", {}) or {}).get("select") or {}).get("name", "?")
            prio = ((props.get("Priority", {}) or {}).get("select") or {}).get("name", "?")
            task_lines.append(f"- {name} ({status}, {prio})")

        projects_text = "\n".join(project_lines) if project_lines else "- нет активных проектов"
        tasks_text = "\n".join(task_lines) if task_lines else "- нет активных задач"

        return (
            "Текущее состояние из Notion:\n"
            f"Проекты:\n{projects_text}\n\n"
            f"Задачи:\n{tasks_text}"
        )

    async def execute_action(self, action: dict[str, Any]) -> str:
        action_type = str(action.get("type", "")).strip()
        if action_type == "add_task":
            task_id = await self.add_task(
                text=str(action.get("title", "")).strip() or "Новая задача",
                project=str(action.get("project", "")).strip(),
                priority=_safe_task_priority(str(action.get("priority", "Medium"))),
            )
            return f"Создана задача: {task_id}"

        if action_type == "add_project":
            project_id = await self.add_project(
                name=str(action.get("name", "")).strip() or "Новый проект",
                status=_safe_project_status(str(action.get("status", "Experiment"))),
                kpi=str(action.get("kpi", "")).strip(),
            )
            return f"Создан проект: {project_id}"

        if action_type == "update_task_status":
            title = str(action.get("title", "")).strip()
            status = _safe_task_status(str(action.get("status", "Todo")))
            ok = await self.update_task_status_by_name(title=title, status=status)
            return f"Статус задачи обновлён: {title} -> {status}" if ok else f"Задача не найдена: {title}"

        if action_type == "update_project_status":
            name = str(action.get("name", "")).strip()
            status = _safe_project_status(str(action.get("status", "Paused")))
            ok = await self.update_project_status_by_name(name=name, status=status)
            return f"Статус проекта обновлён: {name} -> {status}" if ok else f"Проект не найден: {name}"

        return "Пропущено: неизвестное действие"

    async def update_task_status_by_name(self, title: str, status: str) -> bool:
        if not title:
            return False
        ids = await self.ensure_workspace()
        row = await self._find_task_row_by_name(ids.tasks_db_id, title)
        if not row:
            return False
        await self.client.pages.update(
            page_id=row["id"],
            properties={"Status": {"select": {"name": status}}},
        )
        return True

    async def update_project_status_by_name(self, name: str, status: str) -> bool:
        if not name:
            return False
        ids = await self.ensure_workspace()
        row = await self._find_project_row_by_name(ids.projects_db_id, name)
        if not row:
            return False
        await self.client.pages.update(
            page_id=row["id"],
            properties={"Status": {"select": {"name": status}}},
        )
        return True

    async def _find_page_id_by_title(self, title: str) -> str | None:
        result = await self.client.search(
            query=title,
            filter={"property": "object", "value": "page"},
            page_size=20,
        )
        for item in result.get("results", []):
            if _extract_title(item.get("properties", {}).get("title", {})) == title:
                return item.get("id")
        return None

    async def _create_workspace_page(self) -> dict[str, Any]:
        payload = {
            "properties": {
                "title": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": "COO Workspace"},
                        }
                    ]
                }
            }
        }

        if self.parent_page_id:
            try:
                return await self.client.pages.create(
                    parent={"type": "page_id", "page_id": self.parent_page_id},
                    **payload,
                )
            except APIResponseError as exc:
                if exc.code not in {"object_not_found", "validation_error"}:
                    raise

        return await self.client.pages.create(
            parent={"workspace": True},
            **payload,
        )

    async def _find_database_id_by_title(self, title: str) -> str | None:
        result = await self.client.search(
            query=title,
            filter={"property": "object", "value": "database"},
            page_size=20,
        )
        for item in result.get("results", []):
            db_title = "".join(t.get("plain_text", "") for t in item.get("title", []))
            if db_title == title:
                return item.get("id")
        return None

    async def _find_task_row_by_name(self, db_id: str, name: str) -> dict[str, Any] | None:
        result = await self.client.databases.query(database_id=db_id, page_size=50)
        target = name.lower().strip()
        for item in result.get("results", []):
            props = item.get("properties", {})
            current = _extract_title(props.get("Name", {})).lower().strip()
            if current == target:
                return item
        for item in result.get("results", []):
            props = item.get("properties", {})
            current = _extract_title(props.get("Name", {})).lower().strip()
            if target and target in current:
                return item
        return None

    async def _find_project_row_by_name(self, db_id: str, name: str) -> dict[str, Any] | None:
        result = await self.client.databases.query(database_id=db_id, page_size=50)
        target = name.lower().strip()
        for item in result.get("results", []):
            props = item.get("properties", {})
            current = _extract_title(props.get("Name", {})).lower().strip()
            if current == target:
                return item
        for item in result.get("results", []):
            props = item.get("properties", {})
            current = _extract_title(props.get("Name", {})).lower().strip()
            if target and target in current:
                return item
        return None


def _extract_title(prop: dict[str, Any]) -> str:
    parts = prop.get("title", []) if isinstance(prop, dict) else []
    return "".join(p.get("plain_text", "") for p in parts) or "Без названия"


def _safe_task_priority(value: str) -> str:
    allowed = {"High", "Medium", "Low"}
    return value if value in allowed else "Medium"


def _safe_task_status(value: str) -> str:
    allowed = {"Todo", "Doing", "Done", "Paused"}
    return value if value in allowed else "Todo"


def _safe_project_status(value: str) -> str:
    allowed = {"Main", "Support", "Experiment", "Paused", "Done"}
    return value if value in allowed else "Experiment"
