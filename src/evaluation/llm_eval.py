"""LLM-based evaluation for signal detection.

Same pattern as TheAgentCompany: pass content + a plain English predicate,
ask the LLM "does this indicate [predicate]? yes/no."

No keyword lists. No hardcoded detection. Works for any scenario.
"""

from __future__ import annotations

import logging

from src.config import LLM_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)


_judge_log: list[dict] = []  # Module-level log of all judge decisions


def get_judge_log() -> list[dict]:
    """Return all judge decisions from this run for debugging."""
    return _judge_log


async def evaluate_with_llm(
    content: str,
    predicate: str,
    llm_client,
    additional_prompt: str = "",
) -> bool:
    """Evaluate if a predicate can be inferred from the content.

    Args:
        content: The text to evaluate (conversation history, messages, etc.)
        predicate: Plain English description of what should be true
        llm_client: LLM client for making the call
        additional_prompt: Extra instructions for the judge

    Returns:
        True if the LLM judges the predicate is satisfied
    """
    if not content:
        return False

    query = f'Does the following content indicate that: {predicate}?\n\n'
    query += f'Content:\n"""\n{content}\n"""\n\n'
    query += f'Answer in this exact format:\n'
    query += f'VERDICT: yes or no\n'
    query += f'EVIDENCE: one sentence explaining what specific content supports your verdict\n'
    query += f'{additional_prompt}'

    try:
        response = await llm_client.generate(
            query, timeout=LLM_TIMEOUT_DEFAULT, temperature=0.0
        )
        response_lower = response.lower().strip()
        result = "verdict: yes" in response_lower or (response_lower.startswith("yes"))

        # Log verdict with evidence for debugging
        import sys
        evidence = response.strip().replace('\n', ' ')[:200]
        print(f"  [JUDGE] {predicate[:60]}... → {'YES' if result else 'NO'} | {evidence}", file=sys.stderr)

        _judge_log.append({
            "predicate": predicate,
            "verdict": result,
            "evidence": evidence,
            "content_length": len(content),
        })

        return result
    except Exception as e:
        logger.error(f"LLM evaluation failed: {e}")
        return False


def build_conversation_text(world_state, person_a: str, person_b: str) -> str:
    """Extract ALL communication involving two people from world state.

    Includes:
    - DM messages (channel = person's name)
    - Messages where one person talks about the other
    - Messages in any channel from either person that mention the other or relevant topics
    - Emails between them
    - Standup/meeting messages from either person

    This catches cases where:
    - Agent messages channel "Alex Chen" but Alex replies to channel "PM Agent"
    - Alex posts in standup channels about the blocker
    - Alex posts in #billing-migration about issues
    """
    messages = []

    person_a_first = person_a.split()[0] if person_a != "PM Agent" else "PM"
    person_b_first = person_b.split()[0] if person_b != "PM Agent" else "PM"

    # All messages from either person (catch everything)
    rows = world_state.execute(
        """SELECT tick, sender, channel, content, timestamp FROM messages
           WHERE sender = ? OR sender = ?
           ORDER BY tick, id""",
        (person_a, person_b),
    ).fetchall()

    for r in rows:
        sender = r["sender"]
        channel = r["channel"]
        content = r["content"]

        # Include if: DM between them, or mentions the other person, or relevant channel
        is_dm = (channel == person_a or channel == person_b or
                 channel == "PM Agent" or channel == "PM")
        mentions_other = (person_a_first.lower() in content.lower() or
                         person_b_first.lower() in content.lower())
        is_relevant_channel = any(kw in channel.lower() for kw in
                                  ["standup", "billing", "general", "pm", "dm"])

        if is_dm or mentions_other or is_relevant_channel or sender == person_a:
            messages.append((r["tick"], f"[Chat #{channel}] {sender}: {content}"))

    # Emails between the two people
    rows = world_state.execute(
        """SELECT tick, sender, recipient, subject, body FROM emails
           WHERE (sender = ? AND recipient = ?)
              OR (sender = ? AND recipient = ?)
           ORDER BY tick, id""",
        (person_a, person_b, person_b, person_a),
    ).fetchall()
    for r in rows:
        messages.append((r["tick"], f"[Email] {r['sender']} → {r['recipient']}: {r['subject']}\n{r['body']}"))

    # Sort by tick and deduplicate
    messages.sort(key=lambda x: x[0])
    seen = set()
    unique = []
    for tick, text in messages:
        if text not in seen:
            seen.add(text)
            unique.append(text)

    return "\n".join(unique)


def build_agent_actions_text(world_state) -> str:
    """Extract all agent actions as readable text."""
    import json
    rows = world_state.execute(
        "SELECT * FROM action_log WHERE actor = 'PM Agent' ORDER BY tick, id"
    ).fetchall()

    lines = []
    for r in rows:
        params = r["params"]
        try:
            params_dict = json.loads(params)
            params_str = ", ".join(f"{k}={v}" for k, v in params_dict.items() if k != "sender")
        except (json.JSONDecodeError, TypeError):
            params_str = str(params)

        status = "OK" if r["success"] else f"FAIL: {r['error']}"
        lines.append(f"{r['action']}({params_str}) [{status}]")

    return "\n".join(lines)


def build_all_messages_text(world_state, sender: str = None) -> str:
    """Extract all messages from a sender (or all) as readable text."""
    if sender:
        rows = world_state.execute(
            "SELECT * FROM messages WHERE sender = ? ORDER BY tick, id",
            (sender,),
        ).fetchall()
    else:
        rows = world_state.execute(
            "SELECT * FROM messages ORDER BY tick, id"
        ).fetchall()

    lines = []
    for r in rows:
        lines.append(f"[{r['timestamp']}] {r['sender']} (#{r['channel']}): {r['content']}")

    # Also include emails
    if sender:
        email_rows = world_state.execute(
            "SELECT * FROM emails WHERE sender = ? ORDER BY tick, id",
            (sender,),
        ).fetchall()
    else:
        email_rows = world_state.execute(
            "SELECT * FROM emails ORDER BY tick, id"
        ).fetchall()

    for r in email_rows:
        lines.append(f"[{r['timestamp']}] {r['sender']} → {r['recipient']}: {r['subject']}\n  {r['body']}")

    return "\n".join(lines)
