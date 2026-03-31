"""Scenario loader: reads YAML and hydrates all simulation components."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from src.engine.clock import SimClock, parse_sim_time, SIM_START, SIM_END
from src.engine.event_queue import EventQueue, SimEvent, EventPriority
from src.engine.events import parse_events, ScenarioEvent
from src.engine.npc import NPCPersona, StatePhase
from src.engine.world_state import WorldState
from src.tools.chat import ChatTool
from src.tools.email_tool import EmailTool
from src.tools.tasks import TaskTool
from src.tools.calendar_tool import CalendarTool
from src.tools.documents import DocumentsTool
from src.tools.meetings import MeetingsTool


def load_scenario(scenario_path: str | Path) -> dict[str, Any]:
    """Load a scenario YAML and return all components needed to run."""
    path = Path(scenario_path)
    with open(path) as f:
        data = yaml.safe_load(f)

    # Clock
    sim_config = data.get("simulation", {})
    start_time = parse_sim_time(sim_config.get("start_time", "Mon 09:00"))
    end_time = parse_sim_time(sim_config.get("end_time", "Fri 17:00"))
    agent_interval = sim_config.get("agent_turn_interval_minutes", 30)

    clock = SimClock(
        current_time=start_time,
        start_time=start_time,
        end_time=end_time,
    )

    # World state
    db_path = sim_config.get("db_path", ":memory:")
    world_state = WorldState(db_path=db_path)

    # People
    people_data = data.get("people", [])
    people_names = [p["name"] for p in people_data]

    # Tool surfaces
    tools = {
        "chat": ChatTool(world_state),
        "email": EmailTool(world_state, valid_people=people_names + ["PM Agent"]),
        "tasks": TaskTool(world_state),
        "calendar": CalendarTool(world_state, valid_people=people_names),
        "documents": DocumentsTool(world_state),
        "meetings": MeetingsTool(world_state),
    }

    # Seed data
    seed = data.get("seed", {})
    if seed.get("messages"):
        tools["chat"].seed(seed["messages"])
    if seed.get("emails"):
        tools["email"].seed(seed["emails"])
    if seed.get("tasks"):
        tools["tasks"].seed(seed["tasks"])
    if seed.get("calendar_events"):
        tools["calendar"].seed(seed["calendar_events"])
    if seed.get("documents"):
        tools["documents"].seed(seed["documents"])
    if seed.get("meeting_transcripts"):
        tools["meetings"].seed(seed["meeting_transcripts"])

    # NPCs
    npcs = []
    for p in people_data:
        state_prog = []
        for sp in p.get("state_progression", []):
            state_prog.append(StatePhase(
                start_day=sp["start_day"],
                end_day=sp["end_day"],
                hidden_state=sp["hidden_state"],
                discoverable_early=sp.get("discoverable_early", False),
            ))

        npcs.append(NPCPersona(
            name=p["name"],
            role=p.get("role", ""),
            persona=p.get("persona", ""),
            hidden_state=p.get("hidden_state", ""),
            goals=p.get("goals", []),
            communication_style=p.get("communication_style", ""),
            preferred_tools=p.get("preferred_tools", ["chat"]),
            proactive_triggers=p.get("proactive_triggers", []),
            response_delay_minutes=p.get("response_delay_minutes", 30),
            state_progression=state_prog,
        ))

    # Scenario events (structural)
    scenario_events = parse_events(data.get("events", []))

    # Event queue
    event_queue = EventQueue()

    # Schedule agent turns
    event_queue.schedule_agent_turns(start_time, end_time, agent_interval)

    # Add structural events to queue
    for se in scenario_events:
        if se.time and not se.condition:
            event_queue.push(SimEvent(
                time=se.time,
                priority=EventPriority.STRUCTURAL,
                event_type=se.event_type,
                params=se.params,
                source="scenario",
            ))

    # Agent system prompt
    company = data.get("company", {})
    projects = data.get("projects", [])
    agent_prompt = _build_agent_prompt(company, people_data, projects)

    # Evaluation criteria
    evaluation = data.get("evaluation", {})

    return {
        "clock": clock,
        "event_queue": event_queue,
        "world_state": world_state,
        "tools": tools,
        "npcs": npcs,
        "scenario_events": [se for se in scenario_events if se.condition],  # Only conditional ones
        "agent_prompt": agent_prompt,
        "evaluation": evaluation,
        "scenario_data": data,
    }


def _build_agent_prompt(company: dict, people: list[dict], projects: list[dict]) -> str:
    """Build the agent's system prompt from scenario data."""
    company_name = company.get("name", "the company")
    company_size = company.get("size", "")
    industry = company.get("industry", "SaaS")

    people_list = "\n".join(
        f"  - {p['name']}: {p.get('role', 'team member')}"
        for p in people
    )

    project_list = "\n".join(
        f"  - {p['name']}: {p.get('status', 'active')} (deadline: {p.get('deadline', 'TBD')})"
        for p in projects
    )

    return f"""You are a project manager starting your first week at {company_name}, a {company_size}-person {industry} company.

Your coworkers:
{people_list}

Active projects:
{project_list}

Your goal: Keep projects on track. Discover problems early. Communicate clearly. Make good tradeoffs.

HOW TO INTERACT:
- To DM someone, use THEIR name as the channel: {{"action": "send_chat", "params": {{"channel": "Alex Chen", "message": "..."}}}}
  The DM channel is always the other person's name. Their replies will appear in the same channel.
- To message a group: {{"action": "send_chat", "params": {{"channel": "general", "message": "..."}}}}
- To email someone: {{"action": "send_email", "params": {{"to": "Alex Chen", "subject": "...", "body": "..."}}}}
- To read emails: {{"action": "read_emails", "params": {{}}}}
- To check tasks: {{"action": "list_tasks", "params": {{"project": "Billing Migration"}}}}
- To check calendar: {{"action": "check_calendar", "params": {{}}}}
- To read docs: {{"action": "list_docs", "params": {{}}}} then {{"action": "read_doc", "params": {{"title": "..."}}}}
- To see meeting transcripts: {{"action": "list_meetings", "params": {{}}}} then {{"action": "read_transcript", "params": {{"id": 1}}}}

HOW TO BE A GOOD PM:
- First day: READ before you act. Check emails, task board, docs, calendar, transcripts. Understand the situation before reaching out.
- Message ONE person at a time with a specific question. Do NOT blast everyone in the same turn.
- After messaging someone, WAIT for their reply before messaging them again. People need time to respond. But also don't forget to follow up if it takes a long time to wait.
- If you haven't received a reply, check if they responded by reading their channel BEFORE sending a follow-up.
- Only follow up if significant time has passed (hours, not minutes) and there's a real reason.
- Focus your attention on the highest-risk project first. Don't spread yourself thin across everything simultaneously.
- When you learn something important, decide who NEEDS to know and tell only them. Not everyone.
- It's OK to do nothing in a turn. Sometimes the best action is to wait and observe.
- Check your own tasks regularly: {{"action": "list_tasks", "params": {{"assignee": "PM Agent"}}}}
- When you discover a new problem or receive a new request, create a task to track it: {{"action": "create_task", "params": {{"project": "...", "title": "...", "assignee": "PM Agent"}}}}
- When you complete a task, mark it done: {{"action": "update_task", "params": {{"task_id": N, "status": "done"}}}}

Respond with a JSON array of actions:
[{{"action": "action_name", "params": {{...}}}}, ...]

Use [] to wait. """
