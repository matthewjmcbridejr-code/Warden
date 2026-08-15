from __future__ import annotations

import asyncio
from pathlib import Path
import shutil

import pytest
from fastapi import HTTPException

import src.warden.api as api
import src.warden.workbench as workbench_mod


class FakeRequest:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.fixture()
def isolated_workbench_root(tmp_path, monkeypatch):
    root = tmp_path / "mctable" / "workbench"
    monkeypatch.setattr(workbench_mod.STORE, "root", root)
    workbench_mod.STORE.ensure_layout()
    yield root


def test_warden_memory_remember_and_recall(isolated_workbench_root):
    async def run():
        remember_resp = await api.remember_warden_memory(
            FakeRequest(
                {
                    "scope": "warden",
                    "content": "Pieces OS style memory for Warden should keep compact summaries and source refs.",
                    "source": "manual",
                    "tags": ["warden", "pieces", "memory"],
                    "source_ref": "chat://turn-1",
                }
            )
        )
        assert remember_resp["ok"] is True
        memory = remember_resp["memory"]
        assert memory["scope"] == "warden"
        assert memory["summary"].startswith("Pieces OS style memory")
        assert memory["title"].startswith("Pieces OS style memory")
        assert memory["tags"] == ["warden", "pieces", "memory"]
        assert memory["source_ref"] == "chat://turn-1"
        assert memory["memory_id"].startswith("m-")

        recall_resp = api.recall_warden_memories("Pieces")
        assert recall_resp["ok"] is True
        assert recall_resp["count"] == 1
        assert recall_resp["memories"][0]["memory_id"] == memory["memory_id"]

    asyncio.run(run())


def test_warden_memory_create_and_list(isolated_workbench_root):
    create_resp = api.create_warden_memory(
        workbench_mod.WorkbenchMemoryCreateRequest(
            memory_id="warden-memory-one",
            scope="project",
            summary="Track Warden runtime subscription orchestration ideas here.",
            source="research",
            title="Warden runtime memory",
            tags=["warden", "runtime"],
        )
    )
    assert create_resp["ok"] is True
    assert create_resp["memory"]["memory_id"] == "warden-memory-one"
    assert create_resp["memory"]["title"] == "Warden runtime memory"

    list_resp = api.get_warden_memories()
    assert list_resp["ok"] is True
    assert list_resp["count"] == 1
    assert list_resp["memories"][0]["memory_id"] == "warden-memory-one"


def test_memory_history_survives_workbench_directory_loss(tmp_path):
    root = tmp_path / "mctable" / "workbench"
    store = workbench_mod.WorkbenchStore(root)
    memory = store.remember_memory(
        workbench_mod.WorkbenchMemoryRememberRequest(
            memory_id="history-survival-proof",
            scope="warden",
            content="A durable memory version must survive loss of the mutable workbench directory.",
            source="test",
            kind="constraint",
        )
    )

    history_root = tmp_path / "mctable" / "workbench-history" / "memories" / memory.memory_id
    versions = list(history_root.glob("*.json"))
    assert len(versions) == 1
    assert workbench_mod.WorkbenchMemory.model_validate_json(versions[0].read_text()).memory_id == memory.memory_id

    shutil.rmtree(root)
    assert not root.exists()
    assert workbench_mod.WorkbenchMemory.model_validate_json(versions[0].read_text()).summary == memory.summary


def remember(store, *, scope: str, content: str, kind: str, **kwargs):
    return store.remember_memory(
        workbench_mod.WorkbenchMemoryRememberRequest(
            scope=scope,
            content=content,
            source=kwargs.pop("source", "manual"),
            kind=kind,
            **kwargs,
        )
    )


def test_memory_generated_id_and_storage_redaction(isolated_workbench_root):
    memory = remember(
        workbench_mod.STORE,
        scope="warden",
        content=(
            "Use OPENAI_API_KEY=sk-fake-example-123 and "
            "Authorization: Bearer fake.header.value password=hunter2"
        ),
        kind="constraint",
        title="Fake secret redaction",
        source_ref="test://redaction",
        tags=["Safety", "do not touch", "Safety"],
        metadata={"note": "GITHUB_TOKEN=ghp_fakeexample123"},
    )

    assert memory.memory_id.startswith("m-")
    serialized = (isolated_workbench_root / "memories" / f"{memory.memory_id}.json").read_text()
    assert "sk-fake-example-123" not in serialized
    assert "fake.header.value" not in serialized
    assert "hunter2" not in serialized
    assert "ghp_fakeexample123" not in serialized
    assert "[REDACTED]" in serialized
    assert memory.tags == ["safety", "do-not-touch"]


def test_search_is_scoped_bounded_and_stable(isolated_workbench_root):
    first = remember(
        workbench_mod.STORE,
        scope="warden",
        content="The Warden API memory route must remain private.",
        kind="decision",
    )
    remember(
        workbench_mod.STORE,
        scope="other-project",
        content="The other project also has an API memory route.",
        kind="decision",
    )
    second = remember(
        workbench_mod.STORE,
        scope="warden",
        content="The Warden API context pack must be bounded.",
        kind="constraint",
    )

    result_one = workbench_mod.STORE.search_memories("Warden API", scope="warden", limit=2)
    result_two = workbench_mod.STORE.search_memories("Warden API", scope="warden", limit=2)
    assert [row.memory_id for row in result_one] == [row.memory_id for row in result_two]
    assert {row.memory_id for row in result_one} == {first.memory_id, second.memory_id}
    assert all(row.scope == "warden" for row in result_one)


def test_context_pack_categories_scope_bounds_and_redaction(isolated_workbench_root):
    expected_ids = []
    for kind, content in [
        ("decision", "Keep memory local to the selected Warden project."),
        ("failure", "A previous context build failed when output was unbounded."),
        ("proof", "pytest proved the isolated memory tests pass."),
        ("constraint", "Never expose Authorization: Bearer fake.secret.token."),
        ("fragile_file", "src/warden/api.py is a launch-path hot spot."),
        ("acceptance_test", "Run tests/test_warden_memory.py before handoff."),
        ("handoff", "Next agent should verify the private runner prompt."),
        ("claim", "The UI may already support memory previews."),
    ]:
        expected_ids.append(
            remember(
                workbench_mod.STORE,
                scope="warden",
                content=content,
                kind=kind,
                title=kind.replace("_", " ").title(),
            ).memory_id
        )
    remember(
        workbench_mod.STORE,
        scope="unrelated",
        content="This unrelated project fact must never leak.",
        kind="decision",
    )

    pack = workbench_mod.STORE.build_memory_context_pack(
        project_id="warden",
        repo_path="/safe/warden",
        user_prompt="Fix the private runner memory context.",
        max_memories=8,
        max_chars=6000,
    )
    assert pack["memory_count"] == 8
    assert pack["memory_ids"] == workbench_mod.STORE.build_memory_context_pack(
        project_id="warden",
        repo_path="/safe/warden",
        user_prompt="Fix the private runner memory context.",
        max_memories=8,
        max_chars=6000,
    )["memory_ids"]
    assert set(pack["memory_ids"]) == set(expected_ids)
    assert "## Relevant Decisions" in pack["context"]
    assert "## Prior Failures / Avoid" in pack["context"]
    assert "## Proven State" in pack["context"]
    assert "## Claimed But Unproven" in pack["context"]
    assert "## Known Constraints" in pack["context"]
    assert "## Fragile Files / Hot Spots" in pack["context"]
    assert "## Suggested Acceptance Tests" in pack["context"]
    assert "## Handoff / Next Step" in pack["context"]
    assert "unrelated project fact" not in pack["context"]
    assert "fake.secret.token" not in pack["context"]
    assert "Authorization: Bearer [REDACTED]" in pack["context"]

    bounded = workbench_mod.STORE.build_memory_context_pack(
        project_id="warden",
        max_memories=2,
        max_chars=256,
    )
    assert bounded["memory_count"] == 2
    assert len(bounded["context"]) <= 256
    assert bounded["truncated"] is True


def test_context_pack_empty_scope_returns_empty(isolated_workbench_root):
    pack = workbench_mod.STORE.build_memory_context_pack(project_id="missing")
    assert pack == {
        "context": "",
        "memory_count": 0,
        "memory_ids": [],
        "truncated": False,
        "scope": "missing",
    }


def test_prompt_injection_preserves_original_and_no_memory_fallback(isolated_workbench_root):
    original = "Fix the memory panel.\nPreserve this exact second line."
    unchanged, empty_meta = api.build_agent_prompt_with_memory(
        original,
        project_id="warden",
    )
    assert unchanged == original
    assert empty_meta["injected"] is False

    memory = remember(
        workbench_mod.STORE,
        scope="warden",
        content="The memory panel uses private Warden routes.",
        kind="decision",
    )
    injected, meta = api.build_agent_prompt_with_memory(
        original,
        project_id="warden",
        agent="codex_cli",
    )
    assert injected.startswith("# Warden Memory Context")
    assert injected.endswith(original)
    assert "\n\n---\n\n# User Task\n\n" in injected
    assert meta["injected"] is True
    assert memory.memory_id in meta["memory_ids"]


def test_prompt_injection_fails_open_when_memory_unavailable(isolated_workbench_root, monkeypatch):
    original = "Keep the runner usable."

    def fail(**kwargs):
        raise RuntimeError("fake memory outage")

    monkeypatch.setattr(workbench_mod.STORE, "build_memory_context_pack", fail)
    prompt, meta = api.build_agent_prompt_with_memory(original, project_id="warden")
    assert prompt == original
    assert meta["error"] == "memory_context_unavailable"


def test_memory_api_context_pack_private_only_and_no_filesystem_read(
    isolated_workbench_root,
    monkeypatch,
    tmp_path,
):
    remember(
        workbench_mod.STORE,
        scope="warden",
        content="Context endpoint returns project-scoped decisions.",
        kind="decision",
    )

    monkeypatch.delenv("MCHARNESS_TMUX_RUNNER_ENABLED", raising=False)
    monkeypatch.delenv("MCHARNESS_CODEX_RUNNER_ENABLED", raising=False)
    with pytest.raises(HTTPException) as public:
        api._require_private_memory_access()
    assert public.value.status_code == 403

    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    marker = tmp_path / "must-not-be-read.txt"
    marker.write_text("ARBITRARY_FILE_SECRET", encoding="utf-8")
    private = api.post_warden_memory_context_pack(
        api.WardenMemoryContextPackRequest(
            project_id="warden",
            repo_path=str(marker),
            prompt="context endpoint",
        )
    )
    assert private["ok"] is True
    assert private["memory_count"] == 1
    assert "ARBITRARY_FILE_SECRET" not in str(private)

    with pytest.raises(HTTPException) as invalid:
        api.post_warden_memory_context_pack(
            api.WardenMemoryContextPackRequest(
                project_id="warden",
                repo_path="bad\npath",
            )
        )
    assert invalid.value.status_code == 400


def test_private_codex_dispatch_records_memory_enriched_prompt(
    isolated_workbench_root,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("MCHARNESS_TMUX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MCHARNESS_CODEX_RUNNER_ENABLED", "true")
    monkeypatch.setattr(api, "MCTABLE_ROOT", tmp_path)
    monkeypatch.setattr(api, "RUNNER_STATE_ROOT", tmp_path / "mcharness" / "runners")
    monkeypatch.setattr(api, "ARTIFACT_BODY_ROOT", tmp_path / "mcharness" / "artifacts")

    def fake_start(state, cwd):
        state["status"] = "running"
        return state

    monkeypatch.setattr(api, "_start_codex_runner", fake_start)
    repo = Path(__file__).resolve().parents[1]
    remember(
        workbench_mod.STORE,
        scope=repo.name,
        content="Run the Warden memory regression tests before handoff.",
        kind="acceptance_test",
        repo_path=str(repo),
    )
    created = workbench_mod.STORE.create_thread(
        workbench_mod.WorkbenchThreadCreateRequest(
            title="Memory dispatch",
            objective="Prove prompt injection",
            metadata={"repo_path": str(repo), "agent_lane": "codex_cli"},
        )
    )
    session_id = created["thread_id"]
    original = "Inspect memory injection and preserve this task."
    body = api.post_mcharness_runner_start(
        session_id,
        api.McHarnessRunnerStartRequest(
            lane_id="codex_cli",
            repo_id=repo.name,
            title="Memory dispatch",
            prompt=original,
            agent_id="codex_cli",
        ),
    )
    assert body["memory_context"]["injected"] is True
    assert body["dispatch_prompt"].startswith("# Warden Memory Context")
    assert body["dispatch_prompt"].endswith(original)
    prompt_memory = next(
        memory
        for memory in workbench_mod.STORE.list_memories()
        if memory.memory_id == body["prompt_memory_id"]
    )
    assert prompt_memory.kind == "agent_prompt"
    assert prompt_memory.summary == original
    assert prompt_memory.source_ref == f"run://{body['runner_id']}"
    saved_run = api.get_run_record(tmp_path, body["runner_id"])
    assert saved_run is not None
    assert saved_run["prompt"].startswith("# Warden Memory Context")
    assert saved_run["prompt"].endswith(original)
