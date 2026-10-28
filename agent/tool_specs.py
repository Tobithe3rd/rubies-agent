from __future__ import annotations

from typing import Any

# Per-tool argument contract. Descriptions stay in config/tools.yaml; this file
# only declares which arguments the model may supply and their simple types.
# No tool may declare customer_id or a session token: the runtime injects the
# session token from SessionState.
TOOL_SPECS: dict[str, dict[str, Any]] = {
    "verify_customer": {
        "allowed": {"phone": str, "otp": str},
        "required": {"phone"},
    },
    "get_balance": {"allowed": {}, "required": set()},
    "get_mini_statement": {
        "allowed": {"limit": int},
        "required": set(),
    },
    "get_transaction_status": {
        "allowed": {"reference": str},
        "required": {"reference"},
    },
    "open_dispute": {
        "allowed": {"reference": str, "reason": str},
        "required": {"reference", "reason"},
    },
    "block_card": {
        "allowed": {"last4": str},
        "required": {"last4"},
    },
    "check_loan_eligibility": {
        "allowed": {"amount": int},
        "required": {"amount"},
    },
    "get_loan_status": {"allowed": {}, "required": set()},
    "handoff_to_human": {
        "allowed": {"summary": str, "reason": str},
        "required": {"summary"},
    },
    "search_policy": {
        "allowed": {"query": str},
        "required": {"query"},
    },
    "confirm_action": {
        "allowed": {"pending_token": str},
        "required": {"pending_token"},
    },
}

FORBIDDEN_ARGUMENTS = frozenset({"customer_id", "token", "session_token"})

# Fail loudly at import if a schema ever declares an argument the model must
# never control. This keeps the identity rule impossible to violate by accident.
for _tool, _spec in TOOL_SPECS.items():
    _bad = set(_spec["allowed"]) & FORBIDDEN_ARGUMENTS
    if _bad:
        raise ValueError(f"{_tool} declares forbidden argument(s): {sorted(_bad)}")


def allowed_arguments(tool_name: str) -> set[str]:
    return set(TOOL_SPECS[tool_name]["allowed"])


def _type_ok(value: Any, expected: type) -> bool:
    if expected is int:
        # bool is an int subclass; an amount of True/False is not valid.
        return type(value) is int
    return isinstance(value, expected)


def validate_arguments(tool_name: str, args: dict[str, Any]) -> tuple[bool, str, str]:
    """Return (ok, error_code, message) for a tool call's arguments."""
    spec = TOOL_SPECS[tool_name]
    allowed = spec["allowed"]
    required = spec["required"]

    for name in args:
        if name not in allowed:
            return False, "unexpected_argument", f"unexpected argument: {name}"

    for name in required:
        if name not in args:
            return False, "missing_argument", f"missing required argument: {name}"

    for name, value in args.items():
        expected = allowed[name]
        if value is None and name not in required:
            continue
        if not _type_ok(value, expected):
            return False, "invalid_argument", (
                f"argument {name} must be {expected.__name__}"
            )

    return True, "", ""
