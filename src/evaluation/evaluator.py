"""Main evaluator: unified checkpoint scoring.

All checks (deterministic + LLM) are checkpoints with point values.
Final score = sum(result) / sum(total).
Same pattern as TheAgentCompany.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.evaluation.scoring import (
    Checkpoint,
    CheckpointResult,
    checkpoint_flag_exists,
    checkpoint_flag_not_set,
    checkpoint_time_weighted,
    checkpoint_efficiency,
    checkpoint_llm_judge,
)
from src.evaluation.llm_judge import evaluate_with_judge
from src.engine.clock import SIM_START, parse_sim_time
from src.engine.world_state import WorldState


async def evaluate(
    world_state: WorldState,
    evaluation_config: dict,
    scenario_name: str = "Unknown",
    llm_client=None,
    no_llm: bool = False,
    output_dir: Path | None = None,
) -> CheckpointResult:
    """Run the full evaluation pipeline. Returns unified checkpoint result."""

    result = CheckpointResult()

    flags = dict(world_state.flags)
    flag_times = _estimate_flag_times(world_state, flags)
    action_log = world_state.get_action_log()

    # Process rubric criteria as checkpoints
    for criterion in evaluation_config.get("rubric", []):
        scoring = criterion.get("scoring", "flag")
        name = criterion.get("name", "unknown")
        flag = criterion.get("flag", "")
        weight = int(criterion.get("weight", 1))

        if scoring == "time_weighted":
            # Build thresholds from decay config
            decay = criterion.get("decay", {})
            thresholds = _build_thresholds(decay, weight)
            cp = checkpoint_time_weighted(
                name=name, total=weight, flag=flag,
                flags=flags, flag_times=flag_times,
                thresholds=thresholds,
            )

        elif scoring == "inverse_binary":
            cp = checkpoint_flag_not_set(
                name=name, total=weight, flag=flag, flags=flags,
            )

        elif scoring == "efficiency":
            max_invalid = criterion.get("max_invalid_actions", 5)
            cp = checkpoint_efficiency(
                name=name, total=weight, action_log=action_log,
                max_invalid=max_invalid,
            )

        else:
            cp = checkpoint_flag_exists(
                name=name, total=weight, flag=flag, flags=flags,
            )

        result.add(cp)

    # Process LLM judge criteria as checkpoints
    for criterion in evaluation_config.get("llm_judge", []):
        name = criterion.get("name", "unknown")
        weight = int(criterion.get("weight", 1))

        agent_messages = _get_agent_messages(world_state)

        judge_result = await evaluate_with_judge(
            [criterion], action_log, agent_messages,
            llm_client=llm_client, no_llm=no_llm,
        )

        if judge_result.scores:
            score = judge_result.scores[0].score
        else:
            score = 0.5

        cp = checkpoint_llm_judge(name=name, total=weight, judge_score=score)
        result.add(cp)

    # Print and save
    result.print_scorecard(scenario_name)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        score_path = output_dir / "scorecard.json"
        with open(score_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Scorecard saved to {score_path}")

    return result


def _build_thresholds(decay: dict, total_points: int) -> list[dict]:
    """Convert decay config (day -> score) to time-based thresholds.

    Example:
        decay = {"Mon": 0.95, "Tue": 0.80, "Wed": 0.50, "Thu": 0.20}
        total_points = 3
    Becomes:
        [
            {"before": Mon 17:00, "points": 3},   # Mon discovery = full
            {"before": Tue 17:00, "points": 3},    # Tue = full (0.80 * 3 rounds to 2.4 → 3)
            {"before": Wed 17:00, "points": 2},    # Wed = partial
            {"before": Thu 17:00, "points": 1},    # Thu = minimal
        ]
    """
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    thresholds = []

    for day_name, score_value in sorted(decay.items(), key=lambda x: day_map.get(x[0], 5)):
        day_offset = day_map.get(day_name, 0)
        end_of_day = SIM_START + timedelta(days=day_offset, hours=8)  # 5pm that day
        points = max(1, round(score_value * total_points))
        thresholds.append({"before": end_of_day, "points": points})

    return thresholds


def _estimate_flag_times(
    world_state: WorldState, flags: dict[str, bool]
) -> dict[str, datetime]:
    """Estimate when each flag was set from snapshot history."""
    flag_times = {}

    rows = world_state.execute(
        "SELECT tick, state_json FROM snapshots ORDER BY tick"
    ).fetchall()

    for row in rows:
        snapshot = json.loads(row["state_json"])
        snapshot_flags = snapshot.get("flags", {})
        for flag_name, flag_val in snapshot_flags.items():
            if flag_val and flag_name not in flag_times:
                try:
                    flag_times[flag_name] = datetime.fromtimestamp(row["tick"])
                except (OSError, ValueError):
                    flag_times[flag_name] = SIM_START + timedelta(hours=row["tick"])

    return flag_times


def _get_agent_messages(world_state: WorldState) -> list[dict]:
    """Get all messages sent by the PM Agent."""
    messages = []

    rows = world_state.execute(
        "SELECT * FROM messages WHERE sender = 'PM Agent' ORDER BY tick, id"
    ).fetchall()
    for r in rows:
        d = dict(r)
        d["type"] = "chat"
        messages.append(d)

    rows = world_state.execute(
        "SELECT * FROM emails WHERE sender = 'PM Agent' ORDER BY tick, id"
    ).fetchall()
    for r in rows:
        d = dict(r)
        d["type"] = "email"
        messages.append(d)

    return messages
