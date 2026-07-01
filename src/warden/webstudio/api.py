"""Warden API endpoints for the WebStudio Agent: registry, audits, proof packs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import dns_migration, dns_namecheap, dns_strategy, seo, vercel
from .browser import capture_screenshots, playwright_installed
from .proof import DEFAULT_REPORTS_DIR, ProofPack
from .registry import DEFAULT_REGISTRY_PATH, RegistryError, get_site, load_registry
from .repo import get_git_status, inspect_site_repo
from .workflow import run_build_test_workflow

router = APIRouter(prefix="/webstudio", tags=["webstudio"])


class AuditRequest(BaseModel):
    site_name: str = Field(min_length=1)
    run_build: bool = False
    run_test: bool = False
    check_seo: bool = True
    homepage_relpath: Optional[str] = None


class ProofPackRequest(BaseModel):
    site_name: str = Field(min_length=1)
    task: str = Field(default="")
    include_audit: bool = True


def _load_site(site_name: str):
    try:
        return get_site(site_name, DEFAULT_REGISTRY_PATH)
    except RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sites")
def list_sites() -> dict[str, Any]:
    try:
        sites = load_registry(DEFAULT_REGISTRY_PATH)
    except RegistryError as exc:
        return {"ok": False, "error": str(exc), "sites": []}
    return {"ok": True, "sites": [s.model_dump() for s in sites]}


@router.get("/sites/{site_name}")
def read_site(site_name: str) -> dict[str, Any]:
    site = _load_site(site_name)
    return {"ok": True, "site": site.model_dump(), "inspection": inspect_site_repo(site)}


@router.post("/audit")
def run_audit(payload: AuditRequest) -> dict[str, Any]:
    site = _load_site(payload.site_name)
    repo_path = site.resolved_repo_path()
    result: dict[str, Any] = {
        "ok": True,
        "site": site.name,
        "repo_inspection": inspect_site_repo(site),
    }
    if payload.run_build or payload.run_test:
        workflow = run_build_test_workflow(
            site,
            install=payload.run_build or payload.run_test,
            build=payload.run_build,
            test=payload.run_test,
        )
        result["workflow"] = workflow.to_dict()
    if payload.check_seo:
        seo_result: dict[str, Any] = {}
        if payload.homepage_relpath:
            seo_result = seo.check_homepage_file(repo_path, payload.homepage_relpath)
        site_files = seo.check_site_files(repo_path)
        seo_result["site_files"] = site_files
        seo_result.setdefault("issues", [])
        seo_result["issues"] = list(seo_result.get("issues", [])) + site_files.get("issues", [])
        result["seo"] = seo_result
    result["vercel_installed"] = vercel.vercel_installed()
    result["playwright_installed"] = playwright_installed()
    result["dns_credentials"] = dns_namecheap.env_credentials_status()
    result["dns_plan"] = dns_strategy.plan_for_site(site)
    return result


@router.get("/sites/{site_name}/dns-plan")
def get_dns_plan(site_name: str) -> dict[str, Any]:
    site = _load_site(site_name)
    return {"ok": True, "dns_plan": dns_strategy.plan_for_site(site)}


@router.post("/sites/{site_name}/dns-migration-report")
def generate_dns_migration_report(site_name: str) -> dict[str, Any]:
    """Read-only DNS inventory + production-safe migration report. Never mutates DNS."""
    site = _load_site(site_name)

    nameservers = dns_migration.detect_authoritative_nameservers(site.domain)
    records: list[dns_namecheap.DnsRecord] = []
    inventory_note = None
    if dns_namecheap.credentials_available():
        try:
            records = dns_namecheap.fetch_current_records(site.domain)
        except Exception as exc:
            inventory_note = f"Namecheap record fetch failed: {exc}"
    else:
        inventory_note = "Namecheap credentials unavailable; inventory built from nameserver lookup only. " + " ".join(
            dns_namecheap.setup_instructions()
        )

    inventory = dns_migration.build_inventory(site.domain, records, nameservers=nameservers)
    plan = dns_migration.plan_production_migration(site, inventory)
    if inventory_note:
        plan["inventory_note"] = inventory_note

    report_path = dns_migration.write_migration_report(plan)
    return {"ok": True, "report_path": str(report_path), "plan": plan}


@router.post("/proof-pack")
def generate_proof_pack(payload: ProofPackRequest) -> dict[str, Any]:
    site = _load_site(payload.site_name)
    repo_path = site.resolved_repo_path()
    git_status = get_git_status(repo_path) if repo_path.exists() else None

    pack = ProofPack(
        site_name=site.name,
        domain=site.domain,
        repo_path=str(repo_path),
        branch=git_status.current_branch if git_status else None,
        task=payload.task,
        changed_files=git_status.changed_files if git_status else [],
    )

    if payload.include_audit:
        site_files = seo.check_site_files(repo_path) if repo_path.exists() else {"issues": []}
        pack.seo_checks = {"issues": site_files.get("issues", [])}

    pack.recommended_next_action = (
        "Review changed files and SEO issues above, then run a Vercel preview deploy "
        "for client review before merging to the production branch."
    )
    pack.client_summary = f"Automated WebStudio check for {site.domain} completed."

    report_path = pack.write(DEFAULT_REPORTS_DIR)
    return {"ok": True, "report_path": str(report_path), "markdown": pack.to_markdown()}
