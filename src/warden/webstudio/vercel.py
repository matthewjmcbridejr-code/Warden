"""Vercel operator layer: safe command construction, never auto-executes to prod.

Every function here builds argv lists or runs read-only inspection commands.
Production deploys (`vercel --prod` / `vercel deploy --prod`) are never issued
by this module — only preview builds/deploys and read-only inspection.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .commands import CommandResult, run_command

PROD_FLAGS = {"--prod", "-p"}


def vercel_installed() -> bool:
    result = run_command(["bash", "-c", "command -v vercel || true"], cwd=Path.cwd(), timeout=5)
    return bool(result.stdout.strip())


def _assert_not_prod(args: list[str]) -> None:
    if any(flag in args for flag in PROD_FLAGS):
        raise ValueError("Production deploy flags are not permitted through the WebStudio Vercel layer.")


def build_pull_command(*, environment: str = "preview") -> list[str]:
    return ["vercel", "pull", "--yes", f"--environment={environment}"]


def build_build_command(*, prod: bool = False) -> list[str]:
    args = ["vercel", "build"]
    if prod:
        raise ValueError("Production builds are not permitted through the WebStudio Vercel layer.")
    return args


def build_preview_deploy_command(*, prebuilt: bool = True) -> list[str]:
    args = ["vercel", "deploy"]
    if prebuilt:
        args.append("--prebuilt")
    _assert_not_prod(args)
    return args


def build_inspect_command(deployment_url_or_id: str) -> list[str]:
    return ["vercel", "inspect", deployment_url_or_id]


def build_logs_command(deployment_url_or_id: str) -> list[str]:
    return ["vercel", "logs", deployment_url_or_id]


def run_pull(repo_path: Path, *, environment: str = "preview", timeout: float = 120) -> CommandResult:
    return run_command(build_pull_command(environment=environment), cwd=repo_path, timeout=timeout)


def run_build(repo_path: Path, *, timeout: float = 300) -> CommandResult:
    return run_command(build_build_command(prod=False), cwd=repo_path, timeout=timeout)


def run_preview_deploy(repo_path: Path, *, prebuilt: bool = True, timeout: float = 300) -> CommandResult:
    """Deploy a preview build. Never deploys to production."""
    return run_command(build_preview_deploy_command(prebuilt=prebuilt), cwd=repo_path, timeout=timeout)


def inspect_deployment(repo_path: Path, deployment_url_or_id: str, *, timeout: float = 60) -> CommandResult:
    return run_command(build_inspect_command(deployment_url_or_id), cwd=repo_path, timeout=timeout)


def fetch_logs(repo_path: Path, deployment_url_or_id: str, *, timeout: float = 60) -> CommandResult:
    return run_command(build_logs_command(deployment_url_or_id), cwd=repo_path, timeout=timeout)


def extract_preview_url(deploy_result: CommandResult) -> Optional[str]:
    """`vercel deploy` prints the deployment URL as the last non-empty stdout line."""
    for line in reversed(deploy_result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("https://"):
            return line
    return None
