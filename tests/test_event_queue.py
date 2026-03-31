"""Tests for EventQueue — priority queue with timestamp + priority ordering."""

from datetime import datetime, timedelta

from src.engine.event_queue import EventQueue, SimEvent, EventPriority
from src.engine.clock import SIM_START


def test_basic_ordering():
    q = EventQueue()
    t1 = SIM_START
    t2 = SIM_START + timedelta(hours=1)
    q.push(SimEvent(time=t2, priority=EventPriority.STRUCTURAL, event_type="later"))
    q.push(SimEvent(time=t1, priority=EventPriority.STRUCTURAL, event_type="earlier"))

    first = q.pop()
    assert first.event_type == "earlier"
    second = q.pop()
    assert second.event_type == "later"


def test_same_time_priority_ordering():
    """Structural events resolve before NPC events at same timestamp."""
    q = EventQueue()
    t = SIM_START
    q.push(SimEvent(time=t, priority=EventPriority.AGENT_TURN, event_type="agent"))
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="meeting"))
    q.push(SimEvent(time=t, priority=EventPriority.NPC_ACTION, event_type="npc"))

    assert q.pop().event_type == "meeting"    # STRUCTURAL first
    assert q.pop().event_type == "npc"         # NPC_ACTION second
    assert q.pop().event_type == "agent"       # AGENT_TURN last


def test_insertion_order_tiebreaker():
    """Same time + same priority → insertion order."""
    q = EventQueue()
    t = SIM_START
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="first"))
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="second"))
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="third"))

    assert q.pop().event_type == "first"
    assert q.pop().event_type == "second"
    assert q.pop().event_type == "third"


def test_pop_batch():
    """Pop all events at same time and priority."""
    q = EventQueue()
    t = SIM_START
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="a"))
    q.push(SimEvent(time=t, priority=EventPriority.STRUCTURAL, event_type="b"))
    q.push(SimEvent(time=t, priority=EventPriority.NPC_ACTION, event_type="npc"))

    batch = q.pop_batch()
    assert len(batch) == 2  # Only the STRUCTURAL ones
    assert batch[0].event_type == "a"
    assert batch[1].event_type == "b"

    # NPC event still in queue
    assert q.pop().event_type == "npc"


def test_empty_queue():
    q = EventQueue()
    assert q.empty
    assert q.pop() is None
    assert q.pop_batch() == []


def test_schedule_agent_turns():
    q = EventQueue()
    start = SIM_START
    end = SIM_START + timedelta(hours=2)
    q.schedule_agent_turns(start, end, interval_minutes=30)

    assert len(q) == 4  # 0:00, 0:30, 1:00, 1:30
    event = q.pop()
    assert event.event_type == "agent_turn"
    assert event.priority == EventPriority.AGENT_TURN
