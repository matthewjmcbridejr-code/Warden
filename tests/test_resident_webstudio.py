"""WebStudio routing tests (mocked calls into src/warden/webstudio) and
production-domain guard: unlck.shop sandbox vs. other domains require approval."""
from unittest.mock import MagicMock, patch

import pytest

from src.warden.resident.state import ResidentState
from src.warden.resident.tools import ToolContext, tool_webstudio_audit, tool_webstudio_dns_change, tool_webstudio_dns_watch


@pytest.fixture
def ctx(tmp_path):
    state = ResidentState(str(tmp_path / "resident.sqlite"))
    return ToolContext(state)


def test_sandbox_domain_dns_change_does_not_require_approval_block(ctx):
    result = tool_webstudio_dns_change(ctx, "unlck.shop", "test change")
    assert result["ok"] is True
    assert "sandbox" in result["short_summary"].lower()


def test_production_domain_dns_change_requires_approval(ctx):
    result = tool_webstudio_dns_change(ctx, "example.com", "nameserver switch")
    assert result["ok"] is False
    assert "production domain" in result["short_summary"].lower()
    approvals = ctx.approvals.list()
    assert len(approvals) == 1
    assert approvals[0].risk_level == "high"


def test_production_domain_dns_watch_requires_approval(ctx):
    result = tool_webstudio_dns_watch(ctx, "example.com")
    assert result["ok"] is False
    assert "requires approval" in result["short_summary"].lower() or "production domain" in result["short_summary"].lower()


def test_sandbox_domain_dns_watch_allowed(ctx):
    result = tool_webstudio_dns_watch(ctx, "unlck.shop")
    assert result["ok"] is True
    assert "watching" in result["short_summary"].lower()


def test_webstudio_audit_mocked_site(ctx):
    fake_site = MagicMock()
    fake_site.domain = "unlck.shop"
    fake_site.resolved_repo_path.return_value = "/tmp/nonexistent"

    with patch("src.warden.webstudio.registry.get_site", return_value=fake_site), \
         patch("src.warden.webstudio.seo.check_site_files", return_value={"issues": ["missing robots.txt"]}):
        result = tool_webstudio_audit(ctx, "unlck")
    assert result["ok"] is True
    assert result["key_fields"]["issues"] == 1


def test_webstudio_audit_unknown_site(ctx):
    from src.warden.webstudio.registry import RegistryError
    with patch("src.warden.webstudio.registry.get_site", side_effect=RegistryError("no such site")):
        result = tool_webstudio_audit(ctx, "ghost-site")
    assert result["ok"] is False
    assert "unknown site" in result["short_summary"].lower()


def test_webstudio_unavailable_handled_gracefully(ctx):
    with patch("src.warden.webstudio.registry.get_site", side_effect=ImportError("no module")):
        result = tool_webstudio_audit(ctx, "any")
    assert result["ok"] is False
