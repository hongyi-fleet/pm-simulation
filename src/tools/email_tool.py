"""Email tool surface."""

from __future__ import annotations

from typing import Any

from datetime import datetime
from src.tools.protocol import (
    ActionResult,
    validate_text_length,
    MAX_MESSAGE_LENGTH,
    MAX_SUBJECT_LENGTH,
)


class EmailTool:
    """Email tool surface."""

    def __init__(self, world_state, valid_people: list[str] | None = None):
        self.ws = world_state
        self.valid_people = valid_people or []

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "read_emails":
            return self._read_emails(params, tick)
        elif action_name == "send_email":
            return self._send_email(params, tick)
        else:
            return ActionResult(success=False, error=f"Unknown email action: {action_name}")

    def _read_emails(self, params: dict, tick: int) -> ActionResult:
        filters = []
        filter_params = []
        if "sender" in params:
            filters.append("sender = ?")
            filter_params.append(params["sender"])
        if "recipient" in params:
            filters.append("recipient = ?")
            filter_params.append(params["recipient"])

        where = " AND ".join(filters) if filters else "1=1"
        rows = self.ws.execute(
            f"SELECT * FROM emails WHERE {where} ORDER BY tick, id",
            tuple(filter_params),
        ).fetchall()
        return ActionResult(success=True, data=[dict(r) for r in rows])

    def _send_email(self, params: dict, tick: int) -> ActionResult:
        recipient = params.get("to", "") or params.get("recipient", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        sender = params.get("sender", "PM Agent")

        if self.valid_people and recipient not in self.valid_people:
            return ActionResult(success=False, error=f"Unknown recipient: {recipient}")

        err = validate_text_length(subject, "subject", MAX_SUBJECT_LENGTH)
        if err:
            return ActionResult(success=False, error=err)
        err = validate_text_length(body, "body", MAX_MESSAGE_LENGTH)
        if err:
            return ActionResult(success=False, error=err)

        ts = datetime.now().isoformat()
        self.ws.execute(
            "INSERT INTO emails (tick, sender, recipient, subject, body, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (tick, sender, recipient, subject, body, ts),
        )
        self.ws.commit()
        return ActionResult(success=True, data={"sent": True, "to": recipient})

    def schema(self) -> dict[str, Any]:
        return {
            "read_emails": {
                "description": "Read emails, optionally filtered by sender or recipient",
                "parameters": {
                    "sender": {"type": "string", "description": "Filter by sender (optional)"},
                    "recipient": {"type": "string", "description": "Filter by recipient (optional)"},
                },
            },
            "send_email": {
                "description": "Send an email",
                "parameters": {
                    "to": {"type": "string", "required": True},
                    "subject": {"type": "string", "required": True, "description": "Max 500 chars"},
                    "body": {"type": "string", "required": True, "description": "Max 2000 chars"},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        for email in data:
            email.setdefault("tick", tick)
            email.setdefault("timestamp", datetime.now().isoformat())
        self.ws.seed_table("emails", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM emails ORDER BY tick, id").fetchall()
        return [dict(r) for r in rows]
