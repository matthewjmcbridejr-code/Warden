"""Root conftest.py — adds repo root to sys.path for all tests."""
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ollama_reachable() -> bool:
    """True if a local Ollama server is answering. Real network check, not a
    guess — tests marked requires_ollama actually exercise live model
    resolution, so a live server is the only honest way to know."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


def _codex_cli_available() -> bool:
    return shutil.which("codex") is not None


def _google_search_package_available() -> bool:
    try:
        import google.cloud.discoveryengine_v1  # noqa: F401
        return True
    except Exception:
        return False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_ollama: needs a live local Ollama server (skipped automatically when unreachable)",
    )
    config.addinivalue_line(
        "markers",
        "requires_codex_cli: needs the codex CLI binary on PATH (skipped automatically when absent)",
    )
    config.addinivalue_line(
        "markers",
        "requires_google_search: needs the optional google-cloud-discoveryengine package (skipped automatically when not installed)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    ollama_ok = _ollama_reachable()
    codex_ok = _codex_cli_available()
    google_ok = _google_search_package_available()

    skip_ollama = pytest.mark.skip(reason="requires a live local Ollama server, not reachable at http://localhost:11434")
    skip_codex = pytest.mark.skip(reason="requires the codex CLI binary on PATH, not found")
    skip_google = pytest.mark.skip(reason="requires the optional google-cloud-discoveryengine package, not installed")

    for item in items:
        if not ollama_ok and "requires_ollama" in item.keywords:
            item.add_marker(skip_ollama)
        if not codex_ok and "requires_codex_cli" in item.keywords:
            item.add_marker(skip_codex)
        if not google_ok and "requires_google_search" in item.keywords:
            item.add_marker(skip_google)
