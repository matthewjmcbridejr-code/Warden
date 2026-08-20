"""Base interface for visual computer action executors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple
from ..models import ComputerAction, ComputerObservation


class BaseComputerExecutor(ABC):
    """Abstract base class for executing visual computer actions (Playwright or OS desktop)."""

    @abstractmethod
    def start(self, initial_url: str | None = None) -> None:
        """Initialize the execution environment (e.g. launch browser or attach to desktop display)."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Tear down and clean up the execution environment."""
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """Check if the executor is currently running."""
        pass

    @abstractmethod
    def capture_screenshot(self) -> ComputerObservation:
        """Capture current visual display state."""
        pass

    @abstractmethod
    def execute_action(self, action: ComputerAction) -> ComputerObservation:
        """Execute a single visual action and return the resulting observation."""
        pass

    @abstractmethod
    def get_dimensions(self) -> Tuple[int, int]:
        """Return the viewport/display width and height (width, height)."""
        pass
