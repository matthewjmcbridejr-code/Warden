"""Small, signed Slack Events API bridge for Warden."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Awaitable, Callable


def _header(scope: dict[str, Any], name: str) -> str:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("utf-8", "replace")
    return ""


def verify_signature(scope: dict[str, Any], body: bytes) -> bool:
    secret = os.getenv("SLACK_SIGNING_SECRET", "")
    timestamp = _header(scope, "x-slack-request-timestamp")
    signature = _header(scope, "x-slack-signature")
    if not secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    base = f"v0:{timestamp}:".encode() + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_events(scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]], process: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = b"".join(chunks)
    if not verify_signature(scope, body):
        payload = b'{"ok":false,"error":"invalid signature"}'
        await send({"type": "http.response.start", "status": 401, "headers": [[b"content-type", b"application/json"], [b"content-length", str(len(payload)).encode()]]})
        await send({"type": "http.response.body", "body": payload})
        return
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        event = {}
    if event.get("type") == "url_verification":
        payload = json.dumps({"challenge": event.get("challenge", "")}).encode()
    else:
        import asyncio
        asyncio.create_task(process(event))
        payload = b'{"ok":true}'
    await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"], [b"content-length", str(len(payload)).encode()]]})
    await send({"type": "http.response.body", "body": payload})
