"""The web app's emitted events and history must match contract/events.json."""
import json
from pathlib import Path

from tests.adapters.helpers import (
    client_with_runners,
    get_history,
    make_runner,
    open_chat,
    post_stream,
    sse_events,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contract" / "events.json").read_text())


def assert_event(event_name, payload):
    shape = CONTRACT["events"][event_name]
    for key in shape["required"]:
        assert key in payload, f"{event_name} missing {key}: {payload}"
    if event_name == "step":
        assert payload["status"] in shape["properties"]["status"]
    if event_name == "panel":
        for receipt in payload["receipts"]:
            for key in CONTRACT["receipt"]["required"]:
                assert key in receipt
            assert receipt["kind"] in CONTRACT["receipt"]["kinds"]


def assert_history(payload):
    for key in CONTRACT["history"]["required"]:
        assert key in payload
    for message in payload["messages"]:
        shape = CONTRACT["history"]["message"][message["role"]]
        for key in shape["required"]:
            assert key in message
        if message["role"] != "agent":
            continue
        assert message["status"] in CONTRACT["history"]["statuses"]
        for event in message["events"]:
            shape = CONTRACT["history"]["agent_event"][event["type"]]
            for key in shape["required"]:
                assert key in event, f"history {event['type']} missing {key}"
    for receipt in payload["panel"]["receipts"]:
        for key in CONTRACT["receipt"]["required"]:
            assert key in receipt


def test_tool_turn_events_and_history_match_the_contract(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg, [[("tool", "get_balance", {}), ("text", "Your balance is ₦1,000")]]
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        response = post_stream(client, chat_id, "what is my balance?")
        assert response.status_code == 200
        events = sse_events(response.text)
        history = get_history(client, chat_id)

    assert events, "the tool turn must emit at least one event"
    for name, payload in events:
        assert name in CONTRACT["events"], f"unexpected event {name}"
        assert_event(name, payload)

    assert history.status_code == 200
    assert_history(history.json())
