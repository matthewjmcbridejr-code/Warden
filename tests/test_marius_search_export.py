import pytest
import json
import os
from pathlib import Path
from src.marius.search_export import SearchExporter, export_project_context

def test_search_exporter_skips_secrets(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    # Safe file
    safe_file = repo_root / "README.md"
    safe_file.write_text("This is a safe file.")
    
    # Secret file (by name)
    secret_file_name = repo_root / ".env"
    secret_file_name.write_text("VAR=VALUE")
    
    # Secret file (by content)
    secret_file_content = repo_root / "config.py"
    secret_file_content.write_text("API_KEY=sk-123456789")
    
    # Another secret file (by content)
    pem_file = repo_root / "key.pem"
    pem_file.write_text("-----BEGIN PRIVATE KEY-----")
    
    exporter = SearchExporter(repo_root, tmp_path / "exports")
    
    # Manually override should_index to include config.py for testing secret detection
    # because by default .py files in root might not be indexed unless they are README*
    orig_should_index = exporter.should_index
    def mock_should_index(path):
        if path.name == "config.py": return True
        return orig_should_index(path)
    exporter.should_index = mock_should_index
    
    output_file = exporter.export_project("test_project")
    
    assert output_file.exists()
    with open(output_file, "r") as f:
        lines = f.readlines()
        
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["title"] == "README.md"
    assert "README.md" in record["source_path"]
    
    # Check that secrets were skipped
    assert any("config.py" in s for s in exporter.skipped_files)
    assert not any("VAR=VALUE" in line for line in lines)
    assert not any("PRIVATE KEY" in line for line in lines)

def test_export_project_context_real_repo_smoke():
    repo_root = Path(__file__).resolve().parents[2]
    # Use a temp output dir
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = export_project_context("mcharness", str(repo_root), tmp_dir)
        assert output_file.exists()
        assert output_file.stat().st_size > 0
        
        with open(output_file, "r") as f:
            first_line = f.readline()
            record = json.loads(first_line)
            assert record["project"] == "mcharness"
            assert "text" in record
