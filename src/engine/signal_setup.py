"""Wire up signal detectors for a scenario.

Two types:
- SimulationDetector: sync SQL checks, set flags for conditional events
- EvaluationRecorder: record candidates, LLM judge runs post-hoc

Simulation flags are for events like "Dana asks for status IF flag not set".
Evaluation flags are for scoring (blocker_discovered, risk_communicated, etc).
"""

from __future__ import annotations

from typing import Any

from src.engine.signals import (
    SimulationDetector,
    SimulationFlag,
    EvaluationRecorder,
)


def setup_signals_for_scenario(scenario_data: dict, llm_client=None) -> dict:
    """Create both simulation detector and evaluation recorder.

    Returns dict with 'simulation' and 'evaluation' keys.
    """
    sim_detector = SimulationDetector()
    eval_recorder = EvaluationRecorder()

    evaluation = scenario_data.get("evaluation", {})

    for criterion in evaluation.get("rubric", []):
        flag = criterion.get("flag")
        if not flag:
            continue

        detection = criterion.get("detection")
        state_check = criterion.get("state_check", {})
        evidence_from = criterion.get("evidence_from", "agent_actions")

        # Build state check functions
        check_fns = _build_state_checks(state_check)

        if detection:
            # Has LLM predicate → evaluation detector (post-hoc)
            eval_recorder.add_detector({
                "name": criterion.get("name", ""),
                "flag": flag,
                "detection": detection,
                "evidence_from": evidence_from,
                "state_checks": check_fns,
            })

            # Also add a simple simulation flag (SQL only) so conditional events work
            if check_fns:
                sim_detector.add_flag(SimulationFlag(
                    name=f"_sim_{flag}",  # Prefixed to avoid collision
                    check=lambda ws, fns=check_fns: all(fn(ws) for fn in fns),
                ))
        else:
            # No LLM predicate → simulation flag only (efficiency, restraint, etc)
            if check_fns:
                sim_detector.add_flag(SimulationFlag(
                    name=flag,
                    check=lambda ws, fns=check_fns: all(fn(ws) for fn in fns),
                ))

    return {
        "simulation": sim_detector,
        "evaluation": eval_recorder,
    }


def _build_state_checks(state_check: dict) -> list:
    """Build state check functions from YAML config."""
    checks = []

    if not isinstance(state_check, dict) or not state_check:
        return checks

    for check_type, check_params in state_check.items():
        if not isinstance(check_params, dict):
            check_params = {"person": check_params} if isinstance(check_params, str) else {}

        fn = _make_check(check_type, check_params)
        if fn:
            checks.append(fn)

    return checks


def _make_check(check_type: str, params: dict):
    """Create a single state check function."""

    if check_type == "agent_messaged":
        person = params.get("person", "")
        def check(ws):
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = ?",
                (person,),
            ).fetchone()
            if row:
                return True
            row = ws.execute(
                "SELECT id FROM emails WHERE sender = 'PM Agent' AND recipient = ?",
                (person,),
            ).fetchone()
            return row is not None
        return check

    elif check_type == "person_responded":
        person = params.get("person", "")
        def check(ws):
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = ? AND (channel = ? OR channel = 'PM Agent' OR channel = 'pm')",
                (person, person),
            ).fetchone()
            if row:
                return True
            row = ws.execute(
                "SELECT id FROM emails WHERE sender = ? AND recipient = 'PM Agent'",
                (person,),
            ).fetchone()
            return row is not None
        return check

    elif check_type == "agent_sent_email":
        person = params.get("to", "")
        def check(ws):
            row = ws.execute(
                "SELECT id FROM emails WHERE sender = 'PM Agent' AND recipient = ?",
                (person,),
            ).fetchone()
            return row is not None
        return check

    elif check_type == "agent_took_action":
        def check(ws):
            row = ws.execute(
                "SELECT id FROM action_log WHERE actor = 'PM Agent' AND success = 1"
            ).fetchone()
            return row is not None
        return check

    elif check_type == "flag_set":
        flag_name = params.get("flag", "")
        def check(ws):
            return ws.get_flag(flag_name) or ws.get_flag(f"_eval_{flag_name}")
        return check

    elif check_type == "flag_not_set":
        flag_name = params.get("flag", "")
        def check(ws):
            return not ws.get_flag(flag_name)
        return check

    return None
