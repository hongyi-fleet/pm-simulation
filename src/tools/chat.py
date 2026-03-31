"""Chat tool surface."""

from __future__ import annotations

from typing import Any

from datetime import datetime
from src.tools.protocol import (
    ActionResult,
    ToolSurface,
    validate_text_length,
    MAX_MESSAGE_LENGTH,
)


class ChatTool:
    """Chat/messaging tool surface (Slack-like)."""

    def __init__(self, world_state):
        self.ws = world_state

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "read_chats":
            return self._read_chats(params, tick)
        elif action_name == "send_chat":
            return self._send_chat(params, tick)
        else:
            return ActionResult(success=False, error=f"Unknown chat action: {action_name}")

    def _read_chats(self, params: dict, tick: int) -> ActionResult:
        channel = params.get("channel")
        if channel:
            rows = self.ws.execute(
                "SELECT * FROM messages WHERE channel = ? ORDER BY tick, id",
                (channel,),
            ).fetchall()
        else:
            rows = self.ws.execute(
                "SELECT * FROM messages ORDER BY tick, id"
            ).fetchall()
        return ActionResult(success=True, data=[dict(r) for r in rows])

    def _send_chat(self, params: dict, tick: int) -> ActionResult:
        channel = params.get("channel", "general")
        message = params.get("message", "")
        sender = params.get("sender", "PM Agent")

        err = validate_text_length(message, "message", MAX_MESSAGE_LENGTH)
        if err:
            return ActionResult(success=False, error=err)

        ts = datetime.now().isoformat()
        self.ws.execute(
            "INSERT INTO messages (tick, channel, sender, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (tick, channel, sender, message, ts),
        )
        self.ws.commit()
        return ActionResult(success=True, data={"sent": True, "channel": channel})

    def schema(self) -> dict[str, Any]:
        return {
            "read_chats": {
                "description": "Read chat messages, optionally filtered by channel",
                "parameters": {
                    "channel": {"type": "string", "description": "Channel name (optional, omit for all)"},
                },
            },
            "send_chat": {
                "description": "Send a chat message to a channel",
                "parameters": {
                    "channel": {"type": "string", "description": "Channel name", "required": True},
                    "message": {"type": "string", "description": "Message content (max 2000 chars)", "required": True},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        for msg in data:
            msg.setdefault("tick", tick)
            msg.setdefault("timestamp", datetime.now().isoformat())
        self.ws.seed_table("messages", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM messages ORDER BY tick, id").fetchall()
        return [dict(r) for r in rows]
