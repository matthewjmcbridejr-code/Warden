"""Proof pack generator: every WebStudio run produces a client-facing Markdown report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_REPORTS_DIR = Path("_mctable/webstudio/proof/reports")


@dataclass
class ProofPack:
    site_name: str
    domain: str
    repo_path: str
    branch: Optional[str] = None
    task: str = ""
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    build_status: Optional[str] = None
    test_status: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    seo_checks: dict[str, Any] = field(default_factory=dict)
    vercel_preview_url: Optional[str] = None
    dns_summary: Optional[dict[str, Any]] = None
    recommended_next_action: str = ""
    client_summary: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# WebStudio Proof Pack — {self.site_name}")
        lines.append("")
        lines.append(f"- **Domain:** {self.domain}")
        lines.append(f"- **Repo path:** `{self.repo_path}`")
        lines.append(f"- **Branch:** {self.branch or '(none)'}")
        lines.append(f"- **Generated at:** {self.generated_at}")
        lines.append("")
        lines.append("## Request / Task")
        lines.append("")
        lines.append(self.task or "(no task description provided)")
        lines.append("")

        lines.append("## Commands Run")
        lines.append("")
        if self.commands_run:
            for entry in self.commands_run:
                status = "OK" if entry.get("ok") else "FAILED"
                args = " ".join(entry.get("args", []))
                lines.append(f"- `{args}` — **{status}** ({entry.get('duration_seconds', '?')}s)")
        else:
            lines.append("(no commands run)")
        lines.append("")

        lines.append("## Build / Test Status")
        lines.append("")
        lines.append(f"- Build: {self.build_status or 'not run'}")
        lines.append(f"- Test: {self.test_status or 'not run'}")
        lines.append("")

        lines.append("## Changed Files")
        lines.append("")
        if self.changed_files:
            for path in self.changed_files:
                lines.append(f"- `{path}`")
        else:
            lines.append("(no changed files)")
        lines.append("")

        lines.append("## Screenshots")
        lines.append("")
        if self.screenshots:
            for shot in self.screenshots:
                lines.append(f"- `{shot}`")
        else:
            lines.append("(no screenshots captured)")
        lines.append("")

        lines.append("## SEO / AEO Checks")
        lines.append("")
        if self.seo_checks:
            issues = self.seo_checks.get("issues") or []
            if issues:
                for issue in issues:
                    lines.append(f"- ⚠️ {issue}")
            else:
                lines.append("- No issues detected.")
        else:
            lines.append("(no SEO checks run)")
        lines.append("")

        lines.append("## Vercel Preview")
        lines.append("")
        lines.append(self.vercel_preview_url or "(no preview deploy in this run)")
        lines.append("")

        lines.append("## DNS")
        lines.append("")
        if self.dns_summary:
            lines.append(f"- Domain: {self.dns_summary.get('domain')}")
            lines.append(f"- Additions: {len(self.dns_summary.get('additions', []))}")
            lines.append(f"- Modifications: {len(self.dns_summary.get('modifications', []))}")
            lines.append(f"- Approved: {self.dns_summary.get('approved')}")
        else:
            lines.append("(no DNS changes in this run)")
        lines.append("")

        lines.append("## Recommended Next Action")
        lines.append("")
        lines.append(self.recommended_next_action or "(none)")
        lines.append("")

        lines.append("## Client-Facing Summary")
        lines.append("")
        lines.append(self.client_summary or "(none)")
        lines.append("")

        return "\n".join(lines)

    def write(self, reports_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_site = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.site_name)
        path = reports_dir / f"{safe_site}.{timestamp}.md"
        path.write_text(self.to_markdown(), encoding="utf-8")
        return path
