# Agent Turn Policy

## Design Principle

The PM agent is an AI. It has no attention bottleneck. When someone sends it a message, it should respond immediately. There is no reason to simulate "didn't see the notification."

The 30-minute interval is the agent's **proactive patrol frequency** — how often it checks tools when nobody has contacted it. It is NOT a response delay.

## When the Agent Acts

| Trigger | Delay | Why |
|---------|-------|-----|
| NPC replies to agent's DM | Immediate | Agent asked a question, got an answer. Process it now. |
| NPC proactively messages PM | Immediate | Someone is reaching out to you. |
| NPC emails PM Agent | Immediate | Incoming email notification. |
| Structural event directed at PM (e.g., Dana's status request email) | Immediate | Scenario event explicitly targets the agent. |
| NPC chats in #general without mentioning PM | No trigger | You weren't @'d. Wait for patrol. |
| Nothing happening | Every 30 min | Agent proactively checks task board, emails, chat. |

## How It Works

### Immediate Response Path

```
Agent sends chat to Alex ("How's the API going?")
    │
    ▼
Game Master schedules: npc_response_pending at +45 min (Alex's delay)
    │
    ... 45 simulated minutes pass ...
    │
    ▼
npc_response_pending fires → Alex's LLM generates response
    │
    ▼
_execute_npc_action writes Alex's message to SQLite
    │
    ▼
_is_message_for_agent checks: did agent previously send
messages in this channel? → YES (agent started this DM)
    │
    ▼
Immediate agent_turn event pushed to queue
    │
    ▼
Agent sees Alex's reply and acts on it
```

### Proactive Patrol Path

```
No events for 30 minutes
    │
    ▼
Scheduled agent_turn fires
    │
    ▼
Agent reads all tools (chat, email, tasks, calendar, docs)
    │
    ▼
Agent notices something (e.g., Alex's task hasn't moved)
    │
    ▼
Agent takes action (sends message, schedules meeting, etc.)
```

## Detection Logic

```python
def _is_message_for_agent(self, action_name, params):
    if action_name == "send_chat":
        channel = params.get("channel", "")
        # Direct message to PM
        if channel == "PM Agent":
            return True
        # NPC replying in a channel where agent previously sent messages
        row = self.ws.execute(
            "SELECT id FROM messages WHERE sender = 'PM Agent' AND channel = ?",
            (channel,),
        ).fetchone()
        if row:
            return True  # This is a reply to agent's earlier message

    elif action_name == "send_email":
        to = params.get("to", "") + params.get("recipient", "")
        return "PM Agent" in to

    return False
```

## Why Not Delay Agent Responses?

Human PMs have attention constraints: they're in a meeting, they're focused on writing a doc, they didn't hear the notification. AI agents don't have these constraints.

Simulating artificial attention delays for an AI agent would:
1. Add complexity without testing anything meaningful
2. Penalize the agent for something it can't control (the sim's delay policy)
3. Make the evaluation less about PM judgment and more about notification timing

The agent's real constraints are:
- **5 write actions per turn** — can't do everything at once
- **Information is scattered** — must actively look across 6 tools
- **NPCs have response delays** — Alex takes 45 min to reply regardless of how fast the agent reads it

These are the bottlenecks that test PM judgment. Notification timing is not.
