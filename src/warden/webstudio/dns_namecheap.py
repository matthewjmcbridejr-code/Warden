"""Namecheap DNS safety layer: read, backup, diff, propose. Writes are approval-gated.

This is the FALLBACK DNS path. For Vercel-hosted WebStudio sites, prefer
Vercel nameserver delegation (see dns_strategy.py) — Namecheap stays the
registrar, Vercel answers DNS. Use this module's BasicDNS record editing
only when a domain needs Namecheap-specific services (email forwarding,
URL forwarding, Dynamic DNS) or non-Vercel routing.

Namecheap's `namecheap.domains.dns.setHosts` API REPLACES the entire host
record set in one call — it does not merge. Any write path built on top of
this module MUST fetch current records first, merge the proposed change into
the full record list, and require an explicit `approved=True` before calling
setHosts. This module never prints credential values; it only reports which
env vars are present.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

REQUIRED_ENV_VARS = [
    "NAMECHEAP_API_USER",
    "NAMECHEAP_API_KEY",
    "NAMECHEAP_USERNAME",
    "NAMECHEAP_CLIENT_IP",
]

NAMECHEAP_API_URL = "https://api.namecheap.com/xml.response"


@dataclass
class DnsRecord:
    host: str
    record_type: str
    address: str
    ttl: int = 1800
    mx_pref: Optional[int] = None

    def key(self) -> tuple[str, str]:
        return (self.host.lower(), self.record_type.upper())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DnsDiffPlan:
    domain: str
    existing_records: list[DnsRecord] = field(default_factory=list)
    proposed_records: list[DnsRecord] = field(default_factory=list)
    additions: list[DnsRecord] = field(default_factory=list)
    modifications: list[tuple[DnsRecord, DnsRecord]] = field(default_factory=list)
    unchanged: list[DnsRecord] = field(default_factory=list)
    merged_records: list[DnsRecord] = field(default_factory=list)
    approved: bool = False

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "strategy": "namecheap_basicdns",
            "existing_count": len(self.existing_records),
            "additions": [r.to_dict() for r in self.additions],
            "modifications": [
                {"before": before.to_dict(), "after": after.to_dict()} for before, after in self.modifications
            ],
            "unchanged_count": len(self.unchanged),
            "merged_record_count": len(self.merged_records),
            "approved": self.approved,
            "requires_manual_approval": True,
            "risk_note": (
                "Namecheap setHosts replaces the full record set. This plan's merged_records "
                "list is what would be sent — it always includes untouched existing records."
            ),
        }


def env_credentials_status() -> dict[str, bool]:
    """Report which required env vars are set, without ever reading/printing values."""
    return {name: bool(os.getenv(name, "").strip()) for name in REQUIRED_ENV_VARS}


def credentials_available() -> bool:
    return all(env_credentials_status().values())


def setup_instructions() -> list[str]:
    status = env_credentials_status()
    missing = [name for name, present in status.items() if not present]
    if not missing:
        return ["Namecheap credentials are present."]
    return [
        "Namecheap DNS operations require these environment variables (values are never logged):",
        *[f"  - {name}" for name in missing],
        "Set them in your local shell/.env (not committed) and re-run.",
        "Namecheap also requires the calling IP to be allow-listed under API access in your account.",
    ]


def _parse_hosts_xml(xml_text: str) -> list[DnsRecord]:
    root = ElementTree.fromstring(xml_text)
    ns = {"nc": "http://api.namecheap.com/xml.response"}
    records: list[DnsRecord] = []
    for host_el in root.findall(".//nc:host", ns):
        mx_pref = host_el.get("MXPref")
        records.append(
            DnsRecord(
                host=host_el.get("Name", ""),
                record_type=host_el.get("Type", ""),
                address=host_el.get("Address", ""),
                ttl=int(host_el.get("TTL", "1800") or 1800),
                mx_pref=int(mx_pref) if mx_pref else None,
            )
        )
    return records


def fetch_current_records(domain: str, *, timeout: float = 20) -> list[DnsRecord]:
    """Fetch current DNS host records for `domain` via getHosts. Read-only."""
    if not credentials_available():
        raise RuntimeError("Namecheap credentials are not available; see setup_instructions().")
    sld, _, tld = domain.partition(".")
    params = {
        "ApiUser": os.environ["NAMECHEAP_API_USER"],
        "ApiKey": os.environ["NAMECHEAP_API_KEY"],
        "UserName": os.environ["NAMECHEAP_USERNAME"],
        "ClientIp": os.environ["NAMECHEAP_CLIENT_IP"],
        "Command": "namecheap.domains.dns.getHosts",
        "SLD": sld,
        "TLD": tld or "com",
    }
    url = f"{NAMECHEAP_API_URL}?{urlencode(params)}"
    with urlopen(url, timeout=timeout) as response:
        xml_text = response.read().decode("utf-8", errors="replace")
    return _parse_hosts_xml(xml_text)


def save_backup(domain: str, records: list[DnsRecord], *, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_domain = domain.replace("/", "_")
    path = backup_dir / f"{safe_domain}.{timestamp}.json"
    payload = {
        "domain": domain,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "records": [r.to_dict() for r in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def plan_dns_diff(domain: str, existing: list[DnsRecord], proposed: list[DnsRecord]) -> DnsDiffPlan:
    """Build a merge-safe diff plan: proposed records are merged into existing ones.

    Existing records not mentioned in `proposed` are always preserved.
    """
    existing_by_key = {r.key(): r for r in existing}
    additions: list[DnsRecord] = []
    modifications: list[tuple[DnsRecord, DnsRecord]] = []
    touched_keys: set[tuple[str, str]] = set()

    for record in proposed:
        touched_keys.add(record.key())
        current = existing_by_key.get(record.key())
        if current is None:
            additions.append(record)
        elif current.address != record.address or current.ttl != record.ttl:
            modifications.append((current, record))

    unchanged = [r for r in existing if r.key() not in touched_keys]
    modified_records = [after for _before, after in modifications]
    merged = unchanged + modified_records + additions

    return DnsDiffPlan(
        domain=domain,
        existing_records=existing,
        proposed_records=proposed,
        additions=additions,
        modifications=modifications,
        unchanged=unchanged,
        merged_records=merged,
    )


def approve_plan(plan: DnsDiffPlan) -> DnsDiffPlan:
    """Explicit human approval step. Does not perform any network write."""
    plan.approved = True
    return plan


def build_set_hosts_params(domain: str, plan: DnsDiffPlan) -> dict[str, Any]:
    """Build the (unsent) request params for setHosts from an approved, merged plan.

    Raises if the plan has not been explicitly approved. Callers are responsible
    for actually issuing the network request; this module never does so itself.
    """
    if not plan.approved:
        raise RuntimeError("DNS write blocked: plan has not been explicitly approved.")
    sld, _, tld = domain.partition(".")
    params: dict[str, Any] = {
        "Command": "namecheap.domains.dns.setHosts",
        "SLD": sld,
        "TLD": tld or "com",
    }
    for index, record in enumerate(plan.merged_records, start=1):
        params[f"HostName{index}"] = record.host
        params[f"RecordType{index}"] = record.record_type
        params[f"Address{index}"] = record.address
        params[f"TTL{index}"] = str(record.ttl)
        if record.mx_pref is not None:
            params[f"MXPref{index}"] = str(record.mx_pref)
    return params
