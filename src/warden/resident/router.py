"""Deterministic routing: slash commands + keyword-intent classifier.

No LLM call happens in this module. Anything that doesn't match a slash
command or a known keyword pattern falls into the "ambiguous" intent, which
is the only path agent.py is allowed to escalate to synthesis for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

SLASH_COMMANDS = (
    "start", "help", "status", "memory", "watchers", "agents", "sessions",
    "approvals", "approve", "deny",
)


@dataclass
class ParsedCommand:
    command: str
    args: str = ""


def parse_slash_command(text: str) -> Optional[ParsedCommand]:
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return None
    command = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    if command not in SLASH_COMMANDS:
        return ParsedCommand(command="unknown", args=text)
    return ParsedCommand(command=command, args=args)


# ---------------------------------------------------------------------------
# Deterministic NL intents
# ---------------------------------------------------------------------------

@dataclass
class Intent:
    name: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


# Ordered list of (intent_name, compiled_pattern) — first match wins. Order
# matters: more specific patterns (e.g. "draft a reply") must precede
# broader ones (e.g. generic email checks).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email_send", re.compile(r"\bsend (it|that|the (email|draft|reply))\b", re.I)),
    ("email_draft", re.compile(r"\bdraft\b.*\b(reply|email|response)\b|\breply to\b", re.I)),
    ("email_urgent", re.compile(r"\burgent (email|mail)|\bany urgent\b", re.I)),
    ("email_check", re.compile(r"\bcheck (my )?(email|mail|inbox)\b|\bnew (email|mail)\b", re.I)),
    ("overnight_summary", re.compile(r"\bwhat changed overnight\b|\bwhat happened overnight\b|\bovernight (summary|update)\b", re.I)),
    ("webstudio_audit", re.compile(r"\b(run |do )?(a )?webstudio audit\b.*\bon\b|\baudit\b.*\bsite\b", re.I)),
    ("dns_watch", re.compile(r"\bwatch dns\b|\bmonitor dns\b|\bdns watcher\b", re.I)),
    ("memory_search", re.compile(r"\bwhat do (i|you) know about\b|\bdo you remember\b|\brecall\b", re.I)),
    ("memory_remember", re.compile(r"\bsave this to memory\b|\bremember this\b|\bnote this down\b", re.I)),
    ("agents_status", re.compile(r"\bwhat are (the )?agents doing\b|\blist agents\b|\bagent status\b", re.I)),
    ("sessions_stop", re.compile(r"\bstop (that|the) session\b|\bkill (that|the) session\b|\bcancel (that|the) run\b", re.I)),
    ("status", re.compile(r"^\s*(status|how are things|what's up)\s*\??\s*$", re.I)),
]

_DOMAIN_PATTERN = re.compile(r"\b([a-z0-9][a-z0-9-]*\.[a-z]{2,}(?:\.[a-z]{2,})?)\b", re.I)
_SITE_NAME_PATTERN = re.compile(r"\bon\s+([a-z0-9][a-z0-9._-]*)\b", re.I)


def _extract_domain(text: str) -> Optional[str]:
    for m in _DOMAIN_PATTERN.finditer(text):
        candidate = m.group(1)
        if candidate.lower() not in ("e.g.", "i.e."):
            return candidate
    return None


def classify(text: str) -> Intent:
    """Deterministic keyword classifier. No LLM call. Returns Intent('ambiguous')
    if nothing matches — that's the only case agent.py may escalate to synthesis."""
    stripped = text.strip()
    if not stripped:
        return Intent(name="ambiguous")

    for name, pattern in _PATTERNS:
        if pattern.search(stripped):
            slots: dict[str, Any] = {}
            if name in ("webstudio_audit", "dns_watch", "webstudio_dns_change"):
                domain = _extract_domain(stripped)
                site_match = _SITE_NAME_PATTERN.search(stripped)
                if domain:
                    slots["domain"] = domain
                if site_match:
                    slots["site_name"] = site_match.group(1)
            if name in ("memory_search",):
                # crude "about X" slot extraction
                about_match = re.search(r"\babout\s+(.+)$", stripped, re.I)
                if about_match:
                    slots["query"] = about_match.group(1).strip("?. ")
            if name == "memory_remember":
                slots["note"] = stripped
            if name == "sessions_stop":
                slots["session_match"] = stripped
            return Intent(name=name, slots=slots)

    return Intent(name="ambiguous")
