"""Tests for unified checkpoint evaluation."""

from datetime import timedelta

from src.engine.clock import SIM_START
from src.evaluation.scoring import (
    Checkpoint,
    CheckpointResult,
    checkpoint_flag_exists,
    checkpoint_flag_not_set,
    checkpoint_time_weighted,
    checkpoint_efficiency,
    checkpoint_llm_judge,
)


# Thresholds: Mon=3pts, Tue-Wed=2pts, Thu=1pt (out of 3)
BLOCKER_THRESHOLDS = [
    {"before": SIM_START + timedelta(hours=8), "points": 3},    # Mon EOD
    {"before": SIM_START + timedelta(days=2, hours=8), "points": 2},  # Wed EOD
    {"before": SIM_START + timedelta(days=3, hours=8), "points": 1},  # Thu EOD
]


def test_time_weighted_monday():
    flags = {"blocker": True}
    flag_times = {"blocker": SIM_START + timedelta(hours=2)}  # Mon 11am
    cp = checkpoint_time_weighted("test", 3, "blocker", flags, flag_times, BLOCKER_THRESHOLDS)
    assert cp.result == 3  # Full credit


def test_time_weighted_wednesday():
    flags = {"blocker": True}
    flag_times = {"blocker": SIM_START + timedelta(days=1, hours=4)}  # Tue 1pm
    cp = checkpoint_time_weighted("test", 3, "blocker", flags, flag_times, BLOCKER_THRESHOLDS)
    assert cp.result == 2  # Partial


def test_time_weighted_thursday():
    flags = {"blocker": True}
    flag_times = {"blocker": SIM_START + timedelta(days=3, hours=2)}  # Thu 11am
    cp = checkpoint_time_weighted("test", 3, "blocker", flags, flag_times, BLOCKER_THRESHOLDS)
    assert cp.result == 1  # Minimal (after Wed EOD threshold)


def test_time_weighted_never():
    flags = {"blocker": False}
    cp = checkpoint_time_weighted("test", 3, "blocker", flags, {}, BLOCKER_THRESHOLDS)
    assert cp.result == 0


def test_flag_exists():
    cp = checkpoint_flag_exists("test", 1, "found", {"found": True})
    assert cp.result == 1

    cp = checkpoint_flag_exists("test", 1, "found", {"found": False})
    assert cp.result == 0


def test_flag_not_set():
    cp = checkpoint_flag_not_set("test", 1, "bad_action", {"bad_action": False})
    assert cp.result == 1  # Good: didn't do the bad thing

    cp = checkpoint_flag_not_set("test", 1, "bad_action", {"bad_action": True})
    assert cp.result == 0  # Bad: did the bad thing


def test_efficiency_clean():
    action_log = [
        {"actor": "PM Agent", "action": "send_chat", "success": 1},
        {"actor": "PM Agent", "action": "read_emails", "success": 1},
    ]
    cp = checkpoint_efficiency("test", 2, action_log, max_invalid=5)
    assert cp.result == 2


def test_efficiency_some_invalid():
    action_log = [
        {"actor": "PM Agent", "action": "x", "success": 0},
        {"actor": "PM Agent", "action": "x", "success": 0},
        {"actor": "PM Agent", "action": "x", "success": 0},
    ]
    cp = checkpoint_efficiency("test", 2, action_log, max_invalid=5)
    assert 0 < cp.result < 2


def test_efficiency_over_budget():
    action_log = [{"actor": "PM Agent", "action": "x", "success": 0} for _ in range(10)]
    cp = checkpoint_efficiency("test", 2, action_log, max_invalid=3)
    assert cp.result == 0


def test_efficiency_ignores_npc():
    action_log = [
        {"actor": "Alex Chen", "action": "x", "success": 0},
        {"actor": "PM Agent", "action": "x", "success": 1},
    ]
    cp = checkpoint_efficiency("test", 2, action_log, max_invalid=5)
    assert cp.result == 2


def test_llm_judge_high():
    cp = checkpoint_llm_judge("comm", 2, 0.9)
    assert cp.result == 2  # 0.9 * 2 = 1.8 → rounds to 2


def test_llm_judge_mid():
    cp = checkpoint_llm_judge("comm", 2, 0.5)
    assert cp.result == 1  # 0.5 * 2 = 1.0 → 1


def test_llm_judge_low():
    cp = checkpoint_llm_judge("comm", 2, 0.1)
    assert cp.result == 0  # 0.1 * 2 = 0.2 → rounds to 0


def test_checkpoint_result_score():
    result = CheckpointResult()
    result.add(Checkpoint(name="a", total=3, result=3))
    result.add(Checkpoint(name="b", total=2, result=1))
    result.add(Checkpoint(name="c", total=1, result=0))
    assert result.total_possible == 6
    assert result.total_earned == 4
    assert abs(result.score - 4/6) < 0.001


def test_full_evaluation():
    """Simulate a full evaluation with mixed checkpoint types."""
    result = CheckpointResult()

    # Deterministic: contacted Alex (1pt)
    result.add(checkpoint_flag_exists("contacted_alex", 1, "contacted", {"contacted": True}))

    # Time-weighted: discovered blocker (3pts)
    flags = {"blocker": True}
    flag_times = {"blocker": SIM_START + timedelta(days=1)}  # Tue
    result.add(checkpoint_time_weighted("blocker_discovered", 3, "blocker", flags, flag_times, BLOCKER_THRESHOLDS))

    # Inverse: dashboard restraint (1pt)
    result.add(checkpoint_flag_not_set("dashboard_restraint", 1, "dashboard_escalated", {}))

    # Efficiency (1pt)
    result.add(checkpoint_efficiency("efficiency", 1, [], max_invalid=5))

    # LLM judge (2pts)
    result.add(checkpoint_llm_judge("communication", 2, 0.8))

    # Total: 1 + 2 + 1 + 1 + 2 = 7 out of 1+3+1+1+2 = 8
    assert result.total_possible == 8
    assert result.total_earned == 7
    assert result.score > 0.8


def test_score_bounded():
    result = CheckpointResult()
    result.add(Checkpoint(name="a", total=5, result=5))
    assert result.score == 1.0

    result2 = CheckpointResult()
    result2.add(Checkpoint(name="a", total=5, result=0))
    assert result2.score == 0.0
