"""Session panel: verification, expiry and isolation."""
import pytest

from tests.adapters.helpers import (
    FakeClock,
    client_with_runners,
    get_panel as _get_panel,
    make_tool_runner,
    open_chat as _open_chat,
    post_json as _post_json,
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


def post_json_message(client, chat_id, message):
    reply = _post_json(client, chat_id, message)
    assert reply
    return reply


def test_successful_verification_shows_masked_phone_and_expiry(monkeypatch, cfg):
    from tests.adapters.helpers import PHONE, TOKEN, OTP
    clock = FakeClock()
    runner, _ = make_tool_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    events = sse_events(body)
    names = [name for name, _ in events]
    assert "panel" in names
    assert names.index("panel") < names.index("done")
    assert [payload for name, payload in events if name == "panel"][0] == panel
    assert panel == {
        "verified": True,
        "phone_masked": "+234 ••• ••• 4567",
        "expires_in_seconds": cfg.settings.session.expiry_minutes * 60,
        "receipts": [],
    }
    assert PHONE not in body
    assert TOKEN not in body
    assert OTP not in body


def test_json_messages_route_also_updates_panel(monkeypatch, cfg):
    runner, _ = make_tool_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_json_message(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is True
    assert panel["phone_masked"] == "+234 ••• ••• 4567"


def test_sending_a_code_only_does_not_verify(monkeypatch, cfg):
    from tests.adapters.helpers import PHONE
    runner, _ = make_tool_runner(
        cfg, [[("tool", "verify_customer", {"phone": PHONE}), ("text", "Code sent.")]]
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "send me a code")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_wrong_otp_never_shows_verified(monkeypatch, cfg):
    from tests.adapters.helpers import PHONE
    runner, _ = make_tool_runner(
        cfg,
        [[("tool", "verify_customer", {"phone": PHONE, "otp": "000000"}), ("text", "No.")]],
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert panel["expires_in_seconds"] is None


def test_failed_reverification_clears_verified(monkeypatch, cfg):
    from tests.adapters.helpers import PHONE
    clock = FakeClock()
    runner, _ = make_tool_runner(
        cfg,
        [
            verify_script(),
            [("tool", "verify_customer", {"phone": PHONE, "otp": "000000"}), ("text", "No.")],
        ],
    )
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert get_panel(client, chat_id)["verified"] is True
        post_stream(client, chat_id, "try again")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None


def test_two_chats_stay_isolated(monkeypatch, cfg):
    runner_a, _ = make_tool_runner(cfg, [verify_script()])
    runner_b, _ = make_tool_runner(cfg, [[("text", "Hello.")]])
    with client_with_runners(monkeypatch, cfg, [runner_a, runner_b]) as client:
        chat_a = open_chat(client)
        chat_b = open_chat(client)
        post_stream(client, chat_a, "verify me")
        post_stream(client, chat_b, "hi")
        panel_a = get_panel(client, chat_a)
        panel_b = get_panel(client, chat_b)

    assert panel_a["verified"] is True
    assert panel_a["phone_masked"] == "+234 ••• ••• 4567"
    assert panel_b["verified"] is False
    assert panel_b["phone_masked"] is None


def test_expiry_flips_verified_to_false(monkeypatch, cfg):
    clock = FakeClock()
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = False
    cfg.settings.adapters.web.session_idle_seconds = 5000
    runner, _ = make_tool_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert get_panel(client, chat_id)["verified"] is True
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert panel["expires_in_seconds"] is None


def test_delete_removes_panel_state(monkeypatch, cfg):
    runner, _ = make_tool_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert client.delete(f"/chats/{chat_id}").status_code == 200
        response = client.get(f"/chats/{chat_id}/session")

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_chat_expiry_removes_panel_state(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_tool_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        response = client.get(f"/chats/{chat_id}/session")

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"
