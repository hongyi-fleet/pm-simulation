"""EventQueue: priority queue driving the simulation.

Events are sorted by simulated time. Same-timestamp events
are resolved by priority tier:
  1. Structural events (meetings, deadlines) — highest
  2. NPC-generated events (responses, proactive messages)
  3. Agent-generated events (scheduled meetings, etc.)
  4. Agent turn events — lowest (agent acts after seeing everything)

Within the same tier, insertion order is the tiebreaker.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class EventPriority(IntEnum):
    """Priority tiers for same-timestamp ordering."""
    STRUCTURAL = 0    # Meetings, deadlines, external triggers
    NPC_ACTION = 1    # NPC responses, proactive outreach
    AGENT_ACTION = 2  # Agent-generated events
    AGENT_TURN = 3    # Agent gets to observe and act


_counter = 0


def _next_counter() -> int:
    global _counter
    _counter += 1
    return _counter


@dataclass(order=False)
class SimEvent:
    """An event in the simulation."""

    time: datetime
    priority: EventPriority
    event_type: str  # "chat_message", "email", "meeting", "agent_turn", "deadline", etc.
    params: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # Who generated this event
    _order: int = field(default_factory=_next_counter, repr=False)

    def __lt__(self, other: SimEvent) -> bool:
        if self.time != other.time:
            return self.time < other.time
        if self.priority != other.priority:
            return self.priority < other.priority
        return self._order < other._order

    def __le__(self, other: SimEvent) -> bool:
        return self == other or self < other


class EventQueue:
    """Priority queue of simulation events."""

    def __init__(self):
        self._heap: list[SimEvent] = []

    def push(self, event: SimEvent):
        heapq.heappush(self._heap, event)

    def pop(self) -> SimEvent | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    def peek(self) -> SimEvent | None:
        if not self._heap:
            return None
        return self._heap[0]

    def pop_batch(self) -> list[SimEvent]:
        """Pop all events at the same time and priority as the next event."""
        if not self._heap:
            return []
        first = heapq.heappop(self._heap)
        batch = [first]
        while (self._heap and
               self._heap[0].time == first.time and
               self._heap[0].priority == first.priority):
            batch.append(heapq.heappop(self._heap))
        return batch

    @property
    def empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)

    def schedule_agent_turns(self, start: datetime, end: datetime, interval_minutes: int = 30):
        """Schedule regular agent turn events throughout the sim."""
        from src.engine.clock import SimClock
        clock = SimClock(start_time=start, end_time=end)
        t = start
        while t < end:
            if clock.is_work_hours(t):
                self.push(SimEvent(
                    time=t,
                    priority=EventPriority.AGENT_TURN,
                    event_type="agent_turn",
                    source="scheduler",
                ))
            t += __import__("datetime").timedelta(minutes=interval_minutes)
