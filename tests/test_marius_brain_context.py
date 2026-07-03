import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.marius.brain_context import build_brain_context_pack
from src.marius.search_provider import LocalJsonlSearchProvider

@pytest.fixture
def mock_brain_data(tmp_path):
    records_file = tmp_path / "records.jsonl"
    records = [
        {
            "id": "rec1",
            "title": "Matt Profile",
            "project": "personal",
            "collection": "profile",
            "text": "Matt prefers direct technical commands and Pacific time.",
            "snippet": "Matt prefers direct technical commands...",
            "sensitivity": "public"
        },
        {
            "id": "rec2",
            "title": "GradeMy Priority",
            "project": "grademy",
            "collection": "note",
            "text": "Priority is AI visibility tests and Shopify app.",
            "snippet": "Priority is AI visibility tests...",
            "sensitivity": "public"
        },
        {
            "id": "rec3",
            "title": "Secret Note",
            "project": "personal",
            "collection": "note",
            "text": "Secret key is 12345",
            "snippet": "Secret key is...",
            "sensitivity": "secret_excluded"
        }
    ]
    with open(records_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return records_file

def test_build_brain_context_pack_finds_profile(mock_brain_data, tmp_path):
    with patch("src.marius.search_provider.Path.home", return_value=tmp_path.parent):
        # We need to make sure LocalJsonlSearchProvider uses our mock_brain_data
        # LocalJsonlSearchProvider uses Path.home() / ".local/share/marius/brain/records.jsonl"
        brain_dir = tmp_path.parent / ".local" / "share" / "marius" / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        records_path = brain_dir / "records.jsonl"
        import shutil
        shutil.copy(mock_brain_data, records_path)
        
        pack = build_brain_context_pack("Matt prefers direct technical commands")
        assert pack["results"]
        assert any("Matt Profile" in r["title"] for r in pack["results"])
        assert "MARIUS BRAIN CONTEXT" in pack["context_text"]
        assert "rec1" in pack["record_ids"]

def test_build_brain_context_pack_excludes_secrets(mock_brain_data, tmp_path):
    with patch("src.marius.search_provider.Path.home", return_value=tmp_path.parent):
        brain_dir = tmp_path.parent / ".local" / "share" / "marius" / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        records_path = brain_dir / "records.jsonl"
        import shutil
        shutil.copy(mock_brain_data, records_path)
        
        pack = build_brain_context_pack("secret")
        assert "rec3" not in pack["record_ids"]
        # It might find nothing if rec3 was the only match
