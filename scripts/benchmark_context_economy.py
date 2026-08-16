"""Benchmark script measuring Warden context economy and payload byte sizes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))

from src.warden.brain_mcp_server import (
    warden_bootstrap,
    warden_context_delta,
    _service_catalog_data,
    _store,
)
from src.warden.context_protocol import compute_context_revision, get_context_delta
from src.warden.profile_protocol import compute_profile_revision
from src.warden.artifacts_protocol import store_artifact, format_artifact_response


def estimate_tokens(text_or_dict: str | dict) -> int:
    """Estimates token count using standard 4 chars per token rule of thumb."""
    if isinstance(text_or_dict, dict):
        raw = json.dumps(text_or_dict)
    else:
        raw = str(text_or_dict)
    return len(raw) // 4


def run_benchmark() -> dict[str, dict[str, int]]:
    """Runs context economy benchmark without mutating production state."""
    results = {}

    # 1. Cold auto bootstrap (Default)
    cold_str = warden_bootstrap(task="Benchmark task", project="warden", mode="auto")
    results["cold_auto_bootstrap"] = {
        "bytes": len(cold_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(cold_str),
    }
    cold_json = json.loads(cold_str).get("data", {})
    ctx_rev = cold_json.get("context_revision")
    cat_hash = cold_json.get("tool_catalog_revision", {}).get("revision_hash")
    prof_rev = cold_json.get("profile_revision")

    # 2. Warm reconnect (No change)
    warm_str = warden_bootstrap(
        task="Benchmark task",
        project="warden",
        mode="auto",
        known_context_revision=ctx_rev,
        known_tool_catalog_revision=cat_hash,
        known_profile_revision=prof_rev,
    )
    results["warm_reconnect_no_change"] = {
        "bytes": len(warm_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(warm_str),
    }

    # 3. Explicit full bootstrap (mode="full")
    full_str = warden_bootstrap(task="Benchmark task", project="warden", mode="full")
    results["full_bootstrap_explicit"] = {
        "bytes": len(full_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(full_str),
    }

    # 4. Minimal bootstrap (mode="minimal")
    min_str = warden_bootstrap(task="Benchmark task", project="warden", mode="minimal")
    results["minimal_bootstrap"] = {
        "bytes": len(min_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(min_str),
    }

    # 5. Context Revision & Deltas
    store = _store()
    all_memories = [
        {"memory_id": m.memory_id, "title": m.title or m.summary[:60], "summary": m.summary[:300], "kind": m.kind, "project": m.project_id or m.scope}
        for m in store.list_memories()
    ]
    curr_rev = compute_context_revision(project="warden", tasks=[], memories=all_memories)

    # No-change delta
    delta_no_change = get_context_delta(curr_rev, curr_rev, project="warden", tasks=[], memories=all_memories)
    delta_no_change_str = json.dumps(delta_no_change)
    results["delta_no_change"] = {
        "bytes": len(delta_no_change_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(delta_no_change_str),
    }

    # Single-change delta
    mem_sample = all_memories[:1] if all_memories else [{"memory_id": "test_m", "kind": "decision", "title": "Test"}]
    delta_single = get_context_delta("ctx_old_000000", curr_rev, project="warden", tasks=[], memories=mem_sample)
    delta_single_str = json.dumps(delta_single)
    results["delta_single_change"] = {
        "bytes": len(delta_single_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(delta_single_str),
    }

    # 6. Context pack
    pack = store.build_memory_context_pack(project_id="warden", user_prompt="test", max_memories=8)
    pack_str = json.dumps(pack)
    results["context_pack"] = {
        "bytes": len(pack_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(pack_str),
    }

    # 7. Service catalog
    svc_catalog = _service_catalog_data(verify_live_mail=False)
    svc_str = json.dumps(svc_catalog)
    results["service_catalog"] = {
        "bytes": len(svc_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(svc_str),
    }

    # 8. Large test output inline vs artifact
    large_log = "PASSED test_1\nPASSED test_2\n" * 500 # ~12KB
    results["large_log_inline"] = {
        "bytes": len(large_log.encode("utf-8")),
        "estimated_tokens": estimate_tokens(large_log),
    }

    ref = store_artifact(large_log, type="test_report", project="warden")
    art_resp = format_artifact_response("Full test suite passed (500 tests).", [ref])
    art_resp_str = json.dumps(art_resp)
    results["large_log_artifact"] = {
        "bytes": len(art_resp_str.encode("utf-8")),
        "estimated_tokens": estimate_tokens(art_resp_str),
    }

    return results


if __name__ == "__main__":
    benchmark_data = run_benchmark()
    print("==========================================================")
    print("WARDEN CONTEXT ECONOMY BENCHMARK REPORT")
    print("==========================================================")
    for key, data in benchmark_data.items():
        print(f"{key:25s}: {data['bytes']:7d} bytes (~{data['estimated_tokens']:5d} tokens)")
    print("==========================================================")
