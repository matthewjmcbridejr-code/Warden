#!/usr/bin/env python3
"""Inventory/migrate Warden memory records without touching secret stores."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.warden.cloud_brain import PostgresBrain, replay_outbox
from src.warden.paths import data_root
from src.warden.workbench import WorkbenchStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="inventory only (default)")
    parser.add_argument("--apply", action="store_true", help="upsert memory records into configured PostgreSQL")
    parser.add_argument("--replay-outbox", action="store_true", help="replay failed cloud writes")
    parser.add_argument("--root", type=Path, default=None, help="source data root; defaults to Warden data root")
    args = parser.parse_args()

    if args.replay_outbox:
        print(json.dumps(replay_outbox(), indent=2, sort_keys=True))
        return 0

    source_root = (args.root or data_root()) / "workbench"
    store = WorkbenchStore(source_root)
    memories = store.list_memories()
    ids = [memory.memory_id for memory in memories]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    digest = hashlib.sha256("".join(sorted(json.dumps(m.model_dump(mode="json"), sort_keys=True) for m in memories)).encode()).hexdigest()
    report = {
        "source": str(source_root.resolve()),
        "destination": "PostgreSQL via WARDEN_BRAIN_DATABASE_URL/DATABASE_URL" if args.apply else "not written (dry run)",
        "records": len(memories),
        "unique_ids": len(set(ids)),
        "duplicates": duplicates,
        "content_sha256": digest,
        "secret_paths_excluded": ["connectors", "vault", ".env", "*.pem", "*token*", "*key*"],
        "failures": [],
    }
    if args.apply:
        brain = PostgresBrain()
        brain.ensure_schema()
        try:
            applied = brain.upsert_many(memories)
        except Exception as exc:
            applied = 0
            report["failures"].append({"batch": "memories", "error": str(exc)})
        report["applied"] = applied
        report["status"] = "complete" if applied == len(memories) else "partial"
    else:
        report["next_step"] = "Review this inventory, then rerun with --apply after PostgreSQL is provisioned."
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
