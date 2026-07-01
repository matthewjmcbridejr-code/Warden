"""Playwright-backed browser verification: screenshots + console error checks.

Skips gracefully (returns a structured "unavailable" result) when Playwright
is not installed, so the rest of the test suite never depends on it.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


@dataclass
class BrowserCheckResult:
    url: str
    available: bool
    desktop_screenshot: Optional[str] = None
    mobile_screenshot: Optional[str] = None
    console_errors: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "available": self.available,
            "desktop_screenshot": self.desktop_screenshot,
            "mobile_screenshot": self.mobile_screenshot,
            "console_errors": self.console_errors,
            "error": self.error,
        }


def capture_screenshots(url: str, output_dir: Path) -> BrowserCheckResult:
    """Open `url` and capture desktop + mobile screenshots plus console errors.

    Returns available=False with an explanatory error if Playwright is not
    installed or the page cannot be reached — never raises.
    """
    if not playwright_installed():
        return BrowserCheckResult(
            url=url,
            available=False,
            error="playwright is not installed; run `pip install playwright && playwright install chromium`",
        )

    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    desktop_path = output_dir / "desktop.png"
    mobile_path = output_dir / "mobile.png"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for viewport, path in ((DESKTOP_VIEWPORT, desktop_path), (MOBILE_VIEWPORT, mobile_path)):
                    page = browser.new_page(viewport=viewport)
                    page.on(
                        "console",
                        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                    )
                    page.goto(url, wait_until="networkidle", timeout=20_000)
                    page.screenshot(path=str(path), full_page=True)
                    page.close()
            finally:
                browser.close()
    except Exception as exc:  # pragma: no cover - depends on live browser/network
        return BrowserCheckResult(url=url, available=False, error=str(exc))

    return BrowserCheckResult(
        url=url,
        available=True,
        desktop_screenshot=str(desktop_path),
        mobile_screenshot=str(mobile_path),
        console_errors=console_errors,
    )
