from __future__ import annotations

import abc
from dataclasses import dataclass
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
    metadata: dict
    # metadata must contain at least doc and section keys when used with RAG


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
    def create_handoff_ticket(self, customer_id_or_none: Optional[int], summary: str) -> dict:
        ...

    @abc.abstractmethod
    def reset_data(self) -> None:
        ...

    @abc.abstractmethod
    def insert_seed_data(self, dataset: dict) -> None:
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
