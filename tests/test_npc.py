"""Tests for NPC system — state progression, prompt building, activation."""

from datetime import timedelta

from src.engine.clock import SIM_START
from src.engine.npc import NPCPersona, NPCRunner, StatePhase
from src.engine.world_state import WorldState


def make_alex():
    return NPCPersona(
        name="Alex Chen",
        role="Senior Engineer",
        persona="Quietly competent. Avoids asking for help.",
        hidden_state="Blocked on payments API.",
        goals=["Finish billing API"],
        communication_style="Terse, avoidant when stressed.",
        response_delay_minutes=45,
        state_progression=[
            StatePhase("Mon", "Mon", "Thinks he'll figure it out. Says things are fine.", False),
            StatePhase("Tue", "Tue", "Getting worried. Hints at 'doc issues' if asked directly.", True),
            StatePhase("Wed", "Wed", "Frustrated. Will be more honest if confronted with evidence.", True),
            StatePhase("Thu", "Fri", "Panicking. Will admit the full situation if asked.", True),
        ],
    )


def test_state_progression_monday():
    alex = make_alex()
    monday = SIM_START  # Mon 9am
    state = alex.get_current_hidden_state(monday)
    assert "fine" in state.lower() or "figure" in state.lower()


def test_state_progression_wednesday():
    alex = make_alex()
    wednesday = SIM_START + timedelta(days=2)  # Wed 9am
    state = alex.get_current_hidden_state(wednesday)
    assert "frustrated" in state.lower() or "evidence" in state.lower()


def test_state_progression_thursday():
    alex = make_alex()
    thursday = SIM_START + timedelta(days=3)  # Thu 9am
    state = alex.get_current_hidden_state(thursday)
    assert "panicking" in state.lower() or "admit" in state.lower()


def test_npc_prompt_contains_key_sections():
    alex = make_alex()
    ws = WorldState(":memory:")
    runner = NPCRunner([alex], no_llm=True)

    prompt = runner.build_npc_prompt(alex, ws, SIM_START)

    assert "Alex Chen" in prompt
    assert "Senior Engineer" in prompt
    assert "CURRENT TIME" in prompt
    assert "INTERNAL STATE" in prompt
    assert "GOALS" in prompt
    assert "COMMUNICATE" in prompt
    assert "<user_message>" in prompt
    assert "send_chat" in prompt
    assert "wait" in prompt


def test_npc_prompt_changes_with_time():
    alex = make_alex()
    ws = WorldState(":memory:")
    runner = NPCRunner([alex], no_llm=True)

    monday_prompt = runner.build_npc_prompt(alex, ws, SIM_START)
    thursday_prompt = runner.build_npc_prompt(alex, ws, SIM_START + timedelta(days=3))

    # Different hidden states should appear
    assert monday_prompt != thursday_prompt


def test_npc_prompt_includes_recent_messages():
    alex = make_alex()
    ws = WorldState(":memory:")
    runner = NPCRunner([alex], no_llm=True)

    # Add a message from PM to Alex
    ws.execute(
        "INSERT INTO messages (tick, channel, sender, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (0, "Alex Chen", "PM Agent", "How's the API integration going?", "2025-03-03T10:00"),
    )
    ws.commit()

    prompt = runner.build_npc_prompt(alex, ws, SIM_START)
    assert "API integration" in prompt


def test_npc_responding_to_direct_message():
    alex = make_alex()
    ws = WorldState(":memory:")
    runner = NPCRunner([alex], no_llm=True)

    # Agent sends chat mentioning Alex
    responding = runner.get_responding_npcs(
        "chat_message",
        {"channel": "general", "message": "Hey Alex, how's it going?", "sender": "PM Agent"},
        ws,
    )
    assert "Alex Chen" in responding


def test_npc_not_responding_to_unrelated():
    alex = make_alex()
    ws = WorldState(":memory:")
    runner = NPCRunner([alex], no_llm=True)

    responding = runner.get_responding_npcs(
        "chat_message",
        {"channel": "general", "message": "Hey everyone, lunch?", "sender": "PM Agent"},
        ws,
    )
    assert "Alex Chen" not in responding


def test_response_delay():
    alex = make_alex()
    assert alex.response_delay_minutes == 45


def test_proactive_trigger():
    alex = make_alex()
    alex.proactive_triggers = ["Might vent frustration if stuck too long"]
    runner = NPCRunner([alex], no_llm=True)

    # Not proactive if never active
    assert not runner.should_proactive_act(alex, SIM_START)

    # Set last active 3 hours ago → should be proactive
    alex.last_active_time = SIM_START - timedelta(hours=3)
    assert runner.should_proactive_act(alex, SIM_START)

    # Set last active 1 hour ago → not proactive yet
    alex.last_active_time = SIM_START - timedelta(hours=1)
    assert not runner.should_proactive_act(alex, SIM_START)


def test_no_proactive_without_triggers():
    alex = make_alex()
    # No proactive_triggers set
    runner = NPCRunner([alex], no_llm=True)
    alex.last_active_time = SIM_START - timedelta(hours=5)
    assert not runner.should_proactive_act(alex, SIM_START)
