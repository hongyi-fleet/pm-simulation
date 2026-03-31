"""Tests for WorldState — from test plan section 'WorldState (SQLite)'."""

import json

from src.engine.world_state import WorldState


def test_snapshot_save_load():
    """Save at tick N, load, verify all tables match."""
    ws = WorldState(":memory:")
    ws.execute(
        "INSERT INTO messages (tick, channel, sender, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (0, "general", "Alex", "hello", "2025-03-03T09:00"),
    )
    ws.execute(
        "INSERT INTO emails (tick, sender, recipient, subject, body, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (0, "Alex", "PM", "Status", "All good", "2025-03-03T09:00"),
    )
    ws.commit()

    ws.save_snapshot(0)
    snapshot = ws.load_snapshot(0)

    assert snapshot is not None
    assert len(snapshot["messages"]) == 1
    assert snapshot["messages"][0]["sender"] == "Alex"
    assert len(snapshot["emails"]) == 1
    assert snapshot["emails"][0]["subject"] == "Status"


def test_snapshot_json_format():
    """Verify JSON blob is valid and parseable."""
    ws = WorldState(":memory:")
    ws.set_flag("test_flag", True)
    ws.save_snapshot(5)

    row = ws.execute("SELECT state_json FROM snapshots WHERE tick = 5").fetchone()
    assert row is not None
    data = json.loads(row["state_json"])
    assert "messages" in data
    assert "flags" in data
    assert data["flags"]["test_flag"] is True


def test_seed_data_loads():
    """Scenario YAML seed data populates tables correctly."""
    ws = WorldState(":memory:")
    ws.seed_table("tasks", [
        {"project": "Billing", "title": "API integration", "assignee": "Alex", "status": "in_progress", "description": "", "created_tick": 0, "updated_tick": 0},
        {"project": "Billing", "title": "Design review", "assignee": "Priya", "status": "todo", "description": "", "created_tick": 0, "updated_tick": 0},
    ])

    rows = ws.execute("SELECT * FROM tasks").fetchall()
    assert len(rows) == 2
    assert rows[0]["assignee"] == "Alex"
    assert rows[1]["assignee"] == "Priya"


def test_flags():
    ws = WorldState(":memory:")
    assert ws.get_flag("blocker_discovered") is False
    ws.set_flag("blocker_discovered", True)
    assert ws.get_flag("blocker_discovered") is True


def test_action_log():
    ws = WorldState(":memory:")
    ws.log_action(5, "PM Agent", "send_chat", {"channel": "general"}, True)
    ws.log_action(5, "PM Agent", "send_email", {"to": "nobody"}, False, "Unknown recipient")

    log = ws.get_action_log(tick=5)
    assert len(log) == 2
    assert log[0]["success"] == 1
    assert log[1]["success"] == 0
    assert log[1]["error"] == "Unknown recipient"
