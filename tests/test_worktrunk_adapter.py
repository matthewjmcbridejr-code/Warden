"""Tests for WorktrunkAdapter using a temp git repo."""
import subprocess
from pathlib import Path

import pytest

from src.warden.projects import WorktrunkAdapter, WardenProject, _save_project, _load_project


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_list_worktrees_returns_main(git_repo: Path) -> None:
    adapter = WorktrunkAdapter()
    worktrees = adapter.list_worktrees(str(git_repo))
    assert len(worktrees) >= 1
    branches = [w.branch for w in worktrees]
    assert "main" in branches


def test_create_worktree(git_repo: Path, tmp_path: Path) -> None:
    adapter = WorktrunkAdapter()
    wt_root = str(tmp_path / "worktrees")
    Path(wt_root).mkdir()
    wt = adapter.create_worktree(str(git_repo), "feature-test", wt_root)
    assert wt.branch == "feature-test"
    assert Path(wt.path).exists()
    worktrees = adapter.list_worktrees(str(git_repo))
    branches = [w.branch for w in worktrees]
    assert "feature-test" in branches


def test_remove_worktree(git_repo: Path, tmp_path: Path) -> None:
    adapter = WorktrunkAdapter()
    wt_root = str(tmp_path / "worktrees")
    Path(wt_root).mkdir()
    wt = adapter.create_worktree(str(git_repo), "to-remove", wt_root)
    adapter.remove_worktree(str(git_repo), wt.path)
    worktrees = adapter.list_worktrees(str(git_repo))
    branches = [w.branch for w in worktrees]
    assert "to-remove" not in branches


def test_project_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.warden.projects as pm
    monkeypatch.setattr(pm, "PROJECTS_ROOT", tmp_path / "projects")
    project = WardenProject(
        project_id="test-proj",
        name="Test Project",
        repo_path="/tmp/fake",
    )
    _save_project(project)
    loaded = _load_project("test-proj")
    assert loaded.name == "Test Project"
    assert loaded.project_id == "test-proj"
