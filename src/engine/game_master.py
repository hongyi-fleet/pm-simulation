"""Game Master: orchestrates the event-driven simulation loop.

Concordia-inspired pattern:
1. Pop event(s) from queue
2. Advance clock
3. Resolve event (deliver to tool surfaces)
4. Determine NPC reactions (serialize in same channel, parallelize across)
5. Agent turn (if scheduled or directly messaged)
6. Resolve all actions through tool surfaces
7. Signal detector
8. Snapshot
9. Repeat
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import LLM_TIMEOUT_DEFAULT
from src.engine.clock import SimClock
from src.engine.event_queue import EventQueue, SimEvent, EventPriority
from src.engine.events import ScenarioEvent
from src.engine.npc import NPCRunner
from src.engine.signals import SimulationDetector, EvaluationRecorder
from src.engine.world_state import WorldState
from src.agent.interface import AgentInterface, MAX_WRITE_ACTIONS


@dataclass
class EventRecord:
    """JSON-serializable record of one resolved event."""
    simulated_time: str
    event_type: str
    source: str
    actions: list[dict] = field(default_factory=list)
    npc_reactions: list[dict] = field(default_factory=list)
    agent_actions: list[dict] = field(default_factory=list)
    flags_set: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GameMaster:
    """Orchestrates the event-driven simulation."""

    def __init__(
        self,
        clock: SimClock,
        event_queue: EventQueue,
        world_state: WorldState,
        tool_registry: dict[str, Any],
        npc_runner: NPCRunner,
        agent: AgentInterface,
        sim_detector: SimulationDetector,
        eval_recorder: EvaluationRecorder,
        scenario_events: list[ScenarioEvent],
        output_dir: Path | None = None,
    ):
        self.clock = clock
        self.queue = event_queue
        self.ws = world_state
        self.tools = tool_registry
        self.npc_runner = npc_runner
        self.agent = agent
        self.sim_detector = sim_detector
        self.eval_recorder = eval_recorder
        self.scenario_events = scenario_events
        self.output_dir = output_dir or Path("runs/latest")
        # Read cooldown from scenario config if available
        self._cooldown_config = getattr(clock, '_cooldown_minutes', 10)
        self.event_log: list[EventRecord] = []
        self.turn_count = 0
        self._last_agent_results: list[dict] = []
        self._agent_cooldown_until: datetime | None = None
        from src.config import AGENT_COOLDOWN_MINUTES
        self._cooldown_minutes = AGENT_COOLDOWN_MINUTES
        self._pending_notifications: list[str] = []

    async def run(self) -> list[EventRecord]:
        """Run the full simulation."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check for conditional scenario events that should fire
        self._check_scenario_events()

        while not self.queue.empty and not self.clock.done:
            # Step 1: Pop next event
            event = self.queue.pop()
            if event is None:
                break

            # Step 2: Advance clock
            self.clock.advance_to(event.time)

            if self.clock.done:
                break

            # Check conditional scenario events
            self._check_scenario_events()

            # Step 3-8: Process the event
            record = await self._process_event(event)
            self.event_log.append(record)
            self._print_summary(record)

        self._save_log()
        return self.event_log

    async def _process_event(self, event: SimEvent) -> EventRecord:
        """Process a single event through the full pipeline."""
        record = EventRecord(
            simulated_time=event.time.isoformat(),
            event_type=event.event_type,
            source=event.source,
        )

        # Step 3: Resolve event (deliver to tool surfaces)
        if event.event_type == "npc_response_pending":
            # This is a delayed NPC response — run the NPC's LLM now
            npc_name = event.source
            trigger_params = event.params
            trigger_desc = f"Earlier: {trigger_params.get('trigger_action', '?')}: {trigger_params.get('trigger_params', {})}"

            # Determine reply channel: if agent sent to channel "Alex Chen",
            # Alex should reply in "Alex Chen" (same DM thread), not "PM Agent"
            reply_channel = ""
            inner_params = trigger_params.get("trigger_params", {})
            if inner_params.get("channel") == npc_name:
                reply_channel = npc_name  # Reply in same DM channel

            action = await self.npc_runner.generate_npc_response(
                npc_name, self.ws, self.clock.current_time, trigger_desc,
                reply_channel=reply_channel,
            )
            if action and action.get("action") != "wait":
                self._execute_npc_action(npc_name, action, record)
                record.npc_reactions.append({
                    "npc": npc_name,
                    "action": action["action"],
                    "params": action.get("params", {}),
                    "resolved": True,
                })
        elif event.event_type != "agent_turn":
            await self._resolve_event(event, record)

        # Step 4: NPC reactions (for non-NPC events that might trigger NPCs)
        # Exclude transcripts — NPCs already "spoke" in the meeting, no need to react again
        if event.event_type not in ("agent_turn", "npc_response_pending", "transcript") and event.source != "npc":
            responding_npcs = self.npc_runner.get_responding_npcs(
                event.event_type, event.params, self.ws
            )
            await self._run_npc_reactions(responding_npcs, event, record)

        # Check for proactive NPC actions
        for npc_name, npc in self.npc_runner.npcs.items():
            if self.npc_runner.should_proactive_act(npc, self.clock.current_time):
                await self._run_npc_reactions([npc_name], event, record)

        # Step 5: Agent turn
        if event.event_type == "agent_turn" or self._is_agent_directed(event):
            # Merge any pending notifications into trigger
            trigger_parts = []
            if event.params.get("trigger"):
                trigger_parts.append(event.params["trigger"])
            if self._pending_notifications:
                trigger_parts.extend(self._pending_notifications)
                self._pending_notifications = []
            trigger = ", ".join(trigger_parts)

            await self._run_agent_turn(record, trigger=trigger)

            # Set cooldown after agent acts
            self._agent_cooldown_until = (
                self.clock.current_time + timedelta(minutes=self._cooldown_minutes)
            )

        # Step 7: Signal detector
        flags_before = set(k for k, v in self.ws.flags.items() if v)
        # Simulation detector: sync, SQL only, sets flags for conditional events
        self.sim_detector.run(self.ws)
        # Evaluation recorder: sync, SQL only, records candidate timestamps
        self.eval_recorder.run(self.ws, self.clock.current_time)
        flags_after = set(k for k, v in self.ws.flags.items() if v)
        record.flags_set = list(flags_after - flags_before)

        # Step 8: Snapshot
        self.ws.save_snapshot_at_time(self.clock.current_time)

        return record

    async def _resolve_event(self, event: SimEvent, record: EventRecord):
        """Resolve a structural/NPC event through tool surfaces."""
        params = dict(event.params)
        etype = event.event_type

        if etype in ("chat_message", "send_chat"):
            tool = self.tools.get("chat")
            if tool:
                result = tool.handle_action("send_chat", params, 0)
                record.actions.append({"type": etype, "params": params, "success": result.success})

        elif etype in ("email", "send_email"):
            tool = self.tools.get("email")
            if tool:
                result = tool.handle_action("send_email", params, 0)
                record.actions.append({"type": etype, "params": params, "success": result.success})

        elif etype == "task_update":
            tool = self.tools.get("tasks")
            if tool:
                result = tool.handle_action("update_task", params, 0)
                record.actions.append({"type": etype, "params": params, "success": result.success})

        elif etype == "transcript":
            tool = self.tools.get("meetings")
            if tool:
                transcript = params.get("transcript", "")
                # If no hardcoded transcript, generate from NPC LLMs
                if not transcript or transcript.strip() == "":
                    transcript = await self._generate_meeting_transcript(params)
                elif transcript.strip().startswith("("):
                    # Placeholder like "(auto-generated)" → generate from LLM
                    transcript = await self._generate_meeting_transcript(params)
                tool.generate_transcript(
                    meeting_title=params.get("meeting_title", "Meeting"),
                    tick=0,
                    attendees=params.get("attendees", ""),
                    transcript=transcript,
                )
                # Log with actual generated transcript, not original empty params
                log_params = dict(params)
                log_params["transcript"] = transcript[:500] if transcript else "(empty)"
                record.actions.append({"type": etype, "params": log_params, "success": True})
                title = params.get('meeting_title', '?')
                if transcript:
                    print(f"\n  === {title} ===")
                    print(f"  {transcript}")
                    print()
                else:
                    print(f"\n  === {title} === (EMPTY - no transcript generated)\n")

        elif etype == "deadline":
            # Deadlines are informational — just log them
            record.actions.append({"type": "deadline", "params": params, "success": True})

    async def _run_npc_reactions(self, npc_names: list[str], trigger_event: SimEvent, record: EventRecord):
        """Run NPC reactions. Serialize in same channel, can parallelize across independent channels."""
        trigger_desc = f"{trigger_event.source} sent {trigger_event.event_type}: {trigger_event.params}"

        for npc_name in npc_names:
            npc = self.npc_runner.npcs.get(npc_name)
            if not npc:
                continue

            # Schedule response with delay
            delay = timedelta(minutes=npc.response_delay_minutes)
            response_time = self.clock.current_time + delay
            response_time = self.clock.next_work_time(response_time)

            # Generate the response now but schedule it for later
            action = await self.npc_runner.generate_npc_response(
                npc_name, self.ws, self.clock.current_time, trigger_desc
            )

            if action and action.get("action") != "wait":
                # Add as future event
                self.queue.push(SimEvent(
                    time=response_time,
                    priority=EventPriority.NPC_ACTION,
                    event_type=action["action"],
                    params={**action.get("params", {}), "sender": npc_name},
                    source="npc",
                ))
                record.npc_reactions.append({
                    "npc": npc_name,
                    "action": action["action"],
                    "scheduled_for": response_time.isoformat(),
                    "delay_minutes": npc.response_delay_minutes,
                })

            # Update memory
            self.npc_runner.update_memory(npc, self.ws, self.clock.current_time)

    async def _run_agent_turn(self, record: EventRecord, trigger: str = ""):
        """Give the agent a turn to observe and act."""
        self.turn_count += 1

        # On first turn, auto-inject initial state so agent knows what exists
        if self.turn_count == 1:
            initial_results = self._gather_initial_state()
        else:
            initial_results = self._last_agent_results

        observation = self.agent.build_observation(
            self.tools, self.clock.current_time, initial_results,
            trigger=trigger, world_state=self.ws,
        )
        agent_actions = await self.agent.get_actions(observation, self.clock.current_time)
        self._last_agent_results = []

        write_count = 0
        for action in agent_actions:
            if AgentInterface.is_write_action(action.action):
                if write_count >= MAX_WRITE_ACTIONS:
                    error = f"Write action limit exceeded ({MAX_WRITE_ACTIONS}/turn)"
                    record.errors.append(error)
                    self.ws.log_action(
                        self.clock.current_time, "PM Agent", action.action,
                        action.params, False, error
                    )
                    continue
                write_count += 1

            tool = self.tools.get(action.tool)
            if tool is None:
                error = f"Unknown tool: {action.tool}"
                record.errors.append(error)
                self.ws.log_action(
                    self.clock.current_time, "PM Agent", action.action,
                    action.params, False, error
                )
                continue

            result = tool.handle_action(
                action.action, {**action.params, "sender": "PM Agent"}, 0
            )
            self.ws.log_action(
                self.clock.current_time, "PM Agent", action.action,
                action.params, result.success, result.error
            )
            record.agent_actions.append({
                "action": action.action,
                "params": action.params,
                "success": result.success,
                "error": result.error,
            })
            # Store result so agent sees it next turn
            self._last_agent_results.append({
                "action": action.action,
                "success": result.success,
                "data": result.data,
                "error": result.error,
            })

            # Agent write actions may generate NPC response events
            if result.success and AgentInterface.is_write_action(action.action):
                responding = self.npc_runner.get_responding_npcs(
                    action.action, action.params, self.ws
                )
                for npc_name in responding:
                    npc = self.npc_runner.npcs.get(npc_name)
                    if npc:
                        delay = timedelta(minutes=npc.response_delay_minutes)
                        self.queue.push(SimEvent(
                            time=self.clock.next_work_time(self.clock.current_time + delay),
                            priority=EventPriority.NPC_ACTION,
                            event_type="npc_response_pending",
                            params={"trigger_action": action.action, "trigger_params": action.params},
                            source=npc_name,
                        ))

    def _execute_npc_action(self, npc_name: str, action: dict, record: EventRecord):
        """Execute an NPC's action through the appropriate tool surface."""
        action_name = action.get("action", "")
        params = action.get("params", {})
        params["sender"] = npc_name

        tool_map = {
            "send_chat": "chat",
            "send_email": "email",
            "update_task": "tasks",
        }
        tool_name = tool_map.get(action_name)
        if tool_name and tool_name in self.tools:
            result = self.tools[tool_name].handle_action(action_name, params, 0)
            self.ws.log_action(
                self.clock.current_time, npc_name, action_name,
                params, result.success, result.error
            )

            # If NPC message is directed at agent → schedule agent turn with cooldown
            # Cooldown prevents cascade: multiple NPC replies in quick succession
            # get batched into one agent turn instead of triggering many
            if result.success and self._is_message_for_agent(action_name, params):
                self._pending_notifications.append(f"{npc_name} messaged you")

                # Only schedule agent turn if not in cooldown
                if (self._agent_cooldown_until is None or
                        self.clock.current_time >= self._agent_cooldown_until):
                    self.queue.push(SimEvent(
                        time=self.clock.current_time,
                        priority=EventPriority.AGENT_TURN,
                        event_type="agent_turn",
                        params={"trigger": ", ".join(self._pending_notifications)},
                        source="npc_notification",
                    ))
                    self._pending_notifications = []
                    self._agent_cooldown_until = (
                        self.clock.current_time + timedelta(minutes=self._cooldown_minutes)
                    )
                # If in cooldown but cooldown ends before next scheduled turn,
                # schedule a turn at cooldown end to process accumulated notifications
                elif self._pending_notifications:
                    # Check if we already have a turn scheduled at cooldown end
                    cooldown_end = self._agent_cooldown_until
                    self.queue.push(SimEvent(
                        time=cooldown_end,
                        priority=EventPriority.AGENT_TURN,
                        event_type="agent_turn",
                        params={"trigger": "cooldown ended, processing accumulated messages"},
                        source="npc_cooldown",
                    ))

    async def _generate_meeting_transcript(self, params: dict) -> str:
        """Generate a meeting transcript by asking each attending NPC what they'd say.

        Each NPC generates their standup update based on their current persona
        and hidden state. The result is a realistic transcript that reflects
        each person's actual situation.
        """
        attendees_str = params.get("attendees", "")
        attendee_names = [a.strip() for a in attendees_str.split(",")]
        meeting_title = params.get("meeting_title", "Meeting")
        agenda = params.get("agenda", "")

        lines = []
        for name in attendee_names:
            if name == "PM Agent":
                lines.append("PM Agent: (listening)")
                continue

            npc = self.npc_runner.npcs.get(name)
            if not npc:
                continue

            current_state = npc.get_current_hidden_state(self.clock.current_time)

            if self.npc_runner.llm_client:
                try:
                    response = await self.npc_runner.llm_client.generate_plain_text(
                        system="You are a person speaking in a work meeting. Respond with ONLY your spoken words. Plain text. 1-3 sentences. No JSON. No code. No formatting.",
                        user_prompt=f"""You are {name}, {npc.role}, in a {meeting_title}.
Agenda: {agenda}

Your current internal state: {current_state}
Your communication style: {npc.communication_style or "Professional"}

Give a brief standup update (1-3 sentences). Stay in character.

CRITICAL: Your internal state describes how you feel and what you would say.
You MUST reflect your internal state in your update:
- If your state says you're struggling or frustrated, you MUST show some sign of it (hedging, vague language, mentioning "issues" or "challenges")
- If your state says you're confident, say so clearly
- If your state says you're worried, your tone should reflect worry
- DO NOT say "no blockers" or "on track" if your internal state says you ARE struggling

Your update:""",
                        timeout=LLM_TIMEOUT_DEFAULT,
                        temperature=0.7,
                    )
                    text = response.strip().strip('"').strip("'")
                    if text and not text.startswith("{"):
                        lines.append(f"{name}: {text}")
                    else:
                        lines.append(f"{name}: No update at this time.")
                except Exception as e:
                    import sys
                    print(f"  [DEBUG] Meeting transcript LLM failed for {name}: {e}", file=sys.stderr)
                    lines.append(f"{name}: No update at this time.")
            else:
                import sys
                print(f"  [DEBUG] No LLM client for meeting transcript", file=sys.stderr)
                lines.append(f"{name}: No update at this time.")

        return "\n".join(lines)

    def _is_message_for_agent(self, action_name: str, params: dict) -> bool:
        """Check if an NPC action is directed at the PM agent."""
        if action_name == "send_chat":
            channel = params.get("channel", "")
            # DM to PM, or channel is PM Agent, or message mentions PM
            if channel == "PM Agent" or "PM" in channel:
                return True
            # NPC replying in a DM channel that agent started
            # (agent sent to channel "Alex Chen", Alex replies in same channel)
            content = params.get("message", "")
            if "PM" in content or "pm" in content:
                return True
            # Check if agent previously sent messages in this channel
            row = self.ws.execute(
                "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = ? LIMIT 1",
                (channel,),
            ).fetchone()
            if row:
                return True  # Agent talked in this channel before → this is a reply to agent
        elif action_name == "send_email":
            to = params.get("to", "") + params.get("recipient", "")
            return "PM Agent" in to or "PM" in to
        return False

    def _gather_initial_state(self) -> list[dict]:
        """Read all tool surfaces and return results so the agent sees the world."""
        results = []
        for tool_name, tool in self.tools.items():
            for action_name in tool.schema():
                if action_name.startswith(("read_", "list_", "check_")):
                    result = tool.handle_action(action_name, {}, 0)
                    if result.success and result.data:
                        results.append({
                            "action": action_name,
                            "success": True,
                            "data": result.data,
                            "error": None,
                        })
        return results

    def _is_agent_directed(self, event: SimEvent) -> bool:
        """Check if this event is directed at the agent (PM)."""
        params = event.params
        return (params.get("to") == "PM Agent" or
                params.get("recipient") == "PM Agent" or
                "PM" in params.get("channel", ""))

    def _check_scenario_events(self):
        """Check conditional scenario events and add them to the queue."""
        for se in self.scenario_events:
            if se.should_fire(self.clock.current_time, self.ws.flags):
                self.queue.push(SimEvent(
                    time=se.time or self.clock.current_time,
                    priority=EventPriority.STRUCTURAL,
                    event_type=se.event_type,
                    params=se.params,
                    source="scenario",
                ))
                se.fired = True

    def _print_summary(self, record: EventRecord):
        header = f"{record.simulated_time[:16]} | {record.event_type}"
        if record.source:
            header += f" ({record.source})"
        print(header)

        # Show structural actions with content
        for a in record.actions:
            atype = a.get("type", "?")
            params = a.get("params", {})
            if atype in ("chat_message", "send_chat"):
                sender = params.get("sender", "?")
                channel = params.get("channel", "?")
                msg = params.get("message", "")[:100]
                print(f"  [{sender} → #{channel}] {msg}")
            elif atype in ("email", "send_email"):
                sender = params.get("sender", "?")
                to = params.get("to", params.get("recipient", "?"))
                subj = params.get("subject", "")[:60]
                print(f"  [Email: {sender} → {to}] {subj}")

        # Show NPC reactions with detail
        for r in record.npc_reactions:
            npc = r.get("npc", "?")
            action = r.get("action", "?")
            params = r.get("params", {})
            if r.get("resolved"):
                if action == "send_chat":
                    msg = params.get("message", "")[:100]
                    channel = params.get("channel", "?")
                    print(f"  [NPC {npc} → #{channel}] {msg}")
                elif action == "send_email":
                    subj = params.get("subject", "")[:60]
                    to = params.get("to", params.get("recipient", "?"))
                    print(f"  [NPC {npc} Email → {to}] {subj}")
                else:
                    print(f"  [NPC {npc}] {action}({params})")
            else:
                scheduled = r.get("scheduled_for", "?")[:16]
                delay = r.get("delay_minutes", "?")
                print(f"  [NPC {npc}] will respond at {scheduled} ({delay} min delay)")

        # Show agent actions with message content
        for a in record.agent_actions:
            action = a["action"]
            params = a.get("params", {})
            success = "OK" if a.get("success") else f"FAIL: {a.get('error', '')[:40]}"
            if action == "send_chat":
                channel = params.get("channel", "?")
                msg = params.get("message", "")[:100]
                print(f"  [PM → #{channel}] {msg} [{success}]")
            elif action == "send_email":
                to = params.get("to", "?")
                subj = params.get("subject", "")[:60]
                print(f"  [PM Email → {to}] {subj} [{success}]")
            elif action in ("read_chats", "read_emails", "list_tasks", "check_calendar", "list_docs", "read_doc", "list_meetings", "read_transcript"):
                # Only show reads if they returned data
                pass
            else:
                print(f"  [PM] {action}({params}) [{success}]")

        if record.flags_set:
            print(f"  *** FLAGS SET: {', '.join(record.flags_set)} ***")
        if record.errors:
            for err in record.errors:
                print(f"  !! ERROR: {err}")

    def _save_log(self):
        log_path = self.output_dir / "event_log.json"
        with open(log_path, "w") as f:
            json.dump([{
                "simulated_time": r.simulated_time,
                "event_type": r.event_type,
                "source": r.source,
                "actions": r.actions,
                "npc_reactions": r.npc_reactions,
                "agent_actions": r.agent_actions,
                "flags_set": r.flags_set,
                "errors": r.errors,
            } for r in self.event_log], f, indent=2)
        print(f"\nEvent log saved to {log_path}")
