"""SimClock: passive simulation clock for event-driven architecture.

The clock does NOT drive the loop. Events do. The clock tracks
the current simulated datetime (Mon-Fri, 9am-5pm work hours).
Events advance it by setting the time when they fire.

"Before time X" means simulated_time < X.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


# Simulation starts Monday 9:00 AM
BASE_DATE = datetime(2025, 3, 3, 9, 0)  # A Monday
WORK_START_HOUR = 9
WORK_END_HOUR = 17
SIM_START = BASE_DATE
SIM_END = BASE_DATE + timedelta(days=4, hours=8)  # Friday 5pm


@dataclass
class SimClock:
    """Passive simulation clock. Events advance it, not ticks."""

    current_time: datetime = None
    start_time: datetime = None
    end_time: datetime = None

    def __post_init__(self):
        if self.current_time is None:
            self.current_time = SIM_START
        if self.start_time is None:
            self.start_time = self.current_time
        if self.end_time is None:
            self.end_time = SIM_END

    def advance_to(self, time: datetime):
        """Advance clock to the given time. Events call this."""
        if time > self.current_time:
            self.current_time = time

    @property
    def done(self) -> bool:
        return self.current_time >= self.end_time

    @property
    def day_name(self) -> str:
        return self.current_time.strftime("%a")

    @property
    def time_str(self) -> str:
        return self.current_time.strftime("%H:%M")

    @property
    def elapsed_hours(self) -> float:
        """Hours elapsed since simulation start."""
        delta = self.current_time - self.start_time
        return delta.total_seconds() / 3600

    def is_work_hours(self, time: datetime | None = None) -> bool:
        t = time or self.current_time
        return (t.weekday() < 5 and
                WORK_START_HOUR <= t.hour < WORK_END_HOUR)

    def next_work_time(self, time: datetime) -> datetime:
        """Given a time, return the next valid work-hours datetime."""
        t = time
        # Skip to next work day if weekend
        while t.weekday() >= 5:
            t = t.replace(hour=WORK_START_HOUR, minute=0, second=0) + timedelta(days=1)
        # Skip to start of work day if before hours
        if t.hour < WORK_START_HOUR:
            t = t.replace(hour=WORK_START_HOUR, minute=0, second=0)
        # Skip to next day if after hours
        if t.hour >= WORK_END_HOUR:
            t = (t + timedelta(days=1)).replace(hour=WORK_START_HOUR, minute=0, second=0)
            while t.weekday() >= 5:
                t += timedelta(days=1)
        return t

    def __repr__(self) -> str:
        return f"SimClock({self.day_name} {self.time_str})"


def is_before_time(current: datetime, target: datetime) -> bool:
    """Check if current time is before target (exclusive)."""
    return current < target


def parse_sim_time(time_str: str) -> datetime:
    """Parse a scenario time string like 'Mon 14:00' or 'Wed 09:30' into datetime.

    Also accepts full ISO format or 'Day HH:MM' format.
    """
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}

    # Try ISO format first
    try:
        return datetime.fromisoformat(time_str)
    except (ValueError, TypeError):
        pass

    # Try "Day HH:MM" format
    parts = time_str.strip().split()
    if len(parts) == 2 and parts[0] in day_map:
        day_offset = day_map[parts[0]]
        time_parts = parts[1].split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        return BASE_DATE + timedelta(days=day_offset, hours=hour - WORK_START_HOUR, minutes=minute)

    raise ValueError(f"Cannot parse time: {time_str}")
