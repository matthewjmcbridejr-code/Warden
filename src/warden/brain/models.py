"""Data models for Warden Brain — local vault, index, and hybrid answering."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BrainSource:
    """A single Markdown document in the vault."""
    source_id: str          # stable hash of vault-relative path
    path: str               # vault-relative path, e.g. "00-inbox/warden-brain.md"
    title: str
    tags: list[str]
    headings: list[str]
    word_count: int
    checksum: str           # sha256 of file content
    provider: str = "local"  # "local" | "google_discovery_engine"
    indexed_at: Optional[str] = None
    abs_path: Optional[str] = None


@dataclass
class BrainChunk:
    """A paragraph/section chunk used for search and citation."""
    chunk_id: str
    source_id: str
    source_path: str
    title: str
    heading: str
    text: str
    provider: str = "local"


@dataclass
class BrainCitation:
    """A citation returned with an answer."""
    source_path: str
    title: str
    heading: str
    excerpt: str
    provider: str = "local"
    score: float = 1.0


@dataclass
class BrainAnswer:
    """Structured answer from the brain (local, Google, or hybrid)."""
    answer: str
    citations: list[BrainCitation] = field(default_factory=list)
    confidence: float = 0.0
    provider_used: str = "local"       # "local" | "google" | "hybrid"
    local_count: int = 0
    google_count: int = 0
    errors: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    recommended_next_action: str = ""

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "citations": [
                {
                    "source_path": c.source_path,
                    "title": c.title,
                    "heading": c.heading,
                    "excerpt": c.excerpt,
                    "provider": c.provider,
                    "score": c.score,
                }
                for c in self.citations
            ],
            "confidence": self.confidence,
            "provider_used": self.provider_used,
            "provider_results": {
                "local": self.local_count,
                "google": self.google_count,
                "errors": self.errors,
            },
            "unresolved_questions": self.unresolved_questions,
            "recommended_next_action": self.recommended_next_action,
        }
