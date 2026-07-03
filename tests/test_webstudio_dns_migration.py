from pathlib import Path

from warden.webstudio import dns_migration, dns_strategy
from warden.webstudio.dns_namecheap import DnsRecord
from warden.webstudio.registry import SiteConfig, load_registry


def _site(**overrides) -> SiteConfig:
    base = dict(name="site", domain="example.com", repo_path="/tmp/site")
    base.update(overrides)
    return SiteConfig(**base)


def test_production_domains_default_to_no_automatic_migration() -> None:
    site = _site(host_provider="vercel", dns_provider="vercel")  # migration_status defaults to "existing"
    assert site.migration_status == "existing"
    assert dns_strategy.recommend_migration_action(site) == "no_automatic_migration"


def test_planned_status_still_blocks_automatic_migration() -> None:
    site = _site(migration_status="planned")
    assert dns_strategy.recommend_migration_action(site) == "no_automatic_migration"


def test_sandbox_domains_may_recommend_vercel_nameservers() -> None:
    site = _site(host_provider="vercel", dns_provider="vercel", migration_status="sandbox")
    assert dns_strategy.recommend_migration_action(site) == "vercel_nameservers_candidate"
    plan = dns_strategy.plan_for_site(site)
    assert plan["plan"] is not None
    assert plan["plan"]["strategy"] == "vercel_nameservers"


def test_unlck_example_config_is_the_sandbox_cutover_candidate() -> None:
    sites = load_registry(Path("configs/webstudio.sites.example.yaml"))
    unlck = next(s for s in sites if s.name == "unlck")
    assert unlck.migration_status == "sandbox"
    non_sandbox = [s.name for s in sites if s.name != "unlck" and s.migration_status == "sandbox"]
    assert non_sandbox == [], "only unlck.shop should be marked as a sandbox cutover candidate"
    for s in sites:
        if s.name != "unlck":
            assert s.migration_status == "existing"


def test_dns_inventory_includes_all_record_type_checks() -> None:
    records = [
        DnsRecord(host="@", record_type="A", address="1.2.3.4"),
        DnsRecord(host="www", record_type="CNAME", address="example.com"),
        DnsRecord(host="@", record_type="MX", address="mail.example.com", mx_pref=10),
        DnsRecord(host="@", record_type="TXT", address="v=spf1 include:_spf.example.com ~all"),
    ]
    inventory = dns_migration.build_inventory("example.com", records, nameservers=["ns1.example.com"])
    counts = inventory.to_dict()["record_counts"]
    assert counts["A"] == 1
    assert counts["AAAA"] == 0
    assert counts["CNAME"] == 1
    assert counts["MX"] == 1
    assert counts["TXT"] == 1


def test_parity_checklist_flags_mx_and_txt_for_preservation() -> None:
    records = [
        DnsRecord(host="@", record_type="MX", address="mail.example.com", mx_pref=10),
        DnsRecord(host="@", record_type="TXT", address="v=spf1 ~all"),
    ]
    inventory = dns_migration.build_inventory("example.com", records)
    checklist = dns_migration.parity_checklist(inventory)
    mx_item = next(i for i in checklist if i["item"] == "email (MX)")
    txt_item = next(i for i in checklist if "TXT" in i["item"])
    assert mx_item["status"] == "present_must_preserve"
    assert txt_item["status"] == "present_must_preserve"


def test_migration_plan_flags_missing_mx_txt_preservation_risks() -> None:
    records = [DnsRecord(host="@", record_type="A", address="1.2.3.4")]
    inventory = dns_migration.build_inventory("example.com", records)
    warnings = dns_migration.missing_record_warnings(
        dns_migration.build_inventory(
            "example.com",
            records + [DnsRecord(host="@", record_type="MX", address="mail.example.com", mx_pref=10)],
        )
    )
    assert any("MX records" in w for w in warnings)

    txt_inventory = dns_migration.build_inventory(
        "example.com", records + [DnsRecord(host="@", record_type="TXT", address="v=spf1 ~all")]
    )
    txt_warnings = dns_migration.missing_record_warnings(txt_inventory)
    assert any("TXT records" in w for w in txt_warnings)


def test_cutover_plan_requires_approval_for_nameserver_change() -> None:
    steps = dns_migration.cutover_checklist("example.com")
    nameserver_step = next(s for s in steps if "nameservers at the registrar" in s["action"])
    assert nameserver_step["requires_approval"] is True
    # Inventory/backup/verification steps should not require approval.
    assert steps[0]["requires_approval"] is False


def test_rollback_plan_exists_and_requires_approval() -> None:
    steps = dns_migration.rollback_checklist("example.com", ["ns1.namecheaphosting.com", "ns2.namecheaphosting.com"])
    assert len(steps) >= 1
    assert any(s["requires_approval"] for s in steps)
    assert "ns1.namecheaphosting.com" in steps[0]["action"]


def test_plan_production_migration_end_to_end_is_read_only() -> None:
    site = _site(domain="unlck.shop", migration_status="sandbox")
    records = [
        DnsRecord(host="@", record_type="A", address="1.2.3.4"),
        DnsRecord(host="www", record_type="CNAME", address="unlck.shop"),
    ]
    inventory = dns_migration.build_inventory("unlck.shop", records, nameservers=["dns1.registrar-servers.com"])
    plan = dns_migration.plan_production_migration(site, inventory)
    assert plan["requires_manual_approval"] is True
    assert plan["recommended_action"] == "vercel_nameservers_candidate"
    assert plan["parity_checklist"]
    assert plan["cutover_checklist"]
    assert plan["rollback_checklist"]


def test_write_migration_report_creates_markdown(tmp_path: Path) -> None:
    site = _site(domain="example.com")
    inventory = dns_migration.build_inventory("example.com", [DnsRecord(host="@", record_type="A", address="1.2.3.4")])
    plan = dns_migration.plan_production_migration(site, inventory)
    path = dns_migration.write_migration_report(plan, reports_dir=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "DNS Migration Report" in text
    assert "no_automatic_migration" in text
