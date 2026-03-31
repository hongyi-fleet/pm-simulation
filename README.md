# PM Simulation Environment

An event-driven simulation where an AI agent plays a project manager during their first week at a SaaS company. The simulation tests PM judgment: information discovery, prioritization, communication, and decision-making under pressure.

## Quick Start

```bash
git clone https://github.com/hongyi-fleet/pm-simulation.git && cd pm-simulation
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your-key-here
python run.py --scenario scenarios/nexus_billing/scenario.yaml
```

Options:
```bash
python run.py --scenario scenarios/nexus_billing/scenario.yaml --agent-model gpt-4o --npc-model gpt-4o
python run.py --scenario scenarios/nexus_billing/scenario.yaml --runs 3  # variance reporting
pytest tests/ -v  # 95 tests, no LLM calls
```

## Architecture

```
SCENARIO (YAML)  →  ENGINE (event-driven)  →  AGENT (any LLM)  →  EVALUATOR
  company             EventQueue                function calls       checkpoints
  NPCs + states       GameMaster                read/write tools     by PM role
  seed data           WorldState (SQLite)
  eval predicates     NPC Runner + Signals
```

Event-driven: time jumps from event to event. No fixed ticks. NPCs respond with realistic delays. Agent gets turns every 30 min + immediately when messaged (with 10-min cooldown to prevent cascade).

### What Advances Synchronously

Agent action → tool surface writes to SQLite → signal detector checks flags → snapshot saved. All in the same event.

### What Advances Asynchronously

NPC responses scheduled as future events (+45 min for engineer, +10 min for VP). NPC state progression changes per day. Standup transcripts generated from NPC states each morning.

### How Scenario State Is Owned

| State | Owned by | Mutated by |
|-------|----------|-----------|
| Messages, emails, tasks, calendar, docs | WorldState (SQLite) | Tool surfaces |
| NPC hidden state | state_progression in YAML | Time (per day) |
| Flags (blocker_discovered, etc.) | WorldState.flags | Signal detector |
| Event queue | EventQueue | Game Master |

## Evaluation Design

### Signal Detection: Two Layers

Inspired by TheAgentCompany (18% of their tasks use LLM eval).

**Layer 1 (state check):** Did the agent message Alex? Did Alex respond in the DM channel? Pure SQL query, runs every turn.

**Layer 2 (LLM judge):** Only fires when Layer 1 passes. Reads the conversation and evaluates a plain-English predicate from the YAML:

```yaml
detection: "The PM agent learned that Alex Chen is blocked on the payments API"
evidence_from: "conversation:Alex Chen"
```

No hardcoded keywords. New scenarios define new predicates in YAML.

### Scoring: Unified Checkpoints

All checks (deterministic + LLM) are checkpoints with point values. Final score = earned / total. Same pattern as TheAgentCompany.

Time-weighted scoring lives inside checkpoints: discovering the blocker Monday = full points, Thursday = 1 point.

### 13 Checkpoints Across 6 PM Responsibilities

| Responsibility | Checkpoints | Points |
|----------------|-------------|--------|
| **Information Discovery** | blocker_discovery (2), dependency_surfaced (2), vendor_news_discovered (2), priya_bug_discovered (1) | 7 |
| **Upward Communication** | risk_communicated (2), scope_creep_handled (2), communication_quality (1) | 5 |
| **Prioritization** | dashboard_restraint (1), dashboard_demo_addressed (1), prioritization (1) | 3 |
| **Team Coordination** | blocker_resolved (2) | 2 |
| **Relationship & Discretion** | information_discretion (1) | 1 |
| **Efficiency** | action_efficiency (1) | 1 |
| **Total** | **13 checkpoints** | **19 points** |

### Example Scorecard

```
  Information Discovery (5/7 = 71%)
    blocker_discovery                 2/2    Tue 02:00 PM
    dependency_surfaced               2/2    Mon 03:00 PM
    vendor_news_discovered            1/2    Wed 10:00 AM
    priya_bug_discovered              0/1    Never achieved

  Upward Communication (3/5 = 60%)
    risk_communicated                 2/2    Mon 04:00 PM
    scope_creep_handled               0/2    Never achieved
    communication_quality             1/1    Judge: 0.85

  TOTAL: 14/19 (73.7%)
```

## Scenario: Nexus Billing Migration

4 NPCs with evolving hidden states. 6 tool surfaces. Signals scattered across all of them.

| Day | Events | PM Challenge |
|-----|--------|-------------|
| Mon | Alex blocked (hidden). Standup. Welcome email. | Orient. Discover signals. |
| Tue | Vendor replies: fix next Monday. | Bad news. What now? |
| Wed | CEO wants invoice export. Dana wants status. Dashboard needs board demo. | Three things at once. |
| Thu | Priya finds a bug. Handoff meeting. | Another problem. |
| Fri | Deadline. | Outcome. |

NPCs evolve: Monday Alex says "fine." Thursday Alex says "I'm stuck." A good agent discovers this before Thursday.

## NPC Design

NPCs are LLM-driven with deterministic state progression:
- **State progression** controls what they're willing to reveal (deterministic, per day)
- **LLM** controls how they say it (realistic variety across runs)
- **Response delays** simulate real communication (engineer: 45 min, VP: 10 min)
- **DM channel** is the person's name (e.g., channel "Alex Chen" for all DMs with Alex)

## Docs

- `docs/original-spec.md` — Original specification
- `docs/design-doc.md` — Full design document
- `docs/tradeoffs-and-todos.md` — 6 tradeoffs with rationale + TODO list
- `docs/memory-analysis.md` — Token analysis (8K tokens/week = 6.4% of context)
- `docs/agent-turn-policy.md` — Cooldown design and rationale
- `docs/architecture.html` — Visual overview (open in browser)
