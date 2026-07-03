"""Repo inspection and task-branch workflow helpers for WebStudio sites."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .commands import CommandResult, run_command
from .registry import SiteConfig

PACKAGE_MANAGER_LOCKFILES = {
    "bun.lockb": "bun",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "package-lock.json": "npm",
}

FRAMEWORK_MARKERS = [
    ("next.config.js", "next"),
    ("next.config.mjs", "next"),
    ("next.config.ts", "next"),
    ("astro.config.mjs", "astro"),
    ("astro.config.ts", "astro"),
    ("svelte.config.js", "sveltekit"),
    ("nuxt.config.ts", "nuxt"),
    ("gatsby-config.js", "gatsby"),
    ("remix.config.js", "remix"),
]

EDITABLE_DIR_HINTS = ("pages", "app", "src", "components", "content")


def detect_package_manager(repo_path: Path) -> str:
    for filename, manager in PACKAGE_MANAGER_LOCKFILES.items():
        if (repo_path / filename).exists():
            return manager
    return "npm"


def detect_framework(repo_path: Path) -> str:
    for filename, framework in FRAMEWORK_MARKERS:
        if (repo_path / filename).exists():
            return framework
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            return "unknown"
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for key in ("next", "astro", "@sveltejs/kit", "nuxt", "gatsby", "@remix-run/react", "vite", "react"):
            if key in deps:
                return key.split("/")[-1].replace("@", "")
    return "unknown"


def slugify_branch_component(text: str) -> str:
    """Sanitize free text into a git-branch-safe slug component."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:60] or "task"


def task_branch_name(site_name: str, task_description: str, *, prefix: str = "webstudio") -> str:
    site_slug = slugify_branch_component(site_name)
    task_slug = slugify_branch_component(task_description)
    return f"{prefix}/{site_slug}/{task_slug}"


@dataclass
class GitStatus:
    current_branch: Optional[str]
    dirty: bool
    changed_files: list[str] = field(default_factory=list)
    last_commit_short: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "current_branch": self.current_branch,
            "dirty": self.dirty,
            "changed_files": self.changed_files,
            "changed_files_count": len(self.changed_files),
            "last_commit_short": self.last_commit_short,
        }


def get_git_status(repo_path: Path) -> GitStatus:
    branch_res = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, timeout=5)
    commit_res = run_command(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, timeout=5)
    status_res = run_command(["git", "status", "--porcelain"], cwd=repo_path, timeout=10)
    changed = [line[3:] for line in status_res.stdout.splitlines() if line.strip()]
    return GitStatus(
        current_branch=branch_res.stdout.strip() or None if branch_res.ok else None,
        dirty=bool(changed),
        changed_files=changed,
        last_commit_short=commit_res.stdout.strip() or None if commit_res.ok else None,
    )


def create_task_branch(repo_path: Path, branch_name: str, *, base_branch: Optional[str] = None) -> CommandResult:
    """Create and check out a new local branch. Never touches remotes."""
    if base_branch:
        run_command(["git", "checkout", base_branch], cwd=repo_path, timeout=15)
    return run_command(["git", "checkout", "-b", branch_name], cwd=repo_path, timeout=15)


def summarize_changed_files(repo_path: Path) -> list[str]:
    return get_git_status(repo_path).changed_files


def likely_editable_files(repo_path: Path, *, limit: int = 200) -> list[str]:
    """Heuristic list of pages/components likely relevant for content edits."""
    results: list[str] = []
    exts = {".tsx", ".ts", ".jsx", ".js", ".astro", ".svelte", ".vue", ".mdx", ".md", ".html"}
    for hint in EDITABLE_DIR_HINTS:
        base = repo_path / hint
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            if path.is_file() and path.suffix in exts:
                results.append(str(path.relative_to(repo_path)))
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return results


def inspect_site_repo(site: SiteConfig) -> dict:
    """One-shot repo inspection summary for a registered site."""
    repo_path = site.resolved_repo_path()
    if not repo_path.exists():
        return {
            "site": site.name,
            "repo_path": str(repo_path),
            "exists": False,
            "error": "repo path does not exist",
        }
    git_status = get_git_status(repo_path)
    return {
        "site": site.name,
        "repo_path": str(repo_path),
        "exists": True,
        "framework_detected": detect_framework(repo_path),
        "framework_configured": site.framework,
        "package_manager_detected": detect_package_manager(repo_path),
        "package_manager_configured": site.package_manager,
        "git_status": git_status.to_dict(),
        "likely_editable_files": likely_editable_files(repo_path, limit=50),
    }
