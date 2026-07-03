"""Production-safe DNS migration workflow: inventory, parity, cutover, rollback.

This module never performs a DNS or nameserver change. It only captures a
read-only inventory of a domain's current DNS state and turns it into a
migration report: a Vercel zone parity checklist, missing-record/preservation
warnings, an ordered cutover checklist, and a rollback checklist. Every
cutover step that would actually change something is flagged
`requires_approval: True`.

Policy this module enforces:
  - Existing production domains stay as-is until explicitly audited — see
    `dns_strategy.recommend_migration_action()`, which returns
    "no_automatic_migration" for migration_status in {existing, planned}.
  - Sandbox domains (migration_status == "sandbox", e.g. unlck.shop) may be
    migrated directly since they're disposable/non-critical.
  - Email (MX/TXT) records must always be preserved — Vercel does not host email.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .dns_namecheap import DnsRecord
from .registry import SiteConfig

COMMON_SUBDOMAINS = ["www", "mail", "webmail", "ftp", "api", "test", "demo", "blog", "shop", "app", "staging"]
INVENTORY_RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT"]
VERCEL_APEX_A_RECORD = "76.76.21.21"
VERCEL_CNAME_TARGET = "cname.vercel-dns.com"

DEFAULT_MIGRATION_REPORTS_DIR = Path("_mctable/webstudio/dns_migration/reports")


@dataclass
class DnsInventory:
    domain: str
    nameservers: list[str] = field(default_factory=list)
    records: list[DnsRecord] = field(default_factory=list)
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def records_by_type(self, record_type: str) -> list[DnsRecord]:
        return [r for r in self.records if r.record_type.upper() == record_type.upper()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "nameservers": self.nameservers,
            "captured_at": self.captured_at,
            "record_counts": {t: len(self.records_by_type(t)) for t in INVENTORY_RECORD_TYPES},
            "records": [r.to_dict() for r in self.records],
        }


def detect_authoritative_nameservers(domain: str, *, timeout: float = 5.0) -> list[str]:
    """Best-effort NS lookup via `dig`. Returns [] (never raises) if unavailable."""
    try:
        proc = subprocess.run(
            ["dig", "+short", "NS", domain],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return sorted({line.strip().rstrip(".") for line in proc.stdout.splitlines() if line.strip()})


def build_inventory(
    domain: str, records: list[DnsRecord], *, nameservers: Optional[list[str]] = None
) -> DnsInventory:
    return DnsInventory(domain=domain, nameservers=list(nameservers or []), records=list(records))


def parity_checklist(inventory: DnsInventory) -> list[dict[str, Any]]:
    """Build a Vercel DNS parity checklist from a captured inventory. Advisory only."""
    checklist: list[dict[str, Any]] = []

    apex_records = [r for r in inventory.records if r.host in ("@", inventory.domain)]
    checklist.append(
        {
            "item": "apex (@) record",
            "current": [r.to_dict() for r in apex_records] or None,
            "target": f"A {VERCEL_APEX_A_RECORD} (or Vercel ALIAS/ANAME if the DNS host supports it)",
            "status": "present" if apex_records else "missing_in_inventory",
        }
    )

    www_records = [r for r in inventory.records if r.host.lower() == "www"]
    checklist.append(
        {
            "item": "www subdomain",
            "current": [r.to_dict() for r in www_records] or None,
            "target": f"CNAME {VERCEL_CNAME_TARGET}",
            "status": "present" if www_records else "missing_in_inventory",
        }
    )

    for host in COMMON_SUBDOMAINS:
        if host == "www":
            continue
        matches = [r for r in inventory.records if r.host.lower() == host]
        if matches:
            checklist.append(
                {
                    "item": f"{host} subdomain",
                    "current": [r.to_dict() for r in matches],
                    "target": "recreate in the new DNS zone (or leave on current DNS provider if not Vercel-served)",
                    "status": "present",
                }
            )

    mx_records = inventory.records_by_type("MX")
    checklist.append(
        {
            "item": "email (MX)",
            "current": [r.to_dict() for r in mx_records] or None,
            "target": "preserve verbatim — Vercel does not provide email hosting",
            "status": "present_must_preserve" if mx_records else "none_found",
        }
    )

    txt_records = inventory.records_by_type("TXT")
    checklist.append(
        {
            "item": "verification / SPF / DKIM (TXT)",
            "current": [r.to_dict() for r in txt_records] or None,
            "target": "preserve verbatim — required for SPF/DKIM/domain verification",
            "status": "present_must_preserve" if txt_records else "none_found",
        }
    )

    return checklist


def missing_record_warnings(inventory: DnsInventory) -> list[str]:
    """Flag preservation risks — most importantly email (MX/TXT) records."""
    warnings: list[str] = []

    if inventory.records_by_type("MX"):
        warnings.append(
            f"{inventory.domain} has MX records — email delivery will break if these are not "
            "preserved during migration. Vercel does not provide email hosting."
        )
    if inventory.records_by_type("TXT"):
        warnings.append(
            f"{inventory.domain} has TXT records (likely SPF/DKIM/domain verification) — these "
            "must be preserved verbatim or deliverability/verification will break."
        )
    if not any(r.host in ("@", inventory.domain) for r in inventory.records):
        warnings.append(
            f"No apex (@) record found in the captured inventory for {inventory.domain} — "
            "confirm this is expected before migrating."
        )

    known_hosts = {r.host.lower() for r in inventory.records}
    unexpected = known_hosts - {"@", "www", inventory.domain.lower(), *COMMON_SUBDOMAINS}
    if unexpected:
        warnings.append(
            f"Unrecognized subdomains present ({', '.join(sorted(unexpected))}) — review before "
            "migrating to ensure they are recreated or intentionally dropped."
        )

    return warnings


def cutover_checklist(domain: str) -> list[dict[str, Any]]:
    """Ordered migration steps. Only the nameserver change itself is a real write."""
    return [
        {"step": 1, "action": f"Capture and back up the current DNS inventory for {domain}.", "requires_approval": False},
        {
            "step": 2,
            "action": "Create matching records in the target DNS zone (Vercel project domain "
            "settings) so the parity checklist is fully satisfied before any nameserver change.",
            "requires_approval": False,
        },
        {
            "step": 3,
            "action": "Verify the parity checklist: apex, www, MX, TXT, and every detected "
            "subdomain accounted for in the target zone.",
            "requires_approval": False,
        },
        {
            "step": 4,
            "action": f"Change {domain}'s nameservers at the registrar (Namecheap) to Vercel's nameservers.",
            "requires_approval": True,
        },
        {
            "step": 5,
            "action": "Monitor DNS propagation; verify site, email, and all subdomains resolve correctly.",
            "requires_approval": False,
        },
        {"step": 6, "action": "Mark migration_status as migrated once verified stable.", "requires_approval": True},
    ]


def rollback_checklist(domain: str, original_nameservers: list[str]) -> list[dict[str, Any]]:
    """Steps to revert a nameserver cutover using the backed-up inventory."""
    ns_list = ", ".join(original_nameservers) if original_nameservers else "(see DNS inventory backup for original nameservers)"
    return [
        {
            "step": 1,
            "action": f"Revert {domain}'s nameservers at the registrar back to: {ns_list}.",
            "requires_approval": True,
        },
        {
            "step": 2,
            "action": "Wait for DNS propagation and re-verify site, email, and subdomains resolve as before.",
            "requires_approval": False,
        },
        {
            "step": 3,
            "action": "Mark migration_status back to its pre-migration value.",
            "requires_approval": True,
        },
    ]


def plan_production_migration(site: SiteConfig, inventory: DnsInventory) -> dict[str, Any]:
    """Build the full production-safe migration report payload. Plan-only, never mutates."""
    from . import dns_strategy  # local import: avoid import cycle at module load time

    action = dns_strategy.recommend_migration_action(site)
    return {
        "domain": inventory.domain,
        "migration_status": site.migration_status,
        "recommended_action": action,
        "requires_manual_approval": True,
        "inventory": inventory.to_dict(),
        "parity_checklist": parity_checklist(inventory),
        "missing_record_warnings": missing_record_warnings(inventory),
        "cutover_checklist": cutover_checklist(inventory.domain),
        "rollback_checklist": rollback_checklist(inventory.domain, inventory.nameservers),
    }


def render_migration_report_markdown(plan: dict[str, Any]) -> str:
    lines = [f"# DNS Migration Report — {plan['domain']}", ""]
    lines.append(f"- Migration status: {plan['migration_status']}")
    lines.append(f"- Recommended action: {plan['recommended_action']}")
    lines.append(f"- Requires manual approval: {plan['requires_manual_approval']}")
    lines.append("")
    lines.append("## Current DNS Inventory")
    lines.append("")
    nameservers = plan["inventory"]["nameservers"]
    lines.append(f"- Nameservers: {', '.join(nameservers) if nameservers else '(unknown — nameserver lookup unavailable)'}")
    for record_type, count in plan["inventory"]["record_counts"].items():
        lines.append(f"- {record_type} records: {count}")
    lines.append("")
    lines.append("## Vercel Parity Checklist")
    lines.append("")
    for item in plan["parity_checklist"]:
        lines.append(f"- **{item['item']}** — {item['status']} — target: {item['target']}")
    lines.append("")
    lines.append("## Missing Record / Preservation Warnings")
    lines.append("")
    if plan["missing_record_warnings"]:
        for warning in plan["missing_record_warnings"]:
            lines.append(f"- ⚠️ {warning}")
    else:
        lines.append("- None detected.")
    lines.append("")
    lines.append("## Cutover Checklist")
    lines.append("")
    for step in plan["cutover_checklist"]:
        approval = " (requires approval)" if step["requires_approval"] else ""
        lines.append(f"{step['step']}. {step['action']}{approval}")
    lines.append("")
    lines.append("## Rollback Checklist")
    lines.append("")
    for step in plan["rollback_checklist"]:
        approval = " (requires approval)" if step["requires_approval"] else ""
        lines.append(f"{step['step']}. {step['action']}{approval}")
    lines.append("")
    return "\n".join(lines)


def write_migration_report(plan: dict[str, Any], reports_dir: Path = DEFAULT_MIGRATION_REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_domain = plan["domain"].replace("/", "_")
    path = reports_dir / f"{safe_domain}.{timestamp}.md"
    path.write_text(render_migration_report_markdown(plan), encoding="utf-8")
    return path
