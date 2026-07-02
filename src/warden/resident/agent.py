"""Resident agent orchestration.

Routing order for every inbound message:
  1. Slash command (deterministic parse, no LLM)
  2. Keyword-intent match (deterministic classifier, no LLM)
  3. Ambiguous fallback -> only here may synthesis be invoked, and only if
     RESIDENT_ENABLE_DEEP_SYNTHESIS is set / the model profile allows it.

This keeps token/cost usage bounded: obvious intents and slash commands
never touch an LLM.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from . import config as config_mod
from . import router
from .formatting import get_more, is_more_request, truncate_for_chat
from .messages import InboundMessage, OutboundMessage
from .state import ResidentState, get_state
from .tools import TOOL_REGISTRY, ToolContext

# Injected by tests to verify obvious intents never call synthesis.
SynthesisFn = Callable[[str, dict], str]


def _default_synthesis(message: str, context: dict) -> str:
    """Only reached for genuinely ambiguous requests. Kept minimal/local —
    real deep synthesis would call out to memory_agent.chat/run_agent, but
    that is gated behind RESIDENT_ENABLE_DEEP_SYNTHESIS."""
    from ..memory_agent import chat as memory_agent_chat
    response = memory_agent_chat(message)
    return response.reply


class ResidentAgent:
    def __init__(
        self,
        cfg: Optional[config_mod.ResidentConfig] = None,
        state: Optional[ResidentState] = None,
        synthesis_fn: Optional[SynthesisFn] = None,
    ) -> None:
        self.cfg = cfg or config_mod.load_config()
        self.state = state or get_state(self.cfg.resident_db_path)
        self.tool_ctx = ToolContext(self.state, self.cfg)
        self.synthesis_fn = synthesis_fn or _default_synthesis
        self.synthesis_calls = 0  # test hook: count of synthesis invocations

    # -- public entrypoint ----------------------------------------------------

    def handle(self, inbound: InboundMessage) -> OutboundMessage:
        chat_id = inbound.chat_id
        text = inbound.text.strip()
        self.state.log_message(chat_id, "user", text)

        if is_more_request(text):
            full = get_more(chat_id)
            reply = full if full else "Nothing to expand."
            self.state.log_message(chat_id, "assistant", reply)
            return OutboundMessage(text=reply, chat_id=chat_id)

        parsed = router.parse_slash_command(text)
        if parsed is not None:
            reply = self._handle_slash(parsed)
        else:
            intent = router.classify(text)
            if intent.name == "ambiguous":
                reply = self._handle_ambiguous(text)
            else:
                reply = self._handle_intent(intent)

        final_text, truncated = truncate_for_chat(reply, self.cfg.max_response_chars, chat_id=chat_id)
        self.state.log_message(chat_id, "assistant", final_text)
        return OutboundMessage(text=final_text, chat_id=chat_id, truncated=truncated)

    # -- slash commands -------------------------------------------------------

    def _handle_slash(self, parsed: router.ParsedCommand) -> str:
        cmd = parsed.command
        args = parsed.args
        ctx = self.tool_ctx

        if cmd == "start":
            return "Warden resident agent online. Send /help for commands, or just talk to me naturally."
        if cmd == "help":
            return (
                "Commands: /status /memory <query> /watchers /agents /sessions "
                "/approvals /approve <id> /deny <id>\n"
                "Or just ask naturally: \"check my email\", \"what changed overnight\", "
                "\"watch dns for example.com\", \"what do I know about X\"."
            )
        if cmd == "status":
            return TOOL_REGISTRY["status"](ctx)["short_summary"]
        if cmd == "memory":
            if not args:
                return "Usage: /memory <query>"
            return TOOL_REGISTRY["memory_search"](ctx, args)["short_summary"]
        if cmd == "watchers":
            return TOOL_REGISTRY["watcher_list"](ctx)["short_summary"]
        if cmd == "agents":
            return TOOL_REGISTRY["agents_list"](ctx)["short_summary"]
        if cmd == "sessions":
            return TOOL_REGISTRY["sessions_list"](ctx)["short_summary"]
        if cmd == "approvals":
            return TOOL_REGISTRY["approvals_list"](ctx)["short_summary"]
        if cmd == "approve":
            if not args:
                return "Usage: /approve <id>"
            return TOOL_REGISTRY["approve"](ctx, args.split()[0])["short_summary"]
        if cmd == "deny":
            if not args:
                return "Usage: /deny <id>"
            return TOOL_REGISTRY["deny"](ctx, args.split()[0])["short_summary"]
        return f"Unknown command: {args or cmd}. Send /help for the list."

    # -- deterministic NL intents ----------------------------------------------

    def _handle_intent(self, intent: router.Intent) -> str:
        ctx = self.tool_ctx
        name = intent.name
        slots = intent.slots

        if name == "email_check":
            return TOOL_REGISTRY["email_summary"](ctx)["short_summary"]
        if name == "email_urgent":
            return TOOL_REGISTRY["email_urgent"](ctx)["short_summary"]
        if name == "email_draft":
            return "To draft a reply I need the recipient and body — reply with: draft to <email>: <message>"
        if name == "email_send":
            return (
                "Sending requires a recipient and body already established in this conversation. "
                "Which email address should I send to, and what should it say?"
            )
        if name == "overnight_summary":
            return self._overnight_summary()
        if name == "webstudio_audit":
            site = slots.get("site_name") or slots.get("domain")
            if not site:
                return "Which site should I audit? (e.g. \"run webstudio audit on unlck\")"
            return TOOL_REGISTRY["webstudio_audit"](ctx, site)["short_summary"]
        if name == "dns_watch":
            domain = slots.get("domain")
            if not domain:
                return "Which domain should I watch DNS for?"
            return TOOL_REGISTRY["webstudio_dns_watch"](ctx, domain)["short_summary"]
        if name == "memory_search":
            query = slots.get("query", "")
            if not query:
                return "What would you like me to search memory for?"
            return TOOL_REGISTRY["memory_search"](ctx, query)["short_summary"]
        if name == "memory_remember":
            note = slots.get("note", "")
            return TOOL_REGISTRY["memory_remember"](ctx, note)["short_summary"]
        if name == "agents_status":
            return TOOL_REGISTRY["agents_list"](ctx)["short_summary"]
        if name == "sessions_stop":
            return TOOL_REGISTRY["session_stop"](ctx, slots.get("session_match", ""))["short_summary"]
        if name == "status":
            return TOOL_REGISTRY["status"](ctx)["short_summary"]

        return self._handle_ambiguous(name)

    def _overnight_summary(self) -> str:
        """Tier 2/3 context pack: watcher events + running sessions + recent memory."""
        ctx = self.tool_ctx
        watcher_result = TOOL_REGISTRY["watcher_run_due"](ctx)
        sessions_result = TOOL_REGISTRY["sessions_list"](ctx)
        memory_result = TOOL_REGISTRY["memory_recent"](ctx, self.cfg.max_context_items)
        parts = [
            f"Watchers: {watcher_result['short_summary']}",
            f"Sessions: {sessions_result['short_summary']}",
            f"Recent memory: {memory_result['short_summary']}",
        ]
        return "\n\n".join(parts)

    # -- ambiguous fallback -----------------------------------------------------

    def _handle_ambiguous(self, text: str) -> str:
        if not self.cfg.enable_deep_synthesis:
            return (
                "I didn't recognize a specific command for that. Try /help, or rephrase — "
                "e.g. \"check my email\", \"what do I know about X\", \"what changed overnight\"."
            )
        self.synthesis_calls += 1
        try:
            return self.synthesis_fn(text, {})
        except Exception as exc:
            return f"Synthesis failed: {exc}"
