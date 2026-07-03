"""Warden Risk Gate — classify, block, and log dangerous actions."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("warden.risk_gate")

# ---------------------------------------------------------------------------
# Risk levels (ordered from safest to most dangerous)
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    read_only = "read_only"
    safe_write = "safe_write"
    repo_mutation = "repo_mutation"
    external_side_effect = "external_side_effect"
    destructive = "destructive"
    financial = "financial"
    identity_security = "identity_security"


RISK_LEVEL_ORDER: List[str] = [
    RiskLevel.read_only,
    RiskLevel.safe_write,
    RiskLevel.repo_mutation,
    RiskLevel.external_side_effect,
    RiskLevel.destructive,
    RiskLevel.financial,
    RiskLevel.identity_security,
]

# Actions that always require explicit human approval regardless of config
ALWAYS_REQUIRE_APPROVAL: List[RiskLevel] = [
    RiskLevel.destructive,
    RiskLevel.financial,
    RiskLevel.identity_security,
]

# ---------------------------------------------------------------------------
# Action patterns → risk classification
# ---------------------------------------------------------------------------

# (keyword_in_action_name, risk_level, description)
_RULES: List[tuple[str, RiskLevel, str]] = [
    # identity / secrets
    ("rotate_secret", RiskLevel.identity_security, "Rotating secrets requires human approval"),
    ("read_secret", RiskLevel.identity_security, "Reading secrets is prohibited"),
    ("read_env", RiskLevel.identity_security, "Reading env files is prohibited"),
    ("write_env", RiskLevel.identity_security, "Writing env files is prohibited"),
    # financial
    ("purchase", RiskLevel.financial, "Financial transactions require human approval"),
    ("charge", RiskLevel.financial, "Financial transactions require human approval"),
    ("spend", RiskLevel.financial, "Financial transactions require human approval"),
    # destructive
    ("delete_file", RiskLevel.destructive, "File deletion requires human approval"),
    ("rm_rf", RiskLevel.destructive, "rm -rf is prohibited"),
    ("drop_table", RiskLevel.destructive, "Database destructive ops require human approval"),
    ("deploy", RiskLevel.destructive, "Deployment requires human approval"),
    ("send_email", RiskLevel.destructive, "Sending email requires human approval"),
    ("force_push", RiskLevel.destructive, "Force push requires human approval"),
    ("mutate_default_branch", RiskLevel.destructive, "Mutating default branch requires human approval"),
    ("install_systemd", RiskLevel.destructive, "Installing systemd units requires human approval"),
    # external side effects
    ("send_slack", RiskLevel.external_side_effect, "Sending Slack messages is an external side effect"),
    ("post_notion", RiskLevel.external_side_effect, "Writing to Notion is an external side effect"),
    ("create_pr", RiskLevel.external_side_effect, "Creating PRs is an external side effect"),
    # repo mutation
    ("git_commit", RiskLevel.repo_mutation, "Git commits mutate repo state"),
    ("git_push", RiskLevel.repo_mutation, "Git push mutates remote state"),
    ("create_branch", RiskLevel.repo_mutation, "Branch creation mutates repo state"),
    ("write_file", RiskLevel.safe_write, "Writing files is a safe write"),
    # read-only (catch-all)
    ("read_file", RiskLevel.read_only, "Reading files is safe"),
    ("search", RiskLevel.read_only, "Search is read-only"),
    ("list", RiskLevel.read_only, "Listing is read-only"),
    ("get", RiskLevel.read_only, "GET is read-only"),
    ("health", RiskLevel.read_only, "Health checks are read-only"),
    ("recall", RiskLevel.read_only, "Memory recall is read-only"),
]


def classify_action(action: str) -> RiskLevel:
    """Return the risk level for a named action."""
    lower = action.lower().replace("-", "_").replace(" ", "_")
    for keyword, level, _ in _RULES:
        if keyword in lower:
            return level
    return RiskLevel.safe_write  # default: safe write if unknown


def describe_action(action: str) -> str:
    """Return the human-readable risk description for an action."""
    lower = action.lower().replace("-", "_").replace(" ", "_")
    for keyword, _, description in _RULES:
        if keyword in lower:
            return description
    return "Action has unknown risk profile"


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------

class RiskGateViolation(Exception):
    """Raised when an action is blocked by the risk gate."""

    def __init__(self, action: str, level: RiskLevel, reason: str) -> None:
        self.action = action
        self.level = level
        self.reason = reason
        super().__init__(f"[RiskGate] BLOCKED {action!r} ({level}): {reason}")


class RiskGate:
    """Checks actions against the configured max allowed risk level."""

    def __init__(
        self,
        max_level: RiskLevel = RiskLevel.safe_write,
        approved_actions: Optional[List[str]] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.max_level = max_level
        self.approved_actions: List[str] = [a.lower() for a in (approved_actions or [])]
        self.log_dir = log_dir

    def _level_index(self, level: RiskLevel) -> int:
        try:
            return RISK_LEVEL_ORDER.index(level)
        except ValueError:
            return len(RISK_LEVEL_ORDER)

    def check(self, action: str, *, approved: bool = False) -> RiskLevel:
        """
        Check an action against the gate. Returns the risk level if allowed.
        Raises RiskGateViolation if blocked.
        """
        level = classify_action(action)
        lower = action.lower()

        # Explicit approval overrides gate for non-always-block actions
        if approved or lower in self.approved_actions:
            if level not in ALWAYS_REQUIRE_APPROVAL:
                self._log_event(action, level, allowed=True, note="explicitly approved")
                return level

        # Always block certain levels
        if level in ALWAYS_REQUIRE_APPROVAL and not approved:
            reason = f"{level} actions always require explicit human approval"
            self._log_event(action, level, allowed=False, note=reason)
            raise RiskGateViolation(action, level, reason)

        # Check against configured max level
        if self._level_index(level) > self._level_index(self.max_level):
            reason = f"action risk {level} exceeds allowed max {self.max_level}"
            self._log_event(action, level, allowed=False, note=reason)
            raise RiskGateViolation(action, level, reason)

        self._log_event(action, level, allowed=True)
        return level

    def _log_event(
        self, action: str, level: RiskLevel, *, allowed: bool, note: str = ""
    ) -> None:
        event: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "level": level,
            "allowed": allowed,
        }
        if note:
            event["note"] = note
        verb = "ALLOW" if allowed else "BLOCK"
        log.info("[RiskGate] %s %s (%s)%s", verb, action, level, f" — {note}" if note else "")
        if self.log_dir:
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                log_file = self.log_dir / "risk_gate.jsonl"
                with log_file.open("a") as fh:
                    fh.write(json.dumps(event) + "\n")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def is_safe(action: str, max_level: RiskLevel = RiskLevel.safe_write) -> bool:
    """Return True if action is within max_level, False otherwise."""
    try:
        RiskGate(max_level=max_level).check(action)
        return True
    except RiskGateViolation:
        return False


def gate_or_raise(action: str, max_level: RiskLevel = RiskLevel.safe_write) -> RiskLevel:
    """Raise RiskGateViolation if action exceeds max_level."""
    return RiskGate(max_level=max_level).check(action)
