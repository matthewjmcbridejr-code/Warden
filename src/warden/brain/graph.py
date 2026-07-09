"""Build the Warden Brain graph: vault notes + agent memories as a node/edge
graph for the Brain Graph UI.

Deliberately simple edge rules (see module docstring in api layer) — this is
the first pass. No embeddings, no LLM clustering; just tags, project, folder
type, and markdown links already on disk.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from .vault import get_vault_path, scan_sources

FOLDER_TYPE = {
    "00-inbox": "inbox",
    "10-projects": "project",
    "20-people": "person",
    "30-clients": "client",
    "40-systems": "system",
    "50-research": "research",
    "60-daily": "note",
    "90-archive": "inbox",
}

MEMORY_KIND_TYPE = {
    "proof": "proof",
    "decision": "decision",
    "failure": "failure",
    "handoff": "handoff",
}

KNOWN_PROJECT_TAGS = {"warden", "grademy", "marius", "hermes", "fable5"}

GENERIC_TAGS = {
    "watcher", "auto", "warden-brain", "dropzone", "agent_generated",
    "source_manual", "source_obsidian", "source_doc", "source_repo",
    "source_agent_proof", "obsidian-vault",
}

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_MDLINK_RE = re.compile(r"\[[^\]]+\]\(([^)#\s]+\.md)\)")

def _infer_project(tags: list[str], project_id: Optional[str] = None) -> Optional[str]:
    if project_id:
        return project_id
    for t in tags or []:
        low = t.strip().lower()
        if low in KNOWN_PROJECT_TAGS:
            return low
    return None


def _folder_type(path: str) -> str:
    top = path.split("/")[0] if "/" in path else ""
    return FOLDER_TYPE.get(top, "note")


def _add_edge(edges: list[dict], seen: set, source: str, target: str, etype: str, weight: int) -> None:
    if source == target:
        return
    key = tuple(sorted((source, target))) + (etype,)
    if key in seen:
        return
    seen.add(key)
    edges.append({"source": source, "target": target, "type": etype, "weight": weight})

def _vault_nodes(vault_path) -> tuple[list[dict], list]:
    """Return (nodes, sources) for every Markdown file in the vault, skipping
    the auto-generated index/README housekeeping files."""
    sources = scan_sources(vault_path)
    nodes = []
    for src in sources:
        if src.path in ("00-index.md",) or src.path.endswith("/README.md") or src.path == "README.md":
            continue
        ntype = _folder_type(src.path)
        project = _infer_project(src.tags)
        nodes.append({
            "id": f"src:{src.source_id}",
            "label": src.title or Path(src.path).stem,
            "type": ntype,
            "project": project,
            "tags": src.tags,
            "status": "archived" if src.path.startswith("90-archive/") else ("raw" if ntype == "inbox" else "distilled"),
            "size": 10,
            "updated_at": src.indexed_at,
            "path": src.path,
            "_abs_path": src.abs_path,
        })
    return nodes, sources


def _memory_nodes(project_filter_ok=True) -> list[dict]:
    """Return nodes for agent proofs/decisions/failures/handoffs. Other memory
    kinds (user_note, agent_prompt, etc.) are left out of the graph for now —
    they'd dominate the view without adding much signal."""
    try:
        from ..workbench import STORE as WORKBENCH_STORE
    except Exception:
        return []
    nodes = []
    try:
        memories = WORKBENCH_STORE.list_memories()
    except Exception:
        return []
    for m in memories:
        if m.status != "active":
            continue
        ntype = MEMORY_KIND_TYPE.get(m.kind)
        if not ntype:
            continue
        project = _infer_project(m.tags, m.project_id)
        nodes.append({
            "id": f"mem:{m.memory_id}",
            "label": m.title or (m.summary or "")[:60] or m.memory_id,
            "type": ntype,
            "project": project,
            "tags": m.tags or [],
            "status": "actioned",
            "size": 10,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "path": m.source_ref,
        })
    return nodes

def _project_edges(edges: list[dict], seen: set, nodes: list[dict]) -> None:
    by_project: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        if n["project"]:
            by_project[n["project"]].append(n["id"])
    for ids in by_project.values():
        ids = list(dict.fromkeys(ids))
        for i in range(len(ids)):
            for j in range(i + 1, min(i + 6, len(ids))):
                _add_edge(edges, seen, ids[i], ids[j], "project", 2)


def _tag_edges(edges: list[dict], seen: set, nodes: list[dict]) -> None:
    by_tag: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        for t in n["tags"] or []:
            low = t.strip().lower()
            if low and low not in GENERIC_TAGS:
                by_tag[low].append(n["id"])
    for ids in by_tag.values():
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, min(i + 6, len(ids))):
                _add_edge(edges, seen, ids[i], ids[j], "tag", 1)


def _link_edges(edges: list[dict], seen: set, nodes: list[dict], sources: list) -> None:
    """Wikilinks ([[Title]]) and relative Markdown links between vault notes."""
    title_to_id = {n["label"].strip().lower(): n["id"] for n in nodes if n.get("path")}
    node_by_id = {n["id"]: n for n in nodes}
    for src in sources:
        src_id = f"src:{src.source_id}"
        if src_id not in node_by_id or not src.abs_path:
            continue
        try:
            text = Path(src.abs_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _WIKILINK_RE.findall(text):
            target_id = title_to_id.get(match.strip().lower())
            if target_id:
                _add_edge(edges, seen, src_id, target_id, "link", 3)
        for match in _MDLINK_RE.findall(text):
            stem = Path(match).stem.strip().lower()
            target_id = title_to_id.get(stem)
            if target_id:
                _add_edge(edges, seen, src_id, target_id, "link", 3)

def build_graph(vault_path=None) -> dict:
    """Build the full Brain Graph: nodes from vault sources + agent memories,
    edges from shared project, shared tags, and markdown links.

    Read-only — never writes to the vault or the memory store. Safe to call
    on every page load.
    """
    vp = vault_path or get_vault_path()
    vault_nodes, sources = _vault_nodes(vp) if vp.exists() else ([], [])
    memory_nodes = _memory_nodes()
    nodes = vault_nodes + memory_nodes

    edges: list[dict] = []
    seen: set = set()
    _project_edges(edges, seen, nodes)
    _tag_edges(edges, seen, nodes)
    _link_edges(edges, seen, nodes, sources)

    degree = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    for n in nodes:
        n.pop("_abs_path", None)
        base = 14 if n["type"] in ("project", "system") else 10
        n["size"] = min(base + degree.get(n["id"], 0) * 2, 34)

    return {"nodes": nodes, "edges": edges}
