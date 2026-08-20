"""Base interface for visual Computer Use reasoning providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple
from ..models import ComputerAction, ComputerObservation, ComputerSession


class BaseComputerProvider(ABC):
    """Abstract base provider that observes screenshots and plans visual actions."""

    @abstractmethod
    def is_available(self) -> Tuple[bool, str]:
        """Check if provider credentials/client are configured and reachable."""
        pass

    @abstractmethod
    def plan_next_action(
        self,
        session: ComputerSession,
        observation: ComputerObservation
    ) -> ComputerAction:
        """Analyze the current visual observation and determine the next action."""
        pass
