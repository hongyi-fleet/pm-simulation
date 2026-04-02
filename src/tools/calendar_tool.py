"""Calendar tool surface."""

from __future__ import annotations

from typing import Any

from datetime import datetime
from src.tools.protocol import ActionResult


class CalendarTool:
    """Calendar tool surface."""

    def __init__(self, world_state, valid_people: list[str] | None = None):
        self.ws = world_state
        self.valid_people = valid_people or []

    def handle_action(self, action_name: str, params: dict[str, Any], tick: int) -> ActionResult:
        if action_name == "check_calendar":
            return self._check_calendar(params, tick)
        elif action_name == "schedule_meeting":
            return self._schedule_meeting(params, tick)
        else:
            return ActionResult(success=False, error=f"Unknown calendar action: {action_name}")

    def _check_calendar(self, params: dict, tick: int) -> ActionResult:
        person = params.get("person")
        day = params.get("day")

        if person:
            rows = self.ws.execute(
                "SELECT * FROM calendar_events WHERE attendees LIKE ? ORDER BY tick",
                (f"%{person}%",),
            ).fetchall()
        elif day is not None:
            # Accept day number (0-4) or day name (Monday, Mon, etc.)
            day_map = {
                "monday": 0, "mon": 0, "0": 0,
                "tuesday": 1, "tue": 1, "1": 1,
                "wednesday": 2, "wed": 2, "2": 2,
                "thursday": 3, "thu": 3, "3": 3,
                "friday": 4, "fri": 4, "4": 4,
            }
            day_str = str(day).lower().strip()
            day_num = day_map.get(day_str)
            if day_num is None:
                try:
                    day_num = int(day)
                except (ValueError, TypeError):
                    return ActionResult(success=False, error=f"Invalid day: {day}. Use 0-4 or Monday-Friday.")
            day_start = day_num * 8
            day_end = day_start + 8
            rows = self.ws.execute(
                "SELECT * FROM calendar_events WHERE tick >= ? AND tick < ? ORDER BY tick",
                (day_start, day_end),
            ).fetchall()
        else:
            rows = self.ws.execute(
                "SELECT * FROM calendar_events ORDER BY tick"
            ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["datetime"] = f"tick-{d['tick']}"
            results.append(d)
        return ActionResult(success=True, data=results)

    def _schedule_meeting(self, params: dict, tick: int) -> ActionResult:
        meeting_tick = params.get("tick")
        if meeting_tick is None:
            meeting_tick = params.get("time")
        if meeting_tick is None:
            return ActionResult(
                success=False,
                error="Meeting tick is required. Use tick=N where N is an integer. "
                      "Day 0 (Mon) ticks 0-15, Day 1 (Tue) 16-31, Day 2 (Wed) 32-47, "
                      "Day 3 (Thu) 48-63, Day 4 (Fri) 64-79. Example: tick=32 for Wed 9am."
            )
        # Accept string numbers
        try:
            meeting_tick = int(meeting_tick)
        except (ValueError, TypeError):
            return ActionResult(
                success=False,
                error=f"Meeting tick must be an integer, got '{meeting_tick}'. "
                      "Example: tick=32 for Wed 9am."
            )
        if meeting_tick <= tick:
            return ActionResult(success=False, error="Cannot schedule meeting in the past")
        if meeting_tick >= 80:  # Max ticks safeguard
            return ActionResult(success=False, error="Meeting tick is beyond simulation end")

        attendees = params.get("attendees", [])
        if isinstance(attendees, list):
            attendees_str = ",".join(attendees)
        else:
            attendees_str = str(attendees)

        title = params.get("title", "Meeting")
        agenda = params.get("agenda", "")
        created_by = params.get("created_by", "PM Agent")

        self.ws.execute(
            "INSERT INTO calendar_events (title, tick, duration_ticks, attendees, agenda, created_by) VALUES (?, ?, ?, ?, ?, ?)",
            (title, meeting_tick, params.get("duration", 1), attendees_str, agenda, created_by),
        )
        self.ws.commit()
        return ActionResult(
            success=True,
            data={"scheduled": True, "tick": meeting_tick, "title": title},
        )

    def schema(self) -> dict[str, Any]:
        return {
            "check_calendar": {
                "description": "Check calendar events, optionally filtered by person or day",
                "parameters": {
                    "person": {"type": "string", "description": "Filter by attendee name (optional)"},
                    "day": {"type": "integer", "description": "Day number 0-4 (Mon-Fri) (optional)"},
                },
            },
            "schedule_meeting": {
                "description": "Schedule a new meeting",
                "parameters": {
                    "tick": {"type": "integer", "required": True, "description": "Tick to schedule at (must be future)"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "required": True},
                    "title": {"type": "string"},
                    "agenda": {"type": "string"},
                },
            },
        }

    def seed(self, data: list[dict[str, Any]], tick: int = 0):
        for event in data:
            event.setdefault("duration_ticks", 1)
            event.setdefault("agenda", "")
            event.setdefault("created_by", "")
            if isinstance(event.get("attendees"), list):
                event["attendees"] = ",".join(event["attendees"])
        self.ws.seed_table("calendar_events", data)

    def dump_state(self) -> list[dict[str, Any]]:
        rows = self.ws.execute("SELECT * FROM calendar_events ORDER BY tick").fetchall()
        return [dict(r) for r in rows]
