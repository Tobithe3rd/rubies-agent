"""Upload guard tests: the request byte cap before the multipart body is buffered."""
import asyncio
import json
from types import SimpleNamespace

import httpx

import adapters.web_chat as web_chat
from adapters.web.app import create_app
from attachments.config import load_attachments_config
from attachments.vision.mock import MockVisionExtractor


class Runner:
    def __init__(self):
        self.session = SimpleNamespace(token="TOKEN", pending={}, verified=True)

    async def stream_events(self, text):
        yield {"data": "hello"}


def setup(monkeypatch, cfg, max_request_bytes=100):
    att = load_attachments_config()
    att.enabled = True
    att.profiles["chat_attachment"].max_request_bytes = max_request_bytes
    monkeypatch.setattr(web_chat, "create_agent_runner", lambda *a, **k: Runner())
    return create_app(cfg, attachments_config=att,
                      vision_extractor=MockVisionExtractor(att.vision))


def test_content_length_over_limit_is_413(monkeypatch, cfg):
    from fastapi.testclient import TestClient
    app = setup(monkeypatch, cfg)
    with TestClient(app) as client:
        chat_id = client.post("/chats").json()["chat_id"]
        response = client.post(
            f"/chats/{chat_id}/messages/stream/files",
            content=b"x" * 200,
            headers={"content-type": "multipart/form-data; boundary=x"},
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "request_too_large"


def test_chunked_body_over_limit_is_413(monkeypatch, cfg):
    app = setup(monkeypatch, cfg, max_request_bytes=10)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat_id = (await client.post("/chats")).json()["chat_id"]

            async def body():
                yield b"x" * 20
                yield b"y" * 20

            return await client.post(
                f"/chats/{chat_id}/messages/stream/files",
                content=body(),
                headers={"content-type": "multipart/form-data; boundary=x"},
            )

    response = asyncio.run(scenario())
    assert response.status_code == 413
    assert response.json()["detail"] == "request_too_large"
