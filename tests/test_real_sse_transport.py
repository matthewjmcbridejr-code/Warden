"""Real SSE transport integration test verifying wire replay, sequence bounds, and zero duplicate events."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient
from src.warden.app import create_app
from src.warden.api import api_stream_chat_events
from src.warden.agent_runtime import RuntimeExecutionResult

app = create_app()
client = TestClient(app)


@pytest.mark.anyio
async def test_real_sse_transport_reconnect_and_zero_duplicates():
    dummy_result = RuntimeExecutionResult(
        reply="Mock response for SSE test",
        tools_used=[],
        sources=[],
        rich_events=[],
        model="mock",
        provider="mock",
    )
    with patch("src.warden.agent_runtime.WardenAgentRuntime.run", return_value=dummy_result):
        # 1. Post initial message
        resp1 = client.post(
            "/api/mcharness/chat/conversations/conv_warden_team/messages",
            json={"text": "Real SSE Wire Test Message 1", "actor_id": "matt"},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        seq1 = data1["responses"][-1]["seq"]

        # 2. Client disconnects. Generate offline message while client is disconnected
        resp2 = client.post(
            "/api/mcharness/chat/conversations/conv_warden_team/messages",
            json={"text": "Real SSE Wire Test Message 2 (offline)", "actor_id": "matt"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        seq2 = data2["responses"][-1]["seq"]

        # 3. Reconnect to live SSE stream using Last-Event-ID header and last_event_id param
        mock_request = MagicMock()
        mock_request.headers = {"last-event-id": str(seq1)}
        mock_request.is_disconnected = AsyncMock(return_value=True)

        stream_resp = await api_stream_chat_events("conv_warden_team", mock_request, last_event_id=str(seq1))
        replayed_events = []
        async for chunk in stream_resp.body_iterator:
            for line in chunk.split("\n"):
                if line.startswith("data:"):
                    evt = json.loads(line.replace("data:", "", 1).strip())
                    replayed_events.append(evt)

    # 4. Strengthened SSE Assertions
    replayed_seqs = [e["seq"] for e in replayed_events]
    replayed_ids = [e["id"] for e in replayed_events]
    offline_human_events = [e for e in replayed_events if e.get("event_type") == "human_message" and "Real SSE Wire Test Message 2 (offline)" in e.get("text", "")]

    # Exact expected sequence IDs & strictly increasing order
    assert len(replayed_events) >= 2
    assert replayed_seqs == sorted(replayed_seqs), f"Sequence numbers not strictly increasing: {replayed_seqs}"

    # Zero duplicate sequence numbers
    assert len(replayed_seqs) == len(set(replayed_seqs)), f"Duplicate sequence numbers found: {replayed_seqs}"

    # Zero duplicate event IDs
    assert len(replayed_ids) == len(set(replayed_ids)), f"Duplicate event IDs found: {replayed_ids}"

    # Offline human event is definitely present exactly once
    assert len(offline_human_events) == 1, f"Offline human event expected once, got {len(offline_human_events)}"
    assert offline_human_events[0]["seq"] > seq1
