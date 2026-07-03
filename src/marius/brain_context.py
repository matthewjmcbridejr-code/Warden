import os
from typing import List, Dict, Optional, Any
from .search_provider import LocalJsonlSearchProvider

def build_brain_context_pack(user_message: str, project: Optional[str] = None, limit: int = 5, max_chars: int = 2500) -> Dict[str, Any]:
    """
    Search local brain records and project exports for relevant context.
    Returns a structured pack with formatted text for the LLM.
    """
    provider = LocalJsonlSearchProvider()
    
    # Simple strategy: search for full message
    # In a more advanced version, we might extract keywords from the message
    results = provider.search(user_message, project=project, limit=limit)
    
    # Filters:
    # 1. Preferred collections: profile, project, note, digest, reminder, article
    # 2. Exclude sensitivity: secret_excluded
    
    preferred_collections = {"profile", "project", "note", "digest", "reminder", "article"}
    
    filtered_results = []
    for r in results:
        # Check sensitivity
        if r.get("sensitivity") == "secret_excluded":
            continue
            
        filtered_results.append(r)
        
    # Formatting
    lines = ["MARIUS BRAIN CONTEXT:"]
    record_ids = []
    
    if not filtered_results:
        return {
            "query": user_message,
            "results": [],
            "context_text": "MARIUS BRAIN CONTEXT: No relevant memory found for this query.",
            "record_ids": []
        }
        
    current_chars = len(lines[0])
    
    for r in filtered_results:
        # Format: * [record_id] title — project — summary/snippet
        record_id = r.get("record_id", "unknown")
        title = r.get("title", "Untitled")
        proj = r.get("project", "unknown")
        snippet = r.get("snippet", "").strip()
        
        entry = f"* [{record_id}] {title} — {proj} — {snippet}"
        
        if current_chars + len(entry) + 1 > max_chars:
            break
            
        lines.append(entry)
        record_ids.append(record_id)
        current_chars += len(entry) + 1
        
    return {
        "query": user_message,
        "results": filtered_results,
        "context_text": "\n".join(lines),
        "record_ids": record_ids
    }
