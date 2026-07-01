"""Install/build/test workflow orchestration for a registered WebStudio site."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .commands import CommandResult, run_command
from .registry import SiteConfig

PACKAGE_MANAGER_RUNNERS = {
    "npm": ["npm", "run"],
    "pnpm": ["pnpm", "run"],
    "yarn": ["yarn"],
    "bun": ["bun", "run"],
}

PACKAGE_MANAGER_INSTALL = {
    "npm": ["npm", "install"],
    "pnpm": ["pnpm", "install"],
    "yarn": ["yarn", "install"],
    "bun": ["bun", "install"],
}


@dataclass
class WorkflowResult:
    install: CommandResult | None = None
    build: CommandResult | None = None
    test: CommandResult | None = None
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        steps = [s for s in (self.install, self.build, self.test) if s is not None]
        return all(step.ok for step in steps)

    def to_dict(self) -> dict:
        return {
            "install": self.install.to_dict() if self.install else None,
            "build": self.build.to_dict() if self.build else None,
            "test": self.test.to_dict() if self.test else None,
            "skipped": self.skipped,
            "ok": self.ok,
        }


def _split_command(command: str) -> list[str]:
    return command.split()


def run_build_test_workflow(
    site: SiteConfig,
    *,
    install: bool = True,
    build: bool = True,
    test: bool = True,
    timeout: float = 300,
) -> WorkflowResult:
    """Run install/build/test for a site using its configured or detected commands.

    Stops early on the first failing step to avoid burning time on a broken build.
    Gracefully skips steps that have no configured command (e.g. sites without tests).
    """
    repo_path = site.resolved_repo_path()
    result = WorkflowResult()
    if not repo_path.exists():
        result.skipped.append("repo path does not exist")
        return result

    if install:
        install_cmd = (
            _split_command(site.install_command)
            if site.install_command
            else PACKAGE_MANAGER_INSTALL.get(site.package_manager, ["npm", "install"])
        )
        result.install = run_command(install_cmd, cwd=repo_path, timeout=timeout)
        if not result.install.ok:
            return result
    else:
        result.skipped.append("install")

    if build and site.build_command:
        result.build = run_command(_split_command(site.build_command), cwd=repo_path, timeout=timeout)
        if not result.build.ok:
            return result
    else:
        result.skipped.append("build (no build_command configured)" if build else "build")

    if test and site.test_command:
        result.test = run_command(_split_command(site.test_command), cwd=repo_path, timeout=timeout)
    else:
        result.skipped.append("test (no test_command configured)" if test else "test")

    return result
