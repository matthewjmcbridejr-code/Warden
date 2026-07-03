from __future__ import annotations

import pytest
from fastapi import HTTPException

import src.warden.api as api
import src.warden.assistant as assistant_mod
import src.warden.workbench as workbench_mod


@pytest.fixture()
def isolated_workbench_root(tmp_path, monkeypatch):
    root = tmp_path / "mctable" / "workbench"
    monkeypatch.setattr(workbench_mod.STORE, "root", root)
    workbench_mod.STORE.ensure_layout()
    yield root


@pytest.fixture()
def allowlisted_repo(tmp_path):
    repo = tmp_path / "warden-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "README.md").write_text("# Warden Repo\nLocal operator notes.\n", encoding="utf-8")
    (repo / "docs" / "warden_memory.md").write_text("Memory is private-runner-only.\n", encoding="utf-8")
    (repo / "docs" / "warden_memory_style.md").write_text("Use compact evidence-backed records.\n", encoding="utf-8")
    (repo / "secret.txt").write_text("OPENAI_API_KEY=sk-top-secret\n", encoding="utf-8")
    return repo


def remember(scope: str, content: str, *, kind: str = "decision"):
    return workbench_mod.STORE.remember_memory(
        workbench_mod.WorkbenchMemoryRememberRequest(
            scope=scope,
            project_id=scope,
            content=content,
            source="manual",
            kind=kind,
        )
    )


def test_assistant_health_payload_reports_disabled_google_rag():
    payload = assistant_mod.assistant_health_payload()
    assert payload["ok"] is True
    assert payload["provider"] == "local-deterministic"
    assert payload["google_rag"]["enabled"] is False
    assert "disabled by default" in payload["google_rag"]["warning"].lower()


def test_assistant_context_reads_allowlisted_docs_and_memory(isolated_workbench_root, allowlisted_repo):
    memory = remember("warden", "Keep the assistant local and private.", kind="constraint")
    payload = assistant_mod.AssistantRequest(
        project_id="warden",
        repo_path=str(allowlisted_repo),
        message="How should the local assistant work?",
    )
    context = assistant_mod.build_assistant_context(payload, workbench_mod.STORE, [allowlisted_repo])
    assert context["ok"] is True
    assert context["memory_context"]["memory_count"] == 1
    assert memory.memory_id in context["memory_context"]["memory_ids"]
    assert "README.md" in context["context_used"]["project_docs"]["paths"]
    assert "secret.txt" not in str(context)


def test_assistant_context_rejects_non_allowlisted_repo(isolated_workbench_root, allowlisted_repo, tmp_path):
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    (outside / "README.md").write_text("Should not be read.\n", encoding="utf-8")
    payload = assistant_mod.AssistantRequest(
        project_id="warden",
        repo_path=str(outside),
        message="Read docs",
    )
    context = assistant_mod.build_assistant_context(payload, workbench_mod.STORE, [allowlisted_repo])
    assert context["context_used"]["project_docs"]["doc_count"] == 0
    assert any("not allowlisted" in warning.lower() for warning in context["warnings"])


def test_assistant_chat_redacts_secrets_and_returns_honest_fallback(isolated_workbench_root, allowlisted_repo):
    remember("warden", "Never expose Authorization: Bearer fake.secret.token.", kind="constraint")
    payload = assistant_mod.AssistantRequest(
        project_id="warden",
        repo_path=str(allowlisted_repo),
        message="Tell me about memory and any tokens you see.",
    )
    response = assistant_mod.chat_with_assistant(payload, workbench_mod.STORE, [allowlisted_repo])
    assert response.ok is True
    assert response.provider == "local-deterministic"
    assert "fake.secret.token" not in response.answer

    no_context = assistant_mod.chat_with_assistant(
        assistant_mod.AssistantRequest(
            project_id="missing",
            repo_path=str(allowlisted_repo),
            message="What do you know?",
            include_memory=False,
            include_project_context=False,
        ),
        workbench_mod.STORE,
        [allowlisted_repo],
    )
    assert "do not have enough local warden context" in no_context.answer.lower()


def test_assistant_chat_google_rag_disabled_by_default(isolated_workbench_root, allowlisted_repo):
    payload = assistant_mod.AssistantRequest(
        project_id="warden",
        repo_path=str(allowlisted_repo),
        message="Use google rag if possible.",
        include_google_rag=True,
    )
    response = assistant_mod.chat_with_assistant(payload, workbench_mod.STORE, [allowlisted_repo])
    assert response.ok is True
    assert any("google rag" in warning.lower() for warning in response.warnings)
    assert response.context_used["google_rag"]["enabled"] is False


def test_assistant_api_private_gate_pattern(isolated_workbench_root, allowlisted_repo, monkeypatch):
    monkeypatch.setattr(api, "_codex_runner_ready", lambda: False)
    with pytest.raises(HTTPException) as excinfo:
        api._require_private_memory_access()
    assert excinfo.value.status_code == 403
