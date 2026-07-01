from pathlib import Path

import pytest

from warden.webstudio import dns_namecheap as dns
from warden.webstudio import dns_strategy
from warden.webstudio.registry import SiteConfig, load_registry


def _site(**overrides) -> SiteConfig:
    base = dict(name="site", domain="example.com", repo_path="/tmp/site")
    base.update(overrides)
    return SiteConfig(**base)


def test_registrar_and_dns_provider_are_independent_fields() -> None:
    site = _site(registrar_provider="namecheap", dns_provider="vercel", host_provider="vercel")
    assert site.registrar_provider == "namecheap"
    assert site.dns_provider == "vercel"
    assert site.registrar_provider != site.dns_provider


def test_vercel_hosted_site_defaults_to_vercel_nameservers() -> None:
    site = _site(host_provider="vercel", dns_provider="vercel")
    assert site.dns_strategy == "vercel_nameservers"
    assert site.nameserver_target == "vercel"


def test_namecheap_dns_provider_defaults_to_basicdns_strategy() -> None:
    site = _site(host_provider="vercel", dns_provider="namecheap")
    assert site.dns_strategy == "namecheap_basicdns"


def test_explicit_dns_strategy_is_respected() -> None:
    site = _site(dns_provider="cloudflare", dns_strategy="external_dns_records")
    assert site.dns_strategy == "external_dns_records"


def test_unknown_dns_provider_rejected() -> None:
    with pytest.raises(Exception):
        _site(dns_provider="godaddy")


def test_unlck_example_config_uses_vercel_nameserver_strategy() -> None:
    sites = load_registry(Path("configs/webstudio.sites.example.yaml"))
    unlck = next(s for s in sites if s.name == "unlck")
    assert unlck.domain == "unlck.shop"
    assert unlck.registrar_provider == "namecheap"
    assert unlck.dns_provider == "vercel"
    assert unlck.dns_strategy == "vercel_nameservers"
    assert unlck.nameserver_target == "vercel"


def test_recommend_dns_strategy_prefers_vercel_for_vercel_hosted_sites() -> None:
    site = _site(host_provider="vercel", dns_provider="vercel")
    assert dns_strategy.recommend_dns_strategy(site) == "vercel_nameservers"


def test_plan_vercel_nameserver_delegation_requires_manual_approval() -> None:
    plan = dns_strategy.plan_vercel_nameserver_delegation("unlck.shop")
    payload = plan.to_dict()
    assert payload["requires_manual_approval"] is True
    assert payload["nameservers"] == dns_strategy.VERCEL_NAMESERVERS
    assert payload["strategy"] == "vercel_nameservers"


def test_plan_for_site_recommends_vercel_nameservers_for_unlck() -> None:
    sites = load_registry(Path("configs/webstudio.sites.example.yaml"))
    unlck = next(s for s in sites if s.name == "unlck")
    payload = dns_strategy.plan_for_site(unlck)
    assert payload["recommended_strategy"] == "vercel_nameservers"
    assert payload["plan"]["requires_manual_approval"] is True
    assert payload["requires_manual_approval"] is True


def test_plan_for_site_falls_back_to_namecheap_basicdns() -> None:
    site = _site(host_provider="vercel", dns_provider="namecheap", dns_strategy="namecheap_basicdns")
    payload = dns_strategy.plan_for_site(site)
    assert payload["recommended_strategy"] == "namecheap_basicdns"
    assert payload["plan"] is None
    assert "fallback_note" in payload


def test_namecheap_diff_plan_still_preserves_existing_records_and_needs_approval() -> None:
    existing = [
        dns.DnsRecord(host="@", record_type="A", address="1.2.3.4"),
        dns.DnsRecord(host="www", record_type="CNAME", address="example.com"),
    ]
    proposed = [dns.DnsRecord(host="@", record_type="A", address="76.76.21.21")]
    plan = dns.plan_dns_diff("example.com", existing, proposed)
    payload = plan.to_dict()
    assert payload["strategy"] == "namecheap_basicdns"
    assert payload["requires_manual_approval"] is True
    assert payload["approved"] is False
    merged_keys = {(r.host, r.record_type) for r in plan.merged_records}
    assert ("www", "CNAME") in merged_keys
