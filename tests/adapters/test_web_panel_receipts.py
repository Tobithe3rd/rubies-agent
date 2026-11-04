"""Session panel: receipts and summary safety."""
import json

from tests.adapters.helpers import (
    PHONE,
    OTP,
    TOKEN,
    FakeClock,
    FakeGateway,
    client_with_runners,
    get_panel as _get_panel,
    make_tool_runner,
    open_chat as _open_chat,
    post_stream as _post_stream,
    sse_events,
    verify_script,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def get_panel(client, chat_id):
    panel = _get_panel(client, chat_id)
    assert panel
    return panel


def post_stream(client, chat_id, message):
    response = _post_stream(client, chat_id, message)
    assert response.status_code == 200
    return response.text


def test_proposal_creates_no_receipt(monkeypatch, cfg):
    runner, _ = make_tool_runner(
        cfg,
        [[("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")]],
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block my card")
        panel = get_panel(client, chat_id)

    assert panel["receipts"] == []
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_executed_dispute_creates_one_receipt(monkeypatch, cfg):
    runner, _ = make_tool_runner(
        cfg,
        [
            [("tool", "open_dispute", {"reference": "RUB-DB-002", "reason": "double debit"}),
             ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-D"}), ("text", "Done.")],
        ],
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        first = post_stream(client, chat_id, "open a dispute")
        assert "panel" not in [name for name, _ in sse_events(first)]
        second = post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert len(panel["receipts"]) == 1
    receipt = panel["receipts"][0]
    assert receipt["kind"] == "dispute"
    assert receipt["reference"] == "RUB-DB-002"
    assert receipt["summary"] == "Dispute opened for RUB-DB-002."
    assert receipt["at"].endswith("+01:00")
    assert "panel" in [name for name, _ in sse_events(second)]


def test_executed_block_creates_one_receipt(monkeypatch, cfg):
    runner, _ = make_tool_runner(
        cfg,
        [
            [("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-C"}), ("text", "Done.")],
        ],
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "block 0001")
        post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert len(panel["receipts"]) == 1
    receipt = panel["receipts"][0]
    assert receipt["kind"] == "card_block"
    assert receipt["reference"] is None
    assert receipt["summary"] == "Card ending 0001 blocked."


def test_failed_confirm_creates_no_receipt(monkeypatch, cfg):
    gateway = FakeGateway()
    gateway.confirm_fails = True
    runner, _ = make_tool_runner(
        cfg,
        [
            [("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-C"}), ("text", "Try again.")],
        ],
        gateway,
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "block 0001")
        body = post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert panel["receipts"] == []
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_handoff_receipt_caps_and_scrubs_summary(monkeypatch, cfg):
    clock = FakeClock()
    secret_summary = (
        f"Please call {PHONE} and use code {OTP} with {TOKEN}. "
        "My balance is ₦25,000. " + "x" * 700
    )
    runner, _ = make_tool_runner(
        cfg,
        [
            verify_script(),
            [("tool", "handoff_to_human", {"summary": secret_summary, "reason": "user_requested"}),
             ("text", "Passed over.")],
        ],
    )
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        body = post_stream(client, chat_id, "human please")
        panel = get_panel(client, chat_id)

    receipt = panel["receipts"][0]
    assert receipt["kind"] == "handoff"
    assert receipt["reference"] == "HT-123"
    assert len(receipt["summary"]) <= cfg.settings.adapters.web.panel_summary_max_chars
    assert "Passed to a human agent:" in receipt["summary"]
    serialized = json.dumps(panel) + body
    for forbidden in (
        PHONE, TOKEN, OTP, "25,000", "handoff_to_human", "confirm_action",
        "verify_customer", "open_dispute", "block_card", "pending_token",
    ):
        assert forbidden not in serialized
