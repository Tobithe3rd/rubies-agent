"""Panel state, receipts, template rendering."""
from __future__ import annotations

import uuid

from core.config import AppConfig
from .store import ChatSessionStore
from .scrub import _mask_phone, _scrub_summary, _history_text


def _record_panel_result(
    cfg: AppConfig,
    store: ChatSessionStore,
    entry: dict,
    tool_name: str,
    status: str,
    args: dict,
    envelope: dict,
) -> bool:
    panel = entry["panel"]
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}

    if tool_name == "verify_customer":
        if status == "success" and data.get("verified") is True:
            panel["verified"] = True
            panel["phone_masked"] = _mask_phone(args.get("phone"))
            panel["verified_at"] = store._now()
            entry["was_verified_at"] = panel["verified_at"]
            return True
        if status != "success":
            return store._clear_verification(panel)
        return False

    if status != "success":
        if envelope.get("error") == "session_expired":
            return store._clear_verification(panel)
        return False

    kind = None
    fields: dict = {}
    if tool_name == "confirm_action":
        result_status = data.get("status")
        if result_status == "dispute_opened":
            kind = "dispute"
            fields = {"reference": data.get("reference")}
        elif result_status == "card_blocked":
            kind = "card_block"
            fields = {"last4": data.get("last4")}
    elif tool_name == "handoff_to_human" and data.get("ticket_id"):
        kind = "handoff"
        fields = {"reference": data.get("ticket_id"), "summary": args.get("summary")}
    if kind is None:
        return False

    _RECEIPT_TOOL_FOR_KIND = {
        "dispute": "open_dispute",
        "card_block": "block_card",
        "handoff": "handoff_to_human",
    }
    source_tool = _RECEIPT_TOOL_FOR_KIND[kind]
    tool_cfg = cfg.tools.get(source_tool)
    receipt_cfg = getattr(tool_cfg, "receipt", None)
    if receipt_cfg is None:
        return False

    values = {
        "reference": "" if fields.get("reference") is None else str(fields["reference"]),
        "last4": "" if fields.get("last4") is None else str(fields["last4"]),
        "summary": fields.get("summary") or "",
    }
    session = getattr(entry.get("runner"), "session", None)
    secrets_to_remove = [getattr(session, "token", None)]
    secrets_to_remove.extend((getattr(session, "pending", None) or {}).keys())
    summary = _scrub_summary(
        receipt_cfg.template.format(**values),
        secrets_to_remove,
        list(cfg.tools),
        cfg.settings.adapters.web.panel_summary_max_chars,
        cfg.settings.bank_api.otp_length,
    )
    reference = None if fields.get("reference") is None else str(fields["reference"])
    from .transcript import _iso_time
    panel["receipts"].append({
        "id": uuid.uuid4().hex,
        "kind": kind,
        "reference": reference,
        "summary": summary,
        "at": _iso_time(store._now(), cfg.settings.timezone),
    })
    return True


def panel_view(entry: dict, cfg: AppConfig, store: ChatSessionStore) -> dict:
    panel = entry["panel"]
    expires_in = None
    if panel["verified"]:
        if panel["verified_at"] is None:
            store._clear_verification(panel)
        else:
            remaining = panel["verified_at"] + store.verification_seconds - store._now()
            if remaining <= 0:
                store._clear_verification(panel)
            else:
                expires_in = max(1, int(remaining))
    return {
        "verified": bool(panel["verified"]),
        "phone_masked": panel["phone_masked"] if panel["verified"] else None,
        "expires_in_seconds": expires_in,
        "receipts": [dict(receipt) for receipt in panel["receipts"]],
    }
