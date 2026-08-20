"""Confirmation policy and checks for high-impact visual actions in Warden Computer Use."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import ActionType, ComputerAction, ComputerObservation, ConfirmationRequest

logger = logging.getLogger(__name__)

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


class ConfirmationStore:
    """Thread-safe manager for pending, approved, and denied visual Computer Use actions."""

    def __init__(self) -> None:
        self._confirmations: Dict[str, ConfirmationRequest] = {}
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create_confirmation(
        self,
        session_id: str,
        action: ComputerAction,
        step_idx: int,
        description: str = "",
    ) -> ConfirmationRequest:
        with self._lock:
            conf_id = f"conf_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            action_id = f"{session_id}_step_{step_idx}"
            act_type_str = action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type)
            clean_desc = description or action.summary or f"Action requires confirmation: {act_type_str}"

            req = ConfirmationRequest(
                confirmation_id=conf_id,
                session_id=session_id,
                action_id=action_id,
                action_type=act_type_str,
                description=clean_desc,
                parameters=action.to_dict(),
                status="pending",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._confirmations[conf_id] = req
            self._events[conf_id] = threading.Event()
            return req

    def get_confirmation(self, confirmation_id: str) -> Optional[ConfirmationRequest]:
        with self._lock:
            return self._confirmations.get(confirmation_id)

    def list_confirmations(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ConfirmationRequest]:
        with self._lock:
            items = list(self._confirmations.values())
            if session_id:
                items = [c for c in items if c.session_id == session_id]
            if status:
                items = [c for c in items if c.status == status]
            return items

    def list_pending(self, session_id: Optional[str] = None) -> List[ConfirmationRequest]:
        return self.list_confirmations(session_id=session_id, status="pending")

    def resolve_confirmation(
        self,
        confirmation_id: str,
        decision: str,
        operator_id: str = "matt",
        expected_session_id: Optional[str] = None,
        expected_action_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ConfirmationRequest]]:
        """Resolve a pending confirmation request.

        Enforces that:
        - decision is either 'approve' or 'deny'
        - confirmation exists and is currently 'pending' (prevents stale / replayed resolutions)
        - session_id and action_id match exactly if provided (prevents cross-action authorization)
        """
        clean_dec = decision.lower().strip()
        if clean_dec not in ("approve", "deny"):
            return False, f"Invalid decision '{decision}'. Must be 'approve' or 'deny'.", None

        with self._lock:
            conf = self._confirmations.get(confirmation_id)
            if not conf:
                return False, f"Confirmation request '{confirmation_id}' not found.", None

            if conf.status != "pending":
                return False, f"Confirmation request '{confirmation_id}' is already resolved as '{conf.status}'.", conf

            if expected_session_id and conf.session_id != expected_session_id:
                return False, f"Mismatched session ID: expected '{expected_session_id}', got '{conf.session_id}'.", conf

            if expected_action_id and conf.action_id != expected_action_id:
                return False, f"Mismatched action ID: expected '{expected_action_id}', got '{conf.action_id}'.", conf

            conf.decision = clean_dec
            conf.status = "approved" if clean_dec == "approve" else "denied"
            conf.operator_id = operator_id
            conf.resolved_at = datetime.now(timezone.utc).isoformat()

            ev = self._events.get(confirmation_id)
            if ev:
                ev.set()

            logger.info(
                "Resolved confirmation %s for session %s: %s by %s",
                confirmation_id,
                conf.session_id,
                conf.status,
                operator_id,
            )
            return True, f"Confirmation {conf.status} successfully.", conf

    def wait_for_decision(
        self,
        confirmation_id: str,
        timeout_seconds: float = 300.0,
    ) -> Tuple[str, Optional[ConfirmationRequest]]:
        """Block execution until the operator resolves the confirmation or timeout expires."""
        ev = None
        with self._lock:
            ev = self._events.get(confirmation_id)
            conf = self._confirmations.get(confirmation_id)

        if not ev or not conf:
            return "not_found", None

        signaled = ev.wait(timeout=timeout_seconds)

        with self._lock:
            conf = self._confirmations.get(confirmation_id)
            if not signaled:
                if conf and conf.status == "pending":
                    conf.status = "expired"
                    conf.resolved_at = datetime.now(timezone.utc).isoformat()
                    return "expired", conf
            return (conf.status if conf else "not_found"), conf

    def cancel_confirmation(self, confirmation_id: str, reason: str = "cancelled") -> bool:
        with self._lock:
            conf = self._confirmations.get(confirmation_id)
            if conf and conf.status == "pending":
                conf.status = "cancelled"
                conf.resolved_at = datetime.now(timezone.utc).isoformat()
                ev = self._events.get(confirmation_id)
                if ev:
                    ev.set()
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._confirmations.clear()
            self._events.clear()


# Default singleton confirmation store
default_confirmation_store = ConfirmationStore()
