import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from .search_export import export_project_context

class SearchProvider:
    def status(self) -> Dict[str, Any]:
        raise NotImplementedError()

    def export(self, project: str, repo_path: str) -> Dict[str, Any]:
        raise NotImplementedError()

    def search(self, query: str, project: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError()

class LocalJsonlSearchProvider(SearchProvider):
    def __init__(self, exports_dir: Optional[Path] = None, brain_data: Optional[Path] = None):
        self.exports_dir = exports_dir or Path.home() / ".local" / "share" / "marius" / "brain" / "exports"
        self.brain_data = brain_data or Path.home() / ".local" / "share" / "marius" / "brain" / "records.jsonl"
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> Dict[str, Any]:
        requested = os.getenv("MARIUS_SEARCH_PROVIDER", "local").lower()
        exports = []
        if self.exports_dir.exists():
            for f in self.exports_dir.glob("*.jsonl"):
                exports.append({
                    "project": f.stem,
                    "size_bytes": f.stat().st_size,
                    "updated_at": Path(f).stat().st_mtime
                })
        
        brain_size = self.brain_data.stat().st_size if self.brain_data.exists() else 0
        
        return {
            "requested_provider": requested,
            "actual_provider": "local",
            "provider": "local",
            "exports_dir": str(self.exports_dir),
            "brain_data": str(self.brain_data),
            "brain_size_bytes": brain_size,
            "exports": exports,
            "ready": True
        }

    def export(self, project: str, repo_path: str) -> Dict[str, Any]:
        output_file = export_project_context(project, repo_path, str(self.exports_dir))
        return {
            "ok": True,
            "project": project,
            "output_file": str(output_file),
            "size_bytes": output_file.stat().st_size
        }

    def search(self, query: str, project: Optional[str] = None, limit: int = 5, collection: Optional[str] = None, tags: List[str] = None) -> List[Dict[str, Any]]:
        results = []
        query_terms = query.lower().split()
        
        target_files = []
        if project:
            target_files = [self.exports_dir / f"{project}.jsonl"]
        else:
            target_files = list(self.exports_dir.glob("*.jsonl"))
            
        if self.brain_data.exists():
            target_files.append(self.brain_data)
            
        for export_file in target_files:
            if not export_file.exists():
                continue
                
            with open(export_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        
                        # Apply filters
                        if record.get("sensitivity") == "secret_excluded":
                            continue

                        if project and record.get("project") != project and export_file != (self.exports_dir / f"{project}.jsonl"):
                            continue
                        if collection and record.get("collection") != collection:
                            continue
                        if tags:
                            record_tags = record.get("tags", [])
                            if not all(tag in record_tags for tag in tags):
                                continue

                        text = record.get("text", "").lower()
                        title = record.get("title", "").lower()
                        summary = record.get("summary", "").lower()
                        
                        score = 0
                        for term in query_terms:
                            if term in title:
                                score += 10
                            if term in summary:
                                score += 5
                            if term in text:
                                score += text.count(term)
                                
                        if score > 0:
                            # Create snippet
                            full_text = record.get("text", "")
                            snippet = ""
                            
                            # Find first matching term to anchor snippet
                            best_term = None
                            for term in query_terms:
                                if term in full_text.lower():
                                    best_term = term
                                    break
                            
                            if best_term:
                                idx = full_text.lower().find(best_term)
                                start = max(0, idx - 100)
                                end = min(len(full_text), idx + 300)
                                snippet = full_text[start:end].replace("\n", " ")
                            else:
                                snippet = full_text[:400].replace("\n", " ")
                                
                            results.append({
                                "project": record.get("project", "unknown"),
                                "collection": record.get("collection", "repo"),
                                "source_path": record.get("source_path") or record.get("source_url", "unknown"),
                                "source_type": record.get("source_type", "file"),
                                "title": record.get("title"),
                                "tags": record.get("tags", []),
                                "snippet": snippet,
                                "score": float(score),
                                "record_id": record.get("id"),
                                "captured_at": record.get("captured_at") or record.get("timestamp"),
                                "provider": "local fallback" if os.getenv("MARIUS_SEARCH_PROVIDER") == "google" else "local"
                            })
                    except Exception:
                        continue
                        
        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        # Deduplicate by record_id
        seen_ids = set()
        unique_results = []
        for r in results:
            if r["record_id"] not in seen_ids:
                unique_results.append(r)
                seen_ids.add(r["record_id"])
                
        return unique_results[:limit]

def get_search_provider() -> SearchProvider:
    # Factory for search provider
    provider_type = os.getenv("MARIUS_SEARCH_PROVIDER", "local").lower()
    if provider_type == "google":
        try:
            from .google_search_provider import GoogleAgentSearchProvider
            return GoogleAgentSearchProvider()
        except ImportError:
            return LocalJsonlSearchProvider()
    return LocalJsonlSearchProvider()
