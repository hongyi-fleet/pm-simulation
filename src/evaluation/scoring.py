"""Unified checkpoint scoring system.

Inspired by TheAgentCompany: all checks (deterministic + LLM) are checkpoints.
Each checkpoint has a point value. Higher value = more important or harder to judge.
Final score = sum(result) / sum(total).

Time-weighted logic lives INSIDE checkpoints, not as a separate scoring pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Checkpoint:
    """A single evaluation checkpoint."""

    name: str
    total: int  # Max points for this checkpoint
    result: int = 0  # Actual points earned (0 to total)
    detail: str = ""  # Human-readable explanation

    def __post_init__(self):
        if self.result > self.total:
            self.result = self.total
        if self.result < 0:
            self.result = 0


@dataclass
class CheckpointResult:
    """Complete evaluation result."""

    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def total_possible(self) -> int:
        return sum(cp.total for cp in self.checkpoints)

    @property
    def total_earned(self) -> int:
        return sum(cp.result for cp in self.checkpoints)

    @property
    def score(self) -> float:
        if self.total_possible == 0:
            return 0.0
        return self.total_earned / self.total_possible

    def add(self, checkpoint: Checkpoint):
        self.checkpoints.append(checkpoint)

    # Category mapping for PM responsibilities
    CATEGORIES = {
        "Information Discovery": [
            "blocker_discovery", "dependency_surfaced",
            "vendor_news_discovered", "priya_bug_discovered",
        ],
        "Upward Communication": [
            "risk_communicated", "scope_creep_handled",
            "communication_quality",
        ],
        "Prioritization": [
            "dashboard_restraint", "dashboard_demo_addressed",
            "prioritization",
        ],
        "Team Coordination": [
            "blocker_resolved",
        ],
        "Relationship & Discretion": [
            "information_discretion",
        ],
        "Efficiency": [
            "action_efficiency",
        ],
    }

    def print_scorecard(self, scenario_name: str = ""):
        print(f"\nSCORECARD{f' — {scenario_name}' if scenario_name else ''}")
        print("=" * 70)

        # Group checkpoints by category
        categorized = {}
        uncategorized = []
        for cp in self.checkpoints:
            placed = False
            for cat, names in self.CATEGORIES.items():
                if cp.name in names:
                    categorized.setdefault(cat, []).append(cp)
                    placed = True
                    break
            if not placed:
                uncategorized.append(cp)

        # Print by category
        for cat in self.CATEGORIES:
            cps = categorized.get(cat, [])
            if not cps:
                continue
            cat_earned = sum(cp.result for cp in cps)
            cat_total = sum(cp.total for cp in cps)
            pct = f"{cat_earned/cat_total:.0%}" if cat_total > 0 else "—"
            print(f"\n  {cat} ({cat_earned}/{cat_total} = {pct})")
            print(f"  {'─'*66}")
            for cp in cps:
                print(f"    {cp.name:<33} {cp.result:>3}/{cp.total:<3}  {cp.detail}")

        if uncategorized:
            print(f"\n  Other")
            print(f"  {'─'*66}")
            for cp in uncategorized:
                print(f"    {cp.name:<33} {cp.result:>3}/{cp.total:<3}  {cp.detail}")

        print(f"\n{'='*70}")
        print(f"  TOTAL: {self.total_earned}/{self.total_possible} ({self.score:.1%})")
        print(f"{'='*70}")

    def to_dict(self) -> dict:
        # Group by category
        categories = {}
        for cat, names in self.CATEGORIES.items():
            cps = [cp for cp in self.checkpoints if cp.name in names]
            if cps:
                cat_earned = sum(cp.result for cp in cps)
                cat_total = sum(cp.total for cp in cps)
                categories[cat] = {
                    "earned": cat_earned,
                    "total": cat_total,
                    "score": round(cat_earned / cat_total, 3) if cat_total > 0 else 0,
                    "checkpoints": [
                        {"name": cp.name, "total": cp.total, "result": cp.result, "detail": cp.detail}
                        for cp in cps
                    ],
                }

        return {
            "checkpoints": [
                {"name": cp.name, "total": cp.total, "result": cp.result, "detail": cp.detail}
                for cp in self.checkpoints
            ],
            "categories": categories,
            "total_earned": self.total_earned,
            "total_possible": self.total_possible,
            "score": round(self.score, 3),
        }


# === Checkpoint Builders ===

def checkpoint_flag_exists(
    name: str,
    total: int,
    flag: str,
    flags: dict[str, bool],
) -> Checkpoint:
    """Simple: flag is set or not."""
    if flags.get(flag, False):
        return Checkpoint(name=name, total=total, result=total, detail="Achieved")
    return Checkpoint(name=name, total=total, result=0, detail="Not achieved")


def checkpoint_flag_not_set(
    name: str,
    total: int,
    flag: str,
    flags: dict[str, bool],
) -> Checkpoint:
    """Inverse: score if flag is NOT set (avoided bad action)."""
    if not flags.get(flag, False):
        return Checkpoint(name=name, total=total, result=total, detail="Avoided (good)")
    return Checkpoint(name=name, total=total, result=0, detail="Triggered (bad)")


def checkpoint_time_weighted(
    name: str,
    total: int,
    flag: str,
    flags: dict[str, bool],
    flag_times: dict[str, datetime],
    thresholds: list[dict],
) -> Checkpoint:
    """Time-weighted: earlier achievement = more points.

    thresholds is a list of {"before": datetime, "points": int}
    sorted from earliest to latest. Agent gets the highest points
    where their achievement time is before the threshold.

    Example:
        thresholds = [
            {"before": Mon 17:00, "points": 3},  # Mon = full credit
            {"before": Wed 17:00, "points": 2},  # Tue-Wed = partial
            {"before": Fri 17:00, "points": 1},  # Thu-Fri = minimal
        ]
    """
    if not flags.get(flag, False):
        return Checkpoint(name=name, total=total, result=0, detail="Never achieved")

    achieved_at = flag_times.get(flag)
    if achieved_at is None:
        return Checkpoint(name=name, total=total, result=0, detail="Flag set but no timestamp")

    time_str = achieved_at.strftime("%a %I:%M %p")

    # Find highest points where achievement is before threshold
    for threshold in thresholds:
        if achieved_at < threshold["before"]:
            points = min(threshold["points"], total)
            return Checkpoint(
                name=name, total=total, result=points,
                detail=f"{time_str} ({points}/{total} pts)",
            )

    # After all thresholds — minimum credit
    return Checkpoint(name=name, total=total, result=1, detail=f"{time_str} (late, 1/{total} pts)")


def checkpoint_efficiency(
    name: str,
    total: int,
    action_log: list[dict],
    max_invalid: int = 5,
) -> Checkpoint:
    """Score based on action efficiency."""
    invalid_count = sum(
        1 for a in action_log
        if a.get("actor") == "PM Agent" and not a.get("success", True)
    )

    if invalid_count == 0:
        return Checkpoint(name=name, total=total, result=total, detail="No invalid actions")
    elif invalid_count <= max_invalid:
        # Partial credit
        points = max(1, total - invalid_count)
        return Checkpoint(name=name, total=total, result=points, detail=f"{invalid_count} invalid actions")
    else:
        return Checkpoint(name=name, total=total, result=0, detail=f"{invalid_count} invalid actions (over budget)")


def checkpoint_llm_judge(
    name: str,
    total: int,
    judge_score: float,
) -> Checkpoint:
    """Convert LLM judge score (0.0-1.0) to checkpoint points."""
    points = round(judge_score * total)
    points = max(0, min(total, points))
    return Checkpoint(name=name, total=total, result=points, detail=f"Judge: {judge_score:.2f}")
