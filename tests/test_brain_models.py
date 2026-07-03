"""Tests for Warden Brain data models."""
import pytest
from src.warden.brain.models import BrainSource, BrainChunk, BrainCitation, BrainAnswer


def test_brain_answer_to_dict():
    ans = BrainAnswer(
        answer="Test answer",
        citations=[BrainCitation(
            source_path="00-inbox/test.md",
            title="Test",
            heading="Heading",
            excerpt="Some text",
            provider="local",
        )],
        confidence=0.8,
        provider_used="local",
        local_count=2,
    )
    d = ans.to_dict()
    assert d["answer"] == "Test answer"
    assert d["confidence"] == 0.8
    assert d["provider_used"] == "local"
    assert d["provider_results"]["local"] == 2
    assert d["citations"][0]["provider"] == "local"
    assert d["citations"][0]["source_path"] == "00-inbox/test.md"


def test_brain_answer_no_secrets():
    ans = BrainAnswer(answer="result", provider_used="local")
    d = ans.to_dict()
    text = str(d)
    assert "access_token" not in text
    assert "refresh_token" not in text
    assert "client_secret" not in text


def test_brain_source_defaults():
    src = BrainSource(
        source_id="abc123",
        path="00-inbox/note.md",
        title="My Note",
        tags=["warden"],
        headings=["Intro"],
        word_count=50,
        checksum="deadbeef",
    )
    assert src.provider == "local"
    assert src.indexed_at is None


def test_brain_chunk_fields():
    chunk = BrainChunk(
        chunk_id="ch1",
        source_id="s1",
        source_path="path/to/file.md",
        title="Title",
        heading="Section",
        text="Some content here.",
    )
    assert chunk.provider == "local"
    assert chunk.text == "Some content here."
