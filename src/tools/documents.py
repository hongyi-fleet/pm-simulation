"""Documents tool surface."""

from __future__ import annotations

from typing import Any

from src.tools.protocol import ActionResult, validate_text_length, MAX_MESSAGE_LENGTH


class DocumentsTool:
    """Document management tool surface (Notion/Confluence-like)."""

    def __init__(self, world_state):
        self.ws = world_state

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "list_docs":
            return self._list_docs()
        elif action_name == "read_doc":
            return self._read_doc(params)
        elif action_name == "create_doc":
            return self._create_doc(params, tick)
        elif action_name == "edit_doc":
            return self._edit_doc(params, tick)
        else:
            return ActionResult(success=False, error=f"Unknown document action: {action_name}")

    def _list_docs(self) -> ActionResult:
        rows = self.ws.execute(
            "SELECT id, title, author, created_tick, updated_tick FROM documents ORDER BY title"
        ).fetchall()
        return ActionResult(success=True, data=[dict(r) for r in rows])

    def _read_doc(self, params: dict) -> ActionResult:
        title = params.get("title", "")
        row = self.ws.execute(
            "SELECT * FROM documents WHERE title = ?", (title,)
        ).fetchone()
        if row is None:
            return ActionResult(success=False, error=f"Document not found: {title}")
        return ActionResult(success=True, data=dict(row))

    def _create_doc(self, params: dict, tick: int) -> ActionResult:
        title = params.get("title", "")
        content = params.get("content", "")
        author = params.get("author", "PM Agent")

        err = validate_text_length(content, "content", MAX_MESSAGE_LENGTH * 5)
        if err:
            return ActionResult(success=False, error=err)

        existing = self.ws.execute(
            "SELECT id FROM documents WHERE title = ?", (title,)
        ).fetchone()
        if existing:
            return ActionResult(success=False, error=f"Document already exists: {title}")

        self.ws.execute(
            "INSERT INTO documents (title, content, author, created_tick, updated_tick) VALUES (?, ?, ?, ?, ?)",
            (title, content, author, tick, tick),
        )
        self.ws.commit()
        return ActionResult(success=True, data={"created": True, "title": title})

    def _edit_doc(self, params: dict, tick: int) -> ActionResult:
        title = params.get("title", "")
        content = params.get("content", "")

        err = validate_text_length(content, "content", MAX_MESSAGE_LENGTH * 5)
        if err:
            return ActionResult(success=False, error=err)

        existing = self.ws.execute(
            "SELECT id FROM documents WHERE title = ?", (title,)
        ).fetchone()
        if not existing:
            return ActionResult(success=False, error=f"Document not found: {title}")

        self.ws.execute(
            "UPDATE documents SET content = ?, updated_tick = ? WHERE title = ?",
            (content, tick, title),
        )
        self.ws.commit()
        return ActionResult(success=True, data={"updated": True, "title": title})

    def schema(self) -> dict[str, Any]:
        return {
            "list_docs": {
                "description": "List all documents",
                "parameters": {},
            },
            "read_doc": {
                "description": "Read a document by title",
                "parameters": {
                    "title": {"type": "string", "required": True},
                },
            },
            "create_doc": {
                "description": "Create a new document",
                "parameters": {
                    "title": {"type": "string", "required": True},
                    "content": {"type": "string", "required": True},
                },
            },
            "edit_doc": {
                "description": "Edit an existing document",
                "parameters": {
                    "title": {"type": "string", "required": True},
                    "content": {"type": "string", "required": True, "description": "New full content"},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        for doc in data:
            doc.setdefault("author", "")
            doc.setdefault("content", "")
            doc.setdefault("created_tick", tick)
            doc.setdefault("updated_tick", tick)
        self.ws.seed_table("documents", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM documents ORDER BY title").fetchall()
        return [dict(r) for r in rows]
