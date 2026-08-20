"""Real Playwright browser executor for Gemini Computer Use visual actions."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page

from ..models import ComputerAction, ComputerObservation, ActionType
from .base import BaseComputerExecutor

logger = logging.getLogger(__name__)


class PlaywrightBrowserExecutor(BaseComputerExecutor):
    """Executes visual Computer Use actions inside a real Playwright-managed Chromium browser."""

    def __init__(
        self,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        headless: Optional[bool] = None,
        slow_mo_ms: int = 100,
    ):
        self.width = viewport_width
        self.height = viewport_height
        if headless is None:
            # Check environment variable WARDEN_COMPUTER_HEADLESS (default True)
            self.headless = os.environ.get("WARDEN_COMPUTER_HEADLESS", "1").lower() not in ("0", "false", "no")
        else:
            self.headless = headless
        self.slow_mo = slow_mo_ms

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def start(self, initial_url: str | None = None) -> None:
        if self._playwright is not None:
            return

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        self._context = self._browser.new_context(
            viewport={"width": self.width, "height": self.height},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        self._page = self._context.new_page()

        if initial_url:
            try:
                self._page.goto(initial_url, timeout=30000, wait_until="domcontentloaded")
                self._page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning("Initial navigation error to %s: %s", initial_url, exc)

    def stop(self) -> None:
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.warning("Error stopping Playwright browser executor: %s", exc)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def is_active(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    def get_dimensions(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def capture_screenshot(self) -> ComputerObservation:
        if not self.is_active():
            raise RuntimeError("Playwright executor is not running")

        # Settle page briefly
        self._page.wait_for_timeout(200)

        # Capture high-quality JPEG for low-latency multimodal transfer
        screenshot_bytes = self._page.screenshot(type="jpeg", quality=85)
        current_url = self._page.url
        title = self._page.title()

        return ComputerObservation(
            screenshot_bytes=screenshot_bytes,
            width=self.width,
            height=self.height,
            url=current_url,
            title=title,
            status_text=f"Page: {title} ({current_url})"
        )

    def execute_action(self, action: ComputerAction) -> ComputerObservation:
        if not self.is_active():
            raise RuntimeError("Playwright executor is not running")

        act_type = action.action_type
        if isinstance(act_type, str):
            act_type = ActionType(act_type)

        try:
            if act_type == ActionType.NAVIGATE:
                target_url = action.url or (action.raw_args.get("url") if action.raw_args else None)
                if target_url:
                    if not target_url.startswith(("http://", "https://", "file://", "about:")):
                        target_url = f"https://{target_url}"
                    self._page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                    self._page.wait_for_timeout(1000)

            elif act_type == ActionType.CLICK:
                x = action.x if action.x is not None else int(action.raw_args.get("x", 0))
                y = action.y if action.y is not None else int(action.raw_args.get("y", 0))
                self._page.mouse.click(x, y)
                self._page.wait_for_timeout(500)

            elif act_type == ActionType.DOUBLE_CLICK:
                x = action.x if action.x is not None else int(action.raw_args.get("x", 0))
                y = action.y if action.y is not None else int(action.raw_args.get("y", 0))
                self._page.mouse.dblclick(x, y)
                self._page.wait_for_timeout(500)

            elif act_type == ActionType.RIGHT_CLICK:
                x = action.x if action.x is not None else int(action.raw_args.get("x", 0))
                y = action.y if action.y is not None else int(action.raw_args.get("y", 0))
                self._page.mouse.click(x, y, button="right")
                self._page.wait_for_timeout(500)

            elif act_type == ActionType.TYPE:
                text = action.text or (action.raw_args.get("text", "") if action.raw_args else "")
                press_enter = bool(action.raw_args.get("press_enter", False)) if action.raw_args else False
                x = action.x if action.x is not None else (action.raw_args.get("x") if action.raw_args else None)
                y = action.y if action.y is not None else (action.raw_args.get("y") if action.raw_args else None)
                if x is not None and y is not None:
                    self._page.mouse.click(int(x), int(y))
                    self._page.wait_for_timeout(200)
                self._page.keyboard.type(text, delay=20)
                if press_enter:
                    self._page.keyboard.press("Enter")
                self._page.wait_for_timeout(500)

            elif act_type in (ActionType.KEY_PRESS, ActionType.HOTKEY):
                key = action.key or (action.raw_args.get("key", "") if action.raw_args else "")
                if key:
                    self._page.keyboard.press(key)
                self._page.wait_for_timeout(300)

            elif act_type == ActionType.SCROLL:
                delta_y = action.delta_y if action.delta_y is not None else int(action.raw_args.get("delta_y", 0))
                delta_x = action.delta_x if action.delta_x is not None else int(action.raw_args.get("delta_x", 0))
                self._page.mouse.wheel(delta_x, delta_y)
                self._page.wait_for_timeout(500)

            elif act_type == ActionType.WAIT:
                sec = action.seconds if action.seconds is not None else float(action.raw_args.get("seconds", 1.0))
                self._page.wait_for_timeout(int(sec * 1000))

            elif act_type in (ActionType.SCREENSHOT, ActionType.COMPLETE, ActionType.FAIL):
                # No mutation needed
                pass

        except Exception as exc:
            logger.warning("Action execution error (%s): %s", act_type, exc)

        return self.capture_screenshot()
