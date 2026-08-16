"""Obsidian-compatible local Markdown vault management.

Works with any folder of Markdown files. Obsidian app is not required.
Default vault: ~/warden-vault
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import BrainSource

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_VAULT_PATH = Path.home() / "warden-vault"

VAULT_FOLDERS = [
    "00-inbox",
    "10-projects",
    "20-people",
    "30-clients",
    "40-systems",
    "50-research",
    "60-daily",
    "90-archive",
    "wiki",
]

EXCLUDE_DIRS = {
    ".git", ".obsidian", ".trash", "node_modules",
    "__pycache__", ".venv", "venv", ".env", "notebooklm",
}

EXCLUDE_EXTENSIONS = {".sh", ".py", ".js", ".ts", ".env", ".pem", ".key", ".crt"}

SECRET_INDICATORS = [
    "password", "secret", "token", "api_key", "apikey",
    "access_key", "private_key", "client_secret",
]

# Paths that must never be written to (path traversal safety)
_FORBIDDEN_SEGMENTS = {"..", "~", ".env", ".ssh", ".config", ".gnupg"}


def get_vault_path() -> Path:
    raw = os.getenv("WARDEN_BRAIN_VAULT_PATH", "")
    return Path(raw).expanduser() if raw else DEFAULT_VAULT_PATH


def get_write_folder() -> str:
    return os.getenv("WARDEN_BRAIN_WRITE_FOLDER", "00-inbox")


def is_enabled() -> bool:
    return os.getenv("WARDEN_BRAIN_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# Vault initialization
# ---------------------------------------------------------------------------

def init_vault(vault_path: Optional[Path] = None) -> dict:
    """Create vault directory structure. Idempotent — safe to call multiple times."""
    vp = vault_path or get_vault_path()
    created = []
    existed = []
    for folder in VAULT_FOLDERS:
        d = vp / folder
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(folder)
        else:
            existed.append(folder)
    # Write a README if inbox is empty
    readme = vp / "00-inbox" / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Warden Brain Vault\n\n"
            "This is your personal knowledge base. Any Markdown file here is searchable by Warden.\n\n"
            "Recommended app: [Obsidian](https://obsidian.md) (optional — not required)\n\n"
            "## Folders\n"
            + "\n".join(f"- `{f}/`" for f in VAULT_FOLDERS)
        )
        created.append("00-inbox/README.md")
    return {
        "vault_path": str(vp),
        "created": created,
        "already_existed": existed,
        "initialized": True,
    }


# ---------------------------------------------------------------------------
# Source scanning
# ---------------------------------------------------------------------------

def _should_skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS or name.startswith(".")


def _should_skip_file(p: Path) -> bool:
    if p.suffix.lower() not in {".md", ".markdown"}:
        return True
    if p.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True
    return False


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-ish frontmatter (simple key: value) and body."""
    fm: dict = {}
    if not text.startswith("---"):
        return fm, text
    end = text.find("\n---", 3)
    if end == -1:
        return fm, text
    block = text[3:end]
    body = text[end + 4:].lstrip("\n")
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def _extract_tags(fm: dict, body: str) -> list[str]:
    tags = []
    raw = fm.get("tags", fm.get("tag", ""))
    if isinstance(raw, str):
        tags = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    inline = re.findall(r"#([A-Za-z0-9_/-]+)", body)
    return list(dict.fromkeys(tags + inline))


def _extract_headings(body: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^#{1,6}\s+(.+)$", body, re.MULTILINE)]


def _stable_source_id(vault_path: Path, file_path: Path) -> str:
    rel = file_path.relative_to(vault_path).as_posix()
    return hashlib.sha256(rel.encode()).hexdigest()[:24]


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def scan_sources(vault_path: Optional[Path] = None) -> list[BrainSource]:
    """Walk the vault and return BrainSource for each Markdown file."""
    vp = vault_path or get_vault_path()
    if not vp.exists():
        return []
    sources: list[BrainSource] = []
    for root, dirs, files in os.walk(vp):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for fname in files:
            fp = Path(root) / fname
            if _should_skip_file(fp):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm, body = _parse_frontmatter(text)
            title = fm.get("title", "") or (
                re.search(r"^#\s+(.+)$", body, re.MULTILINE) or type("", (), {"group": lambda s, n: ""})()
            ).group(1) or fp.stem
            if callable(title):
                title = fp.stem
            sources.append(BrainSource(
                source_id=_stable_source_id(vp, fp),
                path=fp.relative_to(vp).as_posix(),
                title=str(title),
                tags=_extract_tags(fm, body),
                headings=_extract_headings(body),
                word_count=len(body.split()),
                checksum=_checksum(text),
                abs_path=str(fp),
            ))
    return sources


# ---------------------------------------------------------------------------
# Note writing
# ---------------------------------------------------------------------------

_FORBIDDEN_CONTENT_PATTERNS = re.compile(
    r"(password|secret|token|api_key|private_key|BEGIN\s+RSA|-----BEGIN)\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def _validate_note_path(rel_path: str, write_folder: str) -> str:
    """Validate and normalize a vault-relative note path. Raises ValueError on bad input."""
    parts = Path(rel_path).parts
    for seg in parts:
        if seg in _FORBIDDEN_SEGMENTS or seg.startswith(".."):
            raise ValueError(f"Forbidden path segment: {seg!r}")
    if Path(rel_path).is_absolute():
        raise ValueError("Absolute paths not allowed")
    # Force into write folder if not already under it
    if not rel_path.startswith(write_folder):
        rel_path = f"{write_folder}/{rel_path}"
    if not rel_path.endswith(".md"):
        rel_path += ".md"
    return rel_path


def write_note(
    title: str,
    body: str,
    tags: Optional[list[str]] = None,
    filename: Optional[str] = None,
    vault_path: Optional[Path] = None,
    extra_frontmatter: Optional[dict[str, str]] = None,
) -> dict:
    """Write a new Markdown note to the vault inbox. Never overwrites existing files."""
    vp = vault_path or get_vault_path()
    write_folder = get_write_folder()

    # Build filename from title if not provided
    if not filename:
        slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
        slug = re.sub(r"[\s_]+", "-", slug)[:60]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"{slug}-{ts}.md"

    rel_path = _validate_note_path(filename, write_folder)
    abs_path = vp / rel_path

    if abs_path.exists():
        raise FileExistsError(f"Note already exists: {rel_path}")

    # Redact any secrets accidentally in body
    body_safe = _FORBIDDEN_CONTENT_PATTERNS.sub("[REDACTED]", body)

    # Build frontmatter
    tag_str = ", ".join(tags or ["warden", "auto"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    extra_lines = ""
    if extra_frontmatter:
        for key, value in extra_frontmatter.items():
            safe_key = re.sub(r"[^\w-]", "", str(key))
            safe_value = str(value).replace("\n", " ").strip()
            if safe_key:
                extra_lines += f"{safe_key}: {safe_value}\n"
    content = (
        f"---\ntitle: {title}\ntags: {tag_str}\ncreated: {now}\nsource: warden\n{extra_lines}---\n\n"
        f"# {title}\n\n{body_safe}\n"
    )

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(abs_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass

    return {
        "ok": True,
        "path": rel_path,
        "abs_path": str(abs_path),
        "title": title,
        "word_count": len(body_safe.split()),
    }
