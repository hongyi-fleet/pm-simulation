# Memory & Token Analysis

## Current Setup: 1 Week, 4 NPCs, 1 Project

| Data source | Token count | % of context (128K) |
|-------------|------------|-------------------|
| Seed data (emails, tasks, docs, transcripts) | ~508 | 0.4% |
| Agent chat messages (~120 msgs) | ~3,600 | 2.8% |
| NPC chat responses (~60 msgs) | ~1,800 | 1.4% |
| Agent emails (~10) | ~800 | 0.6% |
| Standup transcripts (5 days) | ~1,000 | 0.8% |
| **Total by Friday** | **~7,700** | **6.0%** |

Even if the agent reads ALL 6 tools in a single turn: **~8,400 tokens = 6.6% of context.**

**Conclusion: Agent memory summarization is unnecessary for a 1-week simulation.** The data fits easily in context. The agent can re-read everything from SQLite every turn without hitting limits.

## When Does Memory Become a Problem?

### Scaling by simulation length (4 NPCs, 1 project)

| Duration | Total tokens | % of context | Status |
|----------|-------------|--------------|--------|
| 1 week | 8,200 | 6.4% | Comfortable |
| 4 weeks | 31,300 | 24.5% | Fine |
| 8 weeks | 62,100 | 48.5% | Fine |
| 13 weeks | 100,600 | 78.6% | Getting tight |
| **14 weeks** | **108,300** | **84.6%** | **Needs summarization** |
| 17 weeks | 131,400 | 102.7% | Exceeds context |

**Threshold: ~13 weeks (one quarter) before summarization is needed.**

### Scaling by NPC count (1 week)

| NPCs | Tokens/week | Weeks until context full |
|------|------------|------------------------|
| 4 | 7,700 | 16 weeks |
| 8 | 15,400 | 8 weeks |
| 12 | 23,100 | 5 weeks |
| 20 | 38,500 | 3 weeks |
| **53** | **~102,000** | **1 week** |

**You'd need ~53 NPCs before a single week exceeds context.**

### Scaling by project count (1 week, 4 NPCs)

| Projects | Tokens/week | Weeks until context full |
|----------|------------|------------------------|
| 1 | 5,400 | 23 weeks |
| 3 | 16,200 | 7 weeks |
| 5 | 27,000 | 4 weeks |
| 10 | 53,900 | 2 weeks |

## Design Implications

### Why Agent Doesn't Need Memory Summarization (Current Setup)

1. **Data volume is tiny.** 8K tokens out of 128K context. Not even close to the limit.
2. **Agent has tool access.** It can `read_emails` every turn. Information lives in SQLite, not in conversation history. The sliding window drops the agent's own reasoning, not the source data.
3. **Adding summarization costs more than it saves.** One summarization LLM call per N turns adds latency and risks losing information in the summary.

### When to Add Agent Memory Summarization

Add it when ANY of these are true:
- Simulation exceeds 10 weeks
- NPC count exceeds 15
- Project count exceeds 5
- Agent tool reads exceed 50% of context window per turn

### The Sliding Window IS Sufficient Because

The sliding window (keep first 2 + last 16 messages) drops old **agent reasoning**, not old **data**:

```
What gets dropped:       Agent's observation from Monday + agent's response
What's NOT dropped:      The actual emails, chats, tasks (still in SQLite)
What agent does:         read_emails() again → gets the same data back
```

The agent doesn't need to remember "I read the vendor email on Monday." It can read the vendor email again on Thursday. The email is in the database forever.

### Interview Answer

"One week of simulation with 4 NPCs generates ~8,000 tokens of data. That's 6% of GPT-4o's context window. The agent can re-read all tools every turn without approaching any limit. Memory summarization becomes necessary at ~13 weeks or ~53 NPCs. For our current scope, the database IS the agent's memory. The sliding window on conversation history only drops the agent's past reasoning, not the source data. If we scaled to a quarter-long simulation or a 20+ person company, we'd add summarization using the same pattern we already have for NPCs."
