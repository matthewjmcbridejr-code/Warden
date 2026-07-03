import pytest
import os
from pathlib import Path

def test_old_code_recovery_doc_exists():
    p = Path("docs/marius_v3_old_code_recovery.md")
    assert p.exists()
    content = p.read_text()
    assert "Marius v3 Old Code Recovery" in content
    assert "marius_telegram_bot.md" in content
    assert "marius_persona.md" in content
    assert "Console Mode:" in content

def test_slack_future_doc_exists():
    p = Path("docs/marius_slack_future.md")
    assert p.exists()
    content = p.read_text()
    assert "Socket Mode Only" in content
