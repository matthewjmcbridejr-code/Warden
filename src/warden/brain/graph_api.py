"""Read-only Brain Graph endpoint — powers the Brain Graph UI view.

GET /api/brain/graph -> { nodes: [...], edges: [...] }

Nodes come from indexed vault sources (src.warden.brain.vault.scan_sources)
plus agent proof/decision/failure/handoff memories (WorkbenchStore). Edges
are same-project, shared-tag, and markdown-link based — see graph.py.
"""
from __future__ import annotations

from fastapi import APIRouter

from .graph import build_graph

router = APIRouter(prefix="/api/brain", tags=["brain-graph"])


@router.get("/graph")
def get_brain_graph():
    return build_graph()
