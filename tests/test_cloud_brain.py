from __future__ import annotations

from pathlib import Path

from src.warden import cloud_brain
from src.warden.workbench import WorkbenchMemoryRememberRequest, WorkbenchStore


class FailingCloud:
    def upsert(self, memory):
        raise cloud_brain.CloudBrainUnavailable("offline")

    def list_memories(self):
        raise cloud_brain.CloudBrainUnavailable("offline")

    def search_memories(self, query, *, scope=None, limit=20):
        raise cloud_brain.CloudBrainUnavailable("offline")


def test_cloud_write_is_cached_and_deduplicated_in_outbox(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cloud_brain, "data_root", lambda: tmp_path)
    local = WorkbenchStore(tmp_path / "cache" / "workbench")
    store = cloud_brain.CloudPrimaryMemoryStore(local)
    store.cloud = FailingCloud()

    memory = store.remember_memory(
        WorkbenchMemoryRememberRequest(
            memory_id="m-cloud-outage",
            scope="Warden",
            content="Cloud is canonical; local cache is recoverable.",
            kind="decision",
            project_id="Warden",
        )
    )

    assert memory.memory_id == "m-cloud-outage"
    assert [row.memory_id for row in store.list_memories()] == ["m-cloud-outage"]
    pending = list((tmp_path / "cloud-outbox").glob("*.json"))
    assert len(pending) == 1

    # The same payload hashes to the same outbox path; no duplicate queue item.
    store.cloud.upsert = lambda memory: (_ for _ in ()).throw(cloud_brain.CloudBrainUnavailable("offline"))
    assert store.outbox.enqueue("upsert_memory", memory.model_dump(mode="json")) == pending[0]
    assert len(list((tmp_path / "cloud-outbox").glob("*.json"))) == 1
