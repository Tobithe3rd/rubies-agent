from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from core.clock import Clock


@dataclass
class SessionState:
    """Per-conversation state for one customer. Pure logic, no I/O and no
    Strands/AWS imports. The session token is never printed.

    The two-step confirmation rule lives here: a pending action proposed on
    turn N can only be confirmed once a later user message has started turn
    N+1 (or later).
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    token: Optional[str] = None
    customer_name: Optional[str] = None
    turn: int = 0
    pending: dict = field(default_factory=dict)
    failed_retrievals: int = 0
    consecutive_failed_retrievals: int = 0
    tool_error_count: int = 0
    failed_verifications: int = 0
    # Injected time source; reserved for later steps, unused by pure logic here.
    clock: Optional[Clock] = None

    @property
    def verified(self) -> bool:
        return self.token is not None

    def start_turn(self) -> int:
        """Called once per incoming user message, before it is handled."""
        self.turn += 1
        return self.turn

    # --- two-step confirmation ---

    def register_pending(self, pending_token: str, tool: str) -> None:
        self.pending[pending_token] = {"tool": tool, "proposed_turn": self.turn}

    def can_confirm(self, pending_token: str) -> tuple[bool, str]:
        entry = self.pending.get(pending_token)
        if entry is None:
            return (False, "unknown_token")
        if entry["proposed_turn"] == self.turn:
            return (False, "same_turn")
        return (True, "ok")

    def consume_pending(self, pending_token: str) -> None:
        self.pending.pop(pending_token, None)

    # --- counters ---

    def record_retrieval(self, status: str) -> None:
        if status == "no_relevant_result":
            self.failed_retrievals += 1
            self.consecutive_failed_retrievals += 1
        elif status == "ok":
            self.consecutive_failed_retrievals = 0

    def record_tool_error(self) -> None:
        self.tool_error_count += 1

    def record_failed_verification(self) -> None:
        self.failed_verifications += 1

    # --- identity ---

    def set_verified(self, token: str, customer_name: Optional[str]) -> None:
        self.token = token
        self.customer_name = customer_name

    def clear_verified(self) -> None:
        self.token = None
        self.customer_name = None

    def __repr__(self) -> str:
        return (
            f"SessionState(session_id={self.session_id!r}, verified={self.verified}, "
            f"customer_name={self.customer_name!r}, turn={self.turn}, "
            f"pending={sorted(self.pending)})"
        )

    __str__ = __repr__
