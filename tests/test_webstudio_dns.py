import os
from pathlib import Path

import pytest

from warden.webstudio import dns_namecheap as dns


def test_env_credentials_status_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in dns.REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    status = dns.env_credentials_status()
    assert all(present is False for present in status.values())
    assert dns.credentials_available() is False


def test_env_credentials_status_reports_present(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in dns.REQUIRED_ENV_VARS:
        monkeypatch.setenv(name, "placeholder")
    assert dns.credentials_available() is True


def test_setup_instructions_lists_missing_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in dns.REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    instructions = dns.setup_instructions()
    assert any("NAMECHEAP_API_USER" in line for line in instructions)


def test_diff_plan_preserves_untouched_records() -> None:
    existing = [
        dns.DnsRecord(host="@", record_type="A", address="1.2.3.4"),
        dns.DnsRecord(host="www", record_type="CNAME", address="usemarius.com"),
        dns.DnsRecord(host="mail", record_type="MX", address="mail.example.com", mx_pref=10),
    ]
    proposed = [dns.DnsRecord(host="@", record_type="A", address="76.76.21.21")]

    plan = dns.plan_dns_diff("usemarius.com", existing, proposed)

    assert len(plan.additions) == 0
    assert len(plan.modifications) == 1
    before, after = plan.modifications[0]
    assert before.address == "1.2.3.4"
    assert after.address == "76.76.21.21"

    merged_keys = {r.key() for r in plan.merged_records}
    assert ("www", "CNAME") in merged_keys
    assert ("mail", "MX") in merged_keys
    assert len(plan.merged_records) == 3  # untouched www + mail, updated @


def test_diff_plan_detects_additions() -> None:
    existing = [dns.DnsRecord(host="@", record_type="A", address="1.2.3.4")]
    proposed = [dns.DnsRecord(host="blog", record_type="CNAME", address="ghost.io")]
    plan = dns.plan_dns_diff("usemarius.com", existing, proposed)
    assert len(plan.additions) == 1
    assert len(plan.unchanged) == 1
    assert len(plan.merged_records) == 2


def test_build_set_hosts_params_requires_approval() -> None:
    existing = [dns.DnsRecord(host="@", record_type="A", address="1.2.3.4")]
    proposed = [dns.DnsRecord(host="@", record_type="A", address="76.76.21.21")]
    plan = dns.plan_dns_diff("usemarius.com", existing, proposed)
    with pytest.raises(RuntimeError):
        dns.build_set_hosts_params("usemarius.com", plan)


def test_build_set_hosts_params_after_approval_includes_all_merged_records() -> None:
    existing = [
        dns.DnsRecord(host="@", record_type="A", address="1.2.3.4"),
        dns.DnsRecord(host="www", record_type="CNAME", address="usemarius.com"),
    ]
    proposed = [dns.DnsRecord(host="@", record_type="A", address="76.76.21.21")]
    plan = dns.plan_dns_diff("usemarius.com", existing, proposed)
    dns.approve_plan(plan)
    params = dns.build_set_hosts_params("usemarius.com", plan)
    assert params["Command"] == "namecheap.domains.dns.setHosts"
    addresses = {v for k, v in params.items() if k.startswith("Address")}
    assert "76.76.21.21" in addresses
    assert "usemarius.com" in addresses  # untouched www record preserved


def test_save_backup_writes_json(tmp_path: Path) -> None:
    records = [dns.DnsRecord(host="@", record_type="A", address="1.2.3.4")]
    path = dns.save_backup("usemarius.com", records, backup_dir=tmp_path)
    assert path.exists()
    assert "usemarius.com" in path.read_text(encoding="utf-8")


def test_set_custom_nameservers_requires_approval() -> None:
    with pytest.raises(RuntimeError):
        dns.set_custom_nameservers("unlck.shop", ["ns1.vercel-dns.com", "ns2.vercel-dns.com"], approved=False)


def test_set_custom_nameservers_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in dns.REQUIRED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError):
        dns.set_custom_nameservers("unlck.shop", ["ns1.vercel-dns.com", "ns2.vercel-dns.com"], approved=True)
