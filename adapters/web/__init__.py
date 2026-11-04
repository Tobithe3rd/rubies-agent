"""Web adapter package with split modules (import adapters.web_chat for the shim)."""
from .models import MessageBody, MessageResponse, ChatResponse, OtpResponse
from .store import ChatSessionStore
from .scrub import _mask_phone, _scrub_summary, _history_text
from .transcript import (
    record_user, start_agent, record_agent_event,
    finish_agent, record_reply, history_messages,
)
from .panel import panel_view, _record_panel_result
from .turn import _step_payload, _tool_labels, _extract_citations, stream_response
from .app import create_app
from .routes_chat import create_chat, send_message, get_otp, delete_chat, health
from .routes_stream import stream_message
from .routes_session import get_session, get_history
