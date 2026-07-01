import json
import subprocess
from pathlib import Path

from warden.webstudio.repo import (
    detect_framework,
    detect_package_manager,
    get_git_status,
    slugify_branch_component,
    task_branch_name,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)
    (path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def test_detect_package_manager_from_lockfile(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert detect_package_manager(tmp_path) == "pnpm"


def test_detect_package_manager_defaults_to_npm(tmp_path: Path) -> None:
    assert detect_package_manager(tmp_path) == "npm"


def test_detect_framework_from_config_marker(tmp_path: Path) -> None:
    (tmp_path / "next.config.js").write_text("", encoding="utf-8")
    assert detect_framework(tmp_path) == "next"


def test_detect_framework_from_package_json_deps(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"astro": "^4.0.0"}}), encoding="utf-8")
    assert detect_framework(tmp_path) == "astro"


def test_detect_framework_unknown_when_no_markers(tmp_path: Path) -> None:
    assert detect_framework(tmp_path) == "unknown"


def test_slugify_branch_component_sanitizes() -> None:
    assert slugify_branch_component("Fix Homepage CTA!!") == "fix-homepage-cta"
    assert slugify_branch_component("  multiple   spaces  ") == "multiple-spaces"


def test_task_branch_name_is_git_safe() -> None:
    branch = task_branch_name("usemarius", "Update Homepage CTA copy")
    assert branch == "webstudio/usemarius/update-homepage-cta-copy"
    assert " " not in branch
    assert "!" not in branch


def test_get_git_status_on_clean_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    status = get_git_status(tmp_path)
    assert status.dirty is False
    assert status.changed_files == []
    assert status.last_commit_short is not None


def test_get_git_status_on_dirty_repo(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "new_file.txt").write_text("data", encoding="utf-8")
    status = get_git_status(tmp_path)
    assert status.dirty is True
    assert "new_file.txt" in status.changed_files
