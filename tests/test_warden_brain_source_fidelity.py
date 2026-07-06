"""Source-fidelity diagnostics for Warden Brain ingest paths.

Personal AI OS foundation pass: these tests prove what is and is not
captured today for browser/page captures, ahead of building distillation
features on top. See docs/personal_ai_os_plan.md for the gap analysis.
"""
from __future__ import annotations

import asyncio

import pytest

import src.warden.api as api
import src.warden.workbench as workbench_mod
from src.warden.brain import ingest as brain_ingest
from src.warden.brain import vault as brain_vault


class FakeBrowserRequest:
    def __init__(self, events: list[dict]):
        self.events = events


@pytest.fixture()
def isolated_workbench(tmp_path, monkeypatch):
    """Redirect WorkbenchStore()'s default root to a tmp dir.

    WorkbenchStore.root defaults to the WORKBENCH_ROOT module constant bound
    at class-definition time, so patching the module attribute at test time
    has no effect on new WorkbenchStore() instances (e.g. inside
    api.browser_ingest). Patch the bound default instead.
    """
    root = tmp_path / "workbench"
    monkeypatch.setattr(
        workbench_mod.WorkbenchStore.__init__,
        "__defaults__",
        (root, True),
    )
    yield root


def test_browser_ingest_browse_event_captures_bounded_raw_body(isolated_workbench):
    """v2.4 capture fidelity: a "browse" event carrying body_text stores bounded
    raw_content with an explicit truncation flag; without body_text the memory
    still records title/URL metadata and raw_content stays empty."""
    body = "Paragraph three says something specific. " * 400  # > 12k chars
    event = {
        "kind": "browse",
        "url": "https://aimaker.substack.com/p/claude-code-guide-starter-template",
        "title": "The Complete Guide to Build Your Personal AI Operating System With Claude Code",
        "dwell_sec": 42,
        "scroll_pct": 80,
        "ts": "2026-07-06T00:19:33Z",
        "source": "browser",
        "body_text": body,
    }
    resp = api.browser_ingest(api.BrowserIngestRequest(events=[event]))
    assert resp["stored"] == 1

    store = workbench_mod.WorkbenchStore()
    memories = store.list_memories()
    assert len(memories) == 1
    memory = memories[0]

    assert memory.title and "Personal AI Operating System" in memory.title
    assert memory.metadata["url"] == event["url"]
    assert memory.raw_content and "Paragraph three says something specific." in memory.raw_content
    assert len(memory.raw_content) <= 12000
    assert memory.raw_content_truncated is True

    # Without body_text, raw_content stays honestly empty.
    event2 = dict(event, url=event["url"] + "?v=2", title="No body variant")
    event2.pop("body_text")
    resp2 = api.browser_ingest(api.BrowserIngestRequest(events=[event2]))
    assert resp2["stored"] == 1
    no_body = [m for m in store.list_memories() if m.title and "No body" in m.title][0]
    assert no_body.raw_content is None
    assert no_body.raw_content_truncated is False


def test_brain_ingest_webpage_stores_bounded_content_and_structured_url(tmp_path):
    """v2.4 capture fidelity for the Brain vault pipeline: content is bounded at
    RAW_NOTE_CONTENT_MAX (not the old 2,000-char excerpt), truncation is flagged
    in frontmatter, and the source URL is structured frontmatter."""
    long_text = "Sentence number %d provides filler content for this test. "
    full_content = "".join(long_text % i for i in range(200))
    assert 2000 < len(full_content) < brain_ingest.RAW_NOTE_CONTENT_MAX

    result = brain_ingest.ingest_webpage(
        url="https://aimaker.substack.com/p/llm-wiki-obsidian-knowledge-base-andrej-karphaty",
        title="How I Took Karpathy's LLM Wiki and Built an AI-Powered Second Brain in Obsidian",
        content_text=full_content,
        vault_path=tmp_path,
        local_only=True,
    )
    assert result["ok"] is True
    assert result["raw_content_truncated"] is False

    note_path = tmp_path / result["note_path"]
    note_text = note_path.read_text(encoding="utf-8")

    fm, body = brain_vault._parse_frontmatter(note_text)
    assert fm.get("url", "").startswith("https://aimaker.substack.com")
    assert fm.get("raw_content_truncated") == "false"

    assert "**Source:** https://aimaker.substack.com" in body
    assert full_content[:500] in body
    assert full_content[1900:2100] in body  # tail past the old 2k cut now survives

    # Index entry written (PR 4 linking).
    index = (tmp_path / "00-index.md").read_text(encoding="utf-8")
    assert "Karpathy" in index


def test_brain_ingest_flags_truncation_past_bound(tmp_path):
    huge = "x" * (brain_ingest.RAW_NOTE_CONTENT_MAX + 500)
    result = brain_ingest.ingest_webpage(
        url="https://example.com/huge-page",
        title="Huge page",
        content_text=huge,
        vault_path=tmp_path,
        local_only=True,
    )
    assert result["ok"] is True
    assert result["raw_content_truncated"] is True
    fm, body = brain_vault._parse_frontmatter((tmp_path / result["note_path"]).read_text(encoding="utf-8"))
    assert fm.get("raw_content_truncated") == "true"
    assert "truncated at" in body
