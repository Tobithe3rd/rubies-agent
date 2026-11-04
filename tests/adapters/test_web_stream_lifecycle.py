"""Streaming route tests: disconnect, heartbeat and label config."""
import threading
import time
from pathlib import Path

import pytest

from core.config import ConfigError, load_config
from tests.adapters.helpers import (
    FakeClock,
    SlowRunner,
    client_with_runners,
    config_copy,
    edit_yaml,
    open_chat as _open_chat,
    post_stream,
    set_env,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def test_disconnect_lets_turn_finish_and_frees_lock(monkeypatch, cfg):
    runner = SlowRunner(delay=0.3)
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        entry = client.app.state.chat_store.sessions[chat_id]
        with client.stream(
            "POST", f"/chats/{chat_id}/messages/stream", json={"message": "hi"}
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if "first chunk" in line:
                    break

        deadline = time.time() + 3
        while time.time() < deadline and not runner.finished:
            time.sleep(0.02)
        while time.time() < deadline and entry["lock"].locked():
            time.sleep(0.02)

    assert runner.finished is True
    assert entry["lock"].locked() is False


def test_heartbeat_fires_using_the_clock(monkeypatch, cfg):
    clock = FakeClock()
    cfg.settings.adapters.web.heartbeat_seconds = 1
    cfg.settings.adapters.web.max_stream_seconds = 60
    runner = SlowRunner(delay=0.7)
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        timer = threading.Timer(0.3, clock.advance, args=(2,))
        timer.start()
        try:
            body = post_stream(client, chat_id, "hi").text
        finally:
            timer.cancel()

    assert ": ping" in body
    assert "second chunk" in body


def test_missing_label_fails_fast(tmp_path, monkeypatch):
    set_env(monkeypatch)
    config_dir = config_copy(tmp_path)

    def drop_failed(tools):
        del tools["get_balance"]["labels"]["failed"]

    edit_yaml(Path(config_dir) / "tools.yaml", drop_failed)
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(config_dir))
    assert "get_balance" in str(exc.value)
    assert "labels.failed" in str(exc.value)


def test_missing_awaiting_label_fails_fast(tmp_path, monkeypatch):
    set_env(monkeypatch)
    config_dir = config_copy(tmp_path)

    def drop_awaiting(tools):
        del tools["block_card"]["labels"]["awaiting"]

    edit_yaml(Path(config_dir) / "tools.yaml", drop_awaiting)
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(config_dir))
    assert "block_card" in str(exc.value)
    assert "awaiting" in str(exc.value)


def test_missing_no_action_label_fails_fast(tmp_path, monkeypatch):
    set_env(monkeypatch)
    config_dir = config_copy(tmp_path)

    def drop_no_action(tools):
        del tools["open_dispute"]["labels"]["no_action"]

    edit_yaml(Path(config_dir) / "tools.yaml", drop_no_action)
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(config_dir))
    assert "open_dispute" in str(exc.value)
    assert "no_action" in str(exc.value)
