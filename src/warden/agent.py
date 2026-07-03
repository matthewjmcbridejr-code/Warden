"""WardenAgent — tool-calling agent for 'where we at?' style queries.

Sources: warden memory, git log, GitHub PRs/issues (gh CLI), web search (DDG).
Uses LiteLLM for cloud tool-calling (Groq / Cerebras / OpenRouter) with
Ollama fallback via ReAct-style prompting when no cloud key is available.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_REPO = Path(
    os.getenv("WARDEN_CANONICAL_REPO", "/home/matt/workspaces/warden/mcharness-public-export")
).expanduser()

WARDEN_API_BASE = os.getenv("WARDEN_API_BASE", "http://127.0.0.1:6969/api/mcharness")
CRAWL4AI_URL = os.getenv("CRAWL4AI_SERVICE_URL", "http://127.0.0.1:8099")

AGENT_SYSTEM_PROMPT = """\
You are Warden, a senior engineering assistant with access to tools that let you \
query project memory, git history, GitHub, and the web. \
When asked status questions ("where we at?", "what's blocking X?", "recent wins?"), \
call the appropriate tools to gather real data, then synthesise a concise, specific answer. \
Never invent facts. Cite sources (memory record IDs, commit hashes, PR numbers) when you use them. \
Be terse but complete — bullet points preferred for multi-part answers."""

MAX_ITERATIONS = 6


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 10) -> str:
    try:
        return subprocess.check_output(
            cmd, cwd=cwd or CANONICAL_REPO, stderr=subprocess.DEVNULL, timeout=timeout
        ).decode().strip()
    except Exception as e:
        return f"error: {e}"


def tool_recall_memories(query: str, limit: int = 8) -> dict:
    """Query Warden stored memories."""
    import urllib.request
    import urllib.parse
    url = f"{WARDEN_API_BASE}/memories/recall?q={urllib.parse.quote(query)}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        mems = data.get("memories") or []
        return {
            "count": len(mems),
            "memories": [
                {
                    "id": m.get("memory_id", m.get("id")),
                    "kind": m.get("kind"),
                    "summary": (m.get("summary") or m.get("content") or "")[:200],
                    "source": m.get("source"),
                    "created_at": m.get("created_at"),
                }
                for m in mems
            ],
        }
    except Exception as e:
        return {"error": str(e), "memories": []}


def tool_git_log(n: int = 10, repo_path: str | None = None) -> dict:
    """Recent git commits."""
    repo = Path(repo_path).expanduser() if repo_path else CANONICAL_REPO
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    log = _run(["git", "log", f"-{n}", "--oneline", "--no-decorate"], cwd=repo)
    diff_stat = _run(["git", "diff", "--stat", "HEAD"], cwd=repo)
    return {
        "branch": branch,
        "commits": log.splitlines(),
        "working_tree": diff_stat[:600] or "clean",
    }


def tool_github_prs(state: str = "open", limit: int = 10) -> dict:
    """List GitHub pull requests via gh CLI."""
    raw = _run(
        ["gh", "pr", "list", "--state", state, "--limit", str(limit),
         "--json", "number,title,state,author,createdAt,url,labels"],
        timeout=15,
    )
    try:
        prs = json.loads(raw)
        return {"count": len(prs), "prs": prs}
    except Exception:
        return {"error": raw, "prs": []}


def tool_github_issues(state: str = "open", limit: int = 10, label: str = "") -> dict:
    """List GitHub issues via gh CLI."""
    cmd = ["gh", "issue", "list", "--state", state, "--limit", str(limit),
           "--json", "number,title,state,author,createdAt,url,labels"]
    if label:
        cmd += ["--label", label]
    raw = _run(cmd, timeout=15)
    try:
        issues = json.loads(raw)
        return {"count": len(issues), "issues": issues}
    except Exception:
        return {"error": raw, "issues": []}


def tool_web_search(query: str, max_results: int = 5) -> dict:
    """Web search — Tavily if key available, DuckDuckGo otherwise."""
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            import urllib.request as _ur
            payload = json.dumps({
                "api_key": tavily_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            }).encode()
            req = _ur.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _ur.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            results = data.get("results") or []
            return {
                "count": len(results),
                "source": "tavily",
                "results": [
                    {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content", "")[:300]}
                    for r in results
                ],
            }
        except Exception as e:
            logger.warning("Tavily search failed: %s — falling back to DDG", e)

    # DDG fallback
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return {
            "count": len(results),
            "source": "duckduckgo",
            "results": [
                {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body", "")[:300]}
                for r in results
            ],
        }
    except Exception as e:
        return {"error": str(e), "results": []}


def tool_crawl_url(url: str, markdown_only: bool = True) -> dict:
    """Crawl a URL and return its content as markdown. Uses local crawl4ai service."""
    import urllib.request as _ur
    payload = json.dumps({"url": url, "markdown_only": markdown_only}).encode()
    req = _ur.Request(
        f"{CRAWL4AI_URL}/crawl",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return {
            "url": url,
            "title": data.get("title"),
            "markdown": (data.get("markdown") or "")[:5000],
            "ok": data.get("ok"),
        }
    except Exception as e:
        return {"error": str(e), "url": url}


def tool_warden_context(query: str = "") -> dict:
    """Pull current Warden memory-agent context snapshot (git, shell, board, memories)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{WARDEN_API_BASE}/warden/memory-agent/context", timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def tool_mail_accounts() -> dict:
    """Check which mail accounts are connected (Gmail, iCloud, Outlook)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{WARDEN_API_BASE}/warden/mail/accounts", timeout=5) as r:
            data = json.loads(r.read())
        accounts = data.get("accounts", [])
        return {"connected": bool(accounts), "count": len(accounts),
                "accounts": [{"account_id": a.get("account_id"), "provider": a.get("provider"),
                               "display_email": a.get("display_email"), "status": a.get("status")}
                              for a in accounts]}
    except Exception as e:
        return {"error": str(e), "connected": False}


def tool_mail_search(account_id: str, query: str, limit: int = 10) -> dict:
    """Search mail in a connected account. Returns summaries — subject, from, snippet."""
    import urllib.request, urllib.parse
    if not account_id:
        return {"error": "account_id required", "blocked": True}
    try:
        params = urllib.parse.urlencode({"account_id": account_id, "q": query, "limit": min(limit, 20)})
        with urllib.request.urlopen(f"{WARDEN_API_BASE}/warden/mail/search?{params}", timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def tool_mail_read_message(account_id: str, message_id: str) -> dict:
    """Read a mail message body (plain text only, no HTML, no tokens)."""
    import urllib.request, urllib.parse
    if not account_id or not message_id:
        return {"error": "account_id and message_id required"}
    try:
        url = f"{WARDEN_API_BASE}/warden/mail/messages/{urllib.parse.quote(account_id)}/{urllib.parse.quote(message_id)}"
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool registry — OpenAI function-calling schema
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "recall_memories": tool_recall_memories,
    "git_log": tool_git_log,
    "github_prs": tool_github_prs,
    "github_issues": tool_github_issues,
    "web_search": tool_web_search,
    "crawl_url": tool_crawl_url,
    "warden_context": tool_warden_context,
    "mail_accounts": tool_mail_accounts,
    "mail_search": tool_mail_search,
    "mail_read_message": tool_mail_read_message,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "recall_memories",
            "description": "Search Warden stored memories for decisions, proofs, failures, and handoffs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Get recent git commits and working tree diff stat for the Warden repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of commits", "default": 10},
                    "repo_path": {"type": "string", "description": "Repo path override (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_prs",
            "description": "List GitHub pull requests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "enum": ["open", "closed", "merged", "all"], "default": "open"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_issues",
            "description": "List GitHub issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                    "limit": {"type": "integer", "default": 10},
                    "label": {"type": "string", "description": "Filter by label (optional)", "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo. Use for recent news, docs, or anything not in memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crawl_url",
            "description": "Fetch and read a URL as clean markdown. Use for docs, GitHub pages, articles, or any link from search results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to crawl"},
                    "markdown_only": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "warden_context",
            "description": "Get a live snapshot: current branch, recent commits, board tasks, memory count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mail_accounts",
            "description": "Check which mail accounts are connected (Gmail, iCloud). Use this first before searching mail.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mail_search",
            "description": (
                "Search mail in a connected account. Returns subject, from, date, and snippet. "
                "Use for: 'Search my email for X', 'Find emails from Y', 'Latest invoice emails'. "
                "Always call mail_accounts first to get account_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "Account ID from mail_accounts"},
                    "query": {"type": "string", "description": "Search terms or Gmail-style query"},
                    "limit": {"type": "integer", "default": 10, "description": "Max results (1-20)"},
                },
                "required": ["account_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mail_read_message",
            "description": (
                "Read a mail message body (plain text). Use after mail_search to read a specific message. "
                "Never reads HTML. Never exposes tokens or passwords. "
                "Prefer search summaries — only read full body when user explicitly asks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "message_id": {"type": "string", "description": "Message ID from mail_search results"},
                },
                "required": ["account_id", "message_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# LLM selection
# ---------------------------------------------------------------------------

_LITELLM_PROXY_URL = os.getenv("LITELLM_PROXY_URL", "http://127.0.0.1:4000")


def _pick_litellm_model() -> tuple[str, str, str] | None:
    """Return (provider, litellm_model, api_key) routing through the LiteLLM proxy when available,
    falling back to direct cloud key selection."""
    master_key = os.getenv("LITELLM_MASTER_KEY", "")
    if master_key:
        # warden-code (Groq llama-3.3-70b) has reliable tool-calling support
        return "litellm-proxy", "openai/warden-code", master_key
    # Direct cloud fallback (no proxy)
    from src.marius.model_profiles import TOOL_CALL_CLOUD_CANDIDATES
    for cand in TOOL_CALL_CLOUD_CANDIDATES:
        key = os.getenv(cand["env"])
        if key:
            return cand["provider"], cand["model"], key
    return None


async def _litellm_chat(messages: list[dict], tools: list[dict] | None = None,
                        model: str = "", timeout: int = 60,
                        api_base: str | None = None, api_key: str | None = None) -> Any:
    import litellm
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "timeout": timeout}
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return await litellm.acompletion(**kwargs)


# ---------------------------------------------------------------------------
# Fallback: ReAct loop against Ollama (no tool-calling)
# ---------------------------------------------------------------------------

def _ollama_chat_sync(messages: list[dict], model: str, timeout: float = 60) -> str:
    import urllib.request
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(
        f"{os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"].strip()


def _react_fallback(message: str, history: list[dict]) -> "AgentResponse":
    """When no cloud key: gather context statically and ask Ollama to synthesise."""
    ctx = {
        "git": tool_git_log(10),
        "prs": tool_github_prs("open", 5),
        "memories": tool_recall_memories(message, 6),
        "context": tool_warden_context(message),
    }
    ctx_text = json.dumps(ctx, indent=2)[:4000]
    msgs = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "system", "content": f"# Gathered context\n{ctx_text}"},
    ] + history + [{"role": "user", "content": message}]

    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    # pick first available ollama model
    try:
        import urllib.request as _ur
        tags = json.loads(_ur.urlopen(f"{ollama_url}/api/tags", timeout=3).read())
        models = [m["name"] for m in tags.get("models", []) if "embed" not in m["name"]]
        ollama_model = models[0] if models else "llama3.2:3b"
    except Exception:
        ollama_model = "llama3.2:3b"

    try:
        reply = _ollama_chat_sync(msgs, ollama_model)
        _tu = [{"tool": k, "result_summary": "static gather"} for k in ctx]
        _srcs = ["git", "github", "memories", "context"]
        return AgentResponse(
            reply=reply,
            tools_used=_tu,
            sources=_srcs,
            model=ollama_model,
            provider="ollama",
            fallback=True,
            trace=_build_trace(_tu, _srcs, fallback=True),
        )
    except Exception as e:
        from .memory_agent import _fallback_structured_answer, gather_context
        mc = gather_context(message)
        _srcs = mc.source_labels()
        return AgentResponse(
            reply=_fallback_structured_answer(message, mc),
            tools_used=[],
            sources=_srcs,
            model="fallback",
            provider="fallback",
            fallback=True,
            trace=_build_trace([], _srcs, fallback=True),
        )


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

@dataclass
@dataclass
class TraceStep:
    """Single step in a Marius Trace."""
    type: str  # context_read | memory_read | memory_write | tool_action | proof | blocked | note
    label: str
    status: str = "ok"  # ok | skipped | blocked | error
    detail: str = ""
    ref: str = ""


@dataclass
class MarusTrace:
    """Response-level trace object for Marius Agent."""
    trace_id: str
    agent: str = "Marius Agent"
    steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "agent": self.agent, "steps": self.steps}


@dataclass
class AgentResponse:
    reply: str
    tools_used: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    fallback: bool = False
    trace: dict | None = None


def _build_trace(tools_used: list[dict], sources: list[str], fallback: bool) -> dict:
    """Build a Marius Trace dict from the agent run result."""
    import uuid as _uuid
    steps: list[dict] = []
    if fallback:
        steps.append({"type": "note", "label": "Fallback mode", "status": "ok",
                       "detail": "No cloud LLM available — using local context only.", "ref": ""})
    if "memory" in sources or any(t.get("tool", "").startswith("recall") for t in tools_used):
        steps.append({"type": "memory_read", "label": "Memory context loaded",
                       "status": "ok", "detail": "", "ref": ""})
    elif not fallback:
        steps.append({"type": "memory_read", "label": "Memory context",
                       "status": "skipped", "detail": "No memory queries issued", "ref": ""})
    for t in tools_used:
        tool_name = t.get("tool", "")
        if not tool_name:
            continue
        steps.append({
            "type": "tool_action",
            "label": tool_name,
            "status": "ok",
            "detail": t.get("result_preview", "")[:120],
            "ref": "",
        })
    if not tools_used and not fallback:
        steps.append({"type": "context_read", "label": "Context gathered",
                       "status": "ok", "detail": f"sources: {', '.join(sources) or 'none'}", "ref": ""})
    return MarusTrace(
        trace_id="trace-" + _uuid.uuid4().hex[:10],
        agent="Marius Agent",
        steps=steps,
    ).to_dict()


async def run_agent(message: str, history: list[dict] | None = None) -> AgentResponse:
    """
    Tool-calling agent loop. Returns AgentResponse with synthesised reply.
    Falls back to static gather + Ollama if no cloud key is available.
    """
    history = history or []
    cloud = _pick_litellm_model()

    if cloud is None:
        logger.info("No cloud key found — using ReAct/Ollama fallback")
        return _react_fallback(message, history)

    provider, model, api_key = cloud
    proxy_base = _LITELLM_PROXY_URL if provider == "litellm-proxy" else None
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": message})

    tools_used: list[dict] = []
    sources: set[str] = set()

    for iteration in range(MAX_ITERATIONS):
        resp = await _litellm_chat(messages, tools=TOOL_SCHEMAS, model=model,
                                   api_base=proxy_base, api_key=api_key)
        msg = resp.choices[0].message

        # No tool calls → final answer
        if not getattr(msg, "tool_calls", None):
            _srcs = sorted(sources)
            return AgentResponse(
                reply=msg.content or "",
                tools_used=tools_used,
                sources=_srcs,
                model=model,
                provider=provider,
                fallback=False,
                trace=_build_trace(tools_used, _srcs, fallback=False),
            )

        # Append assistant message — only standard OpenAI fields (strip provider_specific_fields etc.)
        tool_calls_raw = []
        for tc in (msg.tool_calls or []):
            tool_calls_raw.append({
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            })
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": tool_calls_raw,
        })

        # Execute each tool call
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            fn = TOOL_FUNCTIONS.get(fn_name)
            if fn is None:
                result = {"error": f"unknown tool: {fn_name}"}
            else:
                try:
                    result = fn(**args)
                except Exception as e:
                    result = {"error": str(e)}

            result_str = json.dumps(result, default=str)[:3000]
            tools_used.append({"tool": fn_name, "args": args, "result_preview": result_str[:200]})

            # Track sources
            _src_map = {
                "recall_memories": "memories", "warden_context": "memories",
                "git_log": "git",
                "github_prs": "github", "github_issues": "github",
                "web_search": "web", "crawl_url": "web",
                "mail_accounts": "mail", "mail_search": "mail", "mail_read_message": "mail",
            }
            if fn_name in _src_map:
                sources.add(_src_map[fn_name])

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": fn_name,
                "content": result_str,
            })

    # Max iterations hit — ask for final summary
    messages.append({"role": "user", "content": "Summarise what you found so far."})
    final = await _litellm_chat(messages, model=model)
    _srcs = sorted(sources)
    return AgentResponse(
        reply=final.choices[0].message.content or "",
        tools_used=tools_used,
        sources=_srcs,
        model=model,
        provider=provider,
        fallback=False,
        trace=_build_trace(tools_used, _srcs, fallback=False),
    )
