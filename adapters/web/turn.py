"""Turn runner: queue-based turn execution, observers and SSE response."""
from __future__ import annotations

import asyncio
import sys
import uuid

from starlette.responses import StreamingResponse

from core.config import AppConfig
from .panel import _record_panel_result, panel_view
from .scrub import _history_text  # re-exported for backward compatibility
from .sse import _extract_citations, _sse
from .store import ChatSessionStore
from .transcript import (
    finish_agent,
    record_agent_event,
    record_user,
    start_agent,
)


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


def stream_response(app, cfg: AppConfig, store: ChatSessionStore,
                    entry: dict, text: str, chat_id: str,
                    record_text: str = None,
                    has_attachments: bool = False) -> StreamingResponse:
    web_cfg = cfg.settings.adapters.web
    runner = entry["runner"]
    lock = entry["lock"]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    panel_before = panel_view(entry, cfg, store)
    record_user(entry, text if record_text is None else record_text, cfg, store)
    agent_record = start_agent(entry, cfg, store)
    running: dict[str, list[str]] = {}

    def record(event: dict) -> None:
        record_agent_event(entry, agent_record, event, store)

    def emit_step(payload: dict) -> None:
        record({"type": "step", **payload})
        queue.put_nowait({"kind": "step", "payload": payload})

    def on_tool_status(tool_name: str, status: str, is_proposal: bool) -> None:
        labels = _tool_labels(cfg, tool_name)
        if labels is None:
            return
        ids = running.get(tool_name) or []
        step_id = ids.pop(0) if ids else f"step-{uuid.uuid4().hex}"
        emit_step(_step_payload(cfg, tool_name, step_id, status, is_proposal))

    def observer(tool_name: str, status: str, is_proposal: bool) -> None:
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
                events = (runner.stream_events(text, has_attachments=True)
                          if has_attachments else runner.stream_events(text))
                async for event in events:
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
            print(f"[web] stream error in {chat_id}: {exc}", file=sys.stderr)
            failed = True
            record({"type": "error", "message": web_cfg.error_message})
            queue.put_nowait({"kind": "error", "message": web_cfg.error_message})
        finally:
            unique = {(c["document"], c["section"]): c for c in citations}
            panel_after = panel_view(entry, cfg, store)
            if panel_after != panel_before:
                queue.put_nowait({"kind": "panel", "panel": panel_after})
            if failed:
                finish_agent(entry, agent_record, "error", cfg, store)
            else:
                record({"type": "done", "citations": list(unique.values())})
                finish_agent(entry, agent_record, "done", cfg, store)
                queue.put_nowait({"kind": "done", "citations": list(unique.values())})
            queue.put_nowait({"kind": "end"})
            runner.tool_observer = None
            runner.tool_result_observer = None
            lock.release()

    task = asyncio.create_task(run_turn())
    app.state.stream_tasks.add(task)
    task.add_done_callback(app.state.stream_tasks.discard)

    async def event_stream():
        deadline = store._now() + web_cfg.max_stream_seconds
        heartbeat = float(web_cfg.heartbeat_seconds)
        last_ping = store._now()
        while True:
            if store._now() >= deadline:
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=min(0.25, heartbeat))
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
