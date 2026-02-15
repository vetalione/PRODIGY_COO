from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_client import AsyncClient


@dataclass
class NotionIds:
    workspace_page_id: str
    tasks_db_id: str
    projects_db_id: str


class NotionService:
    def __init__(
        self,
        token: str,
        parent_page_id: str,
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
            page = await self.client.pages.create(
                parent={"type": "page_id", "page_id": self.parent_page_id},
                properties={
                    "title": {
                        "title": [
                            {
                                "type": "text",
                                "text": {"content": "COO Workspace"},
                            }
                        ]
                    }
                },
            )
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


def _extract_title(prop: dict[str, Any]) -> str:
    parts = prop.get("title", []) if isinstance(prop, dict) else []
    return "".join(p.get("plain_text", "") for p in parts) or "Без названия"
