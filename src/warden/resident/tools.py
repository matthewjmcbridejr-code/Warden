"""Tool registry: functions callable by the router.

Each tool returns a bounded dict shape:
  {ok, short_summary, key_fields, artifact_path (optional), raw (optional)}

`raw` is only included when the caller explicitly wants full detail (kept
small already, but callers should generally rely on short_summary/key_fields
for Telegram replies and reach for `raw`/artifact_path only for "more").
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import config as config_mod
from .approvals import ApprovalQueue
from .email_adapter import EmailAdapter
from .memory import MemoryAdapter
from .warden_client import WardenClient
from .watchers import WatcherService

ARTIFACT_DIR = Path("_mctable/resident/artifacts")


def _write_artifact(name: str, content: str) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / name
    path.write_text(content)
    return str(path)


class ToolContext:
    """Bundles the adapters a tool needs. Built once per resident agent."""

    def __init__(self, state, cfg: Optional[config_mod.ResidentConfig] = None) -> None:
        self.state = state
        self.cfg = cfg or config_mod.load_config()
        self.memory = MemoryAdapter()
        self.watchers = WatcherService(state)
        self.email = EmailAdapter(self.cfg)
        self.warden = WardenClient()
        self.approvals = ApprovalQueue(state)


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------

def tool_memory_search(ctx: ToolContext, query: str, limit: int = 5) -> dict:
    results = ctx.memory.search(query, limit=limit)
    if not results:
        return {"ok": True, "short_summary": f"No memory found for {query!r}.", "key_fields": {"count": 0}}
    lines = [f"[{r.kind}] {r.summary}" for r in results]
    return {
        "ok": True,
        "short_summary": "\n".join(lines),
        "key_fields": {"count": len(results)},
        "raw": [r.to_dict() for r in results],
    }


def tool_memory_recent(ctx: ToolContext, limit: int = 5) -> dict:
    results = ctx.memory.recent(limit=limit)
    if not results:
        return {"ok": True, "short_summary": "No recent memory activity.", "key_fields": {"count": 0}}
    lines = [f"[{r.kind}] {r.summary}" for r in results]
    return {"ok": True, "short_summary": "\n".join(lines), "key_fields": {"count": len(results)},
            "raw": [r.to_dict() for r in results]}


def tool_memory_remember(ctx: ToolContext, note: str) -> dict:
    result = ctx.memory.remember(note)
    ok = result.kind != "note_failed"
    return {
        "ok": ok,
        "short_summary": "Saved to memory." if ok else "Could not save to memory (store unavailable).",
        "key_fields": {"source_id": result.source_id},
    }


# ---------------------------------------------------------------------------
# Watcher tools
# ---------------------------------------------------------------------------

def tool_watcher_create(ctx: ToolContext, title: str, kind: str, query: str, cadence_seconds: int = 3600) -> dict:
    watcher = ctx.watchers.create(title=title, kind=kind, query=query, cadence_seconds=cadence_seconds)
    return {
        "ok": True,
        "short_summary": f"Created {kind} watcher '{title}' (id={watcher.id}).",
        "key_fields": {"watcher_id": watcher.id, "kind": kind},
    }


def tool_watcher_list(ctx: ToolContext) -> dict:
    watchers = ctx.watchers.list()
    if not watchers:
        return {"ok": True, "short_summary": "No watchers configured.", "key_fields": {"count": 0}}
    lines = [f"[{w.status}] {w.title} ({w.kind}) — last: {w.last_checked_at or 'never'}" for w in watchers]
    return {"ok": True, "short_summary": "\n".join(lines), "key_fields": {"count": len(watchers)},
            "raw": [w.to_dict() for w in watchers]}


def tool_watcher_run_due(ctx: ToolContext) -> dict:
    results = ctx.watchers.run_due()
    notified = [w for w, n in results if n]
    return {
        "ok": True,
        "short_summary": f"Ran {len(results)} due watcher(s); {len(notified)} changed.",
        "key_fields": {"ran": len(results), "notified": len(notified)},
        "raw": [{"title": w.title, "notify": n, "result": w.last_result} for w, n in results],
    }


# ---------------------------------------------------------------------------
# Email tools
# ---------------------------------------------------------------------------

def tool_email_summary(ctx: ToolContext, limit: int = 10) -> dict:
    return ctx.email.summarize(limit=limit)


def tool_email_urgent(ctx: ToolContext, limit: int = 10) -> dict:
    return ctx.email.find_urgent(limit=limit)


def tool_email_search(ctx: ToolContext, query: str, limit: int = 10) -> dict:
    return ctx.email.search(query, limit=limit)


def tool_email_draft(ctx: ToolContext, to: str, subject: str, body: str) -> dict:
    draft = ctx.email.draft(to, subject, body)
    return {
        "ok": draft.ok,
        "short_summary": f"Draft ready to {to}: {subject!r} (id={draft.draft_id}). Not sent.",
        "key_fields": {"draft_id": draft.draft_id, "to": to},
    }


def tool_email_send(ctx: ToolContext, to: str, subject: str, body: str) -> dict:
    """Send always requires a prior approval — creates one if none exists yet."""
    approval = ctx.approvals.create(
        source="email_adapter",
        action_type="email_send",
        summary=f"Send email to {to}: {subject!r}",
        risk_level="medium",
        payload={"to": to, "subject": subject, "body": body[:500]},
    )
    return {
        "ok": False,
        "short_summary": f"Send requires approval. Created approval {approval.approval_id} — "
                          f"use /approve {approval.approval_id} to allow.",
        "key_fields": {"approval_id": approval.approval_id},
    }


# ---------------------------------------------------------------------------
# Warden agent/session tools
# ---------------------------------------------------------------------------

def tool_agents_list(ctx: ToolContext) -> dict:
    return ctx.warden.list_agents()


def tool_sessions_list(ctx: ToolContext) -> dict:
    return ctx.warden.list_sessions()


def tool_session_stop(ctx: ToolContext, session_match: str) -> dict:
    return ctx.warden.stop_session(session_match)


def tool_status(ctx: ToolContext) -> dict:
    return ctx.warden.status()


# ---------------------------------------------------------------------------
# Approval tools
# ---------------------------------------------------------------------------

def tool_approvals_list(ctx: ToolContext) -> dict:
    approvals = ctx.approvals.list(status="pending")
    if not approvals:
        return {"ok": True, "short_summary": "No pending approvals.", "key_fields": {"count": 0}}
    lines = [f"{a.approval_id}: {a.action_type} — {a.summary} ({a.risk_level})" for a in approvals]
    return {"ok": True, "short_summary": "\n".join(lines), "key_fields": {"count": len(approvals)},
            "raw": [a.to_dict() for a in approvals]}


def tool_approve(ctx: ToolContext, approval_id: str) -> dict:
    approval = ctx.approvals.approve(approval_id)
    if approval is None:
        return {"ok": False, "short_summary": f"No approval {approval_id!r} found.", "key_fields": {}}
    return {"ok": True, "short_summary": f"Approval {approval_id} -> {approval.status}.",
            "key_fields": {"status": approval.status}}


def tool_deny(ctx: ToolContext, approval_id: str) -> dict:
    approval = ctx.approvals.deny(approval_id)
    if approval is None:
        return {"ok": False, "short_summary": f"No approval {approval_id!r} found.", "key_fields": {}}
    return {"ok": True, "short_summary": f"Approval {approval_id} -> {approval.status}.",
            "key_fields": {"status": approval.status}}


# ---------------------------------------------------------------------------
# WebStudio tools (wrap, don't reimplement)
# ---------------------------------------------------------------------------

def tool_webstudio_audit(ctx: ToolContext, site_name: str) -> dict:
    """Run a bounded SEO/site-readiness audit for a registered WebStudio site."""
    try:
        from ..webstudio.registry import get_site, RegistryError
        from ..webstudio import seo as webstudio_seo
    except Exception as exc:
        return {"ok": False, "short_summary": f"WebStudio unavailable: {exc}", "key_fields": {}}
    try:
        site = get_site(site_name)
    except RegistryError as exc:
        return {"ok": False, "short_summary": f"Unknown site {site_name!r}: {exc}", "key_fields": {}}
    except Exception as exc:
        return {"ok": False, "short_summary": f"WebStudio unavailable: {exc}", "key_fields": {}}

    file_check = webstudio_seo.check_site_files(site.resolved_repo_path())
    issues = list(file_check.get("issues", []))
    return {
        "ok": True,
        "short_summary": f"Audit for {site_name}: {len(issues)} issue(s) found." if issues
        else f"Audit for {site_name}: no file-presence issues found.",
        "key_fields": {"domain": site.domain, "issues": len(issues)},
        "raw": file_check,
    }


def tool_webstudio_dns_watch(ctx: ToolContext, domain: str) -> dict:
    """Create a DNS watcher for a domain — production domain guard applies."""
    guard = _production_domain_guard(ctx, domain, action_type="dns_change",
                                      summary=f"Create DNS watcher for {domain}")
    if guard is not None:
        return guard
    watcher = ctx.watchers.create(title=f"DNS: {domain}", kind="dns", query=domain, cadence_seconds=1800)
    return {"ok": True, "short_summary": f"Watching DNS for {domain} (id={watcher.id}).",
            "key_fields": {"watcher_id": watcher.id}}


def tool_webstudio_dns_change(ctx: ToolContext, domain: str, change_summary: str) -> dict:
    """Any DNS/deploy change for a non-sandbox domain must go through approval."""
    guard = _production_domain_guard(ctx, domain, action_type="dns_change", summary=change_summary)
    if guard is not None:
        return guard
    # unlck.shop sandbox: still requires an approval record for audit trail,
    # but flagged low risk since it's disposable.
    approval = ctx.approvals.create(
        source="webstudio", action_type="dns_change", summary=change_summary,
        risk_level="low", payload={"domain": domain},
    )
    return {
        "ok": True,
        "short_summary": f"Sandbox domain {domain} — approval {approval.approval_id} created (low risk).",
        "key_fields": {"approval_id": approval.approval_id},
    }


def _production_domain_guard(ctx: ToolContext, domain: str, *, action_type: str, summary: str) -> Optional[dict]:
    if config_mod.is_sandbox_domain(domain):
        return None
    approval = ctx.approvals.create(
        source="webstudio", action_type=action_type, summary=summary,
        risk_level="high", payload={"domain": domain},
    )
    return {
        "ok": False,
        "short_summary": f"{domain} is a production domain — requires approval. "
                          f"Created approval {approval.approval_id}. See dns_migration workflow for full audit.",
        "key_fields": {"approval_id": approval.approval_id, "domain": domain},
    }


TOOL_REGISTRY: dict[str, Any] = {
    "memory_search": tool_memory_search,
    "memory_recent": tool_memory_recent,
    "memory_remember": tool_memory_remember,
    "watcher_create": tool_watcher_create,
    "watcher_list": tool_watcher_list,
    "watcher_run_due": tool_watcher_run_due,
    "email_summary": tool_email_summary,
    "email_urgent": tool_email_urgent,
    "email_search": tool_email_search,
    "email_draft": tool_email_draft,
    "email_send": tool_email_send,
    "agents_list": tool_agents_list,
    "sessions_list": tool_sessions_list,
    "session_stop": tool_session_stop,
    "status": tool_status,
    "approvals_list": tool_approvals_list,
    "approve": tool_approve,
    "deny": tool_deny,
    "webstudio_audit": tool_webstudio_audit,
    "webstudio_dns_watch": tool_webstudio_dns_watch,
    "webstudio_dns_change": tool_webstudio_dns_change,
}
