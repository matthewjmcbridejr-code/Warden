"""Tests for the wiki distillation scaffolding (src/warden/brain/wiki.py).

Covers: page creation, redistillation updating a page in place instead of
duplicating it, index.md/log.md maintenance, and that a distilled page is
actually searchable via the same index the rest of the brain uses.
"""
from __future__ import annotations

from pathlib import Path

from src.warden.brain.index import fts_search
from src.warden.brain.vault import init_vault
from src.warden.brain.wiki import distill_note, list_wiki_pages, parse_wikilinks, slugify


def _vp(tmp_path: Path) -> Path:
    vp = tmp_path / "vault"
    init_vault(vp)
    return vp


def test_slugify_is_stable_and_safe():
    assert slugify("Proof-Gated Agent Loop!") == "proof-gated-agent-loop"
    assert slugify("   ") == "untitled"


def test_distill_note_creates_page_with_sections(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    result = distill_note(
        title="Proof-Gated Agent Loop",
        definition="An agent loop where every action must produce verifiable proof before being marked complete.",
        principles=["Never trust a self-reported ok:true", "Proof lives next to the claim"],
        examples=["Warden's brain ingest fix required grepping the filesystem for the returned ID"],
        tags=["warden", "agents"],
        links=[],
        source_path="10-projects/warden-notes.md",
        vault_path=vp,
        index_path=idx,
    )

    assert result["ok"] is True
    assert result["created"] is True
    assert result["updated"] is False
    assert result["slug"] == "proof-gated-agent-loop"

    page_path = vp / "wiki" / "proof-gated-agent-loop.md"
    assert page_path.exists()
    text = page_path.read_text(encoding="utf-8")
    assert "title: Proof-Gated Agent Loop" in text
    assert "source: 10-projects/warden-notes.md" in text
    assert "## Key Principles" in text
    assert "Never trust a self-reported ok:true" in text
    assert "## Examples" in text


def test_redistilling_same_title_updates_in_place(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    first = distill_note(
        title="Content Hash Dedupe",
        definition="Hash the body of a note to detect duplicates before writing it anywhere.",
        principles=["Hash the body, not the frontmatter"],
        vault_path=vp,
        index_path=idx,
    )
    assert first["created"] is True

    second = distill_note(
        title="Content Hash Dedupe",
        definition="Updated: hash the normalized body to detect duplicates across re-ingests.",
        principles=["Hash the body, not the frontmatter", "Normalize whitespace before hashing"],
        vault_path=vp,
        index_path=idx,
    )
    assert second["created"] is False
    assert second["updated"] is True
    assert second["slug"] == first["slug"]

    matches = list(vp.glob("wiki/*.md"))
    page_files = [p for p in matches if p.name not in ("index.md", "log.md")]
    assert len(page_files) == 1

    text = page_files[0].read_text(encoding="utf-8")
    assert "Normalize whitespace before hashing" in text
    assert "Hash the normalized body" in text.replace("\n", " ") or "Updated:" in text


def test_distill_note_maintains_index_and_log(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    distill_note(
        title="Second Brain Compounding",
        definition="Each new distilled source becomes more valuable because it connects to what already exists.",
        vault_path=vp,
        index_path=idx,
    )

    index_text = (vp / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "[[Second Brain Compounding]]" in index_text

    log_text = (vp / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "created" in log_text
    assert "[[Second Brain Compounding]]" in log_text

    # Redistilling updates the same index line instead of appending a second one
    distill_note(
        title="Second Brain Compounding",
        definition="Updated definition.",
        vault_path=vp,
        index_path=idx,
    )
    index_text_2 = (vp / "wiki" / "index.md").read_text(encoding="utf-8")
    assert index_text_2.count("[[Second Brain Compounding]]") == 1


def test_distilled_page_is_searchable(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"

    distill_note(
        title="Tight Linking Principle",
        definition="Only link two wiki pages when understanding one would meaningfully change how you see the other.",
        vault_path=vp,
        index_path=idx,
    )

    hits = fts_search("meaningfully change", index_path=idx, limit=5)
    assert any("Tight Linking Principle" in (h.title or "") for h in hits)


def test_distill_note_requires_title_and_definition(tmp_path):
    vp = _vp(tmp_path)
    try:
        distill_note(title="", definition="x", vault_path=vp)
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        distill_note(title="X", definition="", vault_path=vp)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_wikilinks_extracts_titles():
    text = "See [[Proof-Gated Agent Loop]] and also [[Content Hash Dedupe|dedupe]]."
    links = parse_wikilinks(text)
    assert "Proof-Gated Agent Loop" in links
    assert "Content Hash Dedupe" in links


def test_list_wiki_pages_returns_metadata(tmp_path):
    vp = _vp(tmp_path)
    idx = tmp_path / "brain.sqlite3"
    distill_note(title="Page One", definition="First page.", vault_path=vp, index_path=idx)
    distill_note(title="Page Two", definition="Second page.", links=["Page One"], vault_path=vp, index_path=idx)

    pages = list_wiki_pages(vp)
    titles = {p["title"] for p in pages}
    assert titles == {"Page One", "Page Two"}
    page_two = next(p for p in pages if p["title"] == "Page Two")
    assert "Page One" in page_two["links"]
