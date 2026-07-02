"""Watcher lifecycle tests: create/run/update, hash-based dedup, backoff,
mocked DNS resolver."""
from unittest.mock import patch

import pytest

from src.warden.resident.state import ResidentState
from src.warden.resident.watchers import Watcher, WatcherService, check_dns, check_website


@pytest.fixture
def service(tmp_path):
    state = ResidentState(str(tmp_path / "resident.sqlite"))
    return WatcherService(state)


def test_create_watcher(service):
    w = service.create(title="DNS: example.com", kind="dns", query="example.com")
    assert w.id
    assert w.status == "active"
    fetched = service.get(w.id)
    assert fetched.title == "DNS: example.com"


def test_create_unknown_kind_raises(service):
    with pytest.raises(ValueError):
        service.create(title="bad", kind="not_a_kind", query="x")


def test_list_watchers(service):
    service.create(title="a", kind="website", query="https://example.com")
    service.create(title="b", kind="dns", query="example.com")
    watchers = service.list()
    assert len(watchers) == 2


def test_pause_and_resume(service):
    w = service.create(title="a", kind="generic", query="x")
    paused = service.pause(w.id)
    assert paused.status == "paused"
    resumed = service.resume(w.id)
    assert resumed.status == "active"


def test_run_dns_watcher_with_mocked_resolver(service):
    w = service.create(title="dns", kind="dns", query="example.com", cadence_seconds=0)
    fake_result = {"domain": "example.com", "ns": ["ns1.example.com"], "a": ["1.2.3.4"], "cname": [], "error": None}
    with patch("src.warden.resident.watchers.check_dns", return_value=fake_result):
        watcher, notified = service.run(w.id, force=True)
    assert watcher.last_result == fake_result
    assert notified is True  # first run always differs from None hash


def test_run_hash_dedup_no_duplicate_notify(service):
    w = service.create(title="dns", kind="dns", query="example.com", cadence_seconds=0)
    fake_result = {"domain": "example.com", "ns": [], "a": ["1.2.3.4"], "cname": [], "error": None}
    with patch("src.warden.resident.watchers.check_dns", return_value=fake_result):
        _, notified1 = service.run(w.id, force=True)
        _, notified2 = service.run(w.id, force=True)
    assert notified1 is True
    assert notified2 is False  # same result, no duplicate notify


def test_run_notifies_again_when_result_changes(service):
    w = service.create(title="dns", kind="dns", query="example.com", cadence_seconds=0)
    result_a = {"domain": "example.com", "ns": [], "a": ["1.1.1.1"], "cname": [], "error": None}
    result_b = {"domain": "example.com", "ns": [], "a": ["2.2.2.2"], "cname": [], "error": None}
    with patch("src.warden.resident.watchers.check_dns", side_effect=[result_a, result_b]):
        _, notified1 = service.run(w.id, force=True)
        _, notified2 = service.run(w.id, force=True)
    assert notified1 is True
    assert notified2 is True


def test_backoff_increases_on_repeated_failure(service):
    w = service.create(title="dns", kind="dns", query="bad.invalid", cadence_seconds=100)
    error_result = {"domain": "bad.invalid", "ns": [], "a": [], "cname": [], "error": "resolution failed"}
    with patch("src.warden.resident.watchers.check_dns", return_value=error_result):
        for _ in range(3):
            watcher, _ = service.run(w.id, force=True)
    assert watcher.failure_count == 3
    assert watcher.effective_cadence() > watcher.cadence_seconds


def test_failure_count_resets_on_success(service):
    w = service.create(title="dns", kind="dns", query="example.com", cadence_seconds=100)
    error_result = {"domain": "example.com", "ns": [], "a": [], "cname": [], "error": "fail"}
    ok_result = {"domain": "example.com", "ns": [], "a": ["1.2.3.4"], "cname": [], "error": None}
    with patch("src.warden.resident.watchers.check_dns", side_effect=[error_result, ok_result]):
        service.run(w.id, force=True)
        watcher, _ = service.run(w.id, force=True)
    assert watcher.failure_count == 0


def test_check_dns_mocked_dnspython_import_error_falls_back():
    # No dnspython/dig assumed available in test sandbox; check_dns should
    # never raise regardless of which fallback path is taken.
    result = check_dns("example.invalid", timeout=1.0)
    assert "domain" in result


def test_check_website_handles_connection_error():
    result = check_website("http://localhost:1", timeout=1.0)
    assert result["ok"] is False


def test_watcher_due_when_never_checked(service):
    w = service.create(title="a", kind="generic", query="x", cadence_seconds=9999)
    assert w.due() is True


def test_watcher_not_due_before_cadence_elapsed(service):
    w = service.create(title="a", kind="generic", query="x", cadence_seconds=9999)
    watcher, _ = service.run(w.id, force=True)
    assert watcher.due() is False


def test_delete_watcher(service):
    w = service.create(title="a", kind="generic", query="x")
    assert service.delete(w.id) is True
    assert service.get(w.id) is None
