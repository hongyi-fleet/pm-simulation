# PM Simulation Environment

A simulation environment for evaluating AI agents on project management tasks. The agent plays a PM during their first week at a SaaS company, navigating incomplete information, conflicting priorities, and stakeholder pressure.

This is not a task-completion benchmark. It tests judgment: can the agent discover a hidden blocker by connecting scattered signals across chat, email, and the task board? Can it make a reasonable tradeoff when two projects compete for attention? Can it communicate risk clearly to an executive on a deadline?

## Quick Start

```bash
git clone <repo-url> && cd pm-simulation
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

Run without LLM calls (scripted NPCs, deterministic):
```bash
python run.py --scenario scenarios/nexus_billing/scenario.yaml --no-llm
```

Run tests:
```bash
pytest tests/
```

Run the evaluator on a completed simulation:
```bash
python evaluate.py --run-dir runs/latest/
```

## Architecture

The system has four decoupled parts. You can swap the agent model, write new scenarios, or change evaluation criteria without touching the engine.

```
┌─────────────────────────────────────────────────┐
│                   SCENARIO                       │
│  (YAML: company, NPCs, events, eval criteria)   │
└──────────────────────┬──────────────────────────┘
                       │ loads into
                       ▼
┌─────────────────────────────────────────────────┐
│          SIMULATION ENGINE (domain-agnostic)     │
│                                                  │
│  SimClock ──► WorldState ──► NPCs               │
│  (N ticks)    (SQLite)     (hybrid: script+LLM) │
│                    │                             │
│         Tool Registry (pluggable)                │
│  chat │ email │ calendar │ tasks │ docs │ meetings │
└────────────────────┬────────────────────────────┘
                     │ function calls
                     ▼
┌─────────────────────────────────────────────────┐
│              PM AGENT (any LLM)                  │
└────────────────────┬────────────────────────────┘
                     │ after run
                     ▼
┌─────────────────────────────────────────────────┐
│    EVALUATOR (rubric + LLM judge → scorecard)    │
└─────────────────────────────────────────────────┘
```

### Module Structure

```
src/
  engine/          # Domain-agnostic: clock, state, NPC runner, signal detector
  tools/           # ToolSurface protocol + implementations (chat, email, calendar, tasks, docs, meetings)
  evaluation/      # Rubric engine + LLM judge
  agent/           # Agent interface + LLM adapter
scenarios/
  nexus_billing/   # Primary scenario (40 ticks, 4 NPCs, full eval)
  onboarding_101/  # Mini scenario (5 ticks, 2 NPCs, proves format scales)
tests/             # Unit + integration tests (run without LLM calls)
```

The engine is domain-agnostic. The PM scenario is a data file. Adding a new scenario means writing YAML, not modifying engine code.

## How One Tick Works

```
Tick N starts
  │
  ├─ 1. Scripted events fire (from scenario YAML)
  │     Deterministic. "Designer sends email at tick 5."
  │
  ├─ 2. NPCs act (sequential, fixed order)
  │     Activation check: new messages involving them, task changes,
  │     or proactive trigger (NPCs initiate on their own every few ticks)
  │     If no trigger: skip (no LLM call)
  │     If activated: NPC sees persona + hidden state + goals + tasks +
  │     memory + recent messages → LLM decides what to do
  │     NPCs are autonomous agents, not scripted actors
  │
  ├─ 3. Agent observes and acts
  │     Reads are free. Up to 5 write actions per tick.
  │     Invalid actions return errors and count as penalties.
  │
  ├─ 3.5. Signal detector
  │     Pattern-matches on state changes to set flags.
  │     e.g., "blocker discovered" requires 3 signals:
  │       agent messaged Alex + Alex revealed blocker + agent took follow-up
  │
  ├─ 4. Snapshot saved
  │     Full world state serialized to SQLite as JSON blob.
  │     JSON log entry written for observability.
  │
  └─ Next tick
```

## Design Decisions

Every decision has a "why" and a "why not the alternatives."

### 1. Time: Discrete time-step (1hr ticks)

Each tick = 1 simulated hour. One work week = 40 ticks (Mon-Fri, 9am-5pm). "Before tick N" means ticks 0 through N-1 (exclusive).

**Why not turn-based:** The world must move independently of the agent. NPCs send messages, deadlines approach, meetings happen whether or not the agent acts.

**Why not event-driven:** Adds complexity (event queue, priority resolution) without proportional realism gain for a 40-tick simulation.

### 2. State: SQLite + per-tick snapshots

One table per tool surface. A `snapshots` table stores JSON blobs of full world state at each tick. The engine defines base table schemas; scenarios populate them with seed data.

**Why not in-memory:** Reviewer can open the DB and query it. Evaluator can inspect any tick. Snapshots enable future counterfactual replay.

**Why not event sourcing:** Overkill. SQLite with snapshots gives 80% of the audit benefit at 20% of the complexity.

### 3. NPCs: LLM-driven with initial conditions

NPCs are autonomous agents, not scripted actors. The scenario defines their persona, hidden state (e.g., "blocked on API"), goals, and communication style. Their behavior emerges from LLM generation. Alex doesn't send a scripted "still looking into it" at tick 5. Alex responds to questions in a way consistent with being blocked and avoidant, and might proactively reach out if something is on his mind.

Only structural events are scripted: meetings exist at fixed ticks, deadlines are set, external emails arrive. Everything NPCs say and do is LLM-generated.

A `--no-llm` flag provides a simple rule-based fallback for deterministic testing of the engine loop.

**Why not scripted NPCs:** If NPCs follow a script, you're testing "can the agent follow breadcrumbs" not "can the agent do PM work." Different runs should produce different conversations around the same underlying situation. That's what makes evaluation meaningful.

**Why this works for evaluation:** The signal detector checks outcomes (did the agent discover the blocker?) not methods (did the agent read the right scripted message?). The underlying truth (Alex is blocked) is constant. The path to discovering it varies.

### 4. Evaluation: Rubric (~2:1) + LLM-as-judge

Hard metrics via rubric (binary checks against state log). Soft metrics via LLM judge (temperature 0, structured JSON, communication quality and prioritization). Target ~2:1 rubric-to-judge ratio, calibrated per scenario.

**Why both:** A rubric checks "did the agent find the blocker?" but not "did it handle the blocker well?" The rubric alone gives a meaningful ranking even without LLM scores.

**Reward hacking resistance:** Scoring outcomes not activity. Penalizing spam actions. Multi-signal detection (can't escalate a blocker you never found).

### 5. Scenarios: Declarative YAML

Scenarios are data, not code. Company state, NPC personas, seeded events, conditional triggers, and evaluation criteria all in YAML. Conditional events use typed triggers: `state_flag_not_set`, `tick_after`, `tick_before`, combinable with `all:`/`any:`.

**Why not Python:** "Support many more scenarios without collapsing into prompt spaghetti." A reviewer reads the scenario in 2 minutes.

### 6. Agent Interface: Typed function calls

`send_chat()`, `send_email()`, `check_calendar()`, `create_task()`, `update_task()`, `read_emails()`, `read_chats()`, `list_docs()`, `read_doc()`, `create_doc()`, `edit_doc()`, `list_meetings()`, `read_transcript()`. Max 2000 chars for message bodies, 500 for subjects. All tool surfaces implement a `ToolSurface` protocol.

**Why not free-text:** Function calls are evaluable, typed, and match how real LLM tool-use works.

### 7. NPC Memory: Summary memory

Every 5 ticks, interactions are summarized into a paragraph. Context = persona + running summary + last 3 messages (sender/recipient == NPC). Hard budget: 2000 tokens.

### 8. Tick Order: Sequential, fixed

Deterministic. Easy to debug. Easy to reproduce.

### 9. Agent Model: OpenAI-compatible, configurable

V1 targets OpenAI API. Model names in YAML config. Any OpenAI-compatible API works. `OPENAI_API_KEY` via environment variable.

### 10. Observability: JSON log + HTML report

Every tick produces a structured JSON record. After a run, an HTML timeline lets the reviewer see what happened at a glance.

### 11. Error Handling: Feedback + penalty

Invalid actions return an error to the agent and are logged. Excessive errors penalize the evaluation score.

## Scenario: Nexus Billing Migration

A 40-person SaaS company. The PM's first week. 4 interactive NPCs (other employees exist in flavor text but aren't interactive).

**The setup:**
- Billing migration launches Friday
- Alex Chen (Senior Engineer): blocked on payments API, hasn't told anyone
- Priya Sharma (Designer): on track, but her timeline depends on Alex's work
- Marcus Johnson (Eng Lead): wants attention for a lower-priority project
- Dana Park (VP Product): wants a status update by Wednesday

**What makes it hard:**
- The blocker is never stated explicitly. Six signals scattered across six tools:
  - **Chat:** Alex says "still looking into the integration"
  - **Task board:** Alex's ticket hasn't moved in 3 days
  - **Email:** Alex emailed the external API vendor about missing docs
  - **Document:** Design doc mentions Priya's handoff depends on Alex's API work
  - **Calendar:** Handoff meeting scheduled Thursday (too late if Alex is still blocked)
  - **Transcript:** Monday standup transcript shows Alex said "should be fine by Wednesday" (turns out to be wrong)
- Priya's dependency on Alex isn't in the task board. It's in a design doc and a calendar invite.
- Dana's Wednesday deadline creates time pressure. Investigate vs. communicate.

**Evaluation (16 points):**

| Check | Points | Type |
|-------|--------|------|
| Discover Alex is blocked (before tick 15) | 2 | Rubric |
| Surface Priya-Alex dependency (before tick 20) | 2 | Rubric |
| Communicate risk to Dana before Wed EOD (tick 24) | 2 | Rubric |
| Resolve or escalate blocker (before tick 30) | 2 | Rubric |
| Avoid unnecessary escalation of dashboard project | 1 | Rubric |
| Action efficiency (< 5 invalid actions) | 1 | Rubric |
| Communication quality | 0-3 | LLM judge |
| Prioritization reasoning | 0-3 | LLM judge |

## Signal Detection

The evaluator doesn't directly observe "did the agent discover the blocker." Instead, a signal detector layer checks for concrete evidence:

1. Agent sent a message to Alex (direct chat or email)
2. Alex's response mentioned the blocker (Alex reveals it when asked directly)
3. Agent took a follow-up action referencing the blocker (email to stakeholder, task update, etc.)

All three signals must fire to count as "discovered." This is more robust than keyword matching and resists reward hacking (you can't get credit by mentioning "blocker" without actually doing the discovery work).

## Related Work

| System | What it does | How we differ |
|--------|-------------|---------------|
| **TheAgentCompany** | 175 independent tasks in a simulated software company, checkpoint eval, real-time execution | We run one continuous week-long scenario with emergent dynamics, time-weighted eval, and simulated time decoupled from inference |
| **EnterpriseBench** | 500 tasks across 10+ domains, configurable complexity | We adopt configurable difficulty but focus on one deep scenario rather than many shallow tasks |
| **Stanford Generative Agents** | 25 agents with memory and social behavior | Our NPCs add deterministic state progression as an evaluation backbone + response delays |
| **Sotopia** | NPC platform used by TheAgentCompany | We build custom NPCs with richer state progression rather than depending on an external platform |

**Our key differentiators:**
1. Simulated time decoupled from inference latency (the spec explicitly requires this)
2. Evaluation rewards decisions, not activity (time-weighted continuous scores, not task completion rate)
3. Coherent tool environment (6 surfaces sharing state, not separate API endpoints)
4. NPC proactive outreach + realistic response delays (most benchmarks have reactive-only NPCs)
5. Emergent dynamics from NPC state progression (the scenario evolves even without agent action)

## Why Not Extend Concordia or tau-Bench?

Concordia (Google DeepMind) has the closest architecture: game-master loop, LLM agents, discrete time-steps. But for this project, the reviewer wants to see design decisions in code you own end-to-end. Wrapping Concordia means the reviewer reads Concordia's abstractions, not yours. Similarly, tau-Bench's tool interaction framework could be extended, but a self-contained system is easier to clone, run, and evaluate.

## Counterfactual Scoring: Future Direction

The SQLite snapshot system stores full world state at every tick. This data is ready for counterfactual evaluation:

1. Mark 3-5 "decision point" ticks in the scenario YAML
2. Fork from a decision point, replay with an alternative action
3. Diff the final scores: "how much better did the agent do than the counterfactual?"

The data layer supports this. The replay engine is future work.

## Failure Modes

| Failure | Response |
|---------|----------|
| LLM API timeout | NPC: canned "busy" response. Agent: error + retry next tick. 10s agent / 5s NPC timeouts (configurable). |
| Malformed agent output | Logged as illegal action, error returned, tick continues |
| NPC hallucination | Prompts include hard constraints. Agent messages wrapped in `<user_message>` delimiters to prevent injection. |
| Cost/latency | ~210 LLM calls per run, ~2 minutes, ~$0.10 with GPT-4o-mini |

## Testing

- **Engine unit tests:** Clock, snapshots, conditional events (boundary values, combinators), signal detector, input validation. No LLM calls.
- **Rubric tests:** Every scoring criterion tested at boundary ticks (14, 15, 16 for "before tick 15"). Partial credit. Total score calculation.
- **Integration test:** Mini scenario (`onboarding_101`) with `--no-llm` + mock LLM judge. Full loop in <1 second.
- **Memory test:** Verify key facts survive NPC memory summarization.
- **Full run:** Manual verification with LLM NPCs, documented expected output below.

## Example Output

```
$ python run.py --scenario scenarios/nexus_billing/scenario.yaml

PM Simulation: Nexus — Billing Migration Week 1
================================================
Tick  0 (Mon  9:00) | Agent reads welcome email, checks calendar
Tick  1 (Mon 10:00) | Agent reads chat, sends message to Alex
Tick  2 (Mon 11:00) | Alex responds: "still looking into the integration"
...
Tick 14 (Wed  2:00) | Agent discovers Alex is blocked (3/3 signals)
Tick 15 (Wed  3:00) | Agent emails Dana with risk assessment
...
Tick 39 (Fri  5:00) | Simulation complete

SCORECARD
─────────────────────────────────────────
Blocker discovery (before tick 15):    2/2  ✓
Dependency surfaced (before tick 20):  2/2  ✓
Risk communicated (before tick 24):    2/2  ✓
Blocker resolved (before tick 30):     2/2  ✓
Dashboard restraint:                   1/1  ✓
Action efficiency:                     1/1  ✓
Communication quality (LLM judge):     2/3
Prioritization (LLM judge):           3/3
─────────────────────────────────────────
TOTAL: 15/16
```
