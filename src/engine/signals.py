"""Signal detector: pattern-matches on world state changes to set flags.

Runs as step 3.5 in the tick loop, after agent actions but before snapshots.
Separates flag-setting from evaluation to avoid circular dependencies.

All check functions can be sync or async. The engine awaits them uniformly.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Signal:
    """A single signal that can be detected from world state."""

    name: str
    check: Callable  # (world_state, time) -> bool (sync or async)
    detected_at: Any = None  # datetime or int

    @property
    def detected(self) -> bool:
        return self.detected_at is not None

    async def run_check(self, world_state, time) -> bool:
        """Run the check function, handling both sync and async."""
        result = self.check(world_state, time)
        if inspect.isawaitable(result):
            return await result
        return result


@dataclass
class MultiSignalDetector:
    """Detects a flag by requiring multiple signals to fire."""

    flag_name: str
    signals: list[Signal] = field(default_factory=list)
    required_count: int | None = None

    @property
    def threshold(self) -> int:
        return self.required_count or len(self.signals)

    async def check(self, world_state, time) -> bool:
        """Check all signals and return True if threshold met."""
        for signal in self.signals:
            if not signal.detected:
                result = await signal.run_check(world_state, time)
                if result:
                    signal.detected_at = time

        detected = sum(1 for s in self.signals if s.detected)
        return detected >= self.threshold


class SignalDetectorEngine:
    """Runs all signal detectors and sets flags in world state."""

    def __init__(self):
        self.detectors: list[MultiSignalDetector] = []
        self._last_message_count: int = 0  # Track state changes to avoid redundant LLM calls

    def add_detector(self, detector: MultiSignalDetector):
        self.detectors.append(detector)

    async def run(self, world_state, time):
        """Run all detectors. Sets flags on world_state when thresholds are met.

        Optimization: only run detectors when new messages/emails have appeared
        since the last check. Avoids redundant LLM calls on turns with no new data.
        """
        # Check if new conversation content appeared since last run
        # Only count messages + emails (actual communication)
        # NOT action_log (read actions don't create new evidence for the judge)
        current_count = 0
        row = world_state.execute("SELECT COUNT(*) as c FROM messages").fetchone()
        current_count += row["c"]
        row = world_state.execute("SELECT COUNT(*) as c FROM emails").fetchone()
        current_count += row["c"]

        if current_count == self._last_message_count:
            return  # No new data, skip all detectors
        self._last_message_count = current_count

        for detector in self.detectors:
            if world_state.get_flag(detector.flag_name):
                continue
            if await detector.check(world_state, time):
                world_state.set_flag(detector.flag_name, True)


# --- Built-in signal checks (sync, no LLM) ---

def check_agent_messaged_person(person: str):
    def check(ws, time) -> bool:
        row = ws.execute(
            "SELECT id FROM messages WHERE sender = 'PM Agent' AND (channel = ? OR content LIKE ?)",
            (person, f"%@{person}%"),
        ).fetchone()
        if row:
            return True
        row = ws.execute(
            "SELECT id FROM emails WHERE sender = 'PM Agent' AND recipient = ?",
            (person,),
        ).fetchone()
        return row is not None
    return check


def check_person_revealed_topic(person: str, keywords: list[str]):
    def check(ws, time) -> bool:
        for kw in keywords:
            pattern = f"%{kw}%"
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = ? AND content LIKE ?",
                (person, pattern),
            ).fetchone()
            if row:
                return True
            row = ws.execute(
                "SELECT id FROM emails WHERE sender = ? AND body LIKE ?",
                (person, pattern),
            ).fetchone()
            if row:
                return True
        return False
    return check


def check_agent_follow_up_action(keywords: list[str]):
    def check(ws, time) -> bool:
        for kw in keywords:
            pattern = f"%{kw}%"
            row = ws.execute(
                "SELECT id FROM emails WHERE sender = 'PM Agent' AND (subject LIKE ? OR body LIKE ?)",
                (pattern, pattern),
            ).fetchone()
            if row:
                return True
            row = ws.execute(
                "SELECT id FROM action_log WHERE actor = 'PM Agent' AND action = 'update_task' AND params LIKE ?",
                (pattern,),
            ).fetchone()
            if row:
                return True
        return False
    return check
