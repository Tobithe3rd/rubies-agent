from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class HealthStatus:
    name: str
    ok: bool
    detail: str
    # detail must never contain secrets (enforced by caller convention)


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    # metadata must contain at least doc and section keys when used with RAG
    doc_id: str = ""
    doc_title: str = ""
    file: str = ""
    section_number: int = 0
    section_heading: str = ""
    citation: str = ""
    word_count: int = 0


@dataclass
class SearchResult:
    chunk: Chunk
    score: float
    # score is higher-is-better, normalised to 0-1.
    # The similarity_threshold in settings.yaml means the same thing
    # regardless of which vector store produces the score.


# --- interfaces ---

class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def get_model(self) -> Any:
        """Return the framework model object the agent will use.

        Intentionally untyped so the agent layer can use Strands
        now and a different framework later without changing this interface.
        """
        ...

    @abc.abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        ...


class Embedder(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @property
    @abc.abstractmethod
    def dimensions(self) -> int:
        ...

    @abc.abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...


class VectorStore(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        ...

    @abc.abstractmethod
    def search(self, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        ...

    @abc.abstractmethod
    def count(self) -> int:
        ...

    @abc.abstractmethod
    def reset(self) -> None:
        ...


class DataStore(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def connect(self) -> None:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...

    # Customer identity
    @abc.abstractmethod
    def init_schema(self) -> None:
        ...

    @abc.abstractmethod
    def get_customer_by_phone(self, phone: str) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def get_customer(self, customer_id: int) -> Optional[dict]:
        ...

    # Account / balance (balance in kobo)
    @abc.abstractmethod
    def get_account(self, customer_id: int) -> Optional[dict]:
        ...

    # Transactions
    @abc.abstractmethod
    def list_transactions(self, customer_id: int, limit: int = 10) -> list[dict]:
        ...

    @abc.abstractmethod
    def get_transaction_by_reference(self, customer_id: int, reference: str) -> Optional[dict]:
        ...

    # Disputes
    @abc.abstractmethod
    def create_dispute(self, customer_id: int, transaction_id: int, reason: str) -> dict:
        ...

    @abc.abstractmethod
    def get_open_dispute_for_transaction(self, customer_id: int, transaction_id: int) -> Optional[dict]:
        ...

    # Cards
    @abc.abstractmethod
    def get_card(self, customer_id: int, last4: str) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def block_card(self, customer_id: int, last4: str) -> dict:
        ...

    # Loans
    @abc.abstractmethod
    def get_active_loan(self, customer_id: int) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def get_loan_inputs(self, customer_id: int) -> dict:
        ...

    # OTP
    @abc.abstractmethod
    def create_otp(self, phone: str, code_hash: str, expires_at: str) -> dict:
        ...

    @abc.abstractmethod
    def get_latest_otp(self, phone: str) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def increment_otp_attempts(self, otp_id: int) -> None:
        ...

    @abc.abstractmethod
    def mark_otp_used(self, otp_id: int) -> None:
        ...

    # Session
    @abc.abstractmethod
    def create_session(self, customer_id: int, token_hash: str, expires_at: str) -> dict:
        ...

    @abc.abstractmethod
    def get_session_by_token_hash(self, token_hash: str) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def revoke_session(self, token_hash: str) -> None:
        ...

    # Audit
    @abc.abstractmethod
    def write_audit(self, session_ref: Optional[str], customer_id: Optional[int], action: str, params_json: str, outcome: str) -> None:
        ...

    # Handoff
    @abc.abstractmethod
    def create_handoff_ticket(self, customer_id_or_none: Optional[int], summary: str, reason: str = "other") -> dict:
        ...

    @abc.abstractmethod
    def reset_data(self) -> None:
        ...

    @abc.abstractmethod
    def insert_seed_data(self, dataset: dict) -> None:
        ...

    # Pending actions (two-step confirmation)
    @abc.abstractmethod
    def create_pending_action(self, customer_id: int, token_hash: str, session_ref: Optional[str],
                              action_type: str, payload_json: str, expires_at: str) -> dict:
        ...

    @abc.abstractmethod
    def get_pending_action_by_token_hash(self, customer_id: int, token_hash: str) -> Optional[dict]:
        ...

    @abc.abstractmethod
    def mark_pending_action_used(self, customer_id: int, pending_action_id: int) -> None:
        ...


ChatHandler = Callable[[str, str], str]
"""Handler signature: (session_id: str, message: str) -> str."""


class InterfaceAdapter(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def start(self, handler: ChatHandler) -> None:
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        ...


class OTPSender(abc.ABC):
    """Delivers a one-time passcode to a phone. Config picks the implementation."""

    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def send(self, phone: str, code: str) -> None:
        ...


class BankGateway(abc.ABC):
    """Agent-side client for the mock bank API.

    Identity rule: no method takes customer_id. The only session identity is
    `token`; `pending_token` is the single-use confirmation token. The phone
    is used only to start/complete verification. Implementations must send the
    token in the same header the API expects and must never put it in errors.
    """

    @abc.abstractmethod
    def verify_start(self, phone: str) -> dict:
        ...

    @abc.abstractmethod
    def verify_complete(self, phone: str, otp: str) -> dict:
        ...

    @abc.abstractmethod
    def get_balance(self, token: str) -> dict:
        ...

    @abc.abstractmethod
    def get_mini_statement(self, token: str, limit: Optional[int] = None) -> dict:
        ...

    @abc.abstractmethod
    def get_transaction_status(self, token: str, reference: str) -> dict:
        ...

    @abc.abstractmethod
    def propose_dispute(self, token: str, reference: str, reason: str) -> dict:
        ...

    @abc.abstractmethod
    def propose_card_block(self, token: str, last4: str) -> dict:
        ...

    @abc.abstractmethod
    def confirm_action(self, token: str, pending_token: str) -> dict:
        ...

    @abc.abstractmethod
    def check_loan_eligibility(self, token: str, amount: int) -> dict:
        ...

    @abc.abstractmethod
    def get_loan_status(self, token: str) -> dict:
        ...

    @abc.abstractmethod
    def create_handoff(self, summary: str, token: Optional[str] = None,
                       reason: Optional[str] = None) -> dict:
        ...
