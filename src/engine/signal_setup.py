"""Wire up signal detectors for a scenario.

Two-layer detection (same pattern as TheAgentCompany):
  Layer 1: Deterministic state check (did the action happen?)
  Layer 2: LLM judge (does the content indicate the predicate?)

Layer 1 gates Layer 2. The LLM only fires when state checks pass.
Predicates are defined in the scenario YAML — no hardcoded keywords.
"""

from __future__ import annotations

from typing import Any

from src.engine.signals import (
    SignalDetectorEngine,
    MultiSignalDetector,
    Signal,
)
from src.evaluation.llm_eval import (
    evaluate_with_llm,
    build_conversation_text,
    build_agent_actions_text,
    build_all_messages_text,
)


def setup_signals_for_scenario(scenario_data: dict, llm_client=None) -> SignalDetectorEngine:
    """Create signal detectors from scenario YAML evaluation config.

    Each rubric criterion can define:
      - flag: the flag name to set
      - detection: plain English description of what "achieved" means
      - state_check: what state condition must be true first
      - evidence_from: where to look for evidence ("conversation:Alex Chen", "agent_actions", "all_messages")
    """
    engine = SignalDetectorEngine()
    evaluation = scenario_data.get("evaluation", {})

    for criterion in evaluation.get("rubric", []):
        flag = criterion.get("flag")
        if not flag:
            continue

        detection = criterion.get("detection")
        state_check = criterion.get("state_check", {})
        evidence_from = criterion.get("evidence_from", "agent_actions")

        if detection:
            # LLM-based detection with state gate
            detector = _build_llm_detector(
                flag, detection, state_check, evidence_from, llm_client
            )
        else:
            # Fallback: simple state check only
            detector = _build_simple_detector(flag, state_check)

        if detector:
            engine.add_detector(detector)

    return engine


def _build_llm_detector(
    flag: str,
    predicate: str,
    state_check: dict,
    evidence_from: str,
    llm_client,
) -> MultiSignalDetector:
    """Build a detector that uses Layer 1 (state) + Layer 2 (LLM judge)."""

    def make_state_check(check_type: str, check_params: dict):
        """Create a state check function."""
        if check_type == "agent_messaged":
            person = check_params.get("person", "")
            def check(ws, time) -> bool:
                # Check chat: exact channel match only (DM channel = person's name)
                row = ws.execute(
                    "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = ?",
                    (person,),
                ).fetchone()
                if row:
                    return True
                # Check email: exact recipient match
                row = ws.execute(
                    "SELECT id FROM emails WHERE sender = 'PM Agent' AND recipient = ?",
                    (person,),
                ).fetchone()
                return row is not None
            return check

        elif check_type == "person_responded":
            person = check_params.get("person", "")
            def check(ws, time) -> bool:
                # Check for messages from this person in DM channels (not seed data in general/engineering)
                # DM channel = person's own name (our convention)
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
            person = check_params.get("to", "")
            def check(ws, time) -> bool:
                row = ws.execute(
                    "SELECT id FROM emails WHERE sender = 'PM Agent' AND recipient = ?",
                    (person,),
                ).fetchone()
                return row is not None
            return check

        elif check_type == "agent_took_action":
            def check(ws, time) -> bool:
                row = ws.execute(
                    "SELECT id FROM action_log WHERE actor = 'PM Agent' AND success = 1"
                ).fetchone()
                return row is not None
            return check

        elif check_type == "flag_not_set":
            flag_name = check_params.get("flag", "")
            def check(ws, time) -> bool:
                return not ws.get_flag(flag_name)
            return check

        elif check_type == "flag_set":
            flag_name = check_params.get("flag", "")
            def check(ws, time) -> bool:
                return ws.get_flag(flag_name)
            return check

        else:
            # Always pass if unknown check type
            return lambda ws, time: True

    def make_llm_check(predicate: str, evidence_from: str, llm_client):
        """Create an async LLM judge check function."""
        async def check(ws, time) -> bool:
            if llm_client is None:
                return False

            # Build evidence text based on source
            if evidence_from.startswith("conversation:"):
                person = evidence_from.split(":", 1)[1]
                content = build_conversation_text(ws, "PM Agent", person)
            elif evidence_from == "agent_actions":
                content = build_agent_actions_text(ws)
            elif evidence_from == "all_messages":
                content = build_all_messages_text(ws)
            elif evidence_from.startswith("messages_from:"):
                sender = evidence_from.split(":", 1)[1]
                content = build_all_messages_text(ws, sender=sender)
            else:
                content = build_agent_actions_text(ws)

            if not content:
                return False

            try:
                return await evaluate_with_llm(content, predicate, llm_client)
            except Exception as e:
                import sys
                print(f"  [DEBUG] LLM judge failed for {predicate[:50]}...: {e}", file=sys.stderr)
                return False

        return check

    # Build signals
    signals = []

    # Layer 1: State checks (deterministic gate)
    if isinstance(state_check, dict) and state_check:
        for check_type, check_params in state_check.items():
            if not isinstance(check_params, dict):
                check_params = {"person": check_params} if isinstance(check_params, str) else {}
            signals.append(Signal(
                name=f"state_{check_type}",
                check=make_state_check(check_type, check_params),
            ))

    # Layer 2: LLM judge (only fires when Layer 1 passes)
    signals.append(Signal(
        name=f"llm_judge_{flag}",
        check=make_llm_check(predicate, evidence_from, llm_client),
    ))

    return MultiSignalDetector(
        flag_name=flag,
        signals=signals,
        required_count=len(signals),  # ALL signals must fire
    )


def _build_simple_detector(flag: str, state_check: dict) -> MultiSignalDetector | None:
    """Fallback: pure state check, no LLM."""

    def always_true(ws, time) -> bool:
        return True

    return MultiSignalDetector(
        flag_name=flag,
        signals=[Signal(name=f"simple_{flag}", check=always_true)],
        required_count=1,
    )
