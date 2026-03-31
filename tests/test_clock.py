"""Tests for SimClock — event-driven passive clock."""

from datetime import datetime, timedelta

from src.engine.clock import SimClock, SIM_START, SIM_END, is_before_time, parse_sim_time


def test_clock_starts_monday_9am():
    clock = SimClock()
    assert clock.current_time == SIM_START
    assert clock.day_name == "Mon"
    assert clock.time_str == "09:00"


def test_advance_to():
    clock = SimClock()
    new_time = SIM_START + timedelta(hours=2)
    clock.advance_to(new_time)
    assert clock.current_time == new_time
    assert clock.time_str == "11:00"


def test_advance_to_does_not_go_backwards():
    clock = SimClock()
    future = SIM_START + timedelta(hours=3)
    clock.advance_to(future)
    clock.advance_to(SIM_START)  # Try to go backwards
    assert clock.current_time == future  # Stays at future


def test_done_at_friday_5pm():
    clock = SimClock()
    assert not clock.done
    clock.advance_to(SIM_END)
    assert clock.done


def test_elapsed_hours():
    clock = SimClock()
    assert clock.elapsed_hours == 0.0
    clock.advance_to(SIM_START + timedelta(hours=4.5))
    assert clock.elapsed_hours == 4.5


def test_is_work_hours():
    clock = SimClock()
    # Monday 9am — work hours
    assert clock.is_work_hours(SIM_START)
    # Monday 8am — before work
    assert not clock.is_work_hours(SIM_START - timedelta(hours=1))
    # Monday 5pm — after work
    assert not clock.is_work_hours(SIM_START + timedelta(hours=8))
    # Saturday — not work
    assert not clock.is_work_hours(SIM_START + timedelta(days=5))


def test_next_work_time():
    clock = SimClock()
    # Friday 6pm → Monday 9am
    friday_evening = SIM_START + timedelta(days=4, hours=9)
    next_work = clock.next_work_time(friday_evening)
    assert next_work.weekday() == 0  # Monday
    assert next_work.hour == 9

    # Monday 7am → Monday 9am
    early_monday = SIM_START - timedelta(hours=2)
    next_work = clock.next_work_time(early_monday)
    assert next_work.hour == 9


def test_is_before_time():
    t1 = SIM_START + timedelta(hours=5)
    t2 = SIM_START + timedelta(hours=10)
    assert is_before_time(t1, t2) is True
    assert is_before_time(t2, t1) is False
    assert is_before_time(t1, t1) is False


def test_parse_sim_time_day_format():
    t = parse_sim_time("Mon 14:00")
    assert t.weekday() == 0  # Monday
    assert t.hour == 14

    t = parse_sim_time("Wed 09:30")
    assert t.weekday() == 2  # Wednesday
    assert t.hour == 9
    assert t.minute == 30


def test_parse_sim_time_iso():
    t = parse_sim_time("2025-03-03T10:00:00")
    assert t.hour == 10
