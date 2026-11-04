"""Multipart upload route tests: validation, extraction, streaming and audit."""
import hashlib
import logging
from types import SimpleNamespace

from attachments.config import load_attachments_config
from attachments.models import MESSAGES, AttachmentRejected
from attachments.vision.mock import MockVisionExtractor
from tests.attachments.fixtures import png_bytes
from tests.adapters.helpers import (
    client_with_runners,
    get_history,
    open_chat as _open_chat,
    post_stream,
    sse_events,
)

TOKEN = "BANK-SECRET-TOKEN"
URL = "/chats/{}/messages/stream/files"


class CaptureRunner:
    def __init__(self, verified=True):
        self.session = SimpleNamespace(
            token=TOKEN if verified else None, pending={}, verified=verified)
        self.texts = []
        self.attachment_flags = []

    async def stream_events(self, text, has_attachments=False):
        self.texts.append(text)
        self.attachment_flags.append(has_attachments)
        yield {"data": "I read the file."}


class FailingVision:
    def transcribe(self, data, kind):
        raise AttachmentRejected("extraction_unavailable", MESSAGES["extraction_unavailable"])


def attachments(enabled=True, **profile):
    cfg = load_attachments_config()
    cfg.enabled = enabled
    for key, value in profile.items():
        setattr(cfg.profiles["chat_attachment"], key, value)
    return cfg


def app_client(monkeypatch, cfg, runner, att=None, vision=None):
    att = att or attachments()
    vision = vision or MockVisionExtractor(att.vision)
    return client_with_runners(
        monkeypatch, cfg, [runner], attachments_config=att, vision_extractor=vision)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def upload(client, chat_id, message="read this", files=None):
    if files is None:
        files = [("files", ("note.txt", b"Rubies statement text", "text/plain"))]
    return client.post(URL.format(chat_id), data={"message": message}, files=files)


def test_disabled_returns_plain_404(monkeypatch, cfg):
    runner = CaptureRunner()
    with app_client(monkeypatch, cfg, runner, attachments(enabled=False)) as client:
        chat_id = open_chat(client)
        response = upload(client, chat_id)
    assert response.status_code == 404
    assert runner.texts == []


def test_unknown_chat_uses_existing_not_found(monkeypatch, cfg):
    with app_client(monkeypatch, cfg, CaptureRunner()) as client:
        response = upload(client, "missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_unverified_session_is_403(monkeypatch, cfg):
    with app_client(monkeypatch, cfg, CaptureRunner(verified=False)) as client:
        chat_id = open_chat(client)
        response = upload(client, chat_id)
    assert response.status_code == 403
    assert response.json()["detail"] == attachments().web_upload.not_verified_message


def test_text_upload_streams_wrapped_content_and_hides_it_from_history(monkeypatch, cfg):
    secret = "UNIQUE-FILE-CONTENT-42"
    runner = CaptureRunner()
    att = attachments()
    with app_client(monkeypatch, cfg, runner, att) as client:
        chat_id = open_chat(client)
        response = upload(
            client, chat_id, "what is this?",
            [("files", ("note.txt", secret.encode(), "text/plain"))])
        history = get_history(client, chat_id).json()

    assert response.status_code == 200
    events = sse_events(response.text)
    assert events[0][0] == "step"
    assert events[0][1]["label"] == att.web_upload.reading_label
    assert [name for name, _ in events][-1] == "done"
    sent = runner.texts[0]
    assert runner.attachment_flags == [True]
    assert "what is this?" in sent and secret in sent
    assert att.chat_format.header in sent
    assert att.chat_format.item_open.split("{")[0] in sent
    user = history["messages"][0]
    assert user["text"] == f"what is this?\n\n[Attached: Attachment 1 (txt)]"
    assert secret not in str(history)


def test_json_stream_route_does_not_pass_an_attachment_flag(monkeypatch, cfg):
    runner = CaptureRunner()
    with app_client(monkeypatch, cfg, runner) as client:
        chat_id = open_chat(client)
        response = post_stream(client, chat_id, "hello")
    assert response.status_code == 200
    assert runner.attachment_flags == [False]


def test_empty_and_long_messages_are_422(monkeypatch, cfg):
    cfg.settings.adapters.web.max_message_chars = 5
    with app_client(monkeypatch, cfg, CaptureRunner()) as client:
        chat_id = open_chat(client)
        empty = upload(client, chat_id, message="   ")
        long = upload(client, chat_id, message="123456")
    assert empty.status_code == 422 and empty.json()["detail"] == "empty_message"
    assert long.status_code == 422 and long.json()["detail"] == "message_too_long"


def test_no_files_is_422(monkeypatch, cfg):
    with app_client(monkeypatch, cfg, CaptureRunner()) as client:
        chat_id = open_chat(client)
        response = client.post(URL.format(chat_id), data={"message": "hello"})
    assert response.status_code == 422
    assert response.json()["detail"] == "no_files"


def test_validation_errors_have_code_and_no_filename(monkeypatch, cfg):
    with app_client(monkeypatch, cfg, CaptureRunner(),
                    attachments(max_file_bytes=10)) as client:
        chat_id = open_chat(client)
        too_many = upload(client, chat_id, files=[
            ("files", (f"file{i}.txt", b"ok", "text/plain")) for i in range(4)])
        oversize = upload(client, chat_id, files=[
            ("files", ("big.txt", b"x" * 20, "text/plain"))])
        spoofed = upload(client, chat_id, files=[
            ("files", ("fake.png", b"not-png!", "image/png"))])

    assert too_many.status_code == 422
    assert too_many.json()["code"] == "too_many_files"
    assert oversize.json()["code"] == "too_large"
    assert spoofed.json()["code"] == "type_mismatch"
    assert "big.txt" not in oversize.text and "fake.png" not in spoofed.text


def test_extraction_failure_emits_error_and_skips_runner(monkeypatch, cfg):
    runner = CaptureRunner()
    att = attachments()
    with app_client(monkeypatch, cfg, runner, att, FailingVision()) as client:
        chat_id = open_chat(client)
        response = upload(
            client, chat_id, files=[("files", ("scan.png", png_bytes(), "image/png"))])

    events = sse_events(response.text)
    assert events[0][0] == "step"
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "extraction_unavailable"
    assert runner.texts == []


def test_audit_line_has_hashes_and_no_content(monkeypatch, cfg, caplog):
    secret = "AUDIT-MUST-NOT-LEAK-THIS"
    caplog.set_level(logging.INFO, logger="adapters.web.upload_helpers")
    runner = CaptureRunner()
    with app_client(monkeypatch, cfg, runner) as client:
        chat_id = open_chat(client)
        upload(client, chat_id, files=[
            ("files", ("note.txt", secret.encode(), "text/plain"))])

    records = [r for r in caplog.records if getattr(r, "event", None) == "attachment_upload"]
    assert len(records) == 1
    record = records[0]
    assert record.sha256 == [hashlib.sha256(secret.encode()).hexdigest()]
    assert record.file_count == 1 and record.outcome == "ok"
    assert secret not in caplog.text and "note.txt" not in caplog.text
