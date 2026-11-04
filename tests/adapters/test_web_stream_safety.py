"""Streaming route tests: safety, validation and isolation."""
from tests.adapters.helpers import (
    FakeRuntime,
    FailingRunner,
    GuardGateway,
    client_with_runners,
    make_runner,
    make_tool_runner,
    open_chat as _open_chat,
    post_stream,
    sse_events,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def test_never_forwards_tool_names_inputs_results_or_secrets(monkeypatch, cfg):
    phone = "+2348031234567"
    token = "BANK-SECRET-TOKEN"
    secret_text = f"CALL {phone} with {token}"
    runtime = FakeRuntime(
        {
            "search_policy": {
                "ok": True,
                "tool": "search_policy",
                "data": {
                    "status": "ok",
                    "results": [
                        {
                            "chunk_id": "RUB-DOC-01#2",
                            "citation": "Fee Schedule, section 2 (Transfer fees)",
                            "doc_title": "Fee Schedule",
                            "section_heading": "Transfer fees",
                            "text": secret_text,
                            "score": 0.9,
                        }
                    ],
                    "top_score": 0.9,
                    "threshold": 0.35,
                    "result_count": 1,
                },
            },
            "verify_customer": {
                "ok": True,
                "tool": "verify_customer",
                "data": {"phone": phone, "token": token},
            },
            "block_card": {
                "ok": True,
                "tool": "block_card",
                "data": {"pending_token": "PENDING-SECRET"},
            },
        }
    )
    runtime.session.set_verified(token, "Alice")
    runner, _ = make_runner(
        cfg,
        [
            [
                ("tool", "search_policy", {"query": "private query words"}),
                ("tool", "verify_customer", {"phone": phone}),
                ("tool", "block_card", {"last4": "0001"}),
                ("text", "Here are the fees."),
            ]
        ],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "fees?").text

    for forbidden in (
        "search_policy",
        "verify_customer",
        "block_card",
        "[using tool",
        "private query words",
        "RUB-DOC-01#2",
        "PENDING-SECRET",
        phone,
        token,
        secret_text,
    ):
        assert forbidden not in body, f"leaked {forbidden!r}"

    done = [p for n, p in sse_events(body) if n == "done"][-1]
    assert done == {
        "citations": [{"document": "Fee Schedule", "section": "Transfer fees"}]
    }


def test_events_stream_failure_gives_friendly_error(monkeypatch, cfg):
    with client_with_runners(monkeypatch, cfg, [FailingRunner()]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "hi").text

    events = sse_events(body)
    assert events[-1] == ("error", {"message": cfg.settings.adapters.web.error_message})
    assert "model exploded" not in body


def test_unknown_chat_404_before_stream(monkeypatch, cfg):
    with client_with_runners(monkeypatch, cfg, []) as client:
        response = client.post(
            "/chats/missing/messages/stream", json={"message": "hello"}
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_empty_message_400_before_stream(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [[("text", "unused")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        response = post_stream(client, chat_id, "   ")
    assert response.status_code == 400
    assert response.json()["detail"] == "empty_message"
    assert not response.headers["content-type"].startswith("text/event-stream")


def test_two_chats_stay_isolated(monkeypatch, cfg):
    runner_a, _ = make_runner(cfg, [[("text", "Answer for A")]])
    runner_b, _ = make_runner(cfg, [[("text", "Answer for B")]])
    runner_a.session.set_verified("TOKEN-A", "A")
    runner_b.session.set_verified("TOKEN-B", "B")
    with client_with_runners(monkeypatch, cfg, [runner_a, runner_b]) as client:
        chat_a = open_chat(client)
        chat_b = open_chat(client)
        body_a = post_stream(client, chat_a, "a").text
        body_b = post_stream(client, chat_b, "b").text

    assert "Answer for A" in body_a and "Answer for B" not in body_a
    assert "Answer for B" in body_b and "Answer for A" not in body_b
    assert "TOKEN-A" not in body_a and "TOKEN-B" not in body_b


def test_same_turn_confirm_action_is_refused(monkeypatch, cfg, tmp_path):
    gateway = GuardGateway()
    runner, _ = make_tool_runner(
        cfg,
        [[
            ("tool", "block_card", {"last4": "0001"}),
            ("tool", "confirm_action", lambda ctx: {"pending_token": ctx.data["pending_token"]}),
            ("text", "Done"),
        ]],
        gateway,
    )
    runner.runtime.session.set_verified("TOKEN", "Alice")

    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block 0001 then confirm").text

    assert ("confirm", "PT-1") not in gateway.calls
    assert ("propose", "0001") in gateway.calls
    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "awaiting", "running", "failed"]
    assert steps[-1]["label"] == cfg.tools["confirm_action"].labels.failed
