# PM Simulation Environment

An event-driven simulation where an AI agent plays a project manager during their first week at a SaaS company. The simulation tests PM judgment: information discovery, prioritization, communication, and decision-making under pressure.

## Quick Start

Requires Python 3.10+ and an OpenAI API key.

```bash
git clone https://github.com/hongyi-fleet/pm-simulation.git && cd pm-simulation
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your-key-here
python run.py --scenario scenarios/nexus_billing/scenario.yaml
```

Options:
```bash
# Choose models (defaults: gpt-4o for agent/npc/judge)
python run.py --scenario scenarios/nexus_billing/scenario.yaml --agent-model gpt-4o --npc-model gpt-4o-mini

# Short scenario (Mon-Wed, faster iteration, ~10 min)
python run.py --scenario scenarios/nexus_billing_short/scenario.yaml

# Full week scenario (~15-30 min)
python run.py --scenario scenarios/nexus_billing/scenario.yaml

# Multiple runs with variance reporting
python run.py --scenario scenarios/nexus_billing/scenario.yaml --runs 3

# Benchmark: compare models in parallel
python bench.py --models gpt-4o-mini gpt-4o --npc-model gpt-4o-mini --runs 3

# Run tests (no LLM calls needed, no API key required)
pytest tests/ -v
```

Each run saves to `runs/<scenario>_<timestamp>/`: `config.json`, `event_log.json`, `scorecard.json`, `judge_log.json`.

## Architecture

```
SCENARIO (YAML)  →  ENGINE (event-driven)  →  AGENT (any LLM)  →  EVALUATOR
  company             EventQueue                function calls       checkpoints
  NPCs + states       GameMaster                read/write tools     by PM role
  seed data           WorldState (SQLite)
  eval predicates     NPC Runner + Signals
```

### Module Structure

```
src/
  config.py          # All constants in one place (timeouts, limits, intervals)
  llm_client.py      # OpenAI API wrapper (supports gpt-4o and gpt-5.x families)
  engine/
    clock.py         # Passive SimClock (event-driven, no ticks)
    event_queue.py   # Priority queue (structural > NPC > agent turns)
    game_master.py   # Main loop: pop event → resolve → NPCs react → agent acts → signals → snapshot
    npc.py           # LLM-driven NPCs with state progression, response delays, greeting guardrails
    signals.py       # Async signal detection engine (skips when no new data)
    signal_setup.py  # Builds detectors from YAML predicates (state check + LLM judge)
    events.py        # Conditional events (flag-based, time-based, combinators)
    scenario_loader.py  # YAML → simulation components
    world_state.py   # SQLite state + snapshots + action log
  tools/
    protocol.py      # ToolSurface interface + input validation
    chat.py, email_tool.py, tasks.py, calendar_tool.py, documents.py, meetings.py
  evaluation/
    scoring.py       # Unified checkpoint system (TheAgentCompany pattern)
    evaluator.py     # Orchestrates rubric + LLM judge → scorecard by PM role
    llm_eval.py      # LLM signal detection with verdict + evidence logging
    llm_judge.py     # LLM quality scoring (median of N runs)
  agent/
    interface.py     # Agent function-call interface, pending reply tracking
scenarios/
  nexus_billing/     # Full week (Mon-Fri), 4 NPCs, 19 checkpoints
  nexus_billing_short/  # Mon-Wed, 60-min intervals (fast iteration)
  onboarding_101/    # Mini scenario (proves format scales)
tests/               # 95 tests, no LLM calls
bench.py             # Parallel benchmark pipeline: compare models, measure variance
```

### What Advances Synchronously

Agent action → tool surface writes to SQLite → signal detector checks flags → snapshot saved. All in the same event.

### What Advances Asynchronously

NPC responses scheduled as future events (+45 min for engineer, +10 min for VP). NPC state progression changes per day. Standup transcripts LLM-generated from NPC states each morning.

### How Scenario State Is Owned

| State | Owned by | Mutated by |
|-------|----------|-----------|
| Messages, emails, tasks, calendar, docs | WorldState (SQLite) | Tool surfaces |
| NPC hidden state | state_progression in YAML | Time (per day) |
| Flags (blocker_discovered, etc.) | WorldState.flags | Signal detector |
| Event queue | EventQueue | Game Master |

### Key Implementation Details

**Cooldown system.** After each agent turn, a 10-minute cooldown prevents NPC-agent cascade. Without it, we measured 796 events instead of ~130 per run.

**Task permissions.** PM can set tasks to `blocked` or `at_risk`, but only the assignee can mark their own task `done`. Prevents agent hallucinating task completion.

**NPC greeting guardrails.** In DM channels, NPC messages addressed to wrong person are sanitized (e.g., Marcus saying "Hi Alex" in his own DM channel → greeting stripped).

**Signal detection optimization.** Hybrid architecture: simulation flags (SQL only, real-time) drive conditional events; evaluation flags (SQL + LLM judge, post-hoc) drive scoring. Reduces LLM judge calls from ~2,435 to ~50 per run.

**Checkpoint causal chains.** `blocker_resolved` requires `blocker_discovered` to fire first. Can't get credit for resolving a blocker you haven't found.

## Evaluation Design

### Signal Detection: Two Layers

Inspired by TheAgentCompany (18% of their tasks use LLM eval).

**Layer 1 (state check):** Did the agent message Alex? Did Alex respond in the DM channel? Pure SQL query, exact channel match.

**Layer 2 (LLM judge):** Only fires when Layer 1 passes AND new data exists. Evaluates a plain-English predicate. Returns verdict + evidence for debugging:

```yaml
detection: "The PM agent learned that Alex Chen is blocked on the payments API"
evidence_from: "conversation:Alex Chen"
```

Judge decisions saved to `judge_log.json` with reasoning:
```json
{
  "predicate": "The PM agent learned that Alex Chen is blocked...",
  "verdict": true,
  "evidence": "VERDICT: yes EVIDENCE: Alex explicitly stated 'Blocker is still the Stripe sandbox 500s'"
}
```

### Scoring: Unified Checkpoints

All checks (deterministic + LLM) are checkpoints with point values. Final score = earned / total. Same pattern as TheAgentCompany.

Time-weighted scoring lives inside checkpoints: discovering the blocker Monday = full points, Thursday = 1 point.

### 19 Checkpoints Across 7 PM Responsibilities

| Responsibility | Checkpoints | Points |
|----------------|-------------|--------|
| **Information Discovery** | blocker_discovery (2), dependency_surfaced (2), vendor_news_discovered (2), priya_bug_discovered (1) | 7 |
| **Upward Communication** | risk_communicated (2), scope_creep_handled (2), communication_quality (1) | 5 |
| **Prioritization** | dashboard_restraint (1), dashboard_demo_addressed (1), prioritization (1) | 3 |
| **Team Coordination** | blocker_resolved (2), concrete_plan (2) | 4 |
| **Relationship & Discretion** | information_discretion (1), spam_penalty (2), misleading_status (2) | 5 |
| **Efficiency** | action_efficiency (1) | 1 |
| **Project Management** | task_management (1), documentation (1), stakeholder_balance (1) | 3 |
| **Total** | **19 checkpoints** | **28 points** |

## Scenario: Nexus Billing Migration

4 NPCs with evolving hidden states. 6 tool surfaces. 12 tasks on the board (4 team + 8 PM). Signals scattered across chat, email, task board, documents, calendar, and meeting transcripts.

| Day | Events | PM Challenge |
|-----|--------|-------------|
| Mon | Alex blocked (hidden). Standup. Welcome email. | Orient. Discover signals across 6 tools. |
| Tue | Vendor replies: fix next Monday. Standup. | Bad news. Workaround or adjust timeline? |
| Wed | CEO wants invoice export. Dana wants status. Dashboard needs board demo. Standup. | Three things explode simultaneously. |
| Thu | Priya finds a bug. Handoff meeting. Standup. | Another problem. Can we still ship? |
| Fri | Deadline. Final standup. | Outcome. |

## NPC Design

NPCs are LLM-driven with deterministic state progression:
- **State progression** controls what they're willing to reveal (deterministic, per day). Standup prompt enforces state consistency.
- **LLM** controls how they say it (realistic variety across runs)
- **Response delays** simulate real communication (engineer: 45 min, VP: 10 min)
- **DM channel** is the person's name (e.g., channel "Alex Chen" for all DMs with Alex)
- **NPCs can only DM the PM Agent.** Cross-NPC communication uses group channels or email.

## Benchmark Results

Scenario: `nexus_billing_short` (Mon-Wed). NPC/Judge: gpt-5.4-mini. Run before new checkpoints (spam_penalty, task_management, etc.) were added — scores are out of the original 19 points.

| Category | gpt-5.4-mini | gpt-5.4 |
|----------|-------------|---------|
| Information Discovery | 5/7 (71%) | 6/7 (86%) |
| Upward Communication | 1/5 (20%) | 5/5 (100%) |
| Prioritization | 3/3 (100%) | 3/3 (100%) |
| Team Coordination | 0/2 (0%) | 1/2 (50%) |
| Relationship & Discretion | 0/1 (0%) | 0/1 (0%) |
| Efficiency | 1/1 (100%) | 1/1 (100%) |
| **Total** | **10/19 (52.6%)** | **16/19 (84.2%)** |

The 32-point gap is almost entirely in **Upward Communication**: both models discover the blocker at similar speed, but gpt-5.4 communicates risk to Dana and pushes back on scope creep. gpt-5.4-mini finds problems but doesn't escalate.

Both models fail **information_discretion** (publicly expose Alex's blocker) and **priya_bug_discovered** (short scenario ends before Thursday).

Full results with judge evidence in `docs/benchmark-results.md`.

## Configuration

All constants centralized in `src/config.py`:

| Setting | Value | Effect |
|---------|-------|--------|
| `MAX_WRITE_ACTIONS` | 5 | Write actions per agent turn (reads are free) |
| `AGENT_COOLDOWN_MINUTES` | 10 | Cooldown after agent acts (prevents cascade) |
| `NPC_CONTEXT_TOKEN_BUDGET` | 2000 | Max tokens for NPC prompt context |
| `MAX_MESSAGE_LENGTH` | 2000 | Max chars for messages/email bodies |
| `LLM_TIMEOUT_DEFAULT` | 180s | LLM call timeout |
| `SUMMARY_EVERY_N_INTERACTIONS` | 5 | NPC memory summarization interval |

Per-scenario settings in YAML: `agent_turn_interval_minutes`, `response_delay_minutes` (per NPC), evaluation predicates.

## Docs

- `docs/original-spec.md` — Original specification
- `docs/design-doc.md` — Full design document
- `docs/benchmark-results.md` — Model comparison with judge evidence
- `docs/tradeoffs-and-todos.md` — 8 tradeoffs with data + TODO list
- `docs/memory-analysis.md` — Token analysis (revised: 125K tokens = 97.6% of context, bottleneck is conversation history)
- `docs/agent-turn-policy.md` — Cooldown design and rationale
- `docs/evaluation-timing.md` — Real-time vs post-hoc evaluation analysis
- `docs/simulation-improvement-plan.md` — 18 improvements implemented
- `docs/research-references.md` — TheAgentCompany, SOTOPIA, Concordia and other references
