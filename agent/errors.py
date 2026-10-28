from __future__ import annotations

from typing import Optional


class BankAPIError(Exception):
    """Base error for the agent-side bank client.

    `message` is safe to log: callers must not put the session token or the
    pending confirmation token into it. The token never appears in str/repr.
    """

    def __init__(self, message: str, status_code: Optional[int] = None,
                 code: Optional[str] = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(status_code={self.status_code!r}, "
            f"code={self.code!r})"
        )


class BankUnauthorized(BankAPIError):
    """401: the session token is missing, expired or revoked."""


class BankNotFound(BankAPIError):
    """404: the resource is not visible to this customer."""


class BankRejected(BankAPIError):
    """400/403/409/422: the request was understood but refused."""


class BankUnavailable(BankAPIError):
    """Timeout, connection failure or 5xx from the bank API."""
