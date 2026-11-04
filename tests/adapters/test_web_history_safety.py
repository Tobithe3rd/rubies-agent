"""Transcript history: privacy and safety."""
from tests.adapters.helpers import (
    PHONE,
    OTP,
    TOKEN,
    client_with_runners,
    get_history,
    make_runner,
    open_chat as _open_chat,
    post_json as _post_json,
    post_stream,
    verify_runtime,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def json_ok(client, chat_id, message):
    reply = _post_json(client, chat_id, message)
    assert reply
    return reply


def stream_ok(client, chat_id, message):
    response = post_stream(client, chat_id, message)
    assert response.status_code == 200
    return response.text


def test_history_payload_has_no_token_otp_or_full_phone(monkeypatch, cfg):
    runner, runtime = make_runner(
        cfg,
        [
            [
                ("tool", "verify_customer", {"phone": PHONE, "otp": OTP}),
                ("text", "Verified for " + PHONE),
            ]
        ],
        verify_runtime(),
    )
    runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        stream_ok(client, chat_id, f"my number is {PHONE} and code is {OTP}")
        body = get_history(client, chat_id).text

    for forbidden in (PHONE, OTP, TOKEN):
        assert forbidden not in body
    assert "[redacted]" in body


def test_no_transcript_text_in_logs(monkeypatch, cfg, caplog):
    marker = "SECRET-TRANSCRIPT-MARKER"
    runner, _ = make_runner(cfg, [[("text", "Echo " + marker)]])
    with caplog.at_level("DEBUG"):
        with client_with_runners(monkeypatch, cfg, [runner]) as client:
            chat_id = open_chat(client)
            json_ok(client, chat_id, marker)
            get_history(client, chat_id)

    assert marker not in caplog.text
