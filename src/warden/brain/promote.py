"""Deterministic inbox triage: dedupe + promote captured notes into vault folders.

No LLM organizer here on purpose (see docs/warden_personal_ai_os_plan.md —
that's a later phase). This is pass 1: hash-based dedupe, then tag-based
routing with a fixed rule table. Anything that doesn't match a rule is left
in 00-inbox and reported as unclassified rather than guessed at.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from .ingest import _frontmatter_field, compute_content_hash
from .index import reindex_sources
from .vault import get_vault_path, scan_sources

log = logging.getLogger(__name__)

INBOX_FOLDER = "00-inbox"
ARCHIVE_DUPLICATES = "90-archive/duplicates"

# First matching tag wins. Order matters — most specific first.
ROUTE_RULES: list[tuple[str, str]] = [
    ("person", "20-people"),
    ("profile", "20-people"),
    ("client", "30-clients"),
    ("system", "40-systems"),
    ("architecture", "40-systems"),
    ("daily", "60-daily"),
    ("warden", "10-projects"),
    ("grademy", "10-projects"),
    ("marius", "10-projects"),
    ("hermes", "10-projects"),
    ("fable5", "10-projects"),
    ("project", "10-projects"),
    ("research", "50-research"),
    ("article", "50-research"),
    ("paper", "50-research"),
    ("watcher", "50-research"),
    ("webpage", "50-research"),
    ("youtube", "50-research"),
    ("video", "50-research"),
]


def _route_for_tags(tags: list[str]) -> Optional[str]:
    tagset = {t.lower() for t in tags}
    for tag, folder in ROUTE_RULES:
        if tag in tagset:
            return folder
    return None


def _read_tags(text: str) -> list[str]:
    raw = _frontmatter_field(text, "tags")
    if not raw:
        return []
    return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]

def _content_hash_for(text: str) -> str:
    existing = _frontmatter_field(text, "content_hash")
    if existing:
        return existing
    # Fall back to hashing the body under the frontmatter block, so notes
    # written before content_hash existed can still be deduped.
    if text.startswith("---"):
        end = text.find("\n---", 3)
        body = text[end + 4:] if end != -1 else text
    else:
        body = text
    return compute_content_hash(body)


def promote_inbox(
    *,
    vault_path=None,
    index_path=None,
    dry_run: bool = False,
) -> dict:
    """Deterministically dedupe and file 00-inbox notes into vault folders.

    Pass 1: hash every inbox file's content; first occurrence of a hash is
    kept, later ones are duplicates and get archived (never deleted).
    Pass 2: kept files are routed to a destination folder by tag (see
    ROUTE_RULES). No matching tag -> left in 00-inbox, reported as
    unclassified rather than guessed at.
    """
    vp = vault_path or get_vault_path()
    inbox = vp / INBOX_FOLDER
    if not inbox.exists():
        return {"ok": True, "scanned": 0, "promoted": [], "duplicates": [], "unclassified": []}

    files = sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix == ".md" and p.name != "README.md"
    )

    seen_hashes: dict[str, Path] = {}
    duplicates: list[dict] = []
    promote_candidates: list[tuple[Path, list[str]]] = []

    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            log.warning("Could not read %s: %s", p, exc)
            continue
        chash = _content_hash_for(text)
        if chash in seen_hashes:
            duplicates.append({
                "path": p.relative_to(vp).as_posix(),
                "duplicate_of": seen_hashes[chash].relative_to(vp).as_posix(),
            })
            if not dry_run:
                dest_dir = vp / ARCHIVE_DUPLICATES
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / p.name
                if not dest.exists():
                    shutil.move(str(p), str(dest))
            continue
        seen_hashes[chash] = p
        promote_candidates.append((p, _read_tags(text)))

    promoted: list[dict] = []
    unclassified: list[dict] = []

    for p, tags in promote_candidates:
        folder = _route_for_tags(tags)
        if folder is None:
            unclassified.append({"path": p.relative_to(vp).as_posix(), "tags": tags})
            continue
        dest_dir = vp / folder
        if dry_run:
            promoted.append({"from": p.relative_to(vp).as_posix(), "to": f"{folder}/{p.name}", "tags": tags})
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if dest.exists():
            # Never overwrite — leave the inbox copy and report the clash.
            unclassified.append({
                "path": p.relative_to(vp).as_posix(),
                "tags": tags,
                "reason": f"destination exists: {dest.relative_to(vp).as_posix()}",
            })
            continue
        shutil.move(str(p), str(dest))
        promoted.append({
            "from": p.relative_to(vp).as_posix(),
            "to": dest.relative_to(vp).as_posix(),
            "tags": tags,
        })

    result = {
        "ok": True,
        "dry_run": dry_run,
        "scanned": len(files),
        "promoted": promoted,
        "duplicates": duplicates,
        "unclassified": unclassified,
    }

    if not dry_run and (promoted or duplicates):
        sources = scan_sources(vp)
        reindex_sources(sources, index_path=index_path)

    return result
