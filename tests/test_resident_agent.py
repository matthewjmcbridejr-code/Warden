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
    out = agent.handle(InboundMessage(text="tell me a joke about the moon landing", chat_id=1))
    assert agent.synthesis_calls == 0
    assert "didn't recognize" in out.text.lower() or "/help" in out.text


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
