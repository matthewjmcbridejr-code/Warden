"""Data models and session tracking schemas for Warden Computer Use subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEY_PRESS = "key_press"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    COMPLETE = "complete"
    FAIL = "fail"
    REQUEST_CONFIRMATION = "request_confirmation"


class SessionStatus(str, Enum):
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ComputerAction:
    action_type: ActionType
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None
    delta_x: Optional[int] = None
    delta_y: Optional[int] = None
    url: Optional[str] = None
    seconds: Optional[float] = None
    summary: str = ""
    requires_confirmation: bool = False
    raw_args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value if isinstance(self.action_type, ActionType) else str(self.action_type),
            "x": self.x,
            "y": self.y,
            "text": self.text,
            "key": self.key,
            "delta_x": self.delta_x,
            "delta_y": self.delta_y,
            "url": self.url,
            "seconds": self.seconds,
            "summary": self.summary,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class ComputerObservation:
    screenshot_bytes: Optional[bytes] = None
    screenshot_path: Optional[str] = None
    width: int = 1280
    height: int = 800
    url: Optional[str] = None
    title: Optional[str] = None
    status_text: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConfirmationRequest:
    confirmation_id: str
    session_id: str
    action_id: str
    action_type: str
    description: str
    parameters: Dict[str, Any]
    status: str = "pending"  # "pending", "approved", "denied", "expired", "cancelled"
    decision: Optional[str] = None  # "approve", "deny"
    operator_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "description": self.description,
            "parameters": self.parameters,
            "status": self.status,
            "decision": self.decision,
            "operator_id": self.operator_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class ComputerSession:
    session_id: str
    objective: str
    environment: str = "browser"
    provider_name: str = "gemini_vertex"
    model_name: str = "gemini-2.5-flash"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    status: SessionStatus = SessionStatus.RUNNING
    active_confirmation_id: Optional[str] = None
    step_count: int = 0
    max_steps: int = 30
    actions: List[ComputerAction] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    current_url: Optional[str] = None
    page_title: Optional[str] = None
    latest_screenshot: Optional[str] = None
    current_action_summary: Optional[str] = None
    final_result: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_waiting_for_confirmation(self) -> bool:
        return self.status == SessionStatus.WAITING_FOR_CONFIRMATION

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.status == SessionStatus.COMPLETED,
            "session_id": self.session_id,
            "objective": self.objective,
            "environment": self.environment,
            "provider": self.provider_name,
            "model": self.model_name,
            "status": self.status.value if isinstance(self.status, SessionStatus) else str(self.status),
            "active_confirmation_id": self.active_confirmation_id,
            "is_waiting_for_confirmation": self.is_waiting_for_confirmation,
            "steps": self.step_count,
            "current_step": self.step_count,
            "max_steps": self.max_steps,
            "current_url": self.current_url,
            "page_title": self.page_title,
            "latest_screenshot": self.latest_screenshot,
            "current_action_summary": self.current_action_summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.final_result or ("Session completed" if self.status == SessionStatus.COMPLETED else None),
            "evidence": self.evidence,
            "error": self.error,
        }
