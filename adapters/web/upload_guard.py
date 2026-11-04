"""ASGI guard for the multipart upload route: enforce the request byte cap."""
from __future__ import annotations

import json
import re

UPLOAD_PATH = re.compile(r"^/chats/[^/]+/messages/stream/files/?$")
REQUEST_TOO_LARGE = "request_too_large"


class _BodyTooLarge(Exception):
    pass


class UploadGuardMiddleware:
    def __init__(self, app, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not UPLOAD_PATH.match(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        declared = self._content_length(scope)
        if declared is not None and declared > self.max_request_bytes:
            await self._reject(send)
            return

        received = 0
        started = False

        async def receive_limited():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    raise _BodyTooLarge
            return message

        async def send_tracked(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive_limited, send_tracked)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    def _content_length(scope) -> int | None:
        for key, value in scope.get("headers") or []:
            if key.lower() == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    async def _reject(send) -> None:
        body = json.dumps({"detail": REQUEST_TOO_LARGE}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})
