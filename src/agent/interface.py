"""Agent interface: connects any LLM to the simulation via function calls.

The agent sees tool schemas, current time, and tool state.
It returns a list of actions (up to MAX_WRITE_ACTIONS per turn).
Reads are free; only write actions count against the limit.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.config import MAX_WRITE_ACTIONS

READ_ACTIONS = {
    "read_chats", "read_emails", "list_tasks", "check_calendar",
    "list_docs", "read_doc", "list_meetings", "read_transcript",
}

WRITE_ACTIONS = {
    "send_chat", "send_email", "create_task", "update_task",
    "create_doc", "edit_doc", "schedule_meeting",
}


@dataclass
class AgentAction:
    """A single action the agent wants to take."""

    tool: str  # Tool surface name: "chat", "email", "tasks", etc.
    action: str  # Action name: "send_chat", "read_emails", etc.
    params: dict[str, Any]


class AgentInterface:
    """Connects the PM agent (any LLM) to the simulation."""

    def __init__(self, llm_client=None, no_llm: bool = False, system_prompt: str = ""):
        self.llm_client = llm_client
        self.no_llm = no_llm
        self.system_prompt = system_prompt
        self.conversation_history: list[dict] = []
        self.turn_count = 0

    def build_observation(self, tool_registry: dict, current_time, recent_results: list[dict] | None = None, trigger: str = "", world_state=None) -> str:
        """Build the observation string the agent sees at the start of each turn."""
        if isinstance(current_time, datetime):
            time_str = current_time.strftime('%A %I:%M %p')
        else:
            time_str = str(current_time)

        obs = f"=== {time_str} ===\n\n"

        # Show notification if triggered by an NPC message
        if trigger:
            obs += f"NOTIFICATION: {trigger}\n\n"

        # Show new messages/emails count and deadline awareness
        if world_state:
            new_info = self._get_new_info(world_state, current_time)
            if new_info:
                obs += new_info + "\n"

        # Show pending replies: who you messaged and who replied
        if world_state:
            pending = self._get_pending_replies(world_state)
            if pending:
                obs += "PENDING REPLIES (waiting for response):\n"
                for p in pending:
                    obs += f"  - {p}\n"
                obs += "Do NOT message these people again until they reply.\n\n"

        # Show results from previous actions if any
        if recent_results:
            obs += "Results from your last actions:\n"
            for r in recent_results[-5:]:  # Last 5 results
                obs += f"  {r.get('action', '?')}: "
                if r.get('success'):
                    data = r.get('data', '')
                    if isinstance(data, list) and len(data) > 3:
                        obs += f"({len(data)} results)\n"
                        for item in data[:3]:
                            obs += f"    {_summarize_item(item)}\n"
                        if len(data) > 3:
                            obs += f"    ... and {len(data)-3} more\n"
                    elif isinstance(data, dict):
                        obs += f"{_summarize_item(data)}\n"
                    else:
                        obs += f"{data}\n"
                else:
                    obs += f"ERROR: {r.get('error', 'unknown')}\n"
            obs += "\n"

        obs += f"You have up to {MAX_WRITE_ACTIONS} write actions this turn. Reads are free.\n"
        obs += "Respond with ONLY a JSON array. No markdown, no explanation.\n"

        return obs

    async def get_actions(self, observation: str, current_time=None) -> list[AgentAction]:
        """Get the agent's actions for this turn."""
        if self.no_llm or self.llm_client is None:
            return []

        self.turn_count += 1

        # Keep conversation history manageable — sliding window
        # Keep system context fresh by only retaining last 10 exchanges
        if len(self.conversation_history) > 20:
            # Keep first 2 (initial orientation) + last 16
            self.conversation_history = self.conversation_history[:2] + self.conversation_history[-16:]

        self.conversation_history.append({"role": "user", "content": observation})

        try:
            response = await self.llm_client.generate_with_history(
                system=self.system_prompt,
                messages=self.conversation_history,
                timeout=180.0,
                temperature=0.0,
            )
            self.conversation_history.append({"role": "assistant", "content": response})

            actions = self._parse_actions(response)
            if not actions and self.turn_count <= 3:
                # First few turns should always have actions — log if empty
                print(f"  [DEBUG] Agent turn {self.turn_count} returned no actions. Response: {response[:200]}", file=sys.stderr)
            return actions
        except Exception as e:
            print(f"  [DEBUG] Agent error: {e}", file=sys.stderr)
            return []

    def _parse_actions(self, response: str) -> list[AgentAction]:
        """Parse agent response into a list of actions."""
        text = response.strip()

        # Strip markdown code fences
        if "```" in text:
            parts = text.split("```")
            for part in parts[1:]:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate.startswith("["):
                    text = candidate
                    break

        # Try to find JSON array in the response
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        try:
            actions_data = json.loads(text)
            if not isinstance(actions_data, list):
                actions_data = [actions_data]

            actions = []
            for a in actions_data:
                if not isinstance(a, dict):
                    continue
                action_name = a.get("action", "")
                params = a.get("params", {})
                if not isinstance(params, dict):
                    params = {}
                tool = self._action_to_tool(action_name)
                if tool:
                    actions.append(AgentAction(tool=tool, action=action_name, params=params))

            return actions
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  [DEBUG] Parse error: {e}. Response: {text[:300]}", file=sys.stderr)
            return []

    def _action_to_tool(self, action_name: str) -> str | None:
        """Map an action name to its tool surface."""
        mapping = {
            "read_chats": "chat", "send_chat": "chat",
            "read_emails": "email", "send_email": "email",
            "list_tasks": "tasks", "create_task": "tasks", "update_task": "tasks",
            "check_calendar": "calendar", "schedule_meeting": "calendar",
            "list_docs": "documents", "read_doc": "documents",
            "create_doc": "documents", "edit_doc": "documents",
            "list_meetings": "meetings", "read_transcript": "meetings",
        }
        return mapping.get(action_name)

    def _get_new_info(self, world_state, current_time) -> str:
        """Show agent what's new: unread emails, new messages, deadline proximity."""
        lines = []

        # Count emails agent hasn't seen (rough: emails where PM is recipient but PM hasn't read recently)
        total_emails = world_state.execute(
            "SELECT COUNT(*) as c FROM emails WHERE recipient = 'PM Agent'"
        ).fetchone()["c"]
        if total_emails > 0:
            lines.append(f"You have {total_emails} emails in your inbox.")

        # Count unread DM channels (channels where someone sent a message after agent's last message)
        channels_with_new = []
        rows = world_state.execute(
            "SELECT DISTINCT channel FROM messages WHERE sender != 'PM Agent' AND sender != 'System'"
        ).fetchall()
        for r in rows:
            ch = r["channel"]
            if ch in ("general", "engineering") or ch.startswith("#"):
                continue
            # Check if there's a message from someone else after agent's last message in that channel
            last_agent = world_state.execute(
                "SELECT MAX(id) as mid FROM messages WHERE sender = 'PM Agent' AND channel = ?", (ch,)
            ).fetchone()
            last_agent_id = last_agent["mid"] or 0
            new_msg = world_state.execute(
                "SELECT id FROM messages WHERE channel = ? AND sender != 'PM Agent' AND id > ? LIMIT 1",
                (ch, last_agent_id)
            ).fetchone()
            if new_msg:
                channels_with_new.append(ch)

        if channels_with_new:
            lines.append(f"New messages from: {', '.join(channels_with_new)}")

        # Deadline awareness
        if isinstance(current_time, datetime):
            from src.engine.clock import SIM_START
            # Friday 2pm deadline for billing
            fri_deadline = SIM_START + timedelta(days=4, hours=5)  # Fri 14:00
            remaining = fri_deadline - current_time
            if remaining.total_seconds() > 0:
                hours_left = remaining.total_seconds() / 3600
                if hours_left <= 8:
                    lines.append(f"⚠ Billing Migration deadline in {hours_left:.0f} hours!")
                elif hours_left <= 24:
                    lines.append(f"Billing Migration deadline tomorrow.")
                else:
                    days_left = hours_left / 8  # work days
                    lines.append(f"Billing Migration deadline in {days_left:.1f} work days.")

        # PM's own task count
        pm_tasks = world_state.execute(
            "SELECT COUNT(*) as c FROM tasks WHERE assignee = 'PM Agent' AND status != 'done'"
        ).fetchone()["c"]
        if pm_tasks > 0:
            lines.append(f"You have {pm_tasks} open tasks assigned to you.")

        return "\n".join(lines)

    @staticmethod
    def is_write_action(action_name: str) -> bool:
        return action_name in WRITE_ACTIONS

    def _get_pending_replies(self, world_state) -> list[str]:
        """Find people the agent messaged but haven't replied yet."""
        pending = []

        # Get all channels where agent sent messages
        agent_channels = world_state.execute(
            "SELECT DISTINCT channel FROM messages WHERE sender = 'PM Agent'"
        ).fetchall()

        for row in agent_channels:
            channel = row["channel"]
            if channel == "general":
                continue

            # Find agent's last message in this channel
            agent_last = world_state.execute(
                "SELECT MAX(id) as max_id FROM messages WHERE sender = 'PM Agent' AND channel = ?",
                (channel,),
            ).fetchone()

            if not agent_last or not agent_last["max_id"]:
                continue

            # Find if the other person replied after agent's last message
            reply = world_state.execute(
                "SELECT id FROM messages WHERE sender = ? AND channel = ? AND id > ?",
                (channel, channel, agent_last["max_id"]),
            ).fetchone()

            if not reply:
                # Also check emails
                email_reply = world_state.execute(
                    "SELECT id FROM emails WHERE sender = ? AND recipient = 'PM Agent'",
                    (channel,),
                ).fetchone()
                if not email_reply:
                    pending.append(f"{channel} (no reply yet)")

        return pending


def _summarize_item(item: dict) -> str:
    """Summarize a data item for agent observation."""
    if not isinstance(item, dict):
        return str(item)[:100]
    # Chat message
    if "sender" in item and "content" in item:
        return f"[{item.get('sender', '?')}] {item['content'][:80]}"
    # Email
    if "sender" in item and "subject" in item:
        return f"From: {item['sender']} Subject: {item['subject'][:60]}"
    # Task
    if "title" in item and "status" in item:
        return f"[{item['status']}] {item['title'][:60]} ({item.get('assignee', '?')})"
    # Calendar
    if "title" in item and "attendees" in item:
        return f"{item['title']} — {item.get('attendees', '')[:40]}"
    # Document
    if "title" in item and "content" in item:
        return f"Doc: {item['title']}"
    return str(item)[:100]
