"""Conditional event system for event-driven architecture.

Events are defined in scenario YAML with simulated timestamps.
Conditional events fire when their conditions are met.

Condition types:
- flag_not_set / flag_set: checks a boolean flag in world state
- time_after: fires only after a simulated datetime
- time_before: fires only before a simulated datetime
- all: all sub-conditions must be true (AND)
- any: any sub-condition must be true (OR)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Condition:
    """A typed condition that can be evaluated against world state."""

    type: str
    value: Any = None
    children: list[Condition] = field(default_factory=list)

    def evaluate(self, current_time: datetime, flags: dict[str, bool]) -> bool:
        if self.type == "flag_not_set":
            return not flags.get(self.value, False)
        elif self.type == "flag_set":
            return flags.get(self.value, False)
        elif self.type == "time_after":
            return current_time > self.value
        elif self.type == "time_before":
            return current_time < self.value
        elif self.type == "all":
            return all(c.evaluate(current_time, flags) for c in self.children)
        elif self.type == "any":
            return any(c.evaluate(current_time, flags) for c in self.children)
        elif self.type == "always":
            return True
        else:
            return False


@dataclass
class ScenarioEvent:
    """An event defined in the scenario YAML."""

    time: datetime | None  # None = condition-based, can fire anytime
    event_type: str  # chat_message, email, task_update, transcript, deadline, etc.
    params: dict[str, Any] = field(default_factory=dict)
    condition: Condition | None = None
    fired: bool = False

    def should_fire(self, current_time: datetime, flags: dict[str, bool]) -> bool:
        if self.fired:
            return False
        if self.time is not None and current_time < self.time:
            return False
        if self.condition is not None and not self.condition.evaluate(current_time, flags):
            return False
        return True


def parse_condition(data: Any) -> Condition | None:
    """Parse a condition from YAML data."""
    if data is None:
        return None
    if isinstance(data, str):
        return Condition(type="flag_not_set", value=data)
    if isinstance(data, dict):
        if "flag_not_set" in data:
            return Condition(type="flag_not_set", value=data["flag_not_set"])
        if "flag_set" in data:
            return Condition(type="flag_set", value=data["flag_set"])
        if "time_after" in data:
            from src.engine.clock import parse_sim_time
            return Condition(type="time_after", value=parse_sim_time(data["time_after"]))
        if "time_before" in data:
            from src.engine.clock import parse_sim_time
            return Condition(type="time_before", value=parse_sim_time(data["time_before"]))
        if "all" in data:
            children = [parse_condition(c) for c in data["all"]]
            return Condition(type="all", children=[c for c in children if c])
        if "any" in data:
            children = [parse_condition(c) for c in data["any"]]
            return Condition(type="any", children=[c for c in children if c])
    return None


def parse_events(events_data: list[dict]) -> list[ScenarioEvent]:
    """Parse events from scenario YAML."""
    from src.engine.clock import parse_sim_time
    events = []
    for e in events_data:
        time = None
        if "time" in e:
            time = parse_sim_time(e["time"])
        condition = parse_condition(e.get("condition"))
        events.append(
            ScenarioEvent(
                time=time,
                event_type=e.get("type", ""),
                params=e.get("params", {}),
                condition=condition,
            )
        )
    return events
