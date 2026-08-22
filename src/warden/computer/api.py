"""FastAPI endpoints for Warden Computer Use, Mission Control confirmations, and screenshots."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .confirmations import default_confirmation_store
from .screenshots import SCREENSHOT_DIR
from .service import default_session_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/computer", tags=["computer-use"])


class ResolveConfirmationPayload(BaseModel):
    decision: str = Field(..., description="'approve' or 'deny'")
    operator_id: str = Field(default="operator", description="Operator identity")
    expected_session_id: str = Field(..., min_length=1, description="Session ID bound to this decision")
    expected_action_id: str = Field(..., min_length=1, description="Action ID bound to this decision")


@router.get("/confirmations/pending")
def list_pending_confirmations(session_id: Optional[str] = None):
    """Retrieve all pending Computer Use confirmation requests waiting for operator approval."""
    pending = default_confirmation_store.list_pending(session_id=session_id)
    return {
        "ok": True,
        "count": len(pending),
        "confirmations": [c.to_dict() for c in pending],
    }


@router.get("/confirmations/{confirmation_id}")
def get_confirmation(confirmation_id: str):
    """Retrieve details and status for a specific confirmation request."""
    conf = default_confirmation_store.get_confirmation(confirmation_id)
    if not conf:
        raise HTTPException(status_code=404, detail=f"Confirmation request '{confirmation_id}' not found.")
    return {
        "ok": True,
        "confirmation": conf.to_dict(),
    }


@router.post("/confirmations/{confirmation_id}/resolve")
def resolve_confirmation(confirmation_id: str, body: ResolveConfirmationPayload):
    """Resolve a pending confirmation by allowing ('approve') or denying ('deny') execution."""
    success, message, conf = default_confirmation_store.resolve_confirmation(
        confirmation_id=confirmation_id,
        decision=body.decision,
        operator_id=body.operator_id,
        expected_session_id=body.expected_session_id,
        expected_action_id=body.expected_action_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "ok": True,
        "message": message,
        "confirmation": conf.to_dict() if conf else None,
    }


@router.get("/sessions")
def list_sessions():
    """Retrieve all active / recent Computer Use sessions."""
    sessions = default_session_registry.list()
    return {
        "ok": True,
        "count": len(sessions),
        "sessions": [s.to_summary_dict() for s in sessions],
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    """Retrieve state and evidence for a specific Computer Use session."""
    session = default_session_registry.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Computer Use session '{session_id}' not found.")
    return {
        "ok": True,
        "session": session.to_summary_dict(),
    }


@router.get("/screenshots/{filename}")
def get_screenshot(filename: str):
    """Safely stream a captured JPEG/PNG screenshot without directory traversal or remote access leaks."""
    safe_name = Path(filename).name
    if filename != safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid screenshot filename.")
    if not safe_name.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="Invalid image file extension.")

    file_path = SCREENSHOT_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found.")

    data = file_path.read_bytes()
    media_type = "image/png" if safe_name.lower().endswith(".png") else "image/jpeg"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )
