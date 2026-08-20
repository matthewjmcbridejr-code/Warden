"""Confirmation policy and checks for high-impact visual actions in Warden Computer Use."""

from __future__ import annotations

import re
from typing import Optional
from .models import ComputerAction, ComputerObservation, ActionType


SENSITIVE_KEYWORDS = [
    "delete", "destroy", "remove", "purge", "truncate",
    "buy", "purchase", "order", "pay", "checkout",
    "terminate", "shutdown", "wipe", "drop",
    "sign out", "log out", "revoke", "transfer"
]

CONFIRMATION_PATTERN = re.compile(
    r"\b(" + "|".join(SENSITIVE_KEYWORDS) + r")\b",
    re.IGNORECASE
)


def check_confirmation_required(
    action: ComputerAction,
    observation: Optional[ComputerObservation] = None
) -> bool:
    """Determine if an action requires explicit operator approval before execution."""
    if action.requires_confirmation:
        return True

    if action.action_type == ActionType.REQUEST_CONFIRMATION:
        return True

    # Check text being typed
    if action.text and CONFIRMATION_PATTERN.search(action.text):
        return True

    # Check action summary
    if action.summary and CONFIRMATION_PATTERN.search(action.summary):
        return True

    return False
