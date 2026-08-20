"""ComputerUseService orchestrating visual agent execution loops, evidence capture, and confirmation."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .models import (
    ActionType,
    ComputerAction,
    ComputerObservation,
    ComputerSession,
    ConfirmationRequest,
    SessionStatus,
)
from .confirmations import check_confirmation_required
from .screenshots import save_screenshot
from .executors.base import BaseComputerExecutor
from .executors.playwright_executor import PlaywrightBrowserExecutor
from .executors.linux_desktop_executor import LinuxDesktopExecutor
from .providers.base import BaseComputerProvider
from .providers.gemini_vertex import GeminiVertexComputerProvider

logger = logging.getLogger(__name__)


class ComputerUseService:
    """High-level orchestrator for visual Computer Use missions."""

    def __init__(
        self,
        default_provider: Optional[BaseComputerProvider] = None,
        default_executor: Optional[BaseComputerExecutor] = None,
    ):
        self.default_provider = default_provider
        self.default_executor = default_executor

    def run(
        self,
        objective: str,
        environment: str = "browser",
        start_url: Optional[str] = None,
        max_steps: int = 30,
        provider: Optional[BaseComputerProvider] = None,
        executor: Optional[BaseComputerExecutor] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Execute a full visual computer use mission and return structured evidence."""
        session_id = f"computer-{int(time.time() * 1000)}"
        clean_env = environment.lower().strip() if environment else "browser"

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

                # Plan next action
                action = active_provider.plan_next_action(session, obs)

                # Check confirmation boundary
                if check_confirmation_required(action, obs):
                    _emit("computer_confirmation_required", {
                        "step": step_idx,
                        "action": action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type),
                        "description": action.summary or f"Action requires confirmation: {action.action_type}",
                    })

                session.actions.append(action)
                _emit("computer_action", {
                    "step": step_idx,
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

                # Execute action
                obs_after = active_executor.execute_action(action)
                session.evidence.append({
                    "kind": "observation",
                    "step": step_idx,
                    "summary": action.summary,
                    "url": obs_after.url,
                    "title": obs_after.title,
                })
                _emit("computer_observation", {
                    "step": step_idx,
                    "summary": action.summary,
                    "url": obs_after.url,
                    "title": obs_after.title,
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
            session.completed_at = datetime.now(timezone.utc).isoformat()
            _emit("computer_session_completed", {
                "status": session.status.value if isinstance(session.status, SessionStatus) else str(session.status),
                "steps": session.step_count,
                "result": session.final_result,
                "error": session.error,
            })

        return session.to_summary_dict()
