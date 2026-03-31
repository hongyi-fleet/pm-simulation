"""Tests for conditional events — time-based conditions."""

from datetime import datetime, timedelta

from src.engine.clock import SIM_START
from src.engine.events import Condition, ScenarioEvent, parse_condition


MON_9 = SIM_START
TUE_9 = SIM_START + timedelta(days=1)
WED_14 = SIM_START + timedelta(days=2, hours=5)


def test_time_after():
    cond = Condition(type="time_after", value=WED_14)
    assert cond.evaluate(MON_9, {}) is False
    assert cond.evaluate(WED_14, {}) is False  # Not after, at
    assert cond.evaluate(WED_14 + timedelta(minutes=1), {}) is True


def test_time_before():
    cond = Condition(type="time_before", value=WED_14)
    assert cond.evaluate(MON_9, {}) is True
    assert cond.evaluate(WED_14, {}) is False  # Not before, at
    assert cond.evaluate(WED_14 + timedelta(hours=1), {}) is False


def test_flag_not_set():
    cond = Condition(type="flag_not_set", value="blocker_discovered")
    assert cond.evaluate(MON_9, {}) is True
    assert cond.evaluate(MON_9, {"blocker_discovered": False}) is True
    assert cond.evaluate(MON_9, {"blocker_discovered": True}) is False


def test_flag_set():
    cond = Condition(type="flag_set", value="blocker_discovered")
    assert cond.evaluate(MON_9, {}) is False
    assert cond.evaluate(MON_9, {"blocker_discovered": True}) is True


def test_all_combinator():
    cond = Condition(
        type="all",
        children=[
            Condition(type="time_after", value=TUE_9),
            Condition(type="flag_not_set", value="resolved"),
        ],
    )
    assert cond.evaluate(MON_9, {}) is False
    assert cond.evaluate(TUE_9 + timedelta(hours=1), {}) is True
    assert cond.evaluate(TUE_9 + timedelta(hours=1), {"resolved": True}) is False


def test_any_combinator():
    cond = Condition(
        type="any",
        children=[
            Condition(type="flag_set", value="a"),
            Condition(type="flag_set", value="b"),
        ],
    )
    assert cond.evaluate(MON_9, {}) is False
    assert cond.evaluate(MON_9, {"a": True}) is True
    assert cond.evaluate(MON_9, {"b": True}) is True


def test_nested_combinators():
    cond = Condition(
        type="all",
        children=[
            Condition(type="time_after", value=TUE_9),
            Condition(
                type="any",
                children=[
                    Condition(type="flag_set", value="a"),
                    Condition(type="flag_set", value="b"),
                ],
            ),
        ],
    )
    assert cond.evaluate(MON_9, {"a": True}) is False  # Too early
    assert cond.evaluate(TUE_9 + timedelta(hours=1), {}) is False  # No flags
    assert cond.evaluate(TUE_9 + timedelta(hours=1), {"a": True}) is True


def test_always():
    cond = Condition(type="always")
    assert cond.evaluate(MON_9, {}) is True


def test_scenario_event_should_fire():
    event = ScenarioEvent(
        time=WED_14,
        event_type="email",
        params={"sender": "Dana"},
        condition=Condition(type="flag_not_set", value="status_sent"),
    )
    assert event.should_fire(MON_9, {}) is False  # Too early
    assert event.should_fire(WED_14, {}) is True   # Right time, flag not set
    assert event.should_fire(WED_14, {"status_sent": True}) is False  # Flag set

    event.fired = True
    assert event.should_fire(WED_14, {}) is False  # Already fired


def test_parse_condition_string():
    cond = parse_condition("some_flag")
    assert cond.type == "flag_not_set"
    assert cond.value == "some_flag"


def test_parse_condition_dict():
    cond = parse_condition({"flag_set": "discovered"})
    assert cond.type == "flag_set"
    assert cond.value == "discovered"
