import pytest
import os
import json
from pathlib import Path
from src.marius.brain_ingest import BrainIngest

def test_add_text_creates_record(tmp_path):
    bi = BrainIngest()
    bi.data_path = tmp_path / "records.jsonl"
    
    res = bi.add_text("This is a test note about GradeMy.", "Test Note", project="grademy", tags=["test"])
    assert res["ok"]
    assert res["record"]["project"] == "grademy"
    assert "GradeMy" in res["record"]["summary"]
    
    # Verify file
    with open(bi.data_path, "r") as f:
        line = f.readline()
        record = json.loads(line)
        assert record["title"] == "Test Note"

def test_safety_scan_rejects_secrets():
    bi = BrainIngest()
    res = bi.add_text("My secret is API_KEY=sk-123456", "Secret Note")
    assert not res["ok"]
    assert "secret indicator" in res["error"]
