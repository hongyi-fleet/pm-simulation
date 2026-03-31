"""Meeting transcripts tool surface (read-only)."""

from __future__ import annotations

from typing import Any

from datetime import datetime
from src.tools.protocol import ActionResult


class MeetingsTool:
    """Meeting transcripts tool surface. Read-only for the agent.

    Transcripts are auto-generated from calendar events at the tick
    they occur. The agent can read transcripts from meetings it
    attended or missed.
    """

    def __init__(self, world_state):
        self.ws = world_state

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "list_meetings":
            return self._list_meetings()
        elif action_name == "read_transcript":
            return self._read_transcript(params)
        else:
            return ActionResult(success=False, error=f"Unknown meeting action: {action_name}")

    def _list_meetings(self) -> ActionResult:
        rows = self.ws.execute(
            "SELECT id, meeting_title, tick, attendees FROM meeting_transcripts ORDER BY tick"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["datetime"] = f"tick-{d['tick']}"
            results.append(d)
        return ActionResult(success=True, data=results)

    def _read_transcript(self, params: dict) -> ActionResult:
        transcript_id = params.get("id")
        if transcript_id is None:
            return ActionResult(success=False, error="Transcript id is required")

        row = self.ws.execute(
            "SELECT * FROM meeting_transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()
        if row is None:
            return ActionResult(success=False, error=f"Transcript {transcript_id} not found")

        d = dict(row)
        d["datetime"] = f"tick-{d['tick']}"
        return ActionResult(success=True, data=d)

    def generate_transcript(self, meeting_title: str, tick: int, attendees: str, transcript: str):
        """Called by the engine when a calendar event fires. Not an agent action."""
        self.ws.execute(
            "INSERT INTO meeting_transcripts (meeting_title, tick, attendees, transcript) VALUES (?, ?, ?, ?)",
            (meeting_title, tick, attendees, transcript),
        )
        self.ws.commit()

    def schema(self) -> dict[str, Any]:
        return {
            "list_meetings": {
                "description": "List all meeting transcripts with titles and dates",
                "parameters": {},
            },
            "read_transcript": {
                "description": "Read the full transcript of a meeting",
                "parameters": {
                    "id": {"type": "integer", "required": True, "description": "Meeting transcript ID"},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        self.ws.seed_table("meeting_transcripts", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM meeting_transcripts ORDER BY tick").fetchall()
        return [dict(r) for r in rows]
