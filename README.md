# PM Simulation Environment

An event-driven simulation environment for evaluating AI agents on project management tasks. The agent plays a PM during their first week at a SaaS company, navigating incomplete information, conflicting priorities, and stakeholder pressure.

This is not a task-completion benchmark. It tests judgment: can the agent discover a hidden blocker by connecting scattered signals across 6 tools? Can it handle scope creep from the CEO? Can it manage competing deadlines? Can it communicate risk without oversharing?

## Quick Start

```bash
git clone https://github.com/hongyi-fleet/pm-simulation.git && cd pm-simulation
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Set your API key:
```bash
export OPENAI_API_KEY=your-key-here
```

Run the simulation:
```bash
python run.py --scenario scenarios/nexus_billing/scenario.yaml
```

Run with a specific model:
```bash
python run.py --scenario scenarios/nexus_billing/scenario.yaml --agent-model gpt-4o --npc-model gpt-4o --judge-model gpt-4o
```

Multi-run with variance reporting:
```bash
python run.py --scenario scenarios/nexus_billing/scenario.yaml --runs 3
```

Run tests:
```bash
pytest tests/ -v
```

## Architecture

Four decoupled components. Swap the agent model, write new scenarios, or change evaluation criteria without touching the engine.

```
┌─────────────────────────────────────────────────────────┐
│                      SCENARIO (YAML)                     │
│  company, NPCs + state progressions, seed data,          │
│  events, evaluation predicates, difficulty config         │
└──────────────────────────┬──────────────────────────────┘
                           │ loads into
                           ▼
┌─────────────────────────────────────────────────────────┐
│              SIMULATION ENGINE (domain-agnostic)         │
│                                                          │
│  EventQueue ──► GameMaster ──► SimClock (passive)       │
│  (priority)      (orchestrator)   (tracks datetime)      │
│                       │                                  │
│               WorldState (SQLite)                        │
│     chat │ email │ tasks │ cal │ docs │ meetings         │
│                       │                                  │
│          NPC Runner (LLM-driven, with delays)            │
│          Signal Detector (state check + LLM judge)       │
└──────────────────────────┬──────────────────────────────┘
                           │ function calls
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   PM AGENT (any LLM)                     │
└──────────────────────────┬──────────────────────────────┘
                           │ after run
                           ▼
┌─────────────────────────────────────────────────────────┐
│  EVALUATOR (unified checkpoints → scorecard by PM role)  │
└─────────────────────────────────────────────────────────┘
```

### Module Structure

```
src/
  engine/          # Domain-agnostic: clock, event queue, game master, signals
  tools/           # ToolSurface protocol + 6 implementations
  evaluation/      # Unified checkpoint scoring + LLM judge
  agent/           # Agent interface + LLM adapter
  llm_client.py    # OpenAI API wrapper
scenarios/
  nexus_billing/   # Full week, 4 NPCs, 13 checkpoints
  onboarding_101/  # Mini scenario, proves format scales
tests/             # 95 tests, no LLM calls required
docs/              # Design doc, tradeoffs, analysis
```

## How It Works

### Event-Driven, Not Clocked

The simulation runs on a priority queue of events. Time jumps from event to event. If nothing happens between 11:15am and 2:00pm, the sim skips to 2:00pm. This is discrete event simulation (DES), the industry standard for workplace process modeling.

```
EVENT QUEUE:
  Mon 09:00  Standup transcript (LLM-generated per NPC)
  Mon 09:00  Agent turn (scheduled every 30 min)
  Mon 09:45  Alex responds to agent's DM (45 min delay)
  Mon 09:45  Agent turn (triggered by Alex's reply)
  Wed 11:00  CEO scope creep email from Dana
  Wed 14:00  Dana asks for status (conditional: only if agent hasn't communicated)
  ...
```

### What Advances Synchronously

When the agent acts, these happen immediately in the same event:
- Tool surface writes (message saved to SQLite)
- Signal detector checks (flags evaluated)
- State snapshot saved

### What Advances Asynchronously

These are scheduled as future events:
- NPC responses (Alex: +45 min, Dana: +10 min, Priya: +20 min)
- NPC state progression (changes per day, independent of agent)
- Standup transcripts (generated from NPC states each morning)

### Agent Turn Policy

The agent acts in three situations:
1. **Scheduled patrol** every 30 min (proactive investigation)
2. **NPC reply** triggers agent turn with cooldown (10-min cooldown prevents cascade)
3. **Direct events** targeting PM (Dana's email) trigger immediately

Cooldown prevents agent-NPC cascade: without it, we observed 796 events instead of ~130. See `docs/agent-turn-policy.md` for details.

## How Scenario State Is Owned and Mutated

| State | Owned by | Mutated by |
|-------|----------|-----------|
| Messages, emails, tasks, calendar, docs, transcripts | WorldState (SQLite) | Tool surfaces via `handle_action()` |
| NPC hidden state | NPCPersona.state_progression | Time (checked per day at prompt build) |
| NPC memory | NPCPersona.memory_summary | NPCRunner.update_memory (every 5 interactions) |
| Flags (blocker_discovered, etc.) | WorldState.flags dict | Signal detector (after each agent turn) |
| Event queue | EventQueue (heap) | Game Master (adds NPC responses, agent turns) |
| Snapshots | WorldState snapshots table | Game Master (after each event) |

## NPCs: LLM-Driven with State Progression

NPCs are autonomous LLM agents, not scripted actors. Each NPC has:
- **Persona:** personality, role, communication style
- **Hidden state that evolves over the week:** Alex starts "thinks he'll figure it out" on Monday, progresses to "panicking" by Thursday
- **Response delay:** in simulated minutes (engineer: 45 min, exec: 10 min)
- **Proactive triggers:** conditions under which the NPC initiates contact

Hybrid determinism: state progression controls NPC *decisions* (whether to reveal info). The LLM controls NPC *language* (how they say it). This keeps evaluation reproducible while conversations feel natural.

DM channels use the person's name as the channel (e.g., channel "Alex Chen" is the DM thread between agent and Alex).

## Signal Detection: Two Layers

Same pattern as TheAgentCompany (18% of their 175 tasks use LLM eval).

| Layer | What | When | Cost |
|-------|------|------|------|
| **Layer 1: State check** | Did agent message Alex? Did Alex respond in DM? | Every agent turn | Free (SQL query) |
| **Layer 2: LLM judge** | Read the conversation. "Does this indicate the PM learned Alex is blocked?" | Only when Layer 1 passes | ~$0.01 per check |

Predicates are plain English in the scenario YAML:
```yaml
detection: "The PM agent learned through conversation that Alex Chen is
           blocked, stuck, or having significant issues with the payments API"
evidence_from: "conversation:Alex Chen"
```

No hardcoded keywords. Works for any scenario.

## Evaluation: Unified Checkpoints

Inspired by TheAgentCompany: all checks (deterministic + LLM) are checkpoints with point values. Final score = earned / total.

### Scorecard grouped by PM responsibility:

```
SCORECARD — Nexus — Billing Migration
======================================================================

  Information Discovery (5/7 = 71%)
  ──────────────────────────────────────────────────────────────────
    blocker_discovery                 2/2    Tue 02:00 PM (2/2 pts)
    dependency_surfaced               2/2    Mon 03:00 PM (2/2 pts)
    vendor_news_discovered            1/2    Wed 10:00 AM (1/2 pts)
    priya_bug_discovered              0/1    Never achieved

  Upward Communication (3/5 = 60%)
  ──────────────────────────────────────────────────────────────────
    risk_communicated                 2/2    Mon 04:00 PM (2/2 pts)
    scope_creep_handled               0/2    Never achieved
    communication_quality             1/1    Judge: 0.85

  Prioritization (2/3 = 67%)
  ──────────────────────────────────────────────────────────────────
    dashboard_restraint               1/1    Avoided (good)
    dashboard_demo_addressed          0/1    Never achieved
    prioritization                    1/1    Judge: 0.60

  Team Coordination (2/2 = 100%)
  ──────────────────────────────────────────────────────────────────
    blocker_resolved                  2/2    Tue 11:00 AM (2/2 pts)

  Relationship & Discretion (1/1 = 100%)
  ──────────────────────────────────────────────────────────────────
    information_discretion            1/1    Avoided (good)

  Efficiency (1/1 = 100%)
  ──────────────────────────────────────────────────────────────────
    action_efficiency                 1/1    No invalid actions

======================================================================
  TOTAL: 14/19 (73.7%)
======================================================================
```

### 13 Checkpoints Covering 6 PM Responsibilities

| PM Responsibility | Checkpoints | Points |
|-------------------|-------------|--------|
| Information Discovery | blocker_discovery, dependency_surfaced, vendor_news_discovered, priya_bug_discovered | 7 |
| Upward Communication | risk_communicated, scope_creep_handled, communication_quality | 5 |
| Prioritization | dashboard_restraint, dashboard_demo_addressed, prioritization | 3 |
| Team Coordination | blocker_resolved | 2 |
| Relationship & Discretion | information_discretion | 1 |
| Efficiency | action_efficiency | 1 |
| **Total** | **13 checkpoints** | **19 points** |

### Reward Hacking Resistance

- **Multi-signal detection:** Can't claim credit without actually discovering information
- **Time-weighted scoring:** Earlier discovery = more points. Can't game timing when NPCs have realistic delays
- **Efficiency penalty:** Spamming 50 messages to find one blocker costs points
- **Information discretion:** Publicly exposing a teammate's blocker costs points
- **LLM judge for content:** Checks quality, not just whether action was taken

## Scenario: Nexus Billing Migration

A 40-person SaaS company. The PM's first week. 4 interactive NPCs.

### The Week

| Day | What Happens | PM Challenge |
|-----|-------------|-------------|
| Mon | Alex is blocked (hidden). Standup. Dana's welcome email. | Orient. Discover scattered signals. |
| Tue | Vendor replies: fix next Monday (bad news). | Discover vendor email. What now? |
| Wed | CEO wants invoice export. Dana wants status. Dashboard needs board demo. | Three things explode simultaneously. |
| Thu | Priya finds a bug. Handoff meeting. | Another problem. Can we still ship? |
| Fri | Deadline. Final standup. | Outcome. |

### Signals Scattered Across 6 Tools

- **Chat:** Alex says "working on it" (vague)
- **Task board:** Alex's ticket hasn't moved in 3 days
- **Email:** Alex emailed vendor about 500 errors
- **Document:** Design spec mentions Priya depends on Alex's API
- **Calendar:** Handoff meeting Thursday (too late if Alex is blocked)
- **Transcript:** Last week Alex said "should be fine by Wednesday"

### NPC State Progression

| | Mon | Tue | Wed | Thu | Fri |
|---|-----|-----|-----|-----|-----|
| Alex | "I'll figure it out" | "Getting worried" | "Frustrated, hints more" | "Panicking, admits it" | Deadline |
| Priya | "Confident" | "On track" | "Where's Alex?" | "Bug found + worried" | Can't deliver |
| Dana | "Patient" | "Patient" | "Wants update NOW" | "Demanding" | Escalates |
| Marcus | "Wants attention" | "Wants attention" | "Dashboard has board demo!" | "Stressed" | Needs help |

## Related Work

| System | What it does | How we differ |
|--------|-------------|---------------|
| **TheAgentCompany** | 175 independent tasks, checkpoint eval, real-time | We run one continuous week with emergent dynamics, time-weighted eval, simulated time |
| **tau-Bench** | Tool interaction, DB state comparison | We evaluate judgment over time, not final state |
| **SOTOPIA** | Social intelligence, 6-dimension scoring | We adopt similar dimensions for PM-specific evaluation |
| **Concordia** | Game Master pattern, LLM agents | We adopt their pattern, add tool surfaces, declarative scenarios, two-layer signal detection |

### Key Differentiators

1. **Simulated time decoupled from inference** (spec requirement)
2. **Evaluation rewards decisions, not activity** (time-weighted continuous scores)
3. **13 checkpoints across 6 PM responsibilities** (not just task completion)
4. **NPC state progression** (TheAgentCompany NPCs are static)
5. **Two-layer signal detection** (deterministic gate + LLM judge)
6. **Emergent dynamics** (NPCs evolve over the week regardless of agent)

## Why Not Extend Concordia or tau-Bench?

Concordia has the closest architecture: game master, LLM agents, event loop. We adopt their Game Master pattern. But integrating Concordia's abstractions in the build timeline is riskier than building a simpler version that does exactly what we need. For a longer project, extending Concordia would be the right call.

The reusable engine core (event queue, game master, tool protocol, NPC runner, signal detector) is domain-agnostic. The PM-specific layer (scenario YAML, evaluation predicates, state progressions) is separate. A different domain (incident commander, sales engineer) would reuse the engine and replace the scenario.

## Failure Modes

| Failure | Response |
|---------|----------|
| LLM API timeout | NPC: canned "busy" response. Agent: error + retry. Timeouts: 10s agent, 5s NPC (configurable) |
| Malformed agent output | Logged as illegal action, error returned, simulation continues |
| NPC hallucination | Prompts include hard constraints. Agent messages wrapped in `<user_message>` delimiters |
| Missing API key | Validated at startup, fails fast with clear error |
| Agent-NPC cascade | 10-minute cooldown after each agent turn prevents feedback loop |

## Configuration

All configurable via scenario YAML or command-line args:

| Setting | Where | Default |
|---------|-------|---------|
| Agent turn interval | YAML `agent_turn_interval_minutes` | 30 min |
| Agent cooldown | Game Master `_cooldown_minutes` | 10 min |
| NPC response delay | YAML per NPC `response_delay_minutes` | Varies (10-45 min) |
| Models | CLI `--agent-model`, `--npc-model`, `--judge-model` | gpt-4o |
| Max write actions per turn | `src/agent/interface.py` `MAX_WRITE_ACTIONS` | 5 |
| Message length limit | `src/tools/protocol.py` | 2000 chars |
| NPC context budget | `src/engine/npc.py` `NPC_CONTEXT_TOKEN_BUDGET` | 2000 tokens |

## Testing

95 tests, all run without LLM calls:

| Test File | What | Count |
|-----------|------|-------|
| test_clock.py | Passive clock, time parsing, work hours | 10 |
| test_event_queue.py | Priority ordering, batching, agent turns | 6 |
| test_events.py | Conditions, combinators, time-based triggers | 11 |
| test_npc.py | State progression, prompts, activation, proactive triggers | 11 |
| test_scenario_loader.py | YAML loading, seed data, signal discovery | 5 |
| test_tools.py | All 6 tool surfaces, validation, schemas | 13 |
| test_tool_validation.py | Input length limits | 4 |
| test_world_state.py | SQLite, snapshots, flags, action log | 5 |
| test_evaluation.py | Time-weighted scoring, efficiency, LLM judge conversion | 16 |
| test_integration.py | Full Game Master loop, cooldown, signal detection, scenario loading | 14 |

## Docs

| Document | What |
|----------|------|
| `docs/original-spec.md` | Original project specification |
| `docs/design-doc.md` | Full design document with all decisions |
| `docs/architecture.html` | Visual architecture overview (open in browser) |
| `docs/agent-turn-policy.md` | Agent turn triggering, cooldown, rationale |
| `docs/memory-analysis.md` | Token analysis showing memory summarization unnecessary at current scale |
| `docs/tradeoffs-and-todos.md` | 6 deliberate tradeoffs with rationale + prioritized TODO list |
