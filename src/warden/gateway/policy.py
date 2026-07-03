"""Warden policy router — maps incoming tasks to model aliases.

Strategy:
1. Rule-based classifier (zero tokens, instant)
2. Privacy guard (blocks private content from warden-free)
3. qwen3:0.6b fallback ONLY when rule confidence < 0.6 and Ollama is reachable

Returns a RouteDecision with alias, reason, confidence, privacy classification.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .aliases import ALIAS_DEFS

OLLAMA_URL = "http://127.0.0.1:11434"
CLASSIFIER_MODEL = "qwen3:0.6b"
CLASSIFIER_TIMEOUT = 8.0

# ── Privacy patterns ──────────────────────────────────────────────────────────
# Content matching these must NEVER route to warden-free (OpenRouter logs prompts)
_PRIVATE_PATTERNS = [
    re.compile(r"\b(GROQ|OPENROUTER|CEREBRAS|HF|TAVILY|SERPAPI|FIRECRAWL)_API_KEY\b"),
    re.compile(r"\bsk-or-[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"# Warden Memory Context"),
    re.compile(r"\bwarden_recall\b|\bworkbench\b|\bmemory_id\b"),
    re.compile(r"\bgit (log|diff|commit|push|pull)\b", re.I),
    re.compile(r"src/warden|src/marius|\.env\b"),
    re.compile(r"\brun_id\b|\bsession_id\b|\bevidence_id\b"),
]

# ── Rule-based routing table ──────────────────────────────────────────────────
# Each entry: (pattern, alias, reason, confidence)
_RULES: list[tuple[re.Pattern, str, str, float]] = [
    # Local-only: classification, routing, trivial
    (re.compile(r"^(hi|hello|hey|ok|thanks|yes|no|sure|got it)[\s!?.]*$", re.I),
     "warden-local", "greeting or ack — trivial", 0.95),

    (re.compile(r"\b(classify|categorise|categorize|label|tag|route|intent|is this|what type|which alias)\b", re.I),
     "warden-local", "classification task", 0.90),

    (re.compile(r"\b(summarise|summarize|tldr|brief summary|one.line|in a sentence)\b", re.I),
     "warden-local", "summarisation task", 0.85),

    (re.compile(r"\b(what is \d|calculate|math|[0-9]+\s*[\+\-\*\/]\s*[0-9]+)\b", re.I),
     "warden-local", "simple calculation or factual", 0.90),

    # Code tasks
    (re.compile(r"\b(code|patch|diff|PR|pull request|bug.?fix|fix.{0,10}bug|implement|refactor|function|class|method|unittest|pytest|lint|type error|traceback|stack trace|import error|\.py\b|\.ts\b|\.js\b)\b", re.I),
     "warden-code", "code task", 0.85),

    (re.compile(r"\b(write a|create a|add a|generate)\b.{0,40}\b(function|class|endpoint|module|script|migration)\b", re.I),
     "warden-code", "code generation", 0.85),

    # Deep / architecture
    (re.compile(r"\b(architect|design|trade.?off|should we|recommend|strategy|long.?term|scalab|when to use|pros and cons|compare)\b", re.I),
     "warden-deep", "architecture/design decision", 0.80),

    (re.compile(r"\b(root cause|why (is|does|did)|diagnos|investigate|figure out|what went wrong|slow|bottleneck|memory leak)\b", re.I),
     "warden-deep", "diagnosis/investigation", 0.80),

    # Fast / agent work
    (re.compile(r"\b(where we at|status|what.s (next|left|blocking|done)|progress|update me|catch me up|plan|next steps)\b", re.I),
     "warden-fast", "status/planning query", 0.85),

    (re.compile(r"\b(tool|agent|search|github|git log|PR|issue|memory|recall|warden|marius)\b", re.I),
     "warden-fast", "agent/tool query", 0.75),

    # Free / demo (non-sensitive only — enforced by privacy guard)
    (re.compile(r"\b(demo|example|show me|imagine|hypothetically|pretend|tutorial|explain like)\b", re.I),
     "warden-free", "demo/experiment", 0.70),
]

# Default when no rule matches
_DEFAULT_ALIAS = "warden-fast"
_DEFAULT_REASON = "no strong rule match — defaulting to fast"
_DEFAULT_CONFIDENCE = 0.50


@dataclass
class RouteDecision:
    alias: str
    reason: str
    confidence: float
    privacy: str                       # "private" | "public-safe"
    openrouter_free_blocked: bool
    classifier_used: str               # "rules" | "qwen" | "rules+qwen"
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    likely_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_private(text: str) -> bool:
    return any(p.search(text) for p in _PRIVATE_PATTERNS)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _likely_tools(text: str) -> list[str]:
    tools = []
    t = text.lower()
    if any(w in t for w in ["git", "commit", "branch", "diff", "push"]):
        tools.append("git_log")
    if any(w in t for w in ["pr", "pull request", "issue", "github"]):
        tools.append("github_prs")
    if any(w in t for w in ["memory", "recall", "remember", "decided", "handoff"]):
        tools.append("recall_memories")
    if any(w in t for w in ["search", "web", "news", "latest", "find online"]):
        tools.append("web_search")
    if any(w in t for w in ["crawl", "url", "http", "website", "page"]):
        tools.append("crawl_url")
    if not tools and any(w in t for w in ["where we at", "status", "update", "progress"]):
        tools = ["warden_context", "git_log", "recall_memories"]
    return tools


def _rule_classify(text: str) -> tuple[str, str, float]:
    for pattern, alias, reason, confidence in _RULES:
        if pattern.search(text):
            return alias, reason, confidence
    return _DEFAULT_ALIAS, _DEFAULT_REASON, _DEFAULT_CONFIDENCE


def _qwen_classify(text: str) -> tuple[str, str] | None:
    """Ask qwen3:0.6b to classify — only called when rule confidence is low."""
    prompt = (
        "Classify the following task into exactly one of these categories:\n"
        "local, fast, code, deep, free\n\n"
        "Rules:\n"
        "- local: greeting, ack, simple calculation, trivial classification\n"
        "- fast: status query, agent work, planning, memory/tool lookup\n"
        "- code: code review, bug fix, implementation, patch, test\n"
        "- deep: architecture, design decision, diagnosis, trade-off analysis\n"
        "- free: public demo or tutorial with no private data\n\n"
        f"Task: {text[:400]}\n\n"
        "Reply with ONLY one word from: local fast code deep free"
    )
    try:
        payload = json.dumps({
            "model": CLASSIFIER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 5},
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=CLASSIFIER_TIMEOUT) as r:
            result = json.loads(r.read())
        word = result["message"]["content"].strip().lower().split()[0]
        if word in ("local", "fast", "code", "deep", "free"):
            return f"warden-{word}", f"qwen3:0.6b classified as {word}"
    except Exception:
        pass
    return None


def route(text: str, force_alias: str | None = None) -> RouteDecision:
    """
    Main routing function. Returns a RouteDecision without making any LLM call
    in most cases (rule-based). qwen3:0.6b is only invoked when rule confidence < 0.6.
    """
    if force_alias and force_alias in ALIAS_DEFS:
        return RouteDecision(
            alias=force_alias,
            reason="forced by caller",
            confidence=1.0,
            privacy="private" if force_alias != "warden-free" else "public-safe",
            openrouter_free_blocked=False,
            classifier_used="forced",
            estimated_input_tokens=_estimate_tokens(text),
            likely_tools=_likely_tools(text),
        )

    private = _is_private(text)
    alias, reason, confidence = _rule_classify(text)
    classifier_used = "rules"
    warnings: list[str] = []

    # Use qwen fallback if low confidence and model is local
    if confidence < 0.60:
        qwen_result = _qwen_classify(text)
        if qwen_result:
            alias, reason = qwen_result
            confidence = 0.78
            classifier_used = "rules+qwen"

    # Privacy enforcement: never route private content to warden-free
    if alias == "warden-free" and private:
        alias = "warden-fast"
        reason = "privacy guard: private content blocked from warden-free"
        warnings.append("Content contains private data — routed away from OpenRouter free tier.")

    openrouter_free_blocked = private and alias == "warden-free"
    alias_privacy = ALIAS_DEFS[alias]["privacy"]

    return RouteDecision(
        alias=alias,
        reason=reason,
        confidence=confidence,
        privacy="private" if private else alias_privacy,
        openrouter_free_blocked=openrouter_free_blocked,
        classifier_used=classifier_used,
        estimated_input_tokens=_estimate_tokens(text),
        likely_tools=_likely_tools(text),
        warnings=warnings,
    )
