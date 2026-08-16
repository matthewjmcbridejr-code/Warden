"""Global pytest isolation for Warden's on-disk runtime state.

Several Warden modules bind their data-root constants at import time.  Set a
throwaway root before test modules import any of those modules so a test can
never inherit the live ``_mctable`` directory by accident.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile


PYTEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="warden-pytest-"))
os.environ["MCHARNESS_DATA_ROOT"] = str(PYTEST_DATA_ROOT)
os.environ["WARDEN_DATA_ROOT"] = str(PYTEST_DATA_ROOT)


def pytest_ignore_collect(collection_path, config):  # noqa: ANN001, ARG001
    """Keep live browser tests out of the default suite.

    The e2e tests connect to the operator's running service on port 6969 and
    can create plans, dispatches, and memories.  Requiring an explicit opt-in
    prevents a normal ``pytest`` run from mutating production state.
    """

    try:
        relative = Path(str(collection_path)).resolve().relative_to(Path(__file__).parent.resolve())
    except ValueError:
        return False
    is_live_browser_test = bool(relative.parts and relative.parts[0] in {"e2e", "browser"})
    return is_live_browser_test and os.getenv("WARDEN_RUN_LIVE_E2E") != "1"


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Remove only the explicit temporary root created by this test session."""

    shutil.rmtree(PYTEST_DATA_ROOT, ignore_errors=True)
