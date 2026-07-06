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


def test_browser_ingest_browse_event_captures_title_url_not_full_body(isolated_workbench):
    """Documents current capture fidelity for a plain page visit ("browse" kind).

    Title, URL, and dwell/scroll metadata are stored. Full page body text is
    NOT sent by this event kind and NOT stored — there is no extractive
    summary or raw content field for a bare page visit today.
    TODO(personal-ai-os): once the browser extension sends page body text for
    "browse" events, extend this test to assert body/content is retrievable.
    """
    event = {
        "kind": "browse",
        "url": "https://aimaker.substack.com/p/claude-code-guide-starter-template",
        "title": "The Complete Guide to Build Your Personal AI Operating System With Claude Code",
        "dwell_sec": 42,
        "scroll_pct": 80,
        "ts": "2026-07-06T00:19:33Z",
        "source": "browser",
    }
    resp = api.browser_ingest(api.BrowserIngestRequest(events=[event]))
    assert resp["stored"] == 1

    store = workbench_mod.WorkbenchStore()
    memories = store.list_memories()
    assert len(memories) == 1
    memory = memories[0]

    assert memory.title and "Personal AI Operating System" in memory.title
    assert memory.metadata["url"] == event["url"]
    assert memory.metadata["title"] == event["title"]

    # Current gap: no page body is captured for a "browse" event.
    assert "text" not in event
    assert "content" not in memory.metadata
    assert "body" not in memory.metadata


def test_brain_ingest_webpage_truncates_content_and_drops_structured_url(tmp_path):
    """Documents current capture fidelity for the Brain vault ingest pipeline.

    Full page text passed in IS captured, but hard-truncated to 2000 chars in
    the note body, and the source URL is embedded only as a body text line
    ("**Source:** <url>"), not as a parseable frontmatter field.
    TODO(personal-ai-os): store full raw content (bounded, redacted) and a
    structured source_url frontmatter field so retrieval doesn't depend on
    parsing prose out of the note body.
    """
    long_text = "Sentence number %d provides filler content for this test. "
    full_content = "".join(long_text % i for i in range(200))
    assert len(full_content) > 2000

    result = brain_ingest.ingest_webpage(
        url="https://aimaker.substack.com/p/llm-wiki-obsidian-knowledge-base-andrej-karphaty",
        title="How I Took Karpathy's LLM Wiki and Built an AI-Powered Second Brain in Obsidian",
        content_text=full_content,
        vault_path=tmp_path,
        local_only=True,
    )
    assert result["ok"] is True

    note_path = tmp_path / result["note_path"]
    note_text = note_path.read_text(encoding="utf-8")

    fm, body = brain_vault._parse_frontmatter(note_text)
    assert "url" not in fm  # gap: source URL is not structured frontmatter

    assert "**Source:** https://aimaker.substack.com" in body
    assert full_content[:500] in body  # summary/excerpt survives
    assert full_content[1900:] not in body  # tail of the page is lost
