"""Gemini Vertex AI / Google Cloud provider for Computer Use visual agency."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..models import ComputerAction, ComputerObservation, ComputerSession, ActionType
from .base import BaseComputerProvider

logger = logging.getLogger(__name__)


class GeminiVertexComputerProvider(BaseComputerProvider):
    """Invokes Gemini multimodal models on Vertex AI / Google Cloud to plan visual actions."""

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model = model or os.environ.get("WARDEN_COMPUTER_MODEL", "gemini-2.5-flash")
        self._client: Optional[Any] = None

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client

        from google import genai
        from google.genai import types

        # 1. Check if direct GEMINI_API_KEY is present
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key:
            self._client = genai.Client(api_key=api_key)
            return self._client

        # 2. Vertex AI / Google Cloud ADC / gcloud path
        project = self.project
        credentials = None

        try:
            token = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode().strip()
            if token:
                from google.oauth2.credentials import Credentials
                credentials = Credentials(token)
        except Exception:
            pass

        if not credentials:
            try:
                import google.auth
                creds, default_proj = google.auth.default()
                if not project:
                    project = default_proj
                credentials = creds
            except Exception:
                pass

        if not project:
            try:
                project = subprocess.check_output(
                    ["gcloud", "config", "get-value", "project"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).decode().strip()
            except Exception:
                project = "booming-key-500220-d9"

        self.project = project

        self._client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
            credentials=credentials
        )
        return self._client

    def is_available(self) -> Tuple[bool, str]:
        try:
            client = self._resolve_client()
            return True, f"Vertex AI Gemini Computer Use ready ({self.model} @ {self.project}/{self.location})"
        except Exception as exc:
            return False, f"Google Cloud Vertex AI not configured: {exc}"

    def plan_next_action(
        self,
        session: ComputerSession,
        observation: ComputerObservation
    ) -> ComputerAction:
        from google.genai import types

        client = self._resolve_client()

        # Build explicit function declarations for computer use tools
        tools_list = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="click_coordinate",
                        description="Click at pixel coordinate (x, y) on the screen to focus an input, click a button, or open a link.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "x": types.Schema(type=types.Type.INTEGER, description="X coordinate in pixels"),
                                "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate in pixels"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for clicking"),
                            },
                            required=["x", "y"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="double_click_coordinate",
                        description="Double-click at coordinate (x, y) to select a word or activate an item.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "x": types.Schema(type=types.Type.INTEGER, description="X coordinate in pixels"),
                                "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate in pixels"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for double clicking"),
                            },
                            required=["x", "y"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="right_click_coordinate",
                        description="Right-click at coordinate (x, y) to open a context menu.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "x": types.Schema(type=types.Type.INTEGER, description="X coordinate in pixels"),
                                "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate in pixels"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for right clicking"),
                            },
                            required=["x", "y"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="type_text",
                        description="Type text into the focused input field, or specify (x, y) coordinates to click and focus the input field before typing. Optionally press enter afterwards.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "text": types.Schema(type=types.Type.STRING, description="Text to type"),
                                "x": types.Schema(type=types.Type.INTEGER, description="Optional X pixel coordinate of the input field"),
                                "y": types.Schema(type=types.Type.INTEGER, description="Optional Y pixel coordinate of the input field"),
                                "press_enter": types.Schema(type=types.Type.BOOLEAN, description="Whether to press Enter key after typing"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for typing"),
                            },
                            required=["text"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="press_key",
                        description="Press a keyboard key such as Enter, Escape, Tab, Backspace, ArrowDown, ArrowUp.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "key": types.Schema(type=types.Type.STRING, description="Name of the key to press"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for pressing key"),
                            },
                            required=["key"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="scroll_view",
                        description="Scroll the current view vertically or horizontally. Positive delta_y scrolls down, negative scrolls up.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "delta_y": types.Schema(type=types.Type.INTEGER, description="Vertical scroll delta in pixels"),
                                "delta_x": types.Schema(type=types.Type.INTEGER, description="Horizontal scroll delta in pixels"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for scrolling"),
                            }
                        )
                    ),
                    types.FunctionDeclaration(
                        name="navigate_url",
                        description="Navigate the browser to a specific web URL.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "url": types.Schema(type=types.Type.STRING, description="Target web URL"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for navigation"),
                            },
                            required=["url"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="wait_seconds",
                        description="Wait for content or animations to finish loading.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "seconds": types.Schema(type=types.Type.NUMBER, description="Seconds to wait"),
                                "reason": types.Schema(type=types.Type.STRING, description="Reason for waiting"),
                            }
                        )
                    ),
                    types.FunctionDeclaration(
                        name="finish_task",
                        description="Signal that the visual task/objective has been completely accomplished. Include the final synthesized answer/result.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "result": types.Schema(type=types.Type.STRING, description="Final answer, findings, or proof of task completion"),
                            },
                            required=["result"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="fail_task",
                        description="Signal that the task cannot be completed or reached an unrecoverable state.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "reason": types.Schema(type=types.Type.STRING, description="Explanation of failure reason"),
                            },
                            required=["reason"]
                        )
                    ),
                ]
            )
        ]

        # Prepare history summary
        action_history_lines = []
        for i, a in enumerate(session.actions[-5:], 1):
            action_history_lines.append(f"{i}. {a.summary}")
        history_str = "\n".join(action_history_lines) if action_history_lines else "(None yet)"

        prompt_text = (
            f"You are Warden's Computer Use visual execution agent.\n"
            f"Objective: {session.objective}\n"
            f"Environment: {session.environment}\n"
            f"Current Step: {session.step_count + 1} / {session.max_steps}\n"
            f"Current View: {observation.title} ({observation.url or 'local display'})\n"
            f"Dimensions: {observation.width}x{observation.height}\n\n"
            f"Recent Actions:\n{history_str}\n\n"
            f"Analyze the current screenshot carefully. Choose EXACTLY ONE action function to execute next.\n"
            f"When the objective is achieved, call `finish_task` with a clear explanation of what was found or completed.\n"
            f"If typing into a search or input field, click the input first to focus it, or type directly if already focused."
        )

        content_parts = [prompt_text]
        if observation.screenshot_bytes:
            content_parts.append(
                types.Part.from_bytes(data=observation.screenshot_bytes, mime_type="image/jpeg")
            )

        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    tools=tools_list,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.ANY
                        )
                    ),
                    temperature=0.0
                )
            )

            # Inspect function call candidates
            if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                for part in resp.candidates[0].content.parts:
                    if part.function_call:
                        fc = part.function_call
                        name = fc.name
                        args = fc.args or {}

                        if name == "click_coordinate":
                            return ComputerAction(
                                action_type=ActionType.CLICK,
                                x=int(args.get("x", 0)),
                                y=int(args.get("y", 0)),
                                summary=f"Clicked at ({args.get('x')}, {args.get('y')}): {args.get('reason', '')}".strip(),
                                raw_args=args
                            )
                        elif name == "double_click_coordinate":
                            return ComputerAction(
                                action_type=ActionType.DOUBLE_CLICK,
                                x=int(args.get("x", 0)),
                                y=int(args.get("y", 0)),
                                summary=f"Double-clicked at ({args.get('x')}, {args.get('y')}): {args.get('reason', '')}".strip(),
                                raw_args=args
                            )
                        elif name == "right_click_coordinate":
                            return ComputerAction(
                                action_type=ActionType.RIGHT_CLICK,
                                x=int(args.get("x", 0)),
                                y=int(args.get("y", 0)),
                                summary=f"Right-clicked at ({args.get('x')}, {args.get('y')}): {args.get('reason', '')}".strip(),
                                raw_args=args
                            )
                        elif name == "type_text":
                            x_val = int(args["x"]) if "x" in args and args["x"] is not None else None
                            y_val = int(args["y"]) if "y" in args and args["y"] is not None else None
                            return ComputerAction(
                                action_type=ActionType.TYPE,
                                x=x_val,
                                y=y_val,
                                text=str(args.get("text", "")),
                                summary=f"Typed '{args.get('text')}'{' (and pressed Enter)' if args.get('press_enter') else ''}{f' at ({x_val}, {y_val})' if x_val is not None else ''}",
                                raw_args=args
                            )
                        elif name == "press_key":
                            return ComputerAction(
                                action_type=ActionType.KEY_PRESS,
                                key=str(args.get("key", "")),
                                summary=f"Pressed key '{args.get('key')}'",
                                raw_args=args
                            )
                        elif name == "scroll_view":
                            return ComputerAction(
                                action_type=ActionType.SCROLL,
                                delta_y=int(args.get("delta_y", 300)),
                                delta_x=int(args.get("delta_x", 0)),
                                summary=f"Scrolled view by ({args.get('delta_x', 0)}, {args.get('delta_y', 300)})",
                                raw_args=args
                            )
                        elif name == "navigate_url":
                            return ComputerAction(
                                action_type=ActionType.NAVIGATE,
                                url=str(args.get("url", "")),
                                summary=f"Navigated to {args.get('url')}",
                                raw_args=args
                            )
                        elif name == "wait_seconds":
                            return ComputerAction(
                                action_type=ActionType.WAIT,
                                seconds=float(args.get("seconds", 1.0)),
                                summary=f"Waited {args.get('seconds', 1.0)}s",
                                raw_args=args
                            )
                        elif name == "finish_task":
                            return ComputerAction(
                                action_type=ActionType.COMPLETE,
                                text=str(args.get("result", "Objective accomplished successfully.")),
                                summary=f"Finished: {args.get('result', '')}",
                                raw_args=args
                            )
                        elif name == "fail_task":
                            return ComputerAction(
                                action_type=ActionType.FAIL,
                                text=str(args.get("reason", "Objective could not be completed.")),
                                summary=f"Failed: {args.get('reason', '')}",
                                raw_args=args
                            )

            # Fallback if text only
            text_resp = resp.text or ""
            if "finish" in text_resp.lower() or "complete" in text_resp.lower():
                return ComputerAction(
                    action_type=ActionType.COMPLETE,
                    text=text_resp,
                    summary=f"Finished: {text_resp[:100]}"
                )

            return ComputerAction(
                action_type=ActionType.WAIT,
                seconds=1.0,
                summary="Waited 1.0s for visual state update"
            )

        except Exception as exc:
            logger.warning("Gemini Computer Use planning error: %s", exc)
            return ComputerAction(
                action_type=ActionType.FAIL,
                text=str(exc),
                summary=f"Computer Use provider error: {exc}"
            )
