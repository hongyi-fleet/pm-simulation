# PM Simulation Environment — Build Tips

7 hours. Here's how to make them count.

## What the Reviewer Actually Cares About

From the spec:

> "We care about whether you have strong, defensible opinions about how to build and operate a realistic environment from core principles."

> "We are much more interested in the systems problems behind a realistic simulation than in surface-level mimicry."

> "Coding agents are welcome as part of the workflow, but the design decisions should still be clearly yours and should be legible in the final system."

Translation: **they're hiring for systems thinking, not code volume.** The architecture doc and README matter as much as the code. A clean, small system with clear reasoning beats a large system that's hard to follow.

## Time Budget

| Block | Time | What | Why |
|-------|------|------|-----|
| 1 | 1 hr | Architecture doc + README skeleton | Write design decisions FIRST. Forces clarity before code. Every choice should have a "why." This document IS the deliverable as much as the code. |
| 2 | 2.5 hr | Core engine + tool surfaces | SimClock, WorldState (SQLite), 4 tool surfaces, NPC runner, agent loop. CC can generate most of this from the architecture doc. |
| 3 | 1.5 hr | Scenario + NPCs | One YAML scenario. 4-5 NPC personas. Seeded events. Make it feel real. |
| 4 | 1 hr | Evaluator | Rubric checks + LLM-as-judge. Scorecard output. |
| 5 | 1 hr | Polish + test a full run | Run end-to-end. Fix bugs. Make sure clone-install-run works in under 2 minutes. Flesh out README with example output. |

## Key Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Time system | Discrete time-step, 1hr ticks | Realistic (world moves independently of agent), 40 ticks = one work week |
| 2 | World state | SQLite + per-tick snapshots | Inspectable, replayable, persistent, zero setup |
| 3 | NPC behavior | Hybrid: scripted events + LLM dialog | Key plot points are deterministic, conversations are dynamic |
| 4 | Evaluation | Rubric (hard) + LLM-as-judge (soft) | Binary checks for facts, LLM for judgment quality |
| 5 | Scenario format | Declarative YAML | Data not code, extensible, no prompt spaghetti |
| 6 | Agent interface | Typed function calls | Clean, evaluable, realistic tool usage |
| 7 | NPC memory | Summary memory | NPCs remember context without blowing token budgets |
| 8 | Tick concurrency | Sequential, fixed NPC order | Deterministic, debuggable |
| 9 | Agent model | Provider-agnostic via config | Simulation should evaluate any LLM, not just one |
| 10 | Observability | Structured JSON log + HTML report | JSON for evaluation, HTML for reviewer experience |
| 11 | Illegal actions | Error feedback + penalty | Realistic (tools give errors) and evaluable (spam is scored) |

## Specific Advice

### 1. Write the architecture doc before writing code

Not after. Before. The spec says "design decisions should be legible." A doc that says "I chose discrete time-steps over event-driven because..." shows the reviewer you thought about alternatives. CC can then implement FROM the doc, keeping code consistent with stated design.

### 2. Scope to 4 tool surfaces, not 6

Chat, email, task board, calendar. Skip docs and meeting transcripts. 4 surfaces demonstrate the pattern. 6 doubles the debugging surface for minimal reviewer impact. Spend that time on evaluation quality instead.

### 3. Make the scenario compelling

Don't make a generic company. Make it specific:

- **"Nexus"** — a 40-person SaaS company shipping a billing migration
- Week 1 PM walks into: one project 3 days from launch, one engineer quietly blocked on an API dependency, a designer who thinks they're on track but isn't, an exec who wants a status update by Wednesday
- The "right" answer requires connecting signals across chat + email + task board

A reviewer who runs this should think "oh, this feels like a real company."

### 4. The evaluation section of your README is your secret weapon

Most take-homes skimp here. Don't. Explain:

- What the rubric checks (specific examples)
- Why LLM-as-judge is needed for soft skills and how you keep it stable (temperature 0, structured output, specific rubric in the prompt)
- How the system resists reward hacking (scoring outcomes not activity, penalizing spam actions, checking that the agent actually discovered information before acting on it)

### 5. Don't build a UI

The spec says "a lightweight interface is fine." A Python script that runs the sim and prints a scorecard is enough. Zero time on UI.

### 6. Let CC write the boilerplate, you write the decisions

CC is great at: SQLite schema, tool surface CRUD, NPC prompt templates, YAML parsing, pytest scaffolding.

You should write: the architecture doc, the scenario narrative, the evaluation rubric, the README. Those are the parts the reviewer reads closely.

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                   SCENARIO                       │
│  (YAML: company state, NPCs, events, eval)      │
└──────────────────────┬──────────────────────────┘
                       │ loads into
                       ▼
┌─────────────────────────────────────────────────┐
│               SIMULATION ENGINE                  │
│                                                  │
│  SimClock ──► WorldState ──► NPCs               │
│  (40 ticks)   (SQLite)     (hybrid: script+LLM) │
│                    │                             │
│            Tool Surfaces                         │
│     chat │ email │ calendar │ tasks              │
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

## One Tick Flow

```
Tick N starts
  │
  ├─ 1. Scripted events fire (from scenario YAML)
  │     e.g., designer sends "slight delay" email at tick 5
  │
  ├─ 2. NPCs act (sequential, fixed order)
  │     each NPC: sees world state → LLM generates action → state updates
  │
  ├─ 3. Agent observes (inbox, chat, tasks, calendar)
  │     picks actions via function calls
  │     state updates
  │
  ├─ 4. State snapshot saved to SQLite
  │     JSON log entry written
  │
  └─ Tick N+1 starts
```
