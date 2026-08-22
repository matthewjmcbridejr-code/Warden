"""Warden Computer Use & Local Machine Agency subsystem."""

from .models import (
    ActionType,
    ComputerAction,
    ComputerObservation,
    ComputerSession,
    ConfirmationRequest,
    SessionStatus,
)
from .service import ComputerSessionRegistry, ComputerUseService, default_session_registry
from .providers.base import BaseComputerProvider
from .providers.gemini_vertex import GeminiVertexComputerProvider
from .providers.mock_provider import MockComputerProvider
from .executors.base import BaseComputerExecutor
from .executors.playwright_executor import PlaywrightBrowserExecutor
from .executors.linux_desktop_executor import LinuxDesktopExecutor

from .confirmations import ConfirmationStore, default_confirmation_store, check_confirmation_required

__all__ = [
    "ActionType",
    "ComputerAction",
    "ComputerObservation",
    "ComputerSession",
    "ConfirmationRequest",
    "ConfirmationStore",
    "default_confirmation_store",
    "check_confirmation_required",
    "SessionStatus",
    "ComputerUseService",
    "ComputerSessionRegistry",
    "default_session_registry",
    "BaseComputerProvider",
    "GeminiVertexComputerProvider",
    "MockComputerProvider",
    "BaseComputerExecutor",
    "PlaywrightBrowserExecutor",
    "LinuxDesktopExecutor",
]
