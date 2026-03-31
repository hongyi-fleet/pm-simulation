"""ToolSurface protocol: the contract every tool surface implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ActionResult:
    """Result of a tool action."""

    success: bool
    data: Any = None
    error: str | None = None


@runtime_checkable
class ToolSurface(Protocol):
    """Interface that all tool surfaces must implement.

    The engine calls handle_action() during the tick loop.
    The scenario loader calls seed() to populate initial data.
    The agent and NPCs see schema() to know what actions are available.
    """

    def handle_action(
        self, action_name: str, params: dict[str, Any], tick: int
    ) -> ActionResult:
        """Execute an action on this tool surface.

        Args:
            action_name: The action to perform (e.g., "send_chat", "read_emails")
            params: Action parameters
            tick: Current simulation tick

        Returns:
            ActionResult with success/failure and any data or error message
        """
        ...

    def schema(self) -> dict[str, Any]:
        """Return the tool schema for agent/NPC function calling.

        Returns:
            Dict describing available actions, their parameters, and types.
            Compatible with OpenAI function-calling format.
        """
        ...

    def seed(self, data: list[dict[str, Any]], tick: int = 0) -> None:
        """Populate the tool surface with initial scenario data.

        Args:
            data: List of seed records from the scenario YAML
            tick: The tick at which this data exists (default: 0)
        """
        ...

    def dump_state(self) -> list[dict[str, Any]]:
        """Serialize current state for snapshots.

        Returns:
            List of all records in this tool surface, JSON-serializable.
        """
        ...


# Validation constants
MAX_MESSAGE_LENGTH = 2000
MAX_SUBJECT_LENGTH = 500


def validate_text_length(text: str, field: str, max_length: int) -> str | None:
    """Validate text field length. Returns error message or None."""
    if len(text) > max_length:
        return f"{field} exceeds maximum length ({len(text)} > {max_length} chars)"
    return None
