"""Incrementally summarize Slack conversations into Warden Brain memory."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .cloud_brain import get_memory_store
from .paths import data_root
from .workbench import WorkbenchMemoryRememberRequest

logger = logging.getLogger("warden.slack_sync")
SLACK_API = "https://slack.com/api"
STATE_PATH = Path(os.getenv("WARDEN_SLACK_SYNC_STATE", str(data_root() / "slack-sync-state.json")))
MAX_MESSAGES = max(100, int(os.getenv("WARDEN_SLACK_SYNC_MAX_MESSAGES", "5000")))
LOOKBACK_HOURS = max(1, int(os.getenv("WARDEN_SLACK_SYNC_LOOKBACK_HOURS", "6")))
CHANNEL_TYPES = os.getenv(
    "WARDEN_SLACK_SYNC_CHANNEL_TYPES", "public_channel,private_channel,mpim,im"
).split(",")


def _redact(text: str) -> str:
    text = re.sub(r"xox[baprs]-[A-Za-z0-9-]+", "[SLACK_TOKEN]", text)
    text = re.sub(r"\b(?:sk|gsk|gh[pousr])_[A-Za-z0-9._-]{8,}\b", "[API_TOKEN]", text)
    text = re.sub(r"(?i)\b(password|passwd|secret|api[_ -]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return text


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"channels": {}, "last_sync_at": None}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


async def _slack(client: httpx.AsyncClient, token: str, method: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{SLACK_API}/{method}", headers={"Authorization": f"Bearer {token}"}, params=params)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {payload.get('error', 'unknown error')}")
    return payload


async def _slack_post(client: httpx.AsyncClient, token: str, method: str, **params: Any) -> dict[str, Any]:
    response = await client.post(f"{SLACK_API}/{method}", headers={"Authorization": f"Bearer {token}"}, data=params)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {payload.get('error', 'unknown error')}")
    return payload


async def _list_channels(client: httpx.AsyncClient, token: str) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    cursor = ""
    while True:
        payload = await _slack(
            client,
            token,
            "conversations.list",
            types=",".join(t.strip() for t in CHANNEL_TYPES if t.strip()),
            exclude_archived="true",
            limit=200,
            cursor=cursor,
        )
        channels.extend(c for c in payload.get("channels", []) if not c.get("is_archived"))
        cursor = payload.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return channels


async def _history(client: httpx.AsyncClient, token: str, channel: dict[str, Any], oldest: str) -> list[dict[str, Any]]:
    payload = await _slack(client, token, "conversations.history", channel=channel["id"], oldest=oldest, limit=200)
    return [m for m in reversed(payload.get("messages", [])) if float(m.get("ts", 0)) > float(oldest)]


def _format_messages(messages: list[dict[str, Any]]) -> str:
    rows = []
    for message in messages:
        channel = message["channel_name"]
        author = message.get("user") or message.get("username") or "unknown"
        text = _redact(str(message.get("text") or "").strip())
        if text:
            rows.append(f"[{channel}] {author}: {text[:2000]}")
    return "\n".join(rows)


async def run_once() -> dict[str, Any]:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not configured")
    state = _load_state()
    now = time.time()
    messages: list[dict[str, Any]] = []
    channel_errors: list[str] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        channels = await _list_channels(client, token)
        for channel in channels:
            if len(messages) >= MAX_MESSAGES:
                break
            if channel.get("is_channel") and not channel.get("is_private") and not channel.get("is_member"):
                try:
                    await _slack_post(client, token, "conversations.join", channel=channel["id"])
                except Exception as exc:
                    channel_errors.append(f"{channel.get('name') or channel['id']}: join failed: {exc}")
                    continue
            previous = state.get("channels", {}).get(channel["id"], {}).get("last_ts")
            oldest = str(previous or max(0, now - LOOKBACK_HOURS * 3600))
            try:
                fresh = await _history(client, token, channel, oldest)
            except Exception as exc:
                channel_errors.append(f"{channel.get('name') or channel['id']}: {exc}")
                continue
            for message in fresh:
                message["channel_name"] = channel.get("name") or channel["id"]
            messages.extend(fresh[: MAX_MESSAGES - len(messages)])
            if fresh:
                state.setdefault("channels", {})[channel["id"]] = {
                    "name": channel.get("name") or channel["id"],
                    "last_ts": fresh[-1].get("ts"),
                }
    state["last_sync_at"] = now
    if not messages:
        _save_state(state)
        return {"ok": True, "messages": 0, "channels": len(state.get("channels", {})), "errors": channel_errors}

    transcript = _format_messages(messages)
    from src.marius.provider_gateway import ProviderGateway

    prompt = (
        "Create a concise operational digest of these Slack messages for Warden's shared memory. "
        "Capture decisions, commitments, deadlines, blockers, important facts, and unresolved questions. "
        "Do not invent context. Exclude greetings and repetition. Use bullets and mention the channel.\n\n"
        + transcript[:50000]
    )
    gateway = ProviderGateway()
    result = await gateway.chat(prompt, brain_enabled=False)
    digest = _redact(str(result.get("response") or "").strip())
    if not digest:
        digest = "\n".join(_redact(line) for line in transcript.splitlines()[:80])

    from datetime import datetime, timezone

    window_end = datetime.now(timezone.utc)
    memory = WorkbenchMemoryRememberRequest(
        memory_id=f"m-slack-digest-{int(now * 1000)}",
        scope="slack",
        content=digest[:12000],
        source="slack-sync",
        title=f"Slack digest {window_end.strftime('%Y-%m-%d %H:%M UTC')}",
        source_ref="slack://workspace/Phantom-Workflow",
        tags=["slack", "slack_sync", "shared_context"],
        kind="user_note",
        project_id="Warden",
        metadata={"message_count": len(messages), "channel_count": len({m['channel_name'] for m in messages}), "errors": channel_errors},
        notes="Generated from incremental Slack history; raw message text is not retained in this memory record.",
    )
    get_memory_store().remember_memory(memory)
    _save_state(state)
    return {"ok": True, "messages": len(messages), "channels": len({m['channel_name'] for m in messages}), "errors": channel_errors}


def main() -> None:
    logging.basicConfig(level=os.getenv("WARDEN_SLACK_SYNC_LOG_LEVEL", "INFO"))
    result = asyncio.run(run_once())
    logger.info("Slack sync complete: %s", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
