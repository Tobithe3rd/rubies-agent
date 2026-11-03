"""Web adapter: FastAPI app hosting chat routes backed by AgentRunner."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import StreamingResponse

try:
    from core.factories import register, create_agent_runner
    from core.config import AppConfig, load_config
except ImportError:
    # Fallback for direct import when path differs
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from core.factories import register, create_agent_runner
    from core.config import AppConfig, load_config


class MessageBody(BaseModel):
    message: str


class ChatResponse(BaseModel):
    chat_id: str


class MessageResponse(BaseModel):
    reply: str
    error: bool = False


class OtpResponse(BaseModel):
    otp_line: str


# --- adapter registry ---


@register("adapter", "web")
class WebAdapter:
    """Registered adapter class (not instantiated directly here)."""

    def __init__(self, cfg: AppConfig, env=None):
        self.cfg = cfg
        self.env = env or cfg.env

    def describe(self) -> str:
        return "web:http"

    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("web", True, "http adapter ready")


# --- session store ---

class ChatSessionStore:
    def __init__(self, cfg: AppConfig, clock=None):
        self.cfg = cfg
        self.sessions: dict[str, dict] = {}
        web_cfg = cfg.settings.adapters.web
        self.idle_limit = web_cfg.session_idle_seconds
        self.max_age = web_cfg.session_max_age_seconds
        self.history_max_events = web_cfg.history_max_events
        self.clear_on_verification_expiry = web_cfg.clear_transcript_on_verification_expiry
        self.max_sessions = web_cfg.max_sessions
        self.verification_seconds = cfg.settings.session.expiry_minutes * 60
        # Injectable clock: if clock has .now() use it; else clock is callable directly
        if clock is None:
            self._now = time.time
        elif hasattr(clock, 'now') and callable(clock.now):
            self._now = clock.now
        elif callable(clock):
            self._now = clock
        else:
            self._now = time.time

    def create(self, chat_id: str, runner) -> None:
        import asyncio
        self.sessions[chat_id] = {
            "runner": runner,
            "lock": asyncio.Lock(),
            "created_at": self._now(),
            "last_used": self._now(),
            "history": [],
            "was_verified_at": None,
            "panel": {
                "verified": False,
                "phone_masked": None,
                "verified_at": None,
                "receipts": [],
            },
        }

    def get(self, chat_id: str) -> Optional[dict]:
        entry = self.sessions.get(chat_id)
        if entry is None:
            return None
        now = self._now()
        # Lazy expiry check
        if (now - entry["last_used"] > self.idle_limit) or (now - entry["created_at"] > self.max_age):
            self.sessions.pop(chat_id, None)
            return None
        verified_at = entry.get("was_verified_at")
        if (self.clear_on_verification_expiry and verified_at is not None
                and now - verified_at > self.verification_seconds):
            self.sessions.pop(chat_id, None)
            return None
        entry["last_used"] = now
        return entry

    def delete(self, chat_id: str) -> None:
        self.sessions.pop(chat_id, None)

    # --- transcript (server-side memory only; never logged or persisted) ---

    def record_user(self, entry: dict, text: str) -> None:
        entry["history"].append({
            "role": "user",
            "text": str(text),
            "at": _iso_time(self._now(), self.cfg.settings.timezone),
        })
        self._trim(entry)

    def start_agent(self, entry: dict) -> dict:
        record = {
            "role": "agent",
            "events": [],
            "status": "streaming",
            "at": _iso_time(self._now(), self.cfg.settings.timezone),
        }
        entry["history"].append(record)
        return record

    def record_agent_event(self, entry: dict, record: dict, event: dict) -> None:
        events = record["events"]
        if event.get("type") == "text" and events and events[-1].get("type") == "text":
            events[-1]["text"] += event["text"]
        else:
            events.append(dict(event))
        self._trim(entry)

    def finish_agent(self, entry: dict, record: dict, status: str) -> None:
        record["status"] = status
        record["at"] = _iso_time(self._now(), self.cfg.settings.timezone)
        self._trim(entry)

    def record_reply(self, entry: dict, text: str, status: str = "done") -> None:
        record = self.start_agent(entry)
        self.record_agent_event(entry, record, {"type": "text", "text": str(text)})
        self.finish_agent(entry, record, status)

    def _trim(self, entry: dict) -> None:
        # Drop oldest whole messages (user or agent); the agent's own context is unaffected.
        history = entry["history"]
        def count() -> int:
            return sum(1 if message["role"] == "user" else len(message["events"])
                       for message in history)
        while len(history) > 1 and count() > self.history_max_events:
            history.pop(0)

    @staticmethod
    def _clear_verification(panel: dict) -> bool:
        changed = panel["verified"] or panel["phone_masked"] is not None
        panel["verified"] = False
        panel["phone_masked"] = None
        panel["verified_at"] = None
        return bool(changed)

    def panel(self, entry: dict) -> dict:
        """Customer-safe view; expiry is evaluated against the injectable clock."""
        panel = entry["panel"]
        expires_in = None
        if panel["verified"]:
            if panel["verified_at"] is None:
                self._clear_verification(panel)
            else:
                remaining = panel["verified_at"] + self.verification_seconds - self._now()
                if remaining <= 0:
                    self._clear_verification(panel)
                else:
                    expires_in = max(1, int(remaining))
        return {
            "verified": bool(panel["verified"]),
            "phone_masked": panel["phone_masked"] if panel["verified"] else None,
            "expires_in_seconds": expires_in,
            "receipts": [dict(receipt) for receipt in panel["receipts"]],
        }

    def active_chats(self) -> int:
        # Lazy clean-up before counting
        now = self._now()
        expired = [
            cid for cid, entry in self.sessions.items()
            if (now - entry["last_used"] > self.idle_limit) or (now - entry["created_at"] > self.max_age)
        ]
        for cid in expired:
            self.sessions.pop(cid, None)
        return len(self.sessions)

    def cap_reached(self) -> bool:
        return len(self.sessions) >= self.max_sessions


# --- streaming helpers ---

def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_citations(message: dict) -> list[dict]:
    """Only search_policy document + section; result text is never read out."""
    if message.get("role") != "user":
        return []
    out: list[dict] = []
    for block in message.get("content", []):
        result = block.get("toolResult") if isinstance(block, dict) else None
        if not isinstance(result, dict):
            continue
        for content in result.get("content") or []:
            envelope = content.get("json") if isinstance(content, dict) else None
            if not isinstance(envelope, dict) or envelope.get("tool") != "search_policy":
                continue
            data = envelope.get("data") or {}
            for row in data.get("results") or []:
                document = row.get("doc_title")
                section = row.get("section_heading")
                if document and section:
                    out.append({"document": document, "section": section})
    return out


def _tool_labels(cfg: AppConfig, tool_name: str):
    tool_cfg = cfg.tools.get(tool_name)
    return getattr(tool_cfg, "labels", None)


def _step_payload(cfg: AppConfig, tool_name: str, step_id: str,
                  status: str = "running", is_proposal: bool = False):
    labels = _tool_labels(cfg, tool_name)
    if labels is None:
        return None
    if status == "running":
        return {"id": step_id, "status": "running", "label": labels.running}
    if is_proposal:
        return {"id": step_id, "status": "awaiting", "label": labels.awaiting or labels.done}
    if status == "success":
        tool_cfg = cfg.tools.get(tool_name)
        if getattr(tool_cfg, "requires_confirmation", False):
            return {"id": step_id, "status": "done", "label": labels.no_action or labels.done}
        return {"id": step_id, "status": "done", "label": labels.done}
    return {"id": step_id, "status": "failed", "label": labels.failed}


# --- customer-safe session panel ---

_RECEIPT_TOOL_FOR_KIND = {
    "dispute": "open_dispute",
    "card_block": "block_card",
    "handoff": "handoff_to_human",
}


def _mask_phone(phone) -> Optional[str]:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) < 4:
        return None
    if digits.startswith("234"):
        country, national = "+234", digits[3:]
    elif digits.startswith("0"):
        country, national = "+234", digits[1:]
    elif len(digits) > 10:
        country, national = f"+{digits[:-10]}", digits[-10:]
    else:
        country, national = "+234", digits
    return f"{country} ••• ••• {national[-4:]}"


def _iso_time(value, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    moment = value if isinstance(value, datetime) else datetime.fromtimestamp(value, tz=tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(tz).isoformat(timespec="seconds")


def _scrub_summary(text, secrets_to_remove, tool_names, max_chars: int,
                   otp_length: int) -> str:
    text = str(text or "")
    for secret in secrets_to_remove:
        if secret:
            text = text.replace(str(secret), "[redacted]")
    # Full phone numbers, money and any OTP-length digit run stay server-side.
    text = re.sub(r"(?<![\d+])(?:\+?234|0)[\d\s\-]{8,14}\d(?!\d)", "[redacted]", text)
    text = re.sub(r"(?i)(?:₦|\bNGN\b|\bnaira\b)\s*[\d,]+(?:\.\d+)?", "[redacted]", text)
    text = re.sub(rf"\b\d{{{otp_length},}}\b", "[redacted]", text)
    for name in tool_names:
        text = text.replace(name, "request")
    return " ".join(text.split())[:max_chars]


def _history_text(cfg: AppConfig, entry: dict, text) -> str:
    """Transcript text that is safe to hand back to the browser."""
    session = getattr(entry.get("runner"), "session", None)
    secrets_to_remove = [getattr(session, "token", None)]
    secrets_to_remove.extend((getattr(session, "pending", None) or {}).keys())
    out = str(text or "")
    for secret in secrets_to_remove:
        if secret:
            out = out.replace(str(secret), "[redacted]")
    out = re.sub(r"(?<![\d+])(?:\+?234|0)[\d\s\-]{8,14}\d(?!\d)", "[redacted]", out)
    out = re.sub(rf"\b\d{{{cfg.settings.bank_api.otp_length},}}\b", "[redacted]", out)
    for tool_name in cfg.tools:
        out = out.replace(tool_name, "request")
    return out


def _history_messages(cfg: AppConfig, entry: dict) -> list[dict]:
    messages: list[dict] = []
    for message in entry["history"]:
        if message["role"] == "user":
            messages.append({
                "role": "user",
                "text": _history_text(cfg, entry, message["text"]),
                "at": message["at"],
            })
            continue
        events = []
        for event in message["events"]:
            clean = dict(event)
            if clean.get("type") in ("text", "error"):
                if "text" in clean:
                    clean["text"] = _history_text(cfg, entry, clean["text"])
                if "message" in clean:
                    clean["message"] = _history_text(cfg, entry, clean["message"])
            events.append(clean)
        messages.append({
            "role": "agent",
            "events": events,
            "status": message["status"],
            "at": message["at"],
        })
    return messages


def _record_panel_result(cfg: AppConfig, store: ChatSessionStore, entry: dict,
                         tool_name: str, status: str, args: dict, envelope: dict) -> bool:
    """Allow-listed projection of a tool result; raw args/results stay server-side."""
    panel = entry["panel"]
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}

    if tool_name == "verify_customer":
        if status == "success" and data.get("verified") is True:
            panel["verified"] = True
            panel["phone_masked"] = _mask_phone(args.get("phone"))
            panel["verified_at"] = store._now()
            entry["was_verified_at"] = panel["verified_at"]
            return True
        if status != "success":
            return store._clear_verification(panel)
        return False

    if status != "success":
        if envelope.get("error") == "session_expired":
            return store._clear_verification(panel)
        return False

    kind = None
    fields: dict = {}
    if tool_name == "confirm_action":
        result_status = data.get("status")
        if result_status == "dispute_opened":
            kind = "dispute"
            fields = {"reference": data.get("reference")}
        elif result_status == "card_blocked":
            kind = "card_block"
            fields = {"last4": data.get("last4")}
    elif tool_name == "handoff_to_human" and data.get("ticket_id"):
        kind = "handoff"
        fields = {"reference": data.get("ticket_id"), "summary": args.get("summary")}
    if kind is None:
        return False

    source_tool = _RECEIPT_TOOL_FOR_KIND[kind]
    tool_cfg = cfg.tools.get(source_tool)
    receipt_cfg = getattr(tool_cfg, "receipt", None)
    if receipt_cfg is None:
        return False

    values = {
        "reference": "" if fields.get("reference") is None else str(fields["reference"]),
        "last4": "" if fields.get("last4") is None else str(fields["last4"]),
        "summary": fields.get("summary") or "",
    }
    session = getattr(entry.get("runner"), "session", None)
    secrets_to_remove = [getattr(session, "token", None)]
    secrets_to_remove.extend((getattr(session, "pending", None) or {}).keys())
    summary = _scrub_summary(
        receipt_cfg.template.format(**values),
        secrets_to_remove,
        list(cfg.tools),
        cfg.settings.adapters.web.panel_summary_max_chars,
        cfg.settings.bank_api.otp_length,
    )
    reference = None if fields.get("reference") is None else str(fields["reference"])
    panel["receipts"].append({
        "id": uuid.uuid4().hex,
        "kind": kind,
        "reference": reference,
        "summary": summary,
        "at": _iso_time(store._now(), cfg.settings.timezone),
    })
    return True


# --- app factory ---

def create_app(cfg: AppConfig = None, clock=None) -> FastAPI:
    if cfg is None:
        cfg = load_config()

    web_cfg = cfg.settings.adapters.web
    app = FastAPI(title="Rubies Web Adapter")

    # CORS
    origins = web_cfg.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = ChatSessionStore(cfg, clock=clock)
    app.state.chat_store = store
    app.state.stream_tasks = set()
    _shared_llm = None

    def _get_llm():
        nonlocal _shared_llm
        if _shared_llm is None:
            from core.factories import create_llm
            _shared_llm = create_llm(cfg)
        return _shared_llm

    def _read_otp_line() -> str:
        otp_path = web_cfg.otp_log_path
        try:
            from pathlib import Path
            lines = [line for line in Path(otp_path).read_text().splitlines() if line.strip()]
            return lines[-1] if lines else ""
        except Exception:
            return ""

    @app.get("/health")
    async def health():
        return {"status": "ok", "active_chats": store.active_chats()}

    @app.post("/chats", response_model=ChatResponse)
    async def create_chat():
        if store.cap_reached():
            raise HTTPException(status_code=503, detail="max_sessions")
        chat_id = secrets.token_urlsafe(32)
        # Share LLM across runners
        import time
        start = time.time()
        llm = _get_llm()
        runner = create_agent_runner(cfg, llm=llm)
        duration = time.time() - start
        # Log creation time (to stdout / logs only, never to client)
        print(f"[web] runner created for {chat_id} in {duration:.3f}s")
        store.create(chat_id, runner)
        return ChatResponse(chat_id=chat_id)

    @app.post("/chats/{chat_id}/messages", response_model=MessageResponse)
    async def send_message(chat_id: str, body: MessageBody):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")

        text = body.message
        if text is None or not str(text).strip():
            raise HTTPException(status_code=400, detail="empty_message")
        max_chars = web_cfg.max_message_chars
        if len(str(text)) > max_chars:
            raise HTTPException(status_code=400, detail="message_too_long")

        import asyncio
        runner = entry["runner"]
        lock = entry["lock"]

        async with lock:
            def result_observer(tool_name: str, status: str, args: dict, envelope: dict) -> None:
                _record_panel_result(cfg, store, entry, tool_name, status, args, envelope)

            runner.tool_result_observer = result_observer
            store.record_user(entry, text)
            try:
                try:
                    # Call blocking handle_message in threadpool to avoid blocking event loop
                    reply_text = await asyncio.to_thread(runner.handle_message, text)
                    store.record_reply(entry, reply_text, status="done")
                    return MessageResponse(reply=reply_text, error=False)
                except Exception as exc:
                    # Log exception without exposing details to client
                    import sys
                    print(f"[web] message error in {chat_id}: {exc}", file=sys.stderr)
                    store.record_reply(entry, web_cfg.error_message, status="error")
                    return MessageResponse(reply=web_cfg.error_message, error=True)
            finally:
                runner.tool_result_observer = None

    @app.post("/chats/{chat_id}/messages/stream")
    async def stream_message(chat_id: str, body: MessageBody):
        # Same validation as the JSON route, as normal HTTP responses before streaming.
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")

        text = body.message
        if text is None or not str(text).strip():
            raise HTTPException(status_code=400, detail="empty_message")
        if len(str(text)) > web_cfg.max_message_chars:
            raise HTTPException(status_code=400, detail="message_too_long")
        if not web_cfg.stream_enabled:
            raise HTTPException(status_code=404, detail="stream_disabled")

        runner = entry["runner"]
        lock = entry["lock"]

        # Hold the lock for the whole turn, exactly like the JSON route.
        await lock.acquire()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        panel_before = store.panel(entry)
        store.record_user(entry, text)
        agent_record = store.start_agent(entry)
        running: dict[str, list[str]] = {}

        def record(event: dict) -> None:
            store.record_agent_event(entry, agent_record, event)

        def emit_step(payload: dict) -> None:
            record({"type": "step", **payload})
            queue.put_nowait({"kind": "step", "payload": payload})

        def on_tool_status(tool_name: str, status: str, is_proposal: bool) -> None:
            labels = _tool_labels(cfg, tool_name)
            if labels is None:
                return  # never record or expose an unlabelled tool's name
            ids = running.get(tool_name) or []
            # Opaque id: never let a tool name appear in the payload.
            step_id = ids.pop(0) if ids else f"step-{uuid.uuid4().hex}"
            emit_step(_step_payload(cfg, tool_name, step_id, status, is_proposal))

        def observer(tool_name: str, status: str, is_proposal: bool) -> None:
            # The observer runs in the tool's worker thread; hand off safely.
            loop.call_soon_threadsafe(on_tool_status, tool_name, status, is_proposal)

        def result_observer(tool_name: str, status: str, args: dict, envelope: dict) -> None:
            _record_panel_result(cfg, store, entry, tool_name, status, args, envelope)

        runner.tool_observer = observer
        runner.tool_result_observer = result_observer

        async def run_turn() -> None:
            citations: list[dict] = []
            seen_tool_ids: set[str] = set()
            failed = False
            try:
                async def consume():
                    async for event in runner.stream_events(text):
                        if event.get("type") == "tool_use_stream":
                            current = event.get("current_tool_use") or {}
                            tool_id = current.get("toolUseId")
                            tool_name = current.get("name")
                            if tool_id and tool_name and tool_id not in seen_tool_ids:
                                seen_tool_ids.add(tool_id)
                                payload = _step_payload(cfg, tool_name, tool_id)
                                if payload is not None:
                                    running.setdefault(tool_name, []).append(tool_id)
                                    emit_step(payload)
                        message = event.get("message")
                        if isinstance(message, dict):
                            citations.extend(_extract_citations(message))
                        delta = event.get("data")
                        if isinstance(delta, str) and delta:
                            record({"type": "text", "text": delta})
                            queue.put_nowait({"kind": "text", "delta": delta})

                await asyncio.wait_for(consume(), timeout=web_cfg.max_stream_seconds)
            except asyncio.TimeoutError:
                failed = True
                record({"type": "error", "message": web_cfg.error_message})
                queue.put_nowait({"kind": "error", "message": web_cfg.error_message})
            except Exception as exc:
                import sys
                print(f"[web] stream error in {chat_id}: {exc}", file=sys.stderr)
                failed = True
                record({"type": "error", "message": web_cfg.error_message})
                queue.put_nowait({"kind": "error", "message": web_cfg.error_message})
            finally:
                # Dedupe citations; only document + section ever cross the wire.
                unique = {(c["document"], c["section"]): c for c in citations}
                panel_after = store.panel(entry)
                if panel_after != panel_before:
                    queue.put_nowait({"kind": "panel", "panel": panel_after})
                if failed:
                    store.finish_agent(entry, agent_record, "error")
                else:
                    record({"type": "done", "citations": list(unique.values())})
                    store.finish_agent(entry, agent_record, "done")
                    queue.put_nowait({"kind": "done", "citations": list(unique.values())})
                queue.put_nowait({"kind": "end"})
                runner.tool_observer = None
                runner.tool_result_observer = None
                lock.release()

        task = asyncio.create_task(run_turn())
        app.state.stream_tasks.add(task)
        task.add_done_callback(app.state.stream_tasks.discard)

        async def event_stream():
            # If the client disconnects (Stop button / closed tab) this generator
            # stops being read, but `run_turn` is a separate task: the turn keeps
            # going (bounded by max_stream_seconds) so a propose/confirm is never
            # left half-done. The turn releases the chat lock when it finishes.
            deadline = store._now() + web_cfg.max_stream_seconds
            heartbeat = float(web_cfg.heartbeat_seconds)
            last_ping = store._now()

            while True:
                if store._now() >= deadline:
                    return
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=min(0.25, heartbeat)
                    )
                except asyncio.TimeoutError:
                    now = store._now()
                    if now - last_ping >= heartbeat:
                        last_ping = now
                        yield ": ping\n\n"
                    continue

                kind = item["kind"]
                if kind == "end":
                    return
                if kind == "text":
                    yield _sse("text", {"delta": item["delta"]})
                elif kind == "error":
                    yield _sse("error", {"message": item["message"]})
                    return
                elif kind == "panel":
                    yield _sse("panel", item["panel"])
                elif kind == "done":
                    yield _sse("done", {"citations": item.get("citations", [])})
                elif kind == "step":
                    yield _sse("step", item["payload"])

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/chats/{chat_id}/history")
    async def get_history(chat_id: str):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        lock = entry["lock"]
        if lock.locked():
            try:
                await asyncio.wait_for(lock.acquire(), timeout=web_cfg.history_wait_seconds)
            except asyncio.TimeoutError:
                pass
            else:
                lock.release()
        return {
            "messages": _history_messages(cfg, entry),
            "panel": store.panel(entry),
        }

    @app.get("/chats/{chat_id}/session")
    async def get_session(chat_id: str):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        return store.panel(entry)

    @app.get("/chats/{chat_id}/dev-otp", response_model=OtpResponse)
    async def get_otp(chat_id: str):
        # Check allow_dev_otp FIRST (so disabled endpoint reveals nothing about chat ids)
        if not web_cfg.allow_dev_otp:
            raise HTTPException(status_code=404, detail="dev_otp_disabled")
        # Check chat validity the same way messages route does; counts as activity
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        # Reuse CLI logic for reading OTP line without importing cli_chat
        otp_line = _read_otp_line()
        if not otp_line:
            raise HTTPException(status_code=404, detail="no_otp_line")
        # Scrub session token from line (defensive, same as cli_chat)
        token = getattr(getattr(entry.get("runner"), "session", None), "token", None)
        if token and isinstance(token, str) and token in otp_line:
            otp_line = otp_line.replace(token, "***")
        return OtpResponse(otp_line=otp_line)

    @app.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        store.delete(chat_id)
        return None

    return app


# --- direct uvicorn entry ---

def main():
    cfg = load_config()
    import uvicorn
    uvicorn.run(
        "adapters.web_chat:create_app",
        factory=True,
        host=cfg.settings.adapters.web.host,
        port=cfg.settings.adapters.web.port,
    )


if __name__ == "__main__":
    main()
