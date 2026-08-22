"""ComputerUseService orchestrating visual agent execution loops, evidence capture, and confirmation."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .models import (
    ActionType,
    ComputerAction,
    ComputerObservation,
    ComputerSession,
    ConfirmationRequest,
    SessionStatus,
)
from .confirmations import (
    ConfirmationStore,
    check_confirmation_required,
    default_confirmation_store,
)
from .screenshots import save_screenshot
from .executors.base import BaseComputerExecutor
from .executors.playwright_executor import PlaywrightBrowserExecutor
from .executors.linux_desktop_executor import LinuxDesktopExecutor
from .providers.base import BaseComputerProvider
from .providers.gemini_vertex import GeminiVertexComputerProvider

logger = logging.getLogger(__name__)


class ComputerSessionRegistry:
    """Process-wide source of truth for active and recently completed sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ComputerSession] = {}
        self._lock = threading.Lock()

    def register(self, session: ComputerSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Optional[ComputerSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> List[ComputerSession]:
        with self._lock:
            return list(self._sessions.values())

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


default_session_registry = ComputerSessionRegistry()


class ComputerUseService:
    """High-level orchestrator for visual Computer Use missions."""

    def __init__(
        self,
        default_provider: Optional[BaseComputerProvider] = None,
        default_executor: Optional[BaseComputerExecutor] = None,
        confirmation_store: Optional[ConfirmationStore] = None,
        session_registry: Optional[ComputerSessionRegistry] = None,
        confirmation_timeout: float = 300.0,
    ):
        self.default_provider = default_provider
        self.default_executor = default_executor
        self.confirmation_store = confirmation_store or default_confirmation_store
        self.session_registry = session_registry or default_session_registry
        self.confirmation_timeout = confirmation_timeout

    def get_session(self, session_id: str) -> Optional[ComputerSession]:
        return self.session_registry.get(session_id)

    def list_sessions(self) -> List[ComputerSession]:
        return self.session_registry.list()

    def run(
        self,
        objective: str,
        environment: str = "browser",
        start_url: Optional[str] = None,
        max_steps: int = 30,
        provider: Optional[BaseComputerProvider] = None,
        executor: Optional[BaseComputerExecutor] = None,
        confirmation_store: Optional[ConfirmationStore] = None,
        confirmation_timeout: Optional[float] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Execute a full visual computer use mission and return structured evidence."""
        session_id = f"computer-{int(time.time() * 1000)}-{uuid4().hex[:8]}"
        clean_env = environment.lower().strip() if environment else "browser"
        active_confirmation_store = confirmation_store or self.confirmation_store
        active_timeout = confirmation_timeout if confirmation_timeout is not None else self.confirmation_timeout

        # 1. Environment validation
        if clean_env == "desktop":
            # Check if desktop executor is explicitly provided
            if not executor:
                return {
                    "ok": False,
                    "session_id": session_id,
                    "objective": objective,
                    "environment": "desktop",
                    "status": "failed",
                    "steps": 0,
                    "result": None,
                    "error": "Desktop environment is not yet configured for Phase 1. Use environment='browser'.",
                    "evidence": []
                }

        # 2. Setup Provider
        active_provider = provider or self.default_provider or GeminiVertexComputerProvider()
        is_avail, avail_reason = active_provider.is_available()

        session = ComputerSession(
            session_id=session_id,
            objective=objective,
            environment=clean_env,
            provider_name=active_provider.__class__.__name__,
            model_name=getattr(active_provider, "model", "default"),
            max_steps=max_steps,
        )

        self.session_registry.register(session)

        if not is_avail:
            session.status = SessionStatus.FAILED
            session.error = f"Computer Use unavailable: {avail_reason}"
            session.completed_at = datetime.now(timezone.utc).isoformat()
            return session.to_summary_dict()

        # 3. Setup Executor
        active_executor = executor or self.default_executor or PlaywrightBrowserExecutor()

        def _emit(event_type: str, data: Dict[str, Any]) -> None:
            if event_callback:
                try:
                    event_callback(event_type, {**data, "session_id": session_id})
                except Exception as cb_err:
                    logger.debug("Event callback error: %s", cb_err)

        _emit("computer_session_started", {
            "objective": objective,
            "environment": clean_env,
            "provider": session.provider_name,
            "max_steps": max_steps,
        })

        try:
            active_executor.start(initial_url=start_url)
            time.sleep(0.5)

            # Action loop
            for step_idx in range(1, max_steps + 1):
                session.step_count = step_idx

                # Capture observation
                obs = active_executor.capture_screenshot()
                if obs.screenshot_bytes:
                    try:
                        obs.screenshot_path = save_screenshot(
                            obs.screenshot_bytes,
                            session_id=session.session_id,
                            step_index=step_idx
                        )
                    except Exception as s_err:
                        logger.warning("Screenshot save error: %s", s_err)

                session.current_url = obs.url
                session.page_title = obs.title
                if obs.screenshot_path:
                    session.latest_screenshot = (
                        f"/api/mcharness/computer/screenshots/{Path(obs.screenshot_path).name}"
                    )
                _emit("computer_observation", {
                    "step": step_idx,
                    "summary": "Captured the current browser state.",
                    "url": obs.url,
                    "title": obs.title,
                    "screenshot_path": obs.screenshot_path,
                })

                # Plan next action
                action = active_provider.plan_next_action(session, obs)
                action_id = f"{session.session_id}_step_{step_idx}"
                session.current_action_summary = action.summary

                # Check confirmation boundary BEFORE execution
                if check_confirmation_required(action, obs):
                    conf = active_confirmation_store.create_confirmation(
                        session_id=session.session_id,
                        action=action,
                        step_idx=step_idx,
                        description=action.summary or f"Action requires confirmation: {action.action_type}",
                    )
                    session.status = SessionStatus.WAITING_FOR_CONFIRMATION
                    session.active_confirmation_id = conf.confirmation_id

                    _emit("computer_confirmation_required", {
                        "step": step_idx,
                        "confirmation_id": conf.confirmation_id,
                        "action_id": conf.action_id,
                        "action_type": action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type),
                        "description": conf.description,
                        "reason": "This action matched Warden's consequential-action safety policy.",
                        "risk_level": "high",
                        "parameters": action.to_dict(),
                        "url": obs.url,
                        "title": obs.title,
                        "screenshot_path": obs.screenshot_path,
                    })

                    # Block execution until operator resolves the confirmation
                    status, resolved_conf = active_confirmation_store.wait_for_decision(
                        confirmation_id=conf.confirmation_id,
                        timeout_seconds=active_timeout,
                    )
                    session.active_confirmation_id = None

                    if status != "approved":
                        # Operator denied or confirmation expired/cancelled: DO NOT EXECUTE ACTION
                        denial_msg = f"Action '{action.summary}' was {status} by operator {resolved_conf.operator_id if resolved_conf else ''}".strip()
                        session.evidence.append({
                            "kind": "confirmation_denied",
                            "step": step_idx,
                            "confirmation_id": conf.confirmation_id,
                            "status": status,
                            "summary": denial_msg,
                            "url": obs.url,
                            "title": obs.title,
                        })
                        _emit("computer_confirmation_resolved", {
                            "step": step_idx,
                            "confirmation_id": conf.confirmation_id,
                            "action_id": conf.action_id,
                            "status": status,
                            "decision": resolved_conf.decision if resolved_conf else status,
                            "executed": False,
                            "summary": denial_msg,
                        })
                        session.status = SessionStatus.COMPLETED if status == "denied" else SessionStatus.FAILED
                        if status == "denied":
                            session.final_result = f"Action prevented: {denial_msg}"
                        else:
                            session.error = f"Action prevented: {denial_msg}"
                        break

                    # Approved: resume execution
                    session.status = SessionStatus.RUNNING
                    _emit("computer_confirmation_resolved", {
                        "step": step_idx,
                        "confirmation_id": conf.confirmation_id,
                        "action_id": conf.action_id,
                        "status": "approved",
                        "decision": "approve",
                        "executed": False,
                        "summary": f"Approved by {resolved_conf.operator_id if resolved_conf else 'operator'}. Action is ready to execute.",
                    })

                session.actions.append(action)
                _emit("computer_action", {
                    "step": step_idx,
                    "action_id": action_id,
                    "action_type": action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type),
                    "summary": action.summary,
                })

                # Check completion
                if action.action_type == ActionType.COMPLETE:
                    session.status = SessionStatus.COMPLETED
                    session.final_result = action.text or action.summary
                    session.evidence.append({
                        "kind": "completion",
                        "step": step_idx,
                        "summary": session.final_result,
                        "url": obs.url,
                        "title": obs.title,
                    })
                    break

                elif action.action_type == ActionType.FAIL:
                    session.status = SessionStatus.FAILED
                    session.error = action.text or action.summary
                    session.evidence.append({
                        "kind": "failure",
                        "step": step_idx,
                        "summary": session.error,
                        "url": obs.url,
                        "title": obs.title,
                    })
                    break

                # Execute action (only reached if safe or explicitly approved)
                obs_after = active_executor.execute_action(action)
                if obs_after.screenshot_bytes:
                    try:
                        obs_after.screenshot_path = save_screenshot(
                            obs_after.screenshot_bytes,
                            session_id=session.session_id,
                            step_index=step_idx,
                        )
                    except Exception as s_err:
                        logger.warning("Screenshot save error: %s", s_err)
                session.current_url = obs_after.url
                session.page_title = obs_after.title
                if obs_after.screenshot_path:
                    session.latest_screenshot = (
                        f"/api/mcharness/computer/screenshots/{Path(obs_after.screenshot_path).name}"
                    )
                session.evidence.append({
                    "kind": "observation",
                    "step": step_idx,
                    "summary": action.summary,
                    "url": obs_after.url,
                    "title": obs_after.title,
                })
                _emit("computer_action_executed", {
                    "step": step_idx,
                    "action_id": action_id,
                    "action_type": action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type),
                    "summary": action.summary,
                    "executed": True,
                })
                _emit("computer_observation", {
                    "step": step_idx,
                    "summary": action.summary,
                    "url": obs_after.url,
                    "title": obs_after.title,
                    "screenshot_path": obs_after.screenshot_path,
                })

            # Check if exceeded max steps without terminal state
            if session.status == SessionStatus.RUNNING:
                session.status = SessionStatus.FAILED
                session.error = f"Computer session stopped after reaching its maximum action count ({max_steps})."

        except Exception as run_exc:
            logger.exception("ComputerUseService runtime error: %s", run_exc)
            session.status = SessionStatus.FAILED
            session.error = f"Computer session failed before completing the objective: {run_exc}"

        finally:
            active_executor.stop()
            if session.active_confirmation_id:
                active_confirmation_store.cancel_confirmation(session.active_confirmation_id)
                session.active_confirmation_id = None
            session.completed_at = datetime.now(timezone.utc).isoformat()
            _emit("computer_session_completed", {
                "status": session.status.value if isinstance(session.status, SessionStatus) else str(session.status),
                "steps": session.step_count,
                "result": session.final_result,
                "error": session.error,
            })

        return session.to_summary_dict()
