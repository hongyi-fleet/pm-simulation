"""LLM-as-judge evaluator for soft metrics.

Scores communication quality and prioritization reasoning
by reading the full action log. Temperature 0, structured JSON output.
Runs N times and takes the median for stability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class JudgeScore:
    """Score from the LLM judge on one dimension."""
    name: str
    description: str
    score: float  # 0.0 to 1.0
    weight: float
    weighted_score: float
    justification: str


@dataclass
class JudgeResult:
    """Complete LLM judge result."""
    scores: list[JudgeScore]
    total_weighted: float = 0.0
    total_possible: float = 0.0
    normalized_score: float = 0.0


def build_judge_prompt(
    criterion: dict,
    action_log: list[dict],
    agent_messages: list[dict],
) -> str:
    """Build the LLM judge prompt for one dimension."""
    name = criterion["name"]
    description = criterion.get("description", "")

    # Format agent actions for the judge
    actions_text = ""
    for a in action_log:
        if a.get("actor") == "PM Agent":
            actions_text += f"  [{a.get('tick', '?')}] {a['action']}: {json.dumps(a.get('params', {}))}\n"

    # Format agent messages
    messages_text = ""
    for m in agent_messages:
        messages_text += f"  [{m.get('timestamp', '?')}] → {m.get('recipient', m.get('channel', '?'))}: {m.get('content', m.get('body', ''))}\n"

    prompt = f"""You are evaluating an AI project manager agent on: {name}

CRITERION: {description}

The agent took these actions during a simulated work week:

ACTIONS:
{actions_text if actions_text else "(No actions recorded)"}

MESSAGES SENT BY THE AGENT:
{messages_text if messages_text else "(No messages sent)"}

Score the agent on a scale of 0.0 to 1.0:
- 0.0 = completely failed this dimension
- 0.3 = poor performance, major issues
- 0.5 = adequate but with clear gaps
- 0.7 = good performance, minor issues
- 0.9 = excellent, near-optimal
- 1.0 = perfect, could not be improved

Respond with exactly this JSON format:
{{"score": 0.0, "justification": "1-2 sentence explanation"}}

Be specific about what the agent did well or poorly. Reference specific actions."""
    return prompt


async def evaluate_with_judge(
    criteria: list[dict],
    action_log: list[dict],
    agent_messages: list[dict],
    llm_client=None,
    num_runs: int = 3,
    no_llm: bool = False,
) -> JudgeResult:
    """Run LLM judge on all criteria. Returns median of N runs."""
    scores = []

    for criterion in criteria:
        name = criterion["name"]
        description = criterion.get("description", "")
        weight = criterion.get("weight", 1.0)

        if no_llm or llm_client is None:
            # Mock judge for --no-llm mode
            score = JudgeScore(
                name=name,
                description=description,
                score=0.5,
                weight=weight,
                weighted_score=0.5 * weight,
                justification="Mock judge (--no-llm mode)",
            )
            scores.append(score)
            continue

        # Run N times, take median
        run_scores = []
        prompt = build_judge_prompt(criterion, action_log, agent_messages)

        for _ in range(num_runs):
            try:
                response = await llm_client.generate(
                    prompt, timeout=10.0, temperature=0.0
                )
                text = response.strip()
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                parsed = json.loads(text)
                run_scores.append(float(parsed.get("score", 0.5)))
            except Exception:
                run_scores.append(0.5)  # Default on failure

        # Take median
        run_scores.sort()
        median_score = run_scores[len(run_scores) // 2]

        score = JudgeScore(
            name=name,
            description=description,
            score=round(median_score, 3),
            weight=weight,
            weighted_score=round(median_score * weight, 3),
            justification=f"Median of {num_runs} runs: {[round(s, 2) for s in run_scores]}",
        )
        scores.append(score)

    result = JudgeResult(scores=scores)
    result.total_weighted = sum(s.weighted_score for s in scores)
    result.total_possible = sum(s.weight for s in scores)
    if result.total_possible > 0:
        result.normalized_score = result.total_weighted / result.total_possible
    return result
