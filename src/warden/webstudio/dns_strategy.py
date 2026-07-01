"""DNS strategy planning: choose between Vercel nameserver delegation (the
recommended default for Vercel-hosted WebStudio sites) and Namecheap BasicDNS
record editing (a fallback path, not the default).

Registrar and DNS host are modeled separately on `SiteConfig`:
  - registrar_provider: who the domain is bought through (e.g. namecheap)
  - dns_provider: who answers DNS queries (vercel | namecheap | cloudflare | other)
  - host_provider: who serves the site (e.g. vercel)
  - dns_strategy: vercel_nameservers | external_dns_records | namecheap_basicdns

A domain can be registered at Namecheap while delegating DNS to Vercel's
nameservers — that is the preferred setup unless the domain needs a
Namecheap-specific service (email forwarding, URL forwarding, Dynamic DNS)
or non-Vercel routing, in which case Namecheap BasicDNS record editing
(see dns_namecheap.py) remains available as a fallback.

Nothing in this module changes nameservers or DNS records — it only builds
plans. All plans require explicit manual approval before any write occurs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import SiteConfig

VERCEL_NAMESERVERS = ["ns1.vercel-dns.com", "ns2.vercel-dns.com"]


@dataclass
class NameserverDelegationPlan:
    domain: str
    target: str
    nameservers: list[str]
    requires_manual_approval: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "strategy": "vercel_nameservers",
            "target": self.target,
            "nameservers": self.nameservers,
            "requires_manual_approval": self.requires_manual_approval,
            "notes": self.notes,
        }


def recommend_dns_strategy(site: SiteConfig) -> str:
    """Return the recommended DNS strategy for a site.

    Honors an explicit `dns_strategy` on the site config; otherwise falls
    back to the same default logic as SiteConfig itself (Vercel nameserver
    delegation for Vercel-hosted + Vercel-DNS sites, Namecheap BasicDNS
    when dns_provider is explicitly namecheap, external records otherwise).
    """
    if site.dns_strategy:
        return site.dns_strategy
    if site.host_provider == "vercel" and site.dns_provider == "vercel":
        return "vercel_nameservers"
    if site.dns_provider == "namecheap":
        return "namecheap_basicdns"
    return "external_dns_records"


def recommend_migration_action(site: SiteConfig) -> str:
    """Return the safe migration action for a site based on migration_status.

    This is the gate that prevents any production domain from being treated
    as a one-step "just switch nameservers" operation:
      - existing / planned  -> "no_automatic_migration" (audit-first; a
        production DNS migration report may still be generated, but no
        cutover should ever be auto-recommended)
      - sandbox              -> "vercel_nameservers_candidate" (safe to
        migrate directly — disposable/non-critical domain)
      - approved             -> "vercel_nameservers_migration_approved"
      - migrated             -> "vercel_nameservers_active"
    """
    if site.migration_status == "sandbox":
        return "vercel_nameservers_candidate"
    if site.migration_status == "approved":
        return "vercel_nameservers_migration_approved"
    if site.migration_status == "migrated":
        return "vercel_nameservers_active"
    return "no_automatic_migration"


def plan_vercel_nameserver_delegation(domain: str) -> NameserverDelegationPlan:
    """Build a plan to delegate `domain`'s nameservers to Vercel.

    This is a registrar-level change (made at the registrar, e.g. Namecheap)
    and is the recommended path for Vercel-hosted WebStudio sites. It does
    not touch individual DNS records, so it has no merge risk the way
    Namecheap BasicDNS record edits do — but it is still a real production
    change and always requires manual approval before being applied.
    """
    return NameserverDelegationPlan(
        domain=domain,
        target="vercel",
        nameservers=list(VERCEL_NAMESERVERS),
        requires_manual_approval=True,
        notes=[
            "Nameserver delegation is applied at the registrar (Namecheap for "
            "unlck.shop), pointing DNS resolution at Vercel's nameservers.",
            "Back up current Namecheap DNS records before switching nameservers "
            "so there is a fallback if you ever need to revert to Namecheap DNS.",
            "This plan only describes the target nameservers — it never changes "
            "them itself. Applying it is a manual, explicitly approved operator action.",
        ],
    )


def plan_for_site(site: SiteConfig) -> dict[str, Any]:
    """Build the recommended DNS plan payload for a site, based on its strategy.

    Returns a dict describing which strategy applies and, for the
    vercel_nameservers strategy, the concrete delegation plan. For
    namecheap_basicdns / external_dns_records, callers should use
    dns_namecheap.fetch_current_records + plan_dns_diff for the actual
    record-level plan (this function only reports the recommended strategy).
    """
    strategy = recommend_dns_strategy(site)
    migration_action = recommend_migration_action(site)
    payload: dict[str, Any] = {
        "domain": site.domain,
        "registrar_provider": site.registrar_provider,
        "dns_provider": site.dns_provider,
        "host_provider": site.host_provider,
        "migration_status": site.migration_status,
        "recommended_strategy": strategy,
        "recommended_migration_action": migration_action,
        "requires_manual_approval": True,
    }
    # Never hand back a ready-to-apply nameserver plan for a production
    # domain that hasn't been explicitly cleared for migration — audit first.
    if strategy == "vercel_nameservers" and migration_action in (
        "vercel_nameservers_candidate",
        "vercel_nameservers_migration_approved",
        "vercel_nameservers_active",
    ):
        payload["plan"] = plan_vercel_nameserver_delegation(site.domain).to_dict()
    else:
        payload["plan"] = None
        if migration_action == "no_automatic_migration":
            payload["fallback_note"] = (
                f"{site.domain} has migration_status={site.migration_status!r} — "
                "audit current DNS first with dns_migration.plan_production_migration() "
                "before any nameserver change is proposed."
            )
        else:
            payload["fallback_note"] = (
                "Use dns_namecheap.fetch_current_records() + plan_dns_diff() to build "
                "an explicit Namecheap BasicDNS record-level plan for this domain."
            )
    return payload
