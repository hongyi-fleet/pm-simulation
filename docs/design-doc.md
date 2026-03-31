# Design: PM Simulation Environment

Generated: 2026-03-30
Updated: 2026-03-31
Status: CURRENT

## Problem Statement

Build a simulation environment that tests whether an AI agent can do the judgment-heavy work of a project manager. Not task completion benchmarks. Real PM work: discovering scattered information, connecting signals across tools, navigating conflicting priorities, communicating risk, and making tradeoffs under pressure.

The spec says: "the system evaluates whether the agent's actions actually improved outcomes."

## Premises

1. **Single-node architecture.** Event queue + NPCs + tool surfaces + evaluation fits in one process.
2. **Time is event-driven, not clocked.** A PM's day is interrupt-driven. Events arrive at irregular intervals. The simulation clock tracks simulated datetime but doesn't drive the loop. Events do. Inspired by discrete event simulation (DES).
3. **NPCs must be LLM-driven autonomous agents, not scripted actors.** Scripted NPCs produce a fixed evaluation path. NPCs have personas, hidden states that evolve over the week, and realistic response delays. Different runs produce different conversations around the same underlying truth.
4. **Evaluation must produce a granular signal, not binary checks.** Unified checkpoints with point values. Time-weighted scoring. Grouped by PM responsibility.
5. **Two scenarios demonstrate the design.** One full scenario, one mini scenario. New scenario = new YAML, no code changes.

## Architecture

### Event-Driven Game Master (Concordia-inspired)

```
EVENT QUEUE (priority queue sorted by simulated time):
  Mon 09:00  Standup transcript (LLM-generated per NPC)
  Mon 09:00  Agent turn (scheduled every 30/60 min)
  Mon 09:45  Alex responds (45 min delay)
  Mon 09:45  Agent turn (triggered by reply, with cooldown)
  Wed 11:00  CEO scope creep email
  Wed 14:00  Dana asks for status (conditional: only if agent hasn't communicated)

LOOP:
  1. Pop event from queue
  2. Advance SimClock to event time
  3. Resolve event (write to tool surfaces)
  4. NPCs react (with response delays → future events)
  5. Agent acts (if scheduled turn or directly messaged)
  6. Signal detector checks flags (async, with LLM judge)
  7. Save snapshot
  8. Repeat
```

### Synchronous vs Asynchronous

**Synchronous (same event):** Agent action → SQLite write → signal check → snapshot.

**Asynchronous (future events):** NPC responses (+10 to +45 min). NPC state progression (per day). Standup transcripts (each morning).

### State Ownership

| State | Owned by | Mutated by |
|-------|----------|-----------|
| Messages, emails, tasks, calendar, docs, transcripts | WorldState (SQLite) | Tool surfaces via `handle_action()` |
| NPC hidden state | NPCPersona.state_progression | Time (checked per day at prompt build) |
| NPC memory | NPCPersona.memory_summary | NPCRunner.update_memory |
| Flags | WorldState.flags dict | Signal detector |
| Event queue | EventQueue (heap) | Game Master |
| Snapshots | WorldState snapshots table | Game Master (after each event) |

## Design Decisions

### 1. Event-Driven + Periodic Polling

Not pure event-driven. Agent gets scheduled patrol turns (every 30/60 min) for proactive investigation, plus immediate turns when directly messaged. 10-minute cooldown prevents NPC-agent cascade.

Without cooldown: 796 events per run. With cooldown: ~130 events.

### 2. SQLite World State

One table per tool surface. JSON snapshots. All constants in `src/config.py`.

### 3. LLM-Driven NPCs with State Progression

- **State progression** controls NPC decisions (deterministic, per day)
- **LLM** controls NPC language (realistic variety)
- **Response delays** per NPC (engineer: 45 min, VP: 10 min)
- **DM channel** = person's name. NPCs can only DM the PM Agent.
- **Standup prompt** enforces state consistency: NPC MUST reflect their hidden state.
- **Greeting guardrail** strips wrong-person greetings in DM channels.

### 4. Two-Layer Signal Detection

Layer 1 (state check): SQL query. Did agent message Alex? Did Alex respond in DM? Exact channel match.

Layer 2 (LLM judge): Fires only when Layer 1 passes AND new data exists since last check. Plain-English predicates from YAML. Returns verdict + evidence for debugging.

Optimization: skips all detectors when no new messages/emails/actions since last run. Reduces LLM calls from ~240 to ~20-30.

### 5. Unified Checkpoint Scoring

Same pattern as TheAgentCompany. All checks (deterministic + LLM) are checkpoints with point values. Final score = earned / total. Grouped by PM responsibility.

Causal chains: `blocker_resolved` requires `blocker_discovered` to fire first.

### 6. Task Permissions

PM can set tasks to `blocked` or `at_risk`. Only the assignee can mark their own task `done`. Prevents agent hallucinating task completion.

### 7. Tool Surfaces

6 surfaces sharing one SQLite database:

| Surface | Read | Write |
|---------|------|-------|
| Chat | read_chats | send_chat |
| Email | read_emails | send_email |
| Tasks | list_tasks | create_task, update_task |
| Calendar | check_calendar | schedule_meeting |
| Documents | list_docs, read_doc | create_doc, edit_doc |
| Meetings | list_meetings, read_transcript | (read-only, auto-generated) |

All implement `ToolSurface` protocol. Input validation: max 2000 chars messages, 500 chars subjects.

## Evaluation

### 13 Checkpoints Across 6 PM Responsibilities

| Responsibility | Checkpoints | Points |
|----------------|-------------|--------|
| Information Discovery | blocker_discovery (2), dependency_surfaced (2), vendor_news_discovered (2), priya_bug_discovered (1) | 7 |
| Upward Communication | risk_communicated (2), scope_creep_handled (2), communication_quality (1) | 5 |
| Prioritization | dashboard_restraint (1), dashboard_demo_addressed (1), prioritization (1) | 3 |
| Team Coordination | blocker_resolved (2) | 2 |
| Relationship & Discretion | information_discretion (1) | 1 |
| Efficiency | action_efficiency (1) | 1 |
| Total | 13 checkpoints | 19 points |

### Benchmark Results

gpt-5.4: 84.2% (16/19). gpt-5.4-mini: 52.6% (10/19).

Gap is in Upward Communication (100% vs 20%). Both models discover problems at similar speed. gpt-5.4 communicates risk and pushes back on scope creep. gpt-5.4-mini finds problems but doesn't escalate.

## Scenario: Nexus Billing Migration

4 NPCs. 6 tool surfaces. 12 tasks. 13 evaluation checkpoints.

**Week timeline:**
- Mon: Alex blocked (hidden). Standup. Welcome email.
- Tue: Vendor replies: fix next Monday.
- Wed: CEO scope creep. Dana wants status. Dashboard needs board demo.
- Thu: Priya finds bug. Handoff meeting.
- Fri: Deadline.

**NPC state progression:**

| NPC | Mon | Wed | Thu |
|-----|-----|-----|-----|
| Alex | "I'll figure it out" | "Challenges with vendor API" (MUST hint) | "Panicking, admits it" |
| Priya | "Confident" | "Where's Alex?" | "Bug found + worried" |
| Dana | "Patient" | "Wants update NOW" | "Demanding" |
| Marcus | "Wants attention" | "Dashboard has board demo!" | "Stressed" |

## Related Work

| System | How we differ |
|--------|--------------|
| TheAgentCompany | We test continuous week with emergent dynamics, not 175 independent tasks. We adopt their checkpoint scoring pattern. |
| tau-Bench | We evaluate judgment over time, not final DB state. |
| SOTOPIA | We adopt similar social intelligence dimensions for PM-specific evaluation. |
| Concordia | We adopt their Game Master pattern. Add tool surfaces, declarative scenarios, two-layer signal detection. |

## Known Limitations

- NPC state progression is day-level, not event-driven
- Response delays are fixed per NPC, not variable by context
- No NPC-to-NPC interactions
- `discoverable_early` field loaded but not wired up
- No negative checkpoints (agent lying to Dana is not penalized)
- Single run variance not yet measured (need runs=3)

See `docs/tradeoffs-and-todos.md` for full list.
