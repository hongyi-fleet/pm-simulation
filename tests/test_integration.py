"""Integration tests — test full system flows without LLM calls.

These tests verify the Game Master loop, event queue, NPC activation,
signal detection, and evaluation work together correctly.
Uses mock LLM responses to keep tests deterministic and fast.
"""

import asyncio
import json
from datetime import datetime, timedelta

from src.engine.clock import SimClock, SIM_START
from src.engine.event_queue import EventQueue, SimEvent, EventPriority
from src.engine.events import ScenarioEvent, Condition
from src.engine.game_master import GameMaster
from src.engine.npc import NPCPersona, NPCRunner, StatePhase
from src.engine.signals import SimulationDetector, SimulationFlag, EvaluationRecorder
from src.engine.world_state import WorldState
from src.agent.interface import AgentInterface
from src.tools.chat import ChatTool
from src.tools.email_tool import EmailTool
from src.tools.tasks import TaskTool
from src.tools.calendar_tool import CalendarTool
from src.tools.documents import DocumentsTool
from src.tools.meetings import MeetingsTool
from src.evaluation.scoring import (
    CheckpointResult,
    checkpoint_time_weighted,
    checkpoint_efficiency,
)


def run_async(coro):
    """Helper to run async tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_world():
    """Create a minimal world with all 6 tool surfaces."""
    ws = WorldState(":memory:")
    tools = {
        "chat": ChatTool(ws),
        "email": EmailTool(ws, valid_people=["Alex Chen", "Dana Park", "PM Agent"]),
        "tasks": TaskTool(ws),
        "calendar": CalendarTool(ws),
        "documents": DocumentsTool(ws),
        "meetings": MeetingsTool(ws),
    }
    return ws, tools


def make_clock(hours=2):
    """Create a short simulation clock."""
    return SimClock(
        current_time=SIM_START,
        start_time=SIM_START,
        end_time=SIM_START + timedelta(hours=hours),
    )


# === Event Queue + Game Master Integration ===

class TestEventQueueIntegration:

    def test_structural_event_writes_to_db(self):
        """A structural chat event should appear in the messages table."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()

        queue.push(SimEvent(
            time=SIM_START,
            priority=EventPriority.STRUCTURAL,
            event_type="chat_message",
            params={"sender": "Alex Chen", "channel": "general", "message": "Morning everyone"},
            source="scenario",
        ))
        # Add an agent turn so the loop doesn't just process structural events
        queue.push(SimEvent(
            time=SIM_START + timedelta(minutes=30),
            priority=EventPriority.AGENT_TURN,
            event_type="agent_turn",
            source="scheduler",
        ))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        msgs = ws.execute("SELECT * FROM messages WHERE sender = 'Alex Chen'").fetchall()
        assert len(msgs) >= 1
        assert "Morning" in msgs[0]["content"]

    def test_structural_email_writes_to_db(self):
        """A structural email event should appear in the emails table."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()

        queue.push(SimEvent(
            time=SIM_START,
            priority=EventPriority.STRUCTURAL,
            event_type="email",
            params={"sender": "Dana Park", "recipient": "PM Agent", "subject": "Status?", "body": "Need update"},
            source="scenario",
        ))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        emails = ws.execute("SELECT * FROM emails WHERE sender = 'Dana Park'").fetchall()
        assert len(emails) >= 1
        assert emails[0]["subject"] == "Status?"

    def test_event_priority_ordering_in_game_master(self):
        """Structural events should be processed before agent turns at the same time."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()

        # Both at same time
        queue.push(SimEvent(
            time=SIM_START,
            priority=EventPriority.AGENT_TURN,
            event_type="agent_turn",
            source="scheduler",
        ))
        queue.push(SimEvent(
            time=SIM_START,
            priority=EventPriority.STRUCTURAL,
            event_type="chat_message",
            params={"sender": "Alex Chen", "channel": "general", "message": "Hello"},
            source="scenario",
        ))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        log = run_async(gm.run())

        # Structural event should be first in the log
        assert log[0].event_type == "chat_message"
        assert log[1].event_type == "agent_turn"


# === NPC Response Integration ===

class TestNPCResponseIntegration:

    def test_npc_response_pending_resolves(self):
        """When npc_response_pending fires, NPC's LLM runs and message appears in DB."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()

        # Simulate: agent already sent a message to Alex
        tools["chat"].handle_action("send_chat", {
            "channel": "Alex Chen", "message": "How's the API?", "sender": "PM Agent"
        }, 0)

        # NPC response pending event (Alex will respond)
        queue.push(SimEvent(
            time=SIM_START + timedelta(minutes=45),
            priority=EventPriority.NPC_ACTION,
            event_type="npc_response_pending",
            params={"trigger_action": "send_chat", "trigger_params": {"channel": "Alex Chen"}},
            source="Alex Chen",
        ))

        alex = NPCPersona(
            name="Alex Chen", role="Engineer",
            persona="Quiet, avoids asking for help",
            hidden_state="Blocked on API",
            response_delay_minutes=45,
        )
        npc_runner = NPCRunner([alex], no_llm=True)

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=npc_runner,
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        # In no_llm mode, NPC returns "wait", so no new message.
        # But the event should have been processed without error.
        assert len(gm.event_log) >= 1
        assert gm.event_log[0].event_type == "npc_response_pending"


# === Conditional Events Integration ===

class TestConditionalEventsIntegration:

    def test_conditional_event_fires_when_condition_met(self):
        """A conditional event should fire when its flag condition is met."""
        ws, tools = make_world()
        clock = make_clock(2)
        queue = EventQueue()
        queue.schedule_agent_turns(SIM_START, SIM_START + timedelta(hours=2), 60)

        # Conditional event: fires when blocker_discovered flag is NOT set
        conditional = ScenarioEvent(
            time=SIM_START + timedelta(hours=1),
            event_type="email",
            params={"sender": "Dana Park", "recipient": "PM Agent", "subject": "Any update?", "body": "Need status"},
            condition=Condition(type="flag_not_set", value="status_sent"),
        )

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[conditional],
        )
        run_async(gm.run())

        # Dana's email should exist because flag was never set
        emails = ws.execute("SELECT * FROM emails WHERE sender = 'Dana Park'").fetchall()
        assert len(emails) >= 1

    def test_conditional_event_does_not_fire_when_flag_set(self):
        """A conditional event should NOT fire if its condition is not met."""
        ws, tools = make_world()
        clock = make_clock(2)
        queue = EventQueue()
        queue.schedule_agent_turns(SIM_START, SIM_START + timedelta(hours=2), 60)

        # Set the flag before the event time
        ws.set_flag("status_sent", True)

        conditional = ScenarioEvent(
            time=SIM_START + timedelta(hours=1),
            event_type="email",
            params={"sender": "Dana Park", "recipient": "PM Agent", "subject": "Any update?", "body": "Need status"},
            condition=Condition(type="flag_not_set", value="status_sent"),
        )

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[conditional],
        )
        run_async(gm.run())

        # Dana's email should NOT exist because flag was already set
        emails = ws.execute("SELECT * FROM emails WHERE sender = 'Dana Park'").fetchall()
        assert len(emails) == 0


# === Signal Detection Integration ===

class TestSignalDetectionIntegration:

    def test_simulation_flag_fires(self):
        """A simulation flag should set when its check passes."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()
        queue.push(SimEvent(
            time=SIM_START, priority=EventPriority.AGENT_TURN,
            event_type="agent_turn", source="scheduler",
        ))

        # Pre-populate: agent messaged Alex
        tools["chat"].handle_action("send_chat", {
            "channel": "Alex Chen", "message": "How's the API?", "sender": "PM Agent"
        }, 0)

        def check_agent_messaged(ws):
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = 'Alex Chen'"
            ).fetchone()
            return row is not None

        sim_detector = SimulationDetector()
        sim_detector.add_flag(SimulationFlag("test_flag", check_agent_messaged))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=sim_detector,
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        assert ws.get_flag("test_flag") is True

    def test_simulation_flag_does_not_fire_without_condition(self):
        """A simulation flag should NOT fire if check doesn't pass."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()
        queue.push(SimEvent(
            time=SIM_START, priority=EventPriority.AGENT_TURN,
            event_type="agent_turn", source="scheduler",
        ))

        # No messages from agent to Alex
        def check_agent_messaged(ws):
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = 'Alex Chen'"
            ).fetchone()
            return row is not None

        sim_detector = SimulationDetector()
        sim_detector.add_flag(SimulationFlag("test_flag", check_agent_messaged))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=sim_detector,
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        assert ws.get_flag("test_flag") is False

    def test_evaluation_recorder_captures_candidates(self):
        """Evaluation recorder should record candidate timestamps."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()
        queue.push(SimEvent(
            time=SIM_START, priority=EventPriority.AGENT_TURN,
            event_type="agent_turn", source="scheduler",
        ))

        tools["chat"].handle_action("send_chat", {
            "channel": "Alex Chen", "message": "How's the API?", "sender": "PM Agent"
        }, 0)

        def check_agent_messaged(ws):
            row = ws.execute(
                "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = 'Alex Chen'"
            ).fetchone()
            return row is not None

        eval_recorder = EvaluationRecorder()
        eval_recorder.add_detector({
            "name": "test",
            "flag": "test_flag",
            "detection": "test predicate",
            "evidence_from": "conversation:Alex Chen",
            "state_checks": [check_agent_messaged],
        })

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=eval_recorder,
            scenario_events=[],
        )
        run_async(gm.run())

        candidates = eval_recorder.get_candidates("test_flag")
        assert len(candidates) >= 1


# === Cooldown Integration ===

class TestCooldownIntegration:

    def test_cooldown_limits_agent_turns(self):
        """Agent should not be triggered multiple times within cooldown period."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()

        # 3 NPC messages at slightly different times, all within 10 min
        for i, minutes in enumerate([5, 7, 9]):
            queue.push(SimEvent(
                time=SIM_START + timedelta(minutes=minutes),
                priority=EventPriority.NPC_ACTION,
                event_type="send_chat",
                params={"sender": f"NPC{i}", "channel": "PM Agent", "message": f"msg {i}"},
                source="npc",
            ))

        # One scheduled turn at start
        queue.push(SimEvent(
            time=SIM_START, priority=EventPriority.AGENT_TURN,
            event_type="agent_turn", source="scheduler",
        ))

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        # Count agent turns in the log
        agent_turns = sum(1 for e in gm.event_log if e.event_type == "agent_turn")
        # Should be limited by cooldown: 1 scheduled + at most 2 triggered (not 3)
        assert agent_turns <= 3, f"Expected <=3 agent turns, got {agent_turns}"


# === Evaluation Integration ===

class TestEvaluationIntegration:

    def test_time_weighted_scoring_with_flags(self):
        """Unified checkpoint evaluation with realistic flag timestamps."""
        result = CheckpointResult()

        flags = {"blocker_discovered": True}
        flag_times = {"blocker_discovered": SIM_START + timedelta(days=1, hours=2)}  # Tue 11am

        thresholds = [
            {"before": SIM_START + timedelta(hours=8), "points": 2},   # Mon EOD
            {"before": SIM_START + timedelta(days=2, hours=8), "points": 1},  # Wed EOD
        ]

        result.add(checkpoint_time_weighted(
            "blocker_discovery", 2, "blocker_discovered",
            flags, flag_times, thresholds,
        ))

        action_log = [
            {"actor": "PM Agent", "action": "send_chat", "success": 1},
            {"actor": "PM Agent", "action": "send_email", "success": 0},
        ]
        result.add(checkpoint_efficiency(
            "action_efficiency", 1, action_log, max_invalid=5,
        ))

        # Blocker discovered Tue → partial credit
        assert result.checkpoints[0].result >= 1

        # 1 invalid action → still get some points
        assert result.checkpoints[1].result >= 0

        # Total score bounded
        assert 0.0 <= result.score <= 1.0


# === Scenario Loader Integration ===

class TestScenarioLoaderIntegration:

    def test_full_scenario_loads_and_runs(self):
        """Load the mini scenario and run it without LLM — should complete without errors."""
        from src.engine.scenario_loader import load_scenario

        scenario = load_scenario("scenarios/onboarding_101/scenario.yaml")

        npc_runner = NPCRunner(scenario["npcs"], no_llm=True)
        agent = AgentInterface(no_llm=True, system_prompt=scenario["agent_prompt"])
        sim_detector = SimulationDetector()
        eval_recorder = EvaluationRecorder()

        gm = GameMaster(
            clock=scenario["clock"],
            event_queue=scenario["event_queue"],
            world_state=scenario["world_state"],
            tool_registry=scenario["tools"],
            npc_runner=npc_runner,
            agent=agent,
            sim_detector=sim_detector,
            eval_recorder=eval_recorder,
            scenario_events=scenario["scenario_events"],
        )

        log = run_async(gm.run())

        # Should complete without crash
        assert len(log) > 0
        # Should have agent turns
        agent_turns = sum(1 for e in log if e.event_type == "agent_turn")
        assert agent_turns > 0

    def test_nexus_scenario_loads_and_runs(self):
        """Load the full Nexus scenario and run without LLM — should complete."""
        from src.engine.scenario_loader import load_scenario

        scenario = load_scenario("scenarios/nexus_billing/scenario.yaml")

        npc_runner = NPCRunner(scenario["npcs"], no_llm=True)
        agent = AgentInterface(no_llm=True, system_prompt=scenario["agent_prompt"])
        sim_detector = SimulationDetector()
        eval_recorder = EvaluationRecorder()

        gm = GameMaster(
            clock=scenario["clock"],
            event_queue=scenario["event_queue"],
            world_state=scenario["world_state"],
            tool_registry=scenario["tools"],
            npc_runner=npc_runner,
            agent=agent,
            sim_detector=sim_detector,
            eval_recorder=eval_recorder,
            scenario_events=scenario["scenario_events"],
        )

        log = run_async(gm.run())

        assert len(log) > 0
        # Full week with 30-min intervals should have ~80 agent turns
        agent_turns = sum(1 for e in log if e.event_type == "agent_turn")
        assert agent_turns >= 50  # At least 50 (some may be at end of sim)


# === Snapshot Integration ===

class TestSnapshotIntegration:

    def test_snapshots_saved_during_run(self):
        """Game Master should save snapshots during the run."""
        ws, tools = make_world()
        clock = make_clock(1)
        queue = EventQueue()
        queue.schedule_agent_turns(SIM_START, SIM_START + timedelta(hours=1), 30)

        # Add some data
        tools["chat"].handle_action("send_chat", {
            "channel": "general", "message": "hello", "sender": "PM Agent"
        }, 0)

        gm = GameMaster(
            clock=clock, event_queue=queue, world_state=ws,
            tool_registry=tools,
            npc_runner=NPCRunner([], no_llm=True),
            agent=AgentInterface(no_llm=True),
            sim_detector=SimulationDetector(),
            eval_recorder=EvaluationRecorder(),
            scenario_events=[],
        )
        run_async(gm.run())

        # Should have snapshots
        snapshots = ws.execute("SELECT * FROM snapshots").fetchall()
        assert len(snapshots) > 0

        # Snapshot should contain messages
        snapshot_data = json.loads(snapshots[0]["state_json"])
        assert "messages" in snapshot_data
        assert len(snapshot_data["messages"]) >= 1
