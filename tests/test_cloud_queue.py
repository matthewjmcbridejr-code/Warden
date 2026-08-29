from __future__ import annotations

import json

from src.warden import cloud_queue


class _Message:
    def __init__(self, envelope: dict):
        self.data = json.dumps(envelope).encode("utf-8")
        self.acked = 0
        self.nacked = 0

    def ack(self) -> None:
        self.acked += 1

    def nack(self) -> None:
        self.nacked += 1


class _FakeControlPlane:
    records: dict[tuple[str, str], dict] = {}
    events: list[dict] = []
    leases: set[str] = set()

    def acquire_lease(self, lease_key: str, owner_id: str, *, ttl_seconds: int = 60) -> bool:
        if lease_key in self.leases:
            return False
        self.leases.add(lease_key)
        return True

    def release_lease(self, lease_key: str, owner_id: str) -> bool:
        self.leases.discard(lease_key)
        return True

    def get_record(self, record_type: str, record_id: str):
        return self.records.get((record_type, record_id))

    def upsert_record(self, record_type: str, record_id: str, payload: dict, **kwargs) -> None:
        self.records[(record_type, record_id)] = payload

    def append_event(self, stream_id: str, event_type: str, payload: dict, **kwargs):
        self.events.append({"stream_id": stream_id, "event_type": event_type, **payload})
        return payload, True


def test_safe_cloud_operation_records_artifact_proof_and_suppresses_duplicate(monkeypatch, tmp_path):
    _FakeControlPlane.records = {}
    _FakeControlPlane.events = []
    _FakeControlPlane.leases = set()
    monkeypatch.setattr(cloud_queue, "CloudControlPlane", _FakeControlPlane)
    monkeypatch.setenv("WARDEN_WORKER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("WARDEN_ARTIFACT_BACKEND", "local")
    monkeypatch.setenv("WARDEN_DATA_ROOT", str(tmp_path))

    envelope = {
        "mission_id": "cloud-queue-test",
        "kind": "cloud_safe",
        "body": {"operation": "artifact_proof"},
        "idempotency_key": "cloud-queue-test-v1",
    }
    message = _Message(envelope)
    cloud_queue.handle_mission_message(message, owner_id="test-worker")

    assert message.acked == 1
    assert message.nacked == 0
    mission = _FakeControlPlane.records[("mission", "cloud-queue-test")]
    assert mission["status"] == "completed"
    assert mission["proof_refs"] == ["proof_cloud-queue-test"]
    assert len(_FakeControlPlane.records) == 3  # mission, artifact, proof

    duplicate = _Message(envelope)
    cloud_queue.handle_mission_message(duplicate, owner_id="other-worker")
    assert duplicate.acked == 1
    assert duplicate.nacked == 0
    assert len(_FakeControlPlane.records) == 3


def test_unallowlisted_cloud_operation_fails_closed(monkeypatch, tmp_path):
    _FakeControlPlane.records = {}
    _FakeControlPlane.events = []
    _FakeControlPlane.leases = set()
    monkeypatch.setattr(cloud_queue, "CloudControlPlane", _FakeControlPlane)
    monkeypatch.setenv("WARDEN_WORKER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("WARDEN_DATA_ROOT", str(tmp_path))

    message = _Message({
        "mission_id": "cloud-queue-reject",
        "body": {"operation": "run_user_supplied_command"},
    })
    cloud_queue.handle_mission_message(message, owner_id="test-worker")

    assert message.acked == 1
    assert _FakeControlPlane.records[("mission", "cloud-queue-reject")]["status"] == "failed"
    assert any(event["event_type"] == "mission.failed" for event in _FakeControlPlane.events)
