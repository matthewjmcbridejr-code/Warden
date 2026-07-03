"""Context budget enforcer — scores, ranks, and trims context before LLM dispatch.

Prevents blind dumping of all memory/tool/git history into the prompt.
Uses tiktoken for accurate token counting (already installed via litellm).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .aliases import ALIAS_DEFS

# Lazy import tiktoken — it's available via litellm install
def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        return max(1, len(text) // 4)


@dataclass
class ContextItem:
    source: str        # "memory" | "git" | "github" | "tool" | "message" | "system"
    content: str
    relevance: float   # 0.0 – 1.0
    tokens: int = 0
    status: str = "pending"   # "kept" | "dropped" | "compressed"
    reason: str = ""
    compressed_content: str = ""

    def __post_init__(self):
        if not self.tokens:
            self.tokens = _count_tokens(self.content)


@dataclass
class BudgetResult:
    alias: str
    token_budget: int
    items: list[ContextItem] = field(default_factory=list)
    total_before: int = 0
    total_after: int = 0
    messages_out: list[dict] = field(default_factory=list)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.total_before - self.total_after)

    @property
    def pct_saved(self) -> float:
        if not self.total_before:
            return 0.0
        return round(self.tokens_saved / self.total_before * 100, 1)


# Per-alias input token budgets
_ALIAS_BUDGETS: dict[str, int] = {
    "warden-local": 1024,
    "warden-fast": 4096,
    "warden-free": 2048,
    "warden-code": 8192,
    "warden-deep": 16384,
    "warden-embed": 512,
}

# How aggressively to compress tool results (chars kept per result)
_TOOL_RESULT_MAX = {
    "warden-local": 200,
    "warden-fast": 800,
    "warden-free": 400,
    "warden-code": 1600,
    "warden-deep": 3200,
    "warden-embed": 100,
}


def _relevance_score(item_text: str, query: str) -> float:
    """Simple keyword overlap score — no LLM needed."""
    if not query:
        return 0.5
    q_words = set(re.findall(r"\w{3,}", query.lower()))
    i_words = set(re.findall(r"\w{3,}", item_text.lower()))
    if not q_words:
        return 0.5
    overlap = len(q_words & i_words) / len(q_words)
    return min(1.0, overlap * 1.5)  # slightly amplified


def _compress_tool_result(content: str, max_chars: int) -> str:
    """Keep the most useful part of a large tool result."""
    if len(content) <= max_chars:
        return content
    # Try to keep structured start (JSON keys, first items) + truncate
    lines = content.splitlines()
    kept = []
    chars = 0
    for line in lines:
        if chars + len(line) > max_chars:
            kept.append(f"... ({len(content) - chars} chars truncated)")
            break
        kept.append(line)
        chars += len(line) + 1
    return "\n".join(kept)


def _compress_memory(content: str, max_chars: int = 300) -> str:
    """Keep first meaningful paragraph of a memory."""
    text = content.strip()
    if len(text) <= max_chars:
        return text
    # Find sentence boundary near limit
    cutoff = text.rfind(". ", 0, max_chars)
    if cutoff > max_chars // 2:
        return text[:cutoff + 1] + " [truncated]"
    return text[:max_chars] + "... [truncated]"


def build_budget(
    alias: str,
    query: str,
    memories: list[dict] | None = None,
    git_context: str | None = None,
    github_items: list[dict] | None = None,
    tool_outputs: list[dict] | None = None,
    conversation: list[dict] | None = None,
    system_prompt: str | None = None,
) -> BudgetResult:
    """
    Score, rank, and trim all context sources to fit within the alias token budget.
    Always preserves: system prompt (compressed), latest user message, high-relevance items.
    """
    budget = _ALIAS_BUDGETS.get(alias, 4096)
    tool_max = _TOOL_RESULT_MAX.get(alias, 800)
    result = BudgetResult(alias=alias, token_budget=budget)
    items: list[ContextItem] = []
    messages_out: list[dict] = []

    # 1. System prompt — always keep but compress
    if system_prompt:
        sys_tokens = _count_tokens(system_prompt)
        result.total_before += sys_tokens
        # Allow system prompt to use max 25% of budget
        sys_budget = budget // 4
        if sys_tokens > sys_budget:
            compressed = system_prompt[:sys_budget * 4] + "\n[system prompt truncated]"
            ci = ContextItem("system", system_prompt, 1.0, sys_tokens, "compressed",
                             f"system prompt trimmed from {sys_tokens} to {sys_budget} tokens",
                             compressed)
        else:
            ci = ContextItem("system", system_prompt, 1.0, sys_tokens, "kept", "fits budget")
        items.append(ci)
        messages_out.append({"role": "system", "content": ci.compressed_content or ci.content})

    # 2. Conversation history — keep last N turns, summarise older ones
    if conversation:
        # Always keep the last user message
        last_user = next((m for m in reversed(conversation) if m.get("role") == "user"), None)
        for msg in conversation:
            text = msg.get("content", "")
            tok = _count_tokens(text)
            result.total_before += tok
            is_last_user = msg is last_user
            rel = 1.0 if is_last_user else 0.7
            ci = ContextItem("message", text, rel, tok)
            items.append(ci)

    # 3. Memories — score by relevance, drop low-signal ones
    for mem in (memories or []):
        content = mem.get("summary") or mem.get("content") or ""
        if not content:
            continue
        rel = _relevance_score(content, query)
        tok = _count_tokens(content)
        result.total_before += tok
        ci = ContextItem("memory", content, rel, tok)
        items.append(ci)

    # 4. Git context
    if git_context:
        tok = _count_tokens(git_context)
        result.total_before += tok
        rel = _relevance_score(git_context, query)
        items.append(ContextItem("git", git_context, rel, tok))

    # 5. GitHub items
    for gh in (github_items or []):
        content = str(gh)
        tok = _count_tokens(content)
        result.total_before += tok
        rel = _relevance_score(content, query)
        items.append(ContextItem("github", content, rel, tok))

    # 6. Tool outputs — compress large ones immediately
    for tool in (tool_outputs or []):
        content = str(tool.get("content") or tool.get("result") or tool)
        compressed = _compress_tool_result(content, tool_max * 4)  # chars → tokens *4
        tok_orig = _count_tokens(content)
        tok_comp = _count_tokens(compressed)
        result.total_before += tok_orig
        status = "compressed" if tok_comp < tok_orig else "kept"
        reason = f"tool result compressed {tok_orig}→{tok_comp} tokens" if status == "compressed" else "fits"
        items.append(ContextItem("tool", content, 0.8, tok_orig, status, reason, compressed))

    # ── Budget allocation ──────────────────────────────────────────────────────
    # Priority order: system > last user message > high-relevance memories >
    #                 git > github > tool outputs > older conversation > low-rel memories
    used = 0

    # Always keep system + last user message
    for ci in items:
        if ci.source == "system":
            ci.status = "kept"
            used += _count_tokens(ci.compressed_content or ci.content)
        elif ci.source == "message" and ci.relevance == 1.0:  # last user message
            ci.status = "kept"
            used += ci.tokens

    # Sort remaining by relevance desc
    remaining = [ci for ci in items if ci.status == "pending"]
    remaining.sort(key=lambda x: x.relevance, reverse=True)

    for ci in remaining:
        content = ci.compressed_content or ci.content
        cost = _count_tokens(content)

        if used + cost <= budget:
            ci.status = "kept"
            used += cost
        elif used + cost <= budget * 1.2 and ci.relevance >= 0.6:
            # Try compressing memories to fit
            if ci.source == "memory":
                comp = _compress_memory(content)
                comp_tokens = _count_tokens(comp)
                if used + comp_tokens <= budget:
                    ci.status = "compressed"
                    ci.compressed_content = comp
                    ci.reason = f"memory compressed {ci.tokens}→{comp_tokens} tokens"
                    used += comp_tokens
                    continue
            ci.status = "dropped"
            ci.reason = f"over budget ({used}+{cost}>{budget}), relevance {ci.relevance:.2f}"
        else:
            ci.status = "dropped"
            ci.reason = f"over budget or low relevance ({ci.relevance:.2f})"

    # Build final message list
    result.items = items
    result.total_after = used

    # Reconstruct messages for dispatch
    sys_items = [ci for ci in items if ci.source == "system" and ci.status in ("kept", "compressed")]
    if sys_items:
        result.messages_out = [{"role": "system", "content": sys_items[0].compressed_content or sys_items[0].content}]

    # Add context block from kept non-message items
    ctx_parts = []
    for ci in items:
        if ci.source in ("memory", "git", "github", "tool") and ci.status in ("kept", "compressed"):
            label = {"memory": "Memory", "git": "Git", "github": "GitHub", "tool": "Tool"}[ci.source]
            ctx_parts.append(f"## {label}\n{ci.compressed_content or ci.content}")
    if ctx_parts:
        result.messages_out.append({"role": "system", "content": "\n\n".join(ctx_parts)})

    # Add conversation messages
    for ci in items:
        if ci.source == "message" and ci.status in ("kept", "compressed"):
            role = "user" if ci.relevance == 1.0 else "assistant"
            result.messages_out.append({"role": role, "content": ci.compressed_content or ci.content})

    return result


def inspect(result: BudgetResult) -> list[dict]:
    """Return a UI-friendly breakdown of each context item."""
    rows = []
    for ci in result.items:
        rows.append({
            "source": ci.source,
            "status": ci.status,
            "reason": ci.reason or "—",
            "tokens": ci.tokens,
            "tokens_after": _count_tokens(ci.compressed_content or ci.content) if ci.status in ("kept", "compressed") else 0,
            "relevance": round(ci.relevance, 2),
            "preview": (ci.content or "")[:120],
        })
    return rows
