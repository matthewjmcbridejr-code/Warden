"""Operator Profile Revision protocol for Warden MCP 2.0.

Provides deterministic profile revision hashing so connected clients and agents
do not re-download static operator preferences on every bootstrap.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_profile_revision(profile: dict[str, Any]) -> str:
    """Computes a deterministic hash representing operator profile & preferences.

    Must ONLY change when material profile/preferences change.
    Must NOT change due to timestamps, health checks, or memory updates.
    """
    material_fields = {
        "name": profile.get("name") or "",
        "email": profile.get("email") or "",
        "active_projects": sorted(profile.get("active_projects") or []),
        "current_priorities": sorted(profile.get("current_priorities") or []),
        "preferences": profile.get("preferences") or {},
        "server_context": profile.get("server_context") or {},
    }
    payload = json.dumps(material_fields, sort_keys=True)
    return "prof_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
