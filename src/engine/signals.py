"""Signal detection: two modes.

SimulationDetector: sync, Layer 1 only (SQL checks). Runs every turn.
  Sets flags immediately. Used for conditional events.

EvaluationRecorder: sync, Layer 1 only. Records candidate timestamps.
  LLM judge runs post-hoc in evaluator.

This split eliminates LLM calls during simulation (2435 → 0).
LLM judge runs once after simulation ends (~30-50 calls total).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class SimulationFlag:
    """A flag driven by SQL state check only. Sets immediately during sim."""

    name: str
    check: Callable  # (world_state) -> bool, sync only
    triggered: bool = False


class SimulationDetector:
    """Runs during simulation. Sync only. No LLM calls.
    Sets flags on world_state for conditional events."""

    def __init__(self):
        self.flags: list[SimulationFlag] = []

    def add_flag(self, flag: SimulationFlag):
        self.flags.append(flag)

    def run(self, world_state):
        """Check all flags. Sync. No LLM."""
        for flag in self.flags:
            if flag.triggered:
                continue
            if world_state.get_flag(flag.name):
                flag.triggered = True
                continue
            if flag.check(world_state):
                world_state.set_flag(flag.name, True)
                flag.triggered = True


@dataclass
class EvaluationCandidate:
    """A candidate moment when a flag might have been achieved."""

    timestamp: datetime
    flag_name: str
    evidence_source: str  # "conversation:Alex Chen", "agent_actions", etc.


class EvaluationRecorder:
    """Records candidate timestamps during simulation. No LLM calls.
    Evaluator runs LLM judge on candidates after simulation ends."""

    def __init__(self):
        self.detectors: list[dict] = []  # {name, flag, state_check, detection, evidence_from}
        self.candidates: list[EvaluationCandidate] = []
        self._last_data_count: int = 0

    def add_detector(self, config: dict):
        """Add a detector config from YAML."""
        self.detectors.append(config)

    def run(self, world_state, current_time: datetime):
        """Check state checks and record candidates. Sync. No LLM."""
        # Skip if no new write data
        current_count = 0
        row = world_state.execute("SELECT COUNT(*) as c FROM messages").fetchone()
        current_count += row["c"]
        row = world_state.execute("SELECT COUNT(*) as c FROM emails").fetchone()
        current_count += row["c"]
        row = world_state.execute(
            "SELECT COUNT(*) as c FROM action_log WHERE action IN "
            "('send_chat','send_email','create_task','update_task','schedule_meeting','create_doc','edit_doc')"
        ).fetchone()
        current_count += row["c"]

        if current_count == self._last_data_count:
            return
        self._last_data_count = current_count

        for detector in self.detectors:
            flag_name = detector.get("flag", "")

            # Skip if already have a confirmed candidate for this flag
            # (still record in case earlier candidate fails LLM judge)

            # Run state checks
            state_checks = detector.get("state_checks", [])
            all_pass = True
            for check_fn in state_checks:
                if not check_fn(world_state):
                    all_pass = False
                    break

            if all_pass and state_checks:
                # Record candidate
                self.candidates.append(EvaluationCandidate(
                    timestamp=current_time,
                    flag_name=flag_name,
                    evidence_source=detector.get("evidence_from", "agent_actions"),
                ))

    def get_candidates(self, flag_name: str) -> list[EvaluationCandidate]:
        """Get all candidates for a flag, sorted by time (earliest first)."""
        return sorted(
            [c for c in self.candidates if c.flag_name == flag_name],
            key=lambda c: c.timestamp,
        )
