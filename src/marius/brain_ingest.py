import os
import json
import hashlib
import time
import httpx
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any, Union
from .search_export import SECRET_INDICATORS, EXCLUDE_DIRS, EXCLUDE_EXTENSIONS

logger = logging.getLogger(__name__)

BRAIN_ROOT = Path.home() / ".local" / "share" / "marius" / "brain"
BRAIN_DATA = BRAIN_ROOT / "records.jsonl"
EXPORTS_DIR = BRAIN_ROOT / "exports"
PROFILE_DIR = BRAIN_ROOT / "profile"
INBOX_DIR = Path.home() / "MariusBrain" / "inbox"
PROCESSED_DIR = Path.home() / "MariusBrain" / "processed"
REJECTED_DIR = Path.home() / "MariusBrain" / "rejected"

# Ensure dirs
for d in [BRAIN_ROOT, EXPORTS_DIR, PROFILE_DIR, INBOX_DIR, PROCESSED_DIR, REJECTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class BrainIngest:
    def __init__(self):
        self.data_path = BRAIN_DATA

    def safety_scan(self, text: str) -> Optional[str]:
        """Returns the first matching secret indicator if found, else None."""
        # Add more specific patterns if needed
        extended_patterns = SECRET_INDICATORS + ["oauth", "client_secret", "refresh_token"]
        for indicator in extended_patterns:
            if indicator in text:
                return indicator
        return None

    def create_record(self, 
                      collection: str,
                      project: str,
                      title: str,
                      text: str,
                      source_type: str,
                      source_path: str = "",
                      source_url: str = "",
                      tags: List[str] = None,
                      sensitivity: str = "public",
                      sync_google: bool = True) -> Dict[str, Any]:
        
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        record_id = hashlib.sha256(f"{source_url or source_path}{content_hash}".encode()).hexdigest()[:12]
        
        # Simple extractive summary: first 2-3 sentences
        summary = ". ".join(text.split(". ")[:2]).strip()
        if len(summary) > 300:
            summary = summary[:297] + "..."
            
        record = {
            "id": record_id,
            "schema_version": "brain_record_v1",
            "collection": collection,
            "project": project,
            "title": title,
            "text": text,
            "summary": summary,
            "source_type": source_type,
            "source_path": source_path,
            "source_url": source_url,
            "domain": source_url.split("//")[-1].split("/")[0] if source_url else "",
            "captured_at": datetime.now().isoformat(),
            "tags": tags or [],
            "content_hash": content_hash,
            "sensitivity": sensitivity,
            "sync_google": sync_google,
            "google_uri": "",
            "notes": ""
        }
        return record

    def save_record(self, record: Dict[str, Any]) -> bool:
        # Check if record already exists by ID
        # For v1, we just append to the file.
        # Deduplication could be done by reading the file or using a more robust DB.
        # But we'll do simple append for now.
        with open(self.data_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return True

    async def add_url(self, url: str, project: str = "research", tags: List[str] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {"User-Agent": "MariusBrain/1.0 (Matt's McServer Assistant)"}
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            
            # Very basic HTML-to-Text extraction
            html = resp.text
            import re
            
            # Extract title
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else url
            
            # Strip tags for body text
            text = re.sub(r"<script.*?>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            
            # Safety check
            secret_found = self.safety_scan(text)
            if secret_found:
                return {"ok": False, "error": f"URL content rejected: found secret indicator '{secret_found}'"}
            
            record = self.create_record(
                collection="article",
                project=project,
                title=title,
                text=text,
                source_type="url",
                source_url=url,
                tags=tags,
                sync_google=True
            )
            self.save_record(record)
            return {"ok": True, "record": record}

    def add_file(self, file_path: Union[str, Path], project: str = "unknown", tags: List[str] = None) -> Dict[str, Any]:
        p = Path(file_path)
        if not p.exists():
            return {"ok": False, "error": "File not found"}
        
        if p.suffix.lower() not in [".md", ".txt", ".json", ".jsonl", ".py", ".html", ".csv"]:
            return {"ok": False, "error": f"Unsupported file type: {p.suffix}"}
            
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            return {"ok": False, "error": "File is binary or not UTF-8"}

        # Safety check
        secret_found = self.safety_scan(text)
        if secret_found:
            return {"ok": False, "error": f"File rejected: found secret indicator '{secret_found}'"}

        record = self.create_record(
            collection="file",
            project=project,
            title=p.name,
            text=text,
            source_type="file",
            source_path=str(p.absolute()),
            tags=tags,
            sync_google=True
        )
        self.save_record(record)
        return {"ok": True, "record": record}

    def add_text(self, text: str, title: str, project: str = "personal", tags: List[str] = None) -> Dict[str, Any]:
        secret_found = self.safety_scan(text)
        if secret_found:
            return {"ok": False, "error": f"Text rejected: found secret indicator '{secret_found}'"}

        record = self.create_record(
            collection="personal",
            project=project,
            title=title,
            text=text,
            source_type="text",
            tags=tags,
            sync_google=True
        )
        self.save_record(record)
        return {"ok": True, "record": record}

    def scan_inbox(self) -> Dict[str, Any]:
        processed = 0
        rejected = 0
        results = []
        
        for file in INBOX_DIR.iterdir():
            if file.is_file():
                res = self.add_file(file, project="unknown", tags=["inbox"])
                if res["ok"]:
                    processed += 1
                    shutil.move(str(file), PROCESSED_DIR / file.name)
                else:
                    rejected += 1
                    # Log rejection
                    with open(REJECTED_DIR / f"{file.name}.reason.txt", "w") as f:
                        f.write(res["error"])
                    shutil.move(str(file), REJECTED_DIR / file.name)
                results.append({"file": file.name, "ok": res["ok"], "error": res.get("error")})
                
        return {"processed": processed, "rejected": rejected, "details": results}

    def ingest_profiles(self) -> Dict[str, Any]:
        """Convert profile Markdown files into JSONL records."""
        count = 0
        for f in PROFILE_DIR.glob("*.md"):
            with open(f, "r") as src:
                text = src.read()
            record = self.create_record(
                collection="personal" if "MATT" in f.name else "project",
                project="personal",
                title=f.stem.replace("_", " ").title(),
                text=text,
                source_type="profile",
                source_path=str(f),
                tags=["profile"],
                sync_google=True
            )
            self.save_record(record)
            count += 1
        return {"count": count}
