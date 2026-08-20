"""Screenshot persistence, dimension inspection, and sanitization for Computer Use."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = REPO_ROOT / "_mctable" / "computer" / "screenshots"


def save_screenshot(
    screenshot_bytes: bytes,
    session_id: str,
    step_index: int
) -> str:
    """Persist screenshot bytes to disk and return the relative or absolute path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{session_id}_step_{step_index:03d}.jpg"
    target_path = SCREENSHOT_DIR / filename
    target_path.write_bytes(screenshot_bytes)
    return str(target_path)


def encode_screenshot_base64(screenshot_bytes: bytes) -> str:
    """Encode screenshot bytes to base64 string for multimodal API payloads."""
    return base64.b64encode(screenshot_bytes).decode("utf-8")
