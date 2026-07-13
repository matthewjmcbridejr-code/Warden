from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BRANDING_PATH = _ROOT / "branding.json"
_DEFAULTS = {
    "product_name": "Warden",
    "repo_name": "warden",
    "public_url": "",
    "tagline": "Local-first control room for supervised AI coding agents.",
    "category": "AI agent control room",
}


def _load_branding() -> dict[str, str]:
    try:
        data = json.loads(_BRANDING_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("branding.json must contain an object")
    except Exception:
        data = {}
    merged = {**_DEFAULTS, **{k: str(v) for k, v in data.items() if v is not None}}
    return merged


_BRANDING = _load_branding()

PRODUCT_NAME = _BRANDING["product_name"]
REPO_NAME = _BRANDING["repo_name"]
PUBLIC_URL = _BRANDING["public_url"]
TAGLINE = _BRANDING["tagline"]
CATEGORY = _BRANDING["category"]
