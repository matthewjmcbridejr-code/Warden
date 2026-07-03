import pytest
from src.marius.brain_ingest import BrainIngest

def test_add_file_ingests_markdown(tmp_path):
    bi = BrainIngest()
    bi.data_path = tmp_path / "records.jsonl"
    
    test_file = tmp_path / "note.md"
    test_file.write_text("# Test Note\nDetails about Warden.")
    
    res = bi.add_file(test_file, project="warden")
    assert res["ok"]
    assert res["record"]["title"] == "note.md"
    assert "Warden" in res["record"]["text"]

def test_add_file_rejects_binary(tmp_path):
    bi = BrainIngest()
    
    binary_file = tmp_path / "data.bin"
    with open(binary_file, "wb") as f:
        f.write(b"\x80\x81\x82")
    
    res = bi.add_file(binary_file)
    assert not res["ok"]
    assert "Unsupported" in res["error"] or "binary" in res["error"]
