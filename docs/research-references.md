# Research References

How this project relates to and borrows from recent agent simulation and evaluation research.

---

## Core References

### TheAgentCompany (CMU, Dec 2024)

Benchmark with 175 tasks in a simulated software company. NPCs via SOTOPIA. Checkpoint-based evaluation.

**What we borrowed:**
- Unified checkpoint scoring (all checks are checkpoints with point values, final score = earned/total)
- `evaluate_with_llm(content, predicate)` pattern for subjective evaluation (18% of their tasks)
- Deterministic state checks as primary evaluation (82% of their tasks)
- Post-hoc evaluation (eval runs once after agent finishes, not during)

**What we do differently:**
- Time-weighted scoring (they don't measure when, just whether)
- LLM-driven NPCs with state progression (their NPCs are static — one strategy_hint forever)
- Event-driven simulated time (they run in real-time)
- Continuous week-long scenario vs 175 independent tasks
- NPC response delays (their NPCs reply in ~1 second)

📄 [arxiv.org/abs/2412.14161](https://arxiv.org/abs/2412.14161) | [GitHub](https://github.com/TheAgentCompany/TheAgentCompany)

---

### SOTOPIA (CMU, ICLR 2024 Spotlight)

Open-ended environment for social intelligence evaluation. Agents role-play scenarios with private goals.

**What we borrowed:**
- Multi-dimensional evaluation (they have 7 dimensions, we have 8 PM categories)
- `RuleBasedTerminatedEvaluator(max_turn_number=20, max_stale_turn=4)` — our NPC conversation limits (Layer 1: prompt guidance, Layer 2: stale detection at 50% overlap, Layer 3: hard cap at 5 consecutive replies)
- Agent can choose "leave" / "wait" action — our NPCs can choose "wait"
- GPT-4-as-evaluator validated against human judgment

**What we do differently:**
- Workplace domain (PM) instead of general social scenarios
- Persistent world state in SQLite (their interactions are ephemeral)
- 6 tool surfaces as communication channels (they only have conversation)
- Evaluation across a full work week, not single episodes

📄 [arxiv.org/abs/2310.11667](https://arxiv.org/abs/2310.11667) | [sotopia.world](https://sotopia.world)

---

### Concordia (Google DeepMind, Dec 2023)

Library for generative agent-based simulations. Game Master pattern.

**What we borrowed:**
- Game Master architecture: pop event → resolve → NPCs react → agent acts → repeat
- Agents describe actions in natural language, GM resolves outcomes
- Component-based NPC design (persona, memory, reasoning as separate modules)

**What we do differently:**
- Declarative YAML scenarios instead of Python code
- Two-layer signal detection (they don't have automated evaluation)
- Tool surfaces as first-class objects (they have no structured tools)
- Post-hoc LLM judge evaluation

📄 [arxiv.org/abs/2312.03664](https://arxiv.org/abs/2312.03664) | [GitHub](https://github.com/google-deepmind/concordia)

---

## Papers That Informed Specific Design Decisions

### SOTOPIA-RL (Yu et al., Aug 2025)

Refines coarse episode-level feedback into utterance-level, multi-dimensional rewards for RL training.

**Relevance:** Our reward density is 4.5% (4 flags in 88 turns). SOTOPIA-RL solves this by scoring every utterance on multiple dimensions. We partially addressed this with 19 checkpoints, but the evaluation is still checkpoint-level not turn-level.

**Future direction:** Convert our checkpoints into per-turn shaping rewards. Each agent turn could get +0.1 for reading new information, -0.1 for sending a repetitive message, +0.2 for discovering a new signal.

📄 [sotopia.world/projects/sotopia-rl](https://sotopia.world/projects/sotopia-rl)

---

### LIFELONG-SOTOPIA (Goel & Zhu, Jun 2025)

Multi-episode evaluation. Chains 40 episodes together per character pair. Tests memory across interactions.

**Relevance:** They found all models' goal achievement declines over time. We observed the same: agent is active Mon-Tue, becomes passive Thu-Fri. Their solution: 200-300 word "memory chunks" summarizing prior episodes.

**What we learned:**
- Our token analysis (8K tokens/week = 6.4% of context) suggests we don't need memory summarization for 1 week. But LIFELONG-SOTOPIA's finding that performance degrades confirms it would matter for multi-week simulations.
- Their "episode chaining" maps to our concept of scenario sequences — running progressively harder weeks.

📄 [arxiv.org/abs/2506.12666](https://arxiv.org/abs/2506.12666)

---

### SOTOPIA-π (Zhou et al., ACL 2024)

Interactive learning: behavior cloning + self-reinforcement on filtered interaction data. 7B model reaches GPT-4 level.

**Relevance:** Shows that training on high-quality social interaction data can dramatically improve smaller models. If our simulation produces good interaction traces, they could be training data for PM-specific fine-tuning.

📄 [arxiv.org/abs/2403.08715](https://arxiv.org/abs/2403.08715)

---

### MultiAgentBench / MARBLE (ACL 2025)

Multi-agent collaboration benchmark. Milestone-based metrics. Tests different coordination topologies (star, chain, tree, graph).

**Relevance:** Their milestone-based metrics align with our time-weighted checkpoints — both measure progress, not just final state. Their topology testing is interesting: our scenario is "star" (PM connects to all NPCs). Future work could test "chain" (PM → Alex → Priya dependency).

📄 [arxiv.org/abs/2503.01935](https://arxiv.org/abs/2503.01935)

---

### SocialVeil (Feb 2026)

Social intelligence under communication barriers. Tests agents when communication is impaired by cognitive differences.

**Relevance:** Alex's avoidant personality is a communication barrier — he won't volunteer information unless pressed with evidence. SocialVeil formalizes this: can the agent overcome the barrier to extract needed information?

---

### τ-Bench (Sierra, 2024)

Tool-agent-user interaction benchmark. Uses pass^k metric for reliability across trials.

**What we borrowed:**
- Database state comparison as primary evaluation signal
- The insight that "same task, different trials" reveals reliability (our `--runs N` variance measurement)

**What we do differently:**
- Their tasks are single-turn. Ours are week-long continuous interactions.
- They compare final DB state. We compare trajectory (when things happened).

📄 [arxiv.org/abs/2406.12045](https://arxiv.org/abs/2406.12045)

---

## How Ideas Map to Our Implementation

| Research Idea | Source | Our Implementation |
|--------------|--------|-------------------|
| Unified checkpoint scoring | TheAgentCompany | `scoring.py` — all checks are Checkpoint objects |
| `evaluate_with_llm(content, predicate)` | TheAgentCompany | `llm_eval.py` — same pattern, with verdict + evidence |
| Post-hoc evaluation | TheAgentCompany | `evaluator.py` — Layer 2 runs after simulation |
| Multi-dimensional evaluation | SOTOPIA | 8 PM categories in `scoring.py` CATEGORIES |
| Max turn / stale detection | SOTOPIA | `npc.py` — consecutive reply cap + stale detection |
| Agent "wait" action | SOTOPIA | NPC prompt: "choose wait when nothing to add" |
| Game Master pattern | Concordia | `game_master.py` — event loop orchestrator |
| State progression | Our design | NPC hidden state evolves per day (not in any reference) |
| Time-weighted scoring | Our design | Earlier discovery = more points (not in any reference) |
| Two-layer signal detection | Our design (inspired by TheAgentCompany split) | Layer 1 SQL + Layer 2 LLM judge |
| Hybrid post-hoc evaluation | Our design | Simulation flags (sync) + evaluation candidates (post-hoc) |

---

## Research Gaps We Address

1. **No existing PM benchmark.** TheAgentCompany has PM tasks but they're independent. No one tests continuous PM judgment over a week.

2. **Static NPCs.** TheAgentCompany NPCs have one strategy_hint. SOTOPIA NPCs have goals but no state progression. Our NPCs evolve: Monday Alex says "fine", Thursday Alex says "I'm stuck."

3. **No time-sensitive evaluation.** Existing benchmarks test whether something happened, not when. Our time-weighted scoring is novel.

4. **No anti-spam evaluation.** Existing benchmarks don't penalize an agent that sends 281 emails to accomplish a task that needs 5. Our spam_penalty and NPC conversation limits address this.

5. **No misleading-status detection.** No benchmark checks if the agent told its stakeholder the truth. Our misleading_status checkpoint fills this gap.
