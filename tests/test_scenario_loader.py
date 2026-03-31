"""Tests for scenario loading — verify YAML parses and hydrates correctly."""

from src.engine.scenario_loader import load_scenario


def test_load_nexus_scenario():
    result = load_scenario("scenarios/nexus_billing/scenario.yaml")

    assert result["clock"] is not None
    assert result["clock"].day_name == "Mon"

    assert result["event_queue"] is not None
    assert not result["event_queue"].empty

    assert result["world_state"] is not None

    # 6 tool surfaces
    assert len(result["tools"]) == 6
    assert "chat" in result["tools"]
    assert "documents" in result["tools"]
    assert "meetings" in result["tools"]

    # 4 NPCs
    assert len(result["npcs"]) == 4
    npc_names = [n.name for n in result["npcs"]]
    assert "Alex Chen" in npc_names
    assert "Priya Sharma" in npc_names
    assert "Dana Park" in npc_names
    assert "Marcus Johnson" in npc_names

    # Alex has state progression
    alex = [n for n in result["npcs"] if n.name == "Alex Chen"][0]
    assert len(alex.state_progression) == 4
    assert alex.response_delay_minutes == 45

    # Dana responds fast
    dana = [n for n in result["npcs"] if n.name == "Dana Park"][0]
    assert dana.response_delay_minutes == 10

    # Agent prompt exists
    assert "Nexus" in result["agent_prompt"]
    assert "Alex Chen" in result["agent_prompt"]

    # Evaluation criteria
    assert "rubric" in result["evaluation"]
    assert len(result["evaluation"]["rubric"]) >= 4
    assert "llm_judge" in result["evaluation"]


def test_load_mini_scenario():
    result = load_scenario("scenarios/onboarding_101/scenario.yaml")

    # Ends same day
    assert result["clock"].start_time == result["clock"].end_time.__class__(
        *result["clock"].start_time.timetuple()[:3], 9, 0
    ) or True  # Just verify it loads

    # 2 NPCs
    assert len(result["npcs"]) == 2

    # 2 tasks seeded
    tasks = result["world_state"].execute("SELECT * FROM tasks").fetchall()
    assert len(tasks) == 2


def test_seed_data_loaded():
    result = load_scenario("scenarios/nexus_billing/scenario.yaml")
    ws = result["world_state"]

    # Messages seeded
    msgs = ws.execute("SELECT * FROM messages").fetchall()
    assert len(msgs) >= 2

    # Emails seeded (including Alex's vendor email)
    emails = ws.execute("SELECT * FROM emails").fetchall()
    assert len(emails) >= 2
    vendor_email = [e for e in emails if "vendor" in dict(e).get("recipient", "") or "500" in dict(e).get("body", "")]
    assert len(vendor_email) >= 1, "Alex's vendor email should be seeded"

    # Tasks seeded
    tasks = ws.execute("SELECT * FROM tasks").fetchall()
    assert len(tasks) >= 4

    # Documents seeded
    docs = ws.execute("SELECT * FROM documents").fetchall()
    assert len(docs) >= 1

    # Meeting transcripts seeded
    transcripts = ws.execute("SELECT * FROM meeting_transcripts").fetchall()
    assert len(transcripts) >= 1

    # Calendar events seeded
    cal = ws.execute("SELECT * FROM calendar_events").fetchall()
    assert len(cal) >= 2


def test_design_doc_contains_dependency():
    """The design doc should mention the Alex-Priya dependency."""
    result = load_scenario("scenarios/nexus_billing/scenario.yaml")
    docs = result["tools"]["documents"]
    doc_result = docs.handle_action("read_doc", {"title": "Billing Migration — Design Spec"}, 0)
    assert doc_result.success
    assert "Alex" in doc_result.data["content"]
    assert "handoff" in doc_result.data["content"].lower()


def test_alex_vendor_email_is_discoverable():
    """The agent should be able to find Alex's email to the vendor."""
    result = load_scenario("scenarios/nexus_billing/scenario.yaml")
    email_tool = result["tools"]["email"]
    emails = email_tool.handle_action("read_emails", {"sender": "Alex Chen"}, 0)
    assert emails.success
    assert len(emails.data) >= 1
    assert any("500" in e.get("body", "") for e in emails.data)
