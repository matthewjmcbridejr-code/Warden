"""Canonical filesystem locations for Warden.

Resolution order for the data root (plans, memory, board, secrets):
1. WARDEN_DATA_ROOT / MCHARNESS_DATA_ROOT env var — explicit override
2. ./_mctable if it already exists — long-running installs that predate
   the home-directory default keep their data exactly where it is
3. ~/.warden/data — the default for fresh installs, independent of cwd
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    env = os.getenv("WARDEN_DATA_ROOT") or os.getenv("MCHARNESS_DATA_ROOT")
    if env:
        return Path(env).expanduser()
    legacy = Path("_mctable")
    if legacy.exists():
        return legacy
    return Path.home() / ".warden" / "data"
