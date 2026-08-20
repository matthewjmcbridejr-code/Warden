"""Mock provider for deterministic testing of Warden Computer Use."""

from __future__ import annotations

from typing import List, Optional, Tuple
from ..models import ComputerAction, ComputerObservation, ComputerSession, ActionType
from .base import BaseComputerProvider


class MockComputerProvider(BaseComputerProvider):
    """Provides a scripted sequence of actions for unit and integration testing."""

    def __init__(self, actions: Optional[List[ComputerAction]] = None):
        self.actions = actions or [
            ComputerAction(action_type=ActionType.NAVIGATE, url="https://example.com", summary="Navigated to example.com"),
            ComputerAction(action_type=ActionType.CLICK, x=100, y=200, summary="Clicked button at (100, 200)"),
            ComputerAction(action_type=ActionType.TYPE, text="test query", summary="Typed query"),
            ComputerAction(action_type=ActionType.COMPLETE, text="Found required page title: Example Domain", summary="Completed"),
        ]
        self._index = 0

    def is_available(self) -> Tuple[bool, str]:
        return True, "Mock Computer Use provider ready"

    def plan_next_action(
        self,
        session: ComputerSession,
        observation: ComputerObservation
    ) -> ComputerAction:
        if self._index < len(self.actions):
            action = self.actions[self._index]
            self._index += 1
            return action
        return ComputerAction(
            action_type=ActionType.COMPLETE,
            text="All scripted test actions finished",
            summary="Finished scripted test actions"
        )
