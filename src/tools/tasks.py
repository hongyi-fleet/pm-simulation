"""Task board tool surface."""

from __future__ import annotations

from typing import Any

from src.tools.protocol import ActionResult, validate_text_length, MAX_MESSAGE_LENGTH


class TaskTool:
    """Task tracking tool surface (Jira/Linear-like)."""

    def __init__(self, world_state):
        self.ws = world_state

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "list_tasks":
            return self._list_tasks(params)
        elif action_name == "create_task":
            return self._create_task(params, tick)
        elif action_name == "update_task":
            return self._update_task(params, tick)
        else:
            return ActionResult(success=False, error=f"Unknown task action: {action_name}")

    def _list_tasks(self, params: dict) -> ActionResult:
        filters = []
        filter_params = []
        if "project" in params:
            filters.append("project = ?")
            filter_params.append(params["project"])
        if "assignee" in params:
            filters.append("assignee = ?")
            filter_params.append(params["assignee"])

        where = " AND ".join(filters) if filters else "1=1"
        rows = self.ws.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY id", tuple(filter_params)
        ).fetchall()
        return ActionResult(success=True, data=[dict(r) for r in rows])

    def _create_task(self, params: dict, tick: int) -> ActionResult:
        project = params.get("project", "")
        title = params.get("title", "")
        assignee = params.get("assignee")
        description = params.get("description", "")

        err = validate_text_length(description, "description", MAX_MESSAGE_LENGTH)
        if err:
            return ActionResult(success=False, error=err)

        self.ws.execute(
            "INSERT INTO tasks (project, title, assignee, status, description, created_tick, updated_tick) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project, title, assignee, "todo", description, tick, tick),
        )
        self.ws.commit()
        return ActionResult(success=True, data={"created": True, "title": title})

    def _update_task(self, params: dict, tick: int) -> ActionResult:
        task_id = params.get("task_id") or params.get("id")
        if task_id is None:
            return ActionResult(
                success=False,
                error="task_id is required. Use list_tasks first to see task IDs, then update_task with task_id=N."
            )
        try:
            task_id = int(task_id)
        except (ValueError, TypeError):
            return ActionResult(success=False, error=f"task_id must be an integer, got '{task_id}'")

        row = self.ws.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return ActionResult(success=False, error=f"Task {task_id} not found")

        sender = params.get("sender", "")
        assignee = row["assignee"]
        new_status = params.get("status", "")

        # Permission check: only the assignee can mark their own task as "done"
        # PM can change status to "blocked", "at_risk", or add comments
        if new_status == "done" and sender != assignee:
            return ActionResult(
                success=False,
                error=f"Only {assignee} can mark this task as done. You can set it to 'blocked' or 'at_risk' instead."
            )

        # Prevent re-marking already done tasks
        if new_status == "done" and row["status"] == "done":
            return ActionResult(success=False, error="Task is already done")

        updates = []
        update_params = []
        for field in ("status", "assignee", "description"):
            if field in params:
                updates.append(f"{field} = ?")
                update_params.append(params[field])
        if "comment" in params:
            err = validate_text_length(params["comment"], "comment", MAX_MESSAGE_LENGTH)
            if err:
                return ActionResult(success=False, error=err)

        if updates:
            updates.append("updated_tick = ?")
            update_params.append(tick)
            update_params.append(task_id)
            self.ws.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                tuple(update_params),
            )
            self.ws.commit()

        return ActionResult(success=True, data={"updated": True, "task_id": task_id})

    def schema(self) -> dict[str, Any]:
        return {
            "list_tasks": {
                "description": "List tasks, optionally filtered by project or assignee",
                "parameters": {
                    "project": {"type": "string", "description": "Filter by project (optional)"},
                    "assignee": {"type": "string", "description": "Filter by assignee (optional)"},
                },
            },
            "create_task": {
                "description": "Create a new task",
                "parameters": {
                    "project": {"type": "string", "required": True},
                    "title": {"type": "string", "required": True},
                    "assignee": {"type": "string"},
                    "description": {"type": "string", "description": "Max 2000 chars"},
                },
            },
            "update_task": {
                "description": "Update an existing task",
                "parameters": {
                    "task_id": {"type": "integer", "required": True},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "blocked", "done"]},
                    "assignee": {"type": "string"},
                    "description": {"type": "string"},
                    "comment": {"type": "string", "description": "Optional comment (max 2000 chars)"},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        for task in data:
            task.setdefault("created_tick", tick)
            task.setdefault("updated_tick", tick)
            task.setdefault("status", "todo")
            task.setdefault("description", "")
        self.ws.seed_table("tasks", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [dict(r) for r in rows]
