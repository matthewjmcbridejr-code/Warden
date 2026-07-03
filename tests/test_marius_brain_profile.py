import pytest
from pathlib import Path
from src.marius.brain_ingest import BrainIngest

def test_ingest_profiles_creates_records(tmp_path):
    bi = BrainIngest()
    bi.data_path = tmp_path / "records.jsonl"
    
    # Create a dummy profile
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "MATT_PROFILE.md").write_text("# Matt Profile\nAssistant rules.")
    
    bi.ingest_profiles = lambda: BrainIngest.ingest_profiles(bi) # Use real method but ensure bi instance
    # Mocking PROFILE_DIR to use our temp one
    import src.marius.brain_ingest
    src.marius.brain_ingest.PROFILE_DIR = profile_dir
    
    res = bi.ingest_profiles()
    assert res["count"] >= 1
    
    with open(bi.data_path, "r") as f:
        records = [line for line in f]
        assert len(records) >= 1
