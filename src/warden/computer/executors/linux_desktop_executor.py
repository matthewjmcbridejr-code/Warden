"""Linux OS / X11 visual executor stub for Phase 2 desktop Computer Use."""

from __future__ import annotations

import logging
from typing import Tuple
from ..models import ComputerAction, ComputerObservation
from .base import BaseComputerExecutor

logger = logging.getLogger(__name__)


class LinuxDesktopExecutor(BaseComputerExecutor):
    """Visual executor for native Linux X11 applications."""

    def __init__(self, display_width: int = 1920, display_height: int = 1080):
        self.width = display_width
        self.height = display_height
        self._running = False

    def start(self, initial_url: str | None = None) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_active(self) -> bool:
        return self._running

    def get_dimensions(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def capture_screenshot(self) -> ComputerObservation:
        return ComputerObservation(
            screenshot_bytes=b"",
            width=self.width,
            height=self.height,
            title="Linux Desktop",
            status_text="Linux desktop display active"
        )

    def execute_action(self, action: ComputerAction) -> ComputerObservation:
        logger.info("LinuxDesktopExecutor action: %s", action.summary)
        return self.capture_screenshot()
