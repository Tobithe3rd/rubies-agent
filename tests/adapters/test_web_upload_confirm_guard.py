"""End-to-end guard: confirm_action is refused on an upload turn."""
from attachments.config import load_attachments_config
from attachments.vision.mock import MockVisionExtractor
from tests.adapters.helpers import (
    FakeGateway,
    client_with_runners,
    make_tool_runner,
    open_chat,
    post_json,
    sse_events,
)

TOKEN = "BANK-SECRET-TOKEN"
URL = "/chats/{}/messages/stream/files"


class RecordingGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.calls = []

    def propose_dispute(self, token, reference, reason):
        self.calls.append(("propose_dispute", token, reference, reason))
        return super().propose_dispute(token, reference, reason)

    def confirm_action(self, token, pending_token):
        self.calls.append(("confirm_action", token, pending_token))
        return super().confirm_action(token, pending_token)


def attachments():
    cfg = load_attachments_config()
    cfg.enabled = True
    return cfg


def upload(client, chat_id, message="here is the receipt"):
    return client.post(
        URL.format(chat_id),
        data={"message": message},
        files=[("files", ("note.txt", b"dispute evidence", "text/plain"))],
    )


def test_upload_turn_refuses_confirmation_then_a_clean_turn_confirms(monkeypatch, cfg):
    gateway = RecordingGateway()
    scripts = [
        [
            ("tool", "open_dispute", {
                "reference": "RUB-DB-002", "reason": "double debit"}),
            ("text", "Ready to dispute."),
        ],
        [
            ("tool", "confirm_action", {"pending_token": "PT-D"}),
            ("text", lambda ctx: str(ctx.last_tool_result)),
        ],
        [
            ("tool", "confirm_action", {"pending_token": "PT-D"}),
            ("text", "Dispute opened."),
        ],
    ]
    runner, runtime = make_tool_runner(cfg, scripts, gateway=gateway)
    runtime.session.set_verified(TOKEN, "A")
    att = attachments()
    client_kwargs = dict(
        attachments_config=att, vision_extractor=MockVisionExtractor(att.vision))

    with client_with_runners(
            monkeypatch, cfg, [runner], **client_kwargs) as client:
        chat_id = open_chat(client)
        assert post_json(client, chat_id, "double debit")["reply"] == (
            "Ready to dispute.")
        assert "PT-D" in runtime.session.pending

        refused = upload(client, chat_id)

        assert "confirmation_blocked_by_attachment" in refused.text
        assert [call for call in gateway.calls if call[0] == "confirm_action"] == []
        assert "PT-D" in runtime.session.pending
        assert [name for name, _ in sse_events(refused.text)][-1] == "done"

        allowed = post_json(client, chat_id, "yes, confirm")

    assert allowed["reply"] == "Dispute opened."
    assert [call for call in gateway.calls if call[0] == "confirm_action"] == [
        ("confirm_action", TOKEN, "PT-D")]
    assert runtime.session.pending == {}
