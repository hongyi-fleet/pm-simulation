# Benchmark Results

Scenario: `nexus_billing_short` (Mon-Wed, 60-min agent turns)
NPC/Judge model: gpt-5.4-mini for both runs
Date: 2026-03-30

## Model Comparison

| Checkpoint | gpt-5.4-mini | gpt-5.4 | Category |
|-----------|-------------|---------|----------|
| blocker_discovery | 2/2 Mon 09:45 | 2/2 Mon 10:45 | Information Discovery |
| dependency_surfaced | 1/2 Wed 13:20 | 2/2 Mon 12:00 | Information Discovery |
| vendor_news_discovered | 2/2 Tue 14:20 | 2/2 Tue 14:00 | Information Discovery |
| priya_bug_discovered | 0/1 Never | 0/1 Never | Information Discovery |
| risk_communicated | 0/2 Never | 2/2 Wed 09:00 | Upward Communication |
| scope_creep_handled | 0/2 Never | 2/2 Achieved | Upward Communication |
| communication_quality | 1/1 (0.84) | 1/1 (0.88) | Upward Communication |
| dashboard_restraint | 1/1 | 1/1 | Prioritization |
| dashboard_demo_addressed | 1/1 Wed 13:45 | 1/1 Wed 09:30 | Prioritization |
| prioritization | 1/1 (0.80) | 1/1 (0.84) | Prioritization |
| blocker_resolved | 0/2 Never | 1/2 Wed 09:00 | Team Coordination |
| information_discretion | 0/1 Triggered (bad) | 0/1 Triggered (bad) | Relationship |
| action_efficiency | 1/1 | 1/1 | Efficiency |
| **TOTAL** | **10/19 (52.6%)** | **16/19 (84.2%)** | |

## By PM Responsibility

| Category | gpt-5.4-mini | gpt-5.4 |
|----------|-------------|---------|
| Information Discovery | 5/7 (71%) | 6/7 (86%) |
| Upward Communication | 1/5 (20%) | 5/5 (100%) |
| Prioritization | 3/3 (100%) | 3/3 (100%) |
| Team Coordination | 0/2 (0%) | 1/2 (50%) |
| Relationship & Discretion | 0/1 (0%) | 0/1 (0%) |
| Efficiency | 1/1 (100%) | 1/1 (100%) |

## Key Findings

### gpt-5.4 vs gpt-5.4-mini: +32 percentage points

The gap is almost entirely in **Upward Communication** (20% → 100%):
- gpt-5.4 communicated risk to Dana with specific details (Wed 09:00)
- gpt-5.4-mini found the blocker but never told Dana
- gpt-5.4 pushed back on CEO's scope creep request
- gpt-5.4-mini ignored the scope creep email entirely

### Both models fail on

- **priya_bug_discovered (0/1):** Short scenario ends Wednesday, Priya's bug appears Thursday. Expected failure.
- **information_discretion (0/1):** Both agents exposed Alex's blocker publicly. Neither model has the social awareness to keep sensitive info private.

### blocker_resolved causal chain works

gpt-5.4 discovered the blocker (Mon 10:45) THEN resolved it (Wed 09:00). The causal dependency prevented the old bug where resolution triggered before discovery.

gpt-5.4-mini discovered the blocker (Mon 09:45) but never resolved it — because it never communicated to Dana, which is required by the state_check.

### Judge evidence examples

From `judge_log.json`:

**risk_communicated (gpt-5.4-mini = NO):**
> "The PM agent's message is sent to Alex Chen, not to Dana Park, and it does not directly communicate a concrete risk."

**blocker_resolved (gpt-5.4-mini = NO):**
> "Does not show the PM learning the blocker and then taking any concrete resolution action."

**scope_creep_handled (gpt-5.4 = YES):**
> (Agent responded to Dana's invoice export email with impact assessment)

## Observations for Simulation Design

1. **Upward Communication is the differentiator.** Both models discover problems at similar speed. The gap is in what they do with the information. This validates having separate checkpoints for discovery vs communication.

2. **information_discretion is too hard or too strict.** Both frontier models fail. Either the detection is too sensitive, or current LLMs lack the social judgment to keep information private.

3. **Short scenario (Mon-Wed) can't test Thu/Fri checkpoints.** priya_bug_discovered is always 0. Need full scenario for complete evaluation.

4. **Single run variance.** This is n=1 per model. Need runs=3 to measure whether the 32-point gap is real or noise.
