import pytest
import json
import os
from pathlib import Path
from src.marius.search_provider import LocalJsonlSearchProvider

def test_local_search_provider_smoke(tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    
    # Create fake export
    export_file = exports_dir / "warden.jsonl"
    record = {
        "id": "123",
        "project": "warden",
        "source_path": "README.md",
        "title": "README.md",
        "text": "Warden is Matt's terminal-agent control plane.",
        "timestamp": "2026-06-16T12:00:00"
    }
    with open(export_file, "w") as f:
        f.write(json.dumps(record) + "\n")
        
    provider = LocalJsonlSearchProvider(exports_dir=exports_dir, brain_data=tmp_path / "records.jsonl")
    
    # Test status
    status = provider.status()
    assert status["provider"] == "local"
    assert len(status["exports"]) == 1
    
    # Test search match
    results = provider.search("Warden", project="warden")
    assert len(results) == 1
    assert results[0]["project"] == "warden"
    assert "Warden" in results[0]["snippet"]
    
    # Test search no match
    results = provider.search("MCTable")
    assert len(results) == 0

def test_local_search_ranking(tmp_path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    
    export_file = exports_dir / "test.jsonl"
    records = [
        {"id": "r1", "project": "t", "title": "low", "text": "one match"},
        {"id": "r2", "project": "t", "title": "high match", "text": "high high high high"}
    ]
    with open(export_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
            
    provider = LocalJsonlSearchProvider(exports_dir=exports_dir, brain_data=tmp_path / "records.jsonl")
    results = provider.search("high")
    
    assert len(results) == 1
    assert results[0]["record_id"] == "r2"
