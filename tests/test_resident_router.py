"""Command parsing + deterministic NL intent routing tests."""
from src.warden.resident import router


def test_parse_slash_command_basic():
    parsed = router.parse_slash_command("/status")
    assert parsed.command == "status"
    assert parsed.args == ""


def test_parse_slash_command_with_args():
    parsed = router.parse_slash_command("/memory warden dns migration")
    assert parsed.command == "memory"
    assert parsed.args == "warden dns migration"


def test_parse_slash_command_unknown():
    parsed = router.parse_slash_command("/frobnicate")
    assert parsed.command == "unknown"


def test_parse_slash_command_non_slash_returns_none():
    assert router.parse_slash_command("hello there") is None


def test_classify_email_check():
    intent = router.classify("check my email")
    assert intent.name == "email_check"


def test_classify_email_draft():
    intent = router.classify("draft a reply to Bob")
    assert intent.name == "email_draft"


def test_classify_email_send():
    intent = router.classify("send it")
    assert intent.name == "email_send"


def test_classify_overnight_summary():
    intent = router.classify("what changed overnight")
    assert intent.name == "overnight_summary"


def test_classify_dns_watch_extracts_domain():
    intent = router.classify("watch dns for example.com")
    assert intent.name == "dns_watch"
    assert intent.slots.get("domain") == "example.com"


def test_classify_memory_search():
    intent = router.classify("what do I know about the migration")
    assert intent.name == "memory_search"
    assert "migration" in intent.slots.get("query", "")


def test_classify_memory_remember():
    intent = router.classify("save this to memory: the sky is blue")
    assert intent.name == "memory_remember"


def test_classify_agents_status():
    intent = router.classify("what are agents doing")
    assert intent.name == "agents_status"


def test_classify_sessions_stop():
    intent = router.classify("stop that session")
    assert intent.name == "sessions_stop"


def test_classify_ambiguous_fallback():
    intent = router.classify("tell me a joke about quantum physics")
    assert intent.name == "ambiguous"


def test_classify_empty_string_is_ambiguous():
    intent = router.classify("   ")
    assert intent.name == "ambiguous"
