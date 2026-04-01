"""Main evaluator: unified checkpoint scoring with post-hoc LLM judge.

Simulation records candidate timestamps (Layer 1, SQL only).
Evaluator runs LLM judge on candidates after simulation ends (Layer 2).
This eliminates LLM calls during simulation (2435 → ~30-50).
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
from src.evaluation.llm_eval import evaluate_with_llm, build_conversation_text, build_agent_actions_text, build_all_messages_text, get_judge_log
from src.engine.clock import SIM_START
from src.engine.signals import EvaluationRecorder
from src.engine.world_state import WorldState


async def evaluate(
    world_state: WorldState,
    evaluation_config: dict,
    eval_recorder: EvaluationRecorder = None,
    scenario_name: str = "Unknown",
    llm_client=None,
    no_llm: bool = False,
    output_dir: Path | None = None,
) -> CheckpointResult:
    """Run the full evaluation pipeline.

    1. For criteria with LLM detection: run LLM judge on candidates (post-hoc)
    2. For criteria without LLM: check flags/efficiency directly
    3. Score everything as unified checkpoints
    """
    result = CheckpointResult()
    action_log = world_state.get_action_log()

    # Step 1: Run LLM judge on evaluation candidates (post-hoc)
    eval_flags = {}  # flag_name -> datetime (when achieved)
    if eval_recorder and llm_client:
        eval_flags = await _resolve_candidates(
            eval_recorder, world_state, llm_client, evaluation_config
        )

    # Merge eval flags with simulation flags
    all_flags = dict(world_state.flags)
    for flag_name in eval_flags:
        all_flags[flag_name] = True

    all_flag_times = dict(eval_flags)  # eval flags have exact timestamps

    # Step 2: Process rubric criteria as checkpoints
    for criterion in evaluation_config.get("rubric", []):
        scoring = criterion.get("scoring", "flag")
        name = criterion.get("name", "unknown")
        flag = criterion.get("flag", "")
        weight = int(criterion.get("weight", 1))

        if scoring == "time_weighted":
            decay = criterion.get("decay", {})
            thresholds = _build_thresholds(decay, weight)
            cp = checkpoint_time_weighted(
                name=name, total=weight, flag=flag,
                flags=all_flags, flag_times=all_flag_times,
                thresholds=thresholds,
            )

        elif scoring == "inverse_binary":
            cp = checkpoint_flag_not_set(
                name=name, total=weight, flag=flag, flags=all_flags,
            )

        elif scoring == "efficiency":
            max_invalid = criterion.get("max_invalid_actions", 5)
            cp = checkpoint_efficiency(
                name=name, total=weight, action_log=action_log,
                max_invalid=max_invalid,
            )

        else:
            cp = checkpoint_flag_exists(
                name=name, total=weight, flag=flag, flags=all_flags,
            )

        result.add(cp)

    # Step 3: Process LLM judge criteria (communication quality, prioritization)
    for criterion in evaluation_config.get("llm_judge", []):
        name = criterion.get("name", "unknown")
        weight = int(criterion.get("weight", 1))

        agent_messages = _get_agent_messages(world_state)

        judge_result = await evaluate_with_judge(
            [criterion], action_log, agent_messages,
            llm_client=llm_client, no_llm=no_llm,
        )

        score = judge_result.scores[0].score if judge_result.scores else 0.5
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

        judge_log = get_judge_log()
        if judge_log:
            judge_path = output_dir / "judge_log.json"
            with open(judge_path, "w") as f:
                json.dump(judge_log, f, indent=2)
            print(f"Judge log saved to {judge_path} ({len(judge_log)} decisions)")

    return result


async def _resolve_candidates(
    eval_recorder: EvaluationRecorder,
    world_state: WorldState,
    llm_client,
    evaluation_config: dict,
) -> dict[str, datetime]:
    """Run LLM judge on evaluation candidates. Returns {flag_name: timestamp}.

    For each flag, iterate candidates earliest-first. First YES = flag achieved.
    """
    resolved = {}  # flag_name -> datetime

    for criterion in evaluation_config.get("rubric", []):
        flag = criterion.get("flag", "")
        detection = criterion.get("detection", "")
        evidence_from = criterion.get("evidence_from", "agent_actions")

        if not detection or not flag:
            continue

        candidates = eval_recorder.get_candidates(flag)
        if not candidates:
            continue

        # Check causal dependencies: if this flag requires another flag to be set first,
        # only consider candidates after that dependency
        state_check = criterion.get("state_check", {})
        dep_flag = None
        if isinstance(state_check, dict) and "flag_set" in state_check:
            dep_params = state_check["flag_set"]
            if isinstance(dep_params, dict):
                dep_flag = dep_params.get("flag", "")
            elif isinstance(dep_params, str):
                dep_flag = dep_params

        for candidate in candidates:
            # Check causal dependency
            if dep_flag and dep_flag not in resolved:
                continue  # Dependency not yet achieved
            if dep_flag and resolved[dep_flag] > candidate.timestamp:
                continue  # Dependency achieved after this candidate

            # Build evidence content
            content = _build_evidence(world_state, evidence_from, candidate.timestamp)
            if not content:
                continue

            # Run LLM judge
            verdict = await evaluate_with_llm(content, detection, llm_client)
            if verdict:
                resolved[flag] = candidate.timestamp
                break  # Take earliest passing candidate

    return resolved


def _build_evidence(world_state: WorldState, evidence_from: str, up_to_time: datetime = None) -> str:
    """Build evidence text from world state."""
    if evidence_from.startswith("conversation:"):
        person = evidence_from.split(":", 1)[1]
        return build_conversation_text(world_state, "PM Agent", person)
    elif evidence_from == "agent_actions":
        return build_agent_actions_text(world_state)
    elif evidence_from == "all_messages":
        return build_all_messages_text(world_state)
    elif evidence_from.startswith("messages_from:"):
        sender = evidence_from.split(":", 1)[1]
        return build_all_messages_text(world_state, sender=sender)
    return build_agent_actions_text(world_state)


def _build_thresholds(decay: dict, total_points: int) -> list[dict]:
    """Convert decay config to time-based thresholds."""
    day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    thresholds = []
    for day_name, score_value in sorted(decay.items(), key=lambda x: day_map.get(x[0], 5)):
        day_offset = day_map.get(day_name, 0)
        end_of_day = SIM_START + timedelta(days=day_offset, hours=8)
        points = max(1, round(score_value * total_points))
        thresholds.append({"before": end_of_day, "points": points})
    return thresholds


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
