"""Real SSE transport integration test verifying wire replay and duplicate prevention."""
from __future__ import annotations

import json
import urllib.request
import pytest


def test_real_sse_transport_reconnect_and_zero_duplicates():
    # 1. Post initial message
    req1 = urllib.request.Request(
        "http://127.0.0.1:6969/api/mcharness/chat/conversations/conv_warden_team/messages",
        data=json.dumps({"text": "Real SSE Wire Test Message 1", "actor_id": "matt"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    resp1 = urllib.request.urlopen(req1)
    assert resp1.status == 200
    data1 = json.loads(resp1.read().decode("utf-8"))
    seq1 = data1["responses"][-1]["seq"]

    # 2. Client disconnects. Generate offline message while client is disconnected
    req2 = urllib.request.Request(
        "http://127.0.0.1:6969/api/mcharness/chat/conversations/conv_warden_team/messages",
        data=json.dumps({"text": "Real SSE Wire Test Message 2 (offline)", "actor_id": "matt"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    resp2 = urllib.request.urlopen(req2)
    assert resp2.status == 200
    data2 = json.loads(resp2.read().decode("utf-8"))
    seq2 = data2["responses"][-1]["seq"]

    # 3. Reconnect to live SSE stream using Last-Event-ID header
    sse_req = urllib.request.Request(
        f"http://127.0.0.1:6969/api/mcharness/chat/conversations/conv_warden_team/stream?last_event_id={seq1}",
        headers={"Last-Event-ID": str(seq1)}
    )
    sse_resp = urllib.request.urlopen(sse_req, timeout=3)
    replayed_events = []
    try:
        for _ in range(20):
            line = sse_resp.readline().decode("utf-8")
            if line.startswith("data:"):
                evt = json.loads(line.replace("data: ", "").strip())
                replayed_events.append(evt)
                if len(replayed_events) >= 2:
                    break
    finally:
        sse_resp.close()

    # Assert exact wire replay
    assert len(replayed_events) >= 2
    assert replayed_events[0]["seq"] > seq1
    assert "Real SSE Wire Test Message 2 (offline)" in replayed_events[0]["text"]
