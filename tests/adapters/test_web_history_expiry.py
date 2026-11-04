"""Transcript history: expiry and deletion."""
from tests.adapters.helpers import (
    FakeClock,
    client_with_runners,
    get_history,
    make_runner,
    open_chat as _open_chat,
    post_json as _post_json,
    post_stream,
    verify_runtime,
    verify_script,
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


def test_unknown_chat_gives_404(monkeypatch, cfg):
    with client_with_runners(monkeypatch, cfg, []) as client:
        response = get_history(client, "missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_idle_expiry_at_900_seconds(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [[("text", "Hi")]])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        json_ok(client, chat_id, "hi")
        clock.advance(900)
        assert get_history(client, chat_id).status_code == 200
        clock.advance(901)
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_max_age_expiry_even_with_activity(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [[("text", "Hi")]])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        json_ok(client, chat_id, "hi")
        for _ in range(4):
            clock.advance(800)
            assert get_history(client, chat_id).status_code == 200
        clock.advance(500)
        response = get_history(client, chat_id)

    assert response.status_code == 404


def test_verification_expiry_deletes_chat_when_flag_true(monkeypatch, cfg):
    cfg.settings.adapters.web.session_idle_seconds = 5000
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = True
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        stream_ok(client, chat_id, "verify me")
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_verification_expiry_keeps_chat_when_flag_false(monkeypatch, cfg):
    cfg.settings.adapters.web.session_idle_seconds = 5000
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = False
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        stream_ok(client, chat_id, "verify me")
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        response = get_history(client, chat_id)

    assert response.status_code == 200
    assert response.json()["panel"]["verified"] is False


def test_delete_removes_transcript(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [[("text", "Hello.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        json_ok(client, chat_id, "hi")
        assert client.delete(f"/chats/{chat_id}").status_code == 200
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert not client.app.state.chat_store.sessions.get(chat_id)
