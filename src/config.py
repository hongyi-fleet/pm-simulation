"""Central configuration for all simulation constants.

All hardcoded values live here. Change them in one place,
affects the whole system.
"""

from datetime import datetime, timedelta


# === Simulation Time ===
BASE_DATE = datetime(2025, 3, 3, 9, 0)  # Monday 9:00 AM
WORK_START_HOUR = 9
WORK_END_HOUR = 17
SIM_START = BASE_DATE
SIM_END = BASE_DATE + timedelta(days=4, hours=8)  # Friday 5:00 PM

# === Agent ===
MAX_WRITE_ACTIONS = 5          # Write actions per turn (reads are free)
AGENT_TURN_INTERVAL = 30       # Minutes between scheduled agent turns
AGENT_COOLDOWN_MINUTES = 10    # Cooldown after agent acts (prevents NPC cascade)
AGENT_TEMPERATURE = 0.0        # Agent LLM temperature (deterministic)
AGENT_SLIDING_WINDOW = 18      # Conversation history: keep first 2 + last 16

# === NPC ===
NPC_CONTEXT_TOKEN_BUDGET = 2000   # Max tokens for NPC prompt context
NPC_TEMPERATURE = 0.7             # NPC LLM temperature (variety in responses)
SUMMARY_EVERY_N_INTERACTIONS = 5  # Summarize NPC memory every N interactions

# === Tool Surfaces ===
MAX_MESSAGE_LENGTH = 2000   # Max chars for chat messages and email bodies
MAX_SUBJECT_LENGTH = 500    # Max chars for email subjects
MAX_DOC_LENGTH = MAX_MESSAGE_LENGTH * 5  # Max chars for documents

# === LLM ===
LLM_TIMEOUT_DEFAULT = 180.0   # Default timeout for LLM calls (seconds)
LLM_JUDGE_TIMEOUT = 10.0      # Timeout for LLM judge calls
LLM_JUDGE_RUNS = 3            # Number of LLM judge runs (take median)
LLM_JUDGE_TEMPERATURE = 0.0   # Judge temperature (deterministic)
