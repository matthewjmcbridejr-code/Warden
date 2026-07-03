import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Secret indicators to exclude files
SECRET_INDICATORS = [
    "PRIVATE KEY",
    "API_KEY=",
    "SECRET=",
    "TOKEN=",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "Authorization:",
    "Bearer",
    "password="
]

# Files/Directories to skip
EXCLUDE_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", "dist", "build",
    ".pytest_cache", "google-cloud-sdk", ".agents", ".codex"
}
EXCLUDE_EXTENSIONS = {
    ".pem", ".key", ".exe", ".bin", ".pyc", ".so", ".dll", ".zip", ".tar.gz", ".tgz"
}

class SearchExporter:
    def __init__(self, repo_root: Path, output_dir: Optional[Path] = None):
        self.repo_root = repo_root
        self.output_dir = output_dir or Path.home() / ".local" / "share" / "marius" / "brain" / "exports"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.skipped_files = []

    def is_binary(self, file_path: Path) -> bool:
        try:
            with open(file_path, "tr") as check_file:
                check_file.read(512)
                return False
        except UnicodeDecodeError:
            return True

    def contains_secrets(self, content: str) -> bool:
        for indicator in SECRET_INDICATORS:
            if indicator in content:
                return True
        return False

    def should_index(self, file_path: Path) -> bool:
        # Check extensions
        if file_path.suffix.lower() in EXCLUDE_EXTENSIONS:
            return False
        
        # Check explicit skips
        name = file_path.name.lower()
        if name in {".env", "id_rsa", "id_ed25519"}:
            return False
        if name.startswith(".env."):
            return False
            
        # Check path for excluded dirs
        for part in file_path.parts:
            if part in EXCLUDE_DIRS:
                return False
                
        # Only index selected types or specific files
        # Based on user list: AGENTS.md, README*, docs/**/*.md, docs/**/*.txt, selected src, tests
        try:
            rel_path = file_path.relative_to(self.repo_root)
        except ValueError:
            return False # Path not in repo root

        rel_str = str(rel_path)
        
        if rel_str == "AGENTS.md": return True
        if name.startswith("readme"): return True
        if "docs/" in rel_str and file_path.suffix in {".md", ".txt"}: return True
        
        # Source files
        if "src/marius/" in rel_str and file_path.suffix == ".py": return True
        if "src/warden/" in rel_str and file_path.suffix == ".py": return True
        
        # Tests
        if "tests/test_marius" in rel_str and file_path.suffix == ".py": return True
        if rel_str == "tests/test_warden_api.py": return True
        
        return False

    def export_project(self, project_name: str) -> Path:
        output_file = self.output_dir / f"{project_name}.jsonl"
        count = 0
        
        with open(output_file, "w", encoding="utf-8") as f:
            for root, dirs, files in os.walk(self.repo_root):
                # Prune dirs in place
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                
                for file in files:
                    file_path = Path(root) / file
                    if not self.should_index(file_path):
                        continue
                        
                    try:
                        if self.is_binary(file_path):
                            self.skipped_files.append(str(file_path))
                            continue
                            
                        with open(file_path, "r", encoding="utf-8") as src_f:
                            content = src_f.read()
                            
                        if self.contains_secrets(content):
                            self.skipped_files.append(str(file_path))
                            continue
                            
                        # Create record
                        rel_path = file_path.relative_to(self.repo_root)
                        record = {
                            "id": hashlib.sha256(str(rel_path).encode()).hexdigest()[:12],
                            "project": project_name,
                            "source_type": "file",
                            "source_path": str(rel_path),
                            "title": file_path.name,
                            "text": content,
                            "timestamp": datetime.now().isoformat(),
                            "content_hash": hashlib.sha256(content.encode()).hexdigest()
                        }
                        f.write(json.dumps(record) + "\n")
                        count += 1
                        
                    except Exception as e:
                        self.skipped_files.append(f"{file_path}: {str(e)}")
                        
        return output_file

    def export_brain_records(self, collection_filter: Optional[str] = None) -> Path:
        """Export records from the local brain records.jsonl file."""
        from .brain_ingest import BRAIN_DATA
        
        suffix = f"_{collection_filter}" if collection_filter else "_all"
        output_file = self.output_dir / f"marius_brain{suffix}.jsonl"
        
        if not BRAIN_DATA.exists():
            # Return empty file
            open(output_file, 'w').close()
            return output_file

        count = 0
        with open(BRAIN_DATA, "r", encoding="utf-8") as src:
            with open(output_file, "w", encoding="utf-8") as dst:
                for line in src:
                    try:
                        record = json.loads(line)
                        if collection_filter and record.get("collection") != collection_filter:
                            continue
                        dst.write(line)
                        count += 1
                    except Exception:
                        continue
        return output_file

def export_project_context(project_name: str, repo_path: str, output_dir: Optional[str] = None) -> Path:
    exporter = SearchExporter(Path(repo_path), Path(output_dir) if output_dir else None)
    return exporter.export_project(project_name)

def rebuild_brain_exports(repo_root: Path, output_dir: Optional[Path] = None) -> List[Path]:
    exporter = SearchExporter(repo_root, output_dir)
    files = []
    # 1. Base project export (warden)
    files.append(exporter.export_project("warden"))
    # 2. Brain collection exports
    files.append(exporter.export_brain_records(None)) # all
    files.append(exporter.export_brain_records("article"))
    files.append(exporter.export_brain_records("personal")) # profiles are in here too
    files.append(exporter.export_brain_records("project"))
    return files
