# Evaluation Timing: Real-time vs Post-hoc

## Discovery

During benchmark runs, we measured 2435 LLM judge calls for a single simulation. Root cause: the signal detector runs after every agent turn, and each detector with a passing state check triggers an LLM judge call. With ~80 agent turns and ~10 detectors, this scales to O(turns × detectors).

TheAgentCompany takes a different approach: zero evaluation during agent execution. All checkpoints are evaluated once after the agent finishes, by querying system state (Jira status, Rocket.Chat history, file contents).

## The Fundamental Difference: SWE vs PM Evaluation

**SWE benchmarks evaluate end state.** Did the issue get marked as done? Is the file correct? The path doesn't matter. Check once at the end.

**PM simulation evaluates trajectory.** When did the PM discover the blocker? Monday (great) or Thursday (too late)? The same end state (blocker discovered) has different scores depending on timing. This requires knowing WHEN things happened, not just WHETHER they happened.

## Current Approach: Real-time Signal Detection

```
Every agent turn:
  → Layer 1: SQL state check (free)
  → Layer 2: LLM judge (expensive)
  → If both pass: set flag with timestamp
```

**Pros:**
- Flag timestamps are exact (set at the moment of detection)
- Causal chains work naturally (blocker_resolved checks if blocker_discovered flag exists)
- Conceptually simple: detect → flag → done

**Cons:**
- 2435 LLM judge calls per run (measured)
- Most calls are redundant (same conversation, same answer as last turn)
- Simulation speed bottlenecked by judge calls
- Expensive ($2-5 per run in LLM costs)

## Proposed Approach: Post-hoc Evaluation with Candidate Timestamps

```
During simulation:
  → Layer 1 only: SQL state check (free)
  → If passes: record candidate timestamp (no LLM call)

After simulation:
  → For each flag: get candidate timestamps
  → For each candidate (earliest first): run LLM judge
  → First YES = flag timestamp
  → Score with time-weighted checkpoints
```

**Pros:**
- Zero LLM calls during simulation (fast)
- ~30-50 LLM judge calls total instead of 2435 (50-80x reduction)
- Simulation runs at full speed (only agent + NPC LLM calls)
- Evaluation is repeatable (can re-evaluate same run with different predicates)
- Can re-run evaluation without re-running simulation

**Cons:**
- Causal chains more complex: `blocker_resolved` needs to check that `blocker_discovered` candidate exists at an earlier timestamp, not just that the flag is set
- Candidate timestamps are approximate: state check passed at this turn, but the actual evidence (conversation content) might have appeared earlier
- Two-pass architecture: simulation produces data, evaluator consumes it. More code, more moving parts.
- Can't use flag state to trigger conditional events during simulation (e.g., "Dana asks for status IF blocker not discovered"). Would need to keep some flags real-time.

## The Conditional Event Problem

Current scenario has:
```yaml
- time: "Wed 14:00"
  type: email
  condition:
    flag_not_set: status_communicated_to_dana
```

This event fires only if the agent hasn't communicated with Dana. If flags are post-hoc, this condition can't be evaluated during simulation.

**Options:**
1. Keep conditional event flags real-time (Layer 1 only, no LLM). Use a simpler check: "did agent send email to Dana?" instead of "did agent communicate a specific risk?"
2. Remove conditional events. Make all events unconditional (Dana always asks for status, even if PM already communicated).
3. Hybrid: conditional flags use Layer 1 only (SQL, real-time). Evaluation flags use Layer 1 + Layer 2 (post-hoc).

Option 3 is cleanest: separate "simulation flags" (drive events, Layer 1 only) from "evaluation flags" (drive scoring, Layer 1 + Layer 2 post-hoc).

## Performance Comparison

| Metric | Current (real-time) | Proposed (post-hoc) |
|--------|-------------------|-------------------|
| LLM judge calls during sim | 150-2435 | 0 |
| LLM judge calls after sim | ~6 | ~30-50 |
| Total LLM judge calls | 150-2435 | 30-50 |
| Judge cost per run | $2-5 | $0.10-0.20 |
| Simulation speed | Bottlenecked by judge | Full speed |
| Can re-evaluate without re-running | No | Yes |
| Conditional events work | Yes | Need hybrid approach |
| Causal chain complexity | Simple (check flag) | Medium (check candidate times) |

## Recommendation

Implement Option 3 (hybrid):
- **Simulation flags** (drive conditional events): Layer 1 only, real-time, SQL checks
- **Evaluation flags** (drive scoring): Layer 1 candidates recorded during sim, Layer 2 LLM judge post-hoc

This gives fast simulation + accurate time-weighted evaluation + conditional events still work.

## Implementation Cost

| File | Change |
|------|--------|
| signals.py | Split into SimulationDetector (sync, Layer 1) and EvaluationDetector (candidates) |
| signal_setup.py | Tag each detector as "simulation" or "evaluation" |
| game_master.py | Only run SimulationDetector (sync, no async needed) |
| evaluator.py | After sim, run LLM judge on EvaluationDetector candidates |
| scenario YAML | Add `purpose: simulation` or `purpose: evaluation` to each flag |

Estimated effort: 2-3 hours.
