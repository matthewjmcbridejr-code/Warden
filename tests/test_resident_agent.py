"""Agent orchestration tests — deterministic routing must never call synthesis
for obvious intents/simple commands."""
import pytest

from src.warden.resident.agent import ResidentAgent
from src.warden.resident.config import ResidentConfig
from src.warden.resident.messages import InboundMessage
from src.warden.resident.state import ResidentState


@pytest.fixture
def agent(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "resident.sqlite"))
    state = ResidentState(cfg.resident_db_path)
    synthesis_calls = {"count": 0}

    def fake_synthesis(message, context):
        synthesis_calls["count"] += 1
        return "synthesized reply"

    a = ResidentAgent(cfg=cfg, state=state, synthesis_fn=fake_synthesis)
    a._synthesis_calls_tracker = synthesis_calls
    return a


def test_slash_start_does_not_call_synthesis(agent):
    out = agent.handle(InboundMessage(text="/start", chat_id=1))
    assert "online" in out.text.lower()
    assert agent.synthesis_calls == 0


def test_slash_help_does_not_call_synthesis(agent):
    out = agent.handle(InboundMessage(text="/help", chat_id=1))
    assert "/status" in out.text
    assert agent.synthesis_calls == 0


def test_nl_check_email_does_not_call_synthesis(agent):
    out = agent.handle(InboundMessage(text="check my email", chat_id=1))
    assert "email" in out.text.lower() or "disabled" in out.text.lower()
    assert agent.synthesis_calls == 0


def test_nl_memory_search_does_not_call_synthesis(agent):
    out = agent.handle(InboundMessage(text="what do I know about warden", chat_id=1))
    assert agent.synthesis_calls == 0


def test_nl_overnight_summary_does_not_call_synthesis(agent):
    out = agent.handle(InboundMessage(text="what changed overnight", chat_id=1))
    assert "Watchers" in out.text
    assert agent.synthesis_calls == 0


def test_ambiguous_request_with_synthesis_disabled_gives_static_reply(agent):
    assert agent.cfg.enable_deep_synthesis is False
    assert agent.cfg.enable_general_chat is False
    out = agent.handle(InboundMessage(text="tell me a joke about the moon landing", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "focused on warden operations" in out.text.lower()


def test_ambiguous_warden_adjacent_request_suggests_capabilities(agent):
    out = agent.handle(InboundMessage(text="tell me something about the agent situation", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "/help" in out.text


def test_ambiguous_request_with_synthesis_enabled_calls_synthesis(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "resident2.sqlite"), enable_deep_synthesis=True)
    state = ResidentState(cfg.resident_db_path)
    calls = {"count": 0}

    def fake_synthesis(message, context):
        calls["count"] += 1
        return "synthesized reply"

    agent = ResidentAgent(cfg=cfg, state=state, synthesis_fn=fake_synthesis)
    out = agent.handle(InboundMessage(text="tell me a joke about the moon landing", chat_id=1))
    assert calls["count"] == 1
    assert out.text == "synthesized reply"


def test_email_send_asks_clarifying_question_without_recipient(agent):
    out = agent.handle(InboundMessage(text="send it", chat_id=1))
    assert "recipient" in out.text.lower() or "which email" in out.text.lower()
    assert agent.synthesis_calls == 0


def test_dns_watch_requires_domain(agent):
    out = agent.handle(InboundMessage(text="watch dns for unlck.shop", chat_id=1))
    assert "unlck.shop" in out.text or "watching" in out.text.lower()


def test_response_is_truncated_when_too_long(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "r3.sqlite"), max_response_chars=50)
    state = ResidentState(cfg.resident_db_path)
    agent = ResidentAgent(cfg=cfg, state=state)
    out = agent.handle(InboundMessage(text="/help", chat_id=1))
    assert len(out.text) <= 50 + len("\n\n(truncated — reply \"more\" for the full output)")
    assert out.truncated is True


@pytest.mark.parametrize("phrase", [
    "what happened recently",
    "what changed recently",
    "what happened overnight",
    "what changed overnight",
    "catch me up",
    "what did I miss",
    "anything new",
    "what's going on",
    "recent status",
    "daily brief",
    "overnight brief",
])
def test_recap_phrase_variants_route_to_recap(agent, phrase):
    out = agent.handle(InboundMessage(text=phrase, chat_id=1))
    assert "Watchers" in out.text and "Approvals" in out.text
    assert agent.synthesis_calls == 0


def test_brief_slash_command_routes_to_recap(agent):
    out = agent.handle(InboundMessage(text="/brief", chat_id=1))
    assert "Watchers" in out.text and "Approvals" in out.text
    assert agent.synthesis_calls == 0


def test_email_status_slash_command(agent):
    out = agent.handle(InboundMessage(text="/email status", chat_id=1))
    assert "email" in out.text.lower()
    assert agent.synthesis_calls == 0


def test_email_status_gmail_mode_no_account_explains_gap(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "r4.sqlite"), email_mode="gmail")
    state = ResidentState(cfg.resident_db_path)
    agent = ResidentAgent(cfg=cfg, state=state)
    out = agent.handle(InboundMessage(text="/email status", chat_id=1))
    assert "gmail" in out.text.lower()
    assert "not" in out.text.lower() or "cannot" in out.text.lower() or "no gmail" in out.text.lower()


def test_status_reports_all_fields(agent):
    out = agent.handle(InboundMessage(text="/status", chat_id=1))
    lowered = out.text.lower()
    assert "api" in lowered
    assert "agents" in lowered
    assert "sessions" in lowered
    assert "watchers" in lowered
    assert "approvals" in lowered
    assert "email" in lowered
    assert "dry-run" in lowered


def test_unknown_warden_adjacent_message_gets_capability_hint(agent):
    out = agent.handle(InboundMessage(text="something about my watchers is confusing", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "/help" in out.text


def test_unknown_general_message_respects_general_chat_disabled(agent):
    assert agent.cfg.enable_general_chat is False
    out = agent.handle(InboundMessage(text="why is the sky blue", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "focused on warden operations" in out.text.lower()


def test_unknown_general_message_with_general_chat_enabled(tmp_path):
    cfg = ResidentConfig(resident_db_path=str(tmp_path / "r5.sqlite"), enable_general_chat=True)
    state = ResidentState(cfg.resident_db_path)
    agent = ResidentAgent(cfg=cfg, state=state)
    out = agent.handle(InboundMessage(text="why is the sky blue", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "focused on warden operations" not in out.text.lower()
