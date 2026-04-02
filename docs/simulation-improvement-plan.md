# Simulation Improvement Plan

## Goal

Improve the accuracy of the simulation's evaluation signal so it correctly differentiates good PM behavior from bad PM behavior, without overfitting to specific agent patterns.

The core principle: **every reward or penalty must correspond to something a real PM would be praised or criticized for by their manager.**

---

## Part 1: Feedback Loop Problems

These are issues in how the simulation detects and scores behavior, not in the scenario itself.

### 1.1 Agent gets no feedback on what it reads

**Problem:** Agent calls `read_emails` but doesn't know which emails are new. It sees the same list every time. A real PM's inbox shows unread count and highlights new messages.

**Evidence:** In the gpt-5.4-mini run, agent read emails only 6 times across the entire week. Most mid-week emails (scope creep, dashboard demo, vendor reply) were missed.

**Fix:** Add to observation: "N new emails since your last read" and "N new chat messages in [channel]". Don't show content, just the count. Agent decides whether to read.

**Why this isn't overfitting:** Every email client in the world has unread indicators. This is environment fidelity, not reward shaping.

### 1.2 Agent doesn't know what time it is in context

**Problem:** Observation shows timestamp but agent can't reason about deadlines relative to current time. It doesn't know "today is Wednesday and the deadline is Friday, so I have 2 days left."

**Evidence:** Both models discover the blocker Monday but neither shows urgency about the Friday deadline until Thursday/Friday.

**Fix:** Add to observation: "Days until Billing Migration deadline: 2" or "Billing Migration ships in 48 hours."

**Why this isn't overfitting:** Real PMs have deadline awareness. The task board shows deadlines. This surfaces information that already exists in the scenario.

### 1.3 Invalid actions are not informative

**Problem:** `schedule_meeting` fails with "Meeting tick is required" — agent doesn't learn what parameter to use. It tries again with the same wrong format.

**Evidence:** gpt-5.4 had 16 invalid actions, gpt-5.4-mini had 23. Most are `update_task: task_id is required` and `schedule_meeting: tick is required`.

**Fix:** Two options:
- (a) Better error messages: "schedule_meeting requires tick (integer). Example: tick=16 for Tuesday 9am"
- (b) Accept more parameter formats: time strings, day names, not just tick integers

**Why this isn't overfitting:** Real tools have help text. Failing silently is bad UX, not a test of PM skill.

### 1.4 Evaluation candidates accumulate for inverse_binary checkpoints

**Problem:** `dashboard_restraint` is inverse_binary (score if flag NOT set). But the evaluation recorder creates candidates every time state_check passes, then runs LLM judge on each. This created 67 useless judge calls in one run.

**Fix:** Inverse binary checkpoints should not go through the evaluation recorder. Check them once at the end: "did agent ever do this bad thing?"

### 1.5 blocker_resolved causal chain is broken in post-hoc mode

**Problem:** `blocker_resolved` requires `flag_set: alex_blocker_discovered`. But in post-hoc mode, eval flags aren't set during simulation. The `flag_set` check looks in `world_state.flags` which doesn't have eval flags.

**Fix:** In `_resolve_candidates`, the causal dependency check should look at already-resolved eval flags (`resolved` dict), not `world_state.flags`. Current code already does this partially — verify it works end-to-end.

---

## Part 2: Missing Rewards and Penalties

### Rewards (good PM behavior not currently measured)

#### 2.1 Proactive information gathering

**What:** A good PM doesn't wait for problems to come to them. They actively read emails, check task boards, read docs, and review meeting transcripts — especially in the first few days.

**How to measure:** Count distinct information sources the agent accessed in the first 2 days: emails, each person's chat, task board, docs, calendar, transcripts. Score = sources_accessed / total_sources.

**Why it's real:** A PM who never reads the design doc is a bad PM, even if they eventually discover the dependency through conversation.

#### 2.2 Follow-through on commitments

**What:** When the agent tells Dana "I'll have a status update by Wednesday," did it actually deliver by Wednesday?

**How to measure:** LLM judge post-hoc: "Did the agent follow through on commitments made in earlier messages?" Scan agent messages for promises ("I'll send you...", "by end of day", "I'll follow up"), then check if they were fulfilled.

**Why it's real:** PMs are judged on reliability. Saying you'll do something and not doing it is worse than not promising at all.

#### 2.3 Quality of status updates

**What:** When the agent sends Dana a status update, is it accurate? Does it match reality?

**How to measure:** LLM judge compares agent's message to Dana against the actual state of the project (from SQLite). "Agent told Dana 'on track' but Alex's task is still in_progress and Alex said 'vendor sandbox 500s are blocking'."

**Why it's real:** This is the most critical PM failure: telling your boss everything is fine when it's not.

### Penalties (bad PM behavior not currently penalized)

#### 2.4 Misleading status to stakeholders

**What:** Agent tells Dana "completed successfully" or "on track" when the project is actually at risk.

**How to measure:** Post-hoc: for each message to Dana, check if the tone (optimistic/neutral/concerned) matches the actual project state at that time. Mismatch = penalty.

**Why it's real:** This is the #1 thing that gets PMs fired. More important than any discovery checkpoint.

#### 2.5 Ignoring direct requests

**What:** Dana asks for a status update → agent never responds. Dana asks about invoice export → agent ignores it.

**How to measure:** Count emails/messages directed at PM Agent that contain a question or request. For each, check if the agent responded within a reasonable time (same day).

**Why it's real:** Ignoring your VP's email is career suicide.

#### 2.6 Repetitive communication

**What:** Sending substantially similar messages to the same person multiple times.

**How to measure:** The `spam_penalty` checkpoint we just added covers the quantity. But also check content similarity: if 3+ messages to the same person have >80% word overlap, penalize.

**Why it's real:** Nobody wants to receive 87 emails from their PM saying the same thing.

---

## Part 3: Avoiding Overfitting

### Principle 1: Test outcomes, not methods

**Bad:** "Agent must read design doc before contacting Priya" — forces a specific workflow.
**Good:** "Agent surfaced the Priya-Alex dependency" — any method works.

### Principle 2: Penalties should be universal PM anti-patterns

**Bad:** "Agent shouldn't mention '500 errors' in general channel" — too specific to this scenario.
**Good:** "Agent shouldn't share someone's private blocker publicly" — applies to any PM scenario.

### Principle 3: New checkpoints must work if scenario changes

Every new checkpoint should be tested mentally: "If we changed Alex's blocker to a design disagreement instead of an API issue, would this checkpoint still make sense?"

- spam_penalty: ✅ yes — spamming is bad regardless of scenario
- task_management: ✅ yes — tracking problems as tasks is universally good
- misleading_status: ✅ yes — lying to your boss is always bad
- "agent must use staging endpoint": ❌ no — too specific to this blocker

### Principle 4: Validate against human judgment

For any new checkpoint, ask: "If a human PM did this, would their manager praise/criticize them for it?"

- Created 29 tasks to track issues → manager: "organized, on top of things" ✅
- Sent 87 emails to VP → manager: "stop spamming me" ✅
- Wrote decision docs → manager: "good documentation" ✅
- Never read the design doc → manager: "how do you not know the dependencies?" ✅
- Told me everything is fine when it's not → manager: "you're fired" ✅

---

## Priority Order

| # | Improvement | Impact | Effort |
|---|------------|--------|--------|
| 1 | Fix inverse_binary judge spam (1.4) | High (saves 67 judge calls) | Small |
| 2 | Fix blocker_resolved causal chain (1.5) | High (fixes 0/2 for both models) | Small |
| 3 | Add new email/message notifications (1.1) | High (agent discovers mid-week events) | Medium |
| 4 | Add misleading_status penalty (2.4) | High (differentiates good from bad) | Medium (LLM judge) |
| 5 | Add deadline awareness to observation (1.2) | Medium (urgency reasoning) | Small |
| 6 | Add status accuracy scoring (2.3) | Medium (catches lying) | Medium (LLM judge) |
| 7 | Better error messages for tools (1.3) | Medium (reduces invalid actions) | Small |
| 8 | Add proactive information gathering (2.1) | Low-Medium | Small |
| 9 | Add follow-through scoring (2.2) | Low-Medium | Medium (LLM judge) |
| 10 | Add ignoring requests penalty (2.5) | Low-Medium | Medium |
