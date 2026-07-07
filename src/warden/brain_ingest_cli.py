"""CLI: python -m warden.brain_ingest_cli --path ~/Obsidian --project personal"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ALLOWED_EXTENSIONS = {".md", ".txt", ".py", ".ts", ".js", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".rst"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".codex", ".agents", "_mctable", "dist", "build"}
SKIP_PATTERNS = {".env", ".pem", ".key", "id_rsa", "id_ed25519"}


def _should_skip(p: Path) -> bool:
    name = p.name.lower()
    return any(pat in name for pat in SKIP_PATTERNS)


def collect_files(root: Path, max_files: int) -> list[Path]:
    files = []
    for p in root.rglob("*"):
        if len(files) >= max_files:
            break
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if _should_skip(p):
            continue
        if p.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append(p)
    return files


def main():
    parser = argparse.ArgumentParser(description="Ingest files into Warden brain")
    parser.add_argument("--path", required=True, help="File or directory to ingest")
    parser.add_argument("--project", default="personal", help="Project name")
    parser.add_argument("--source-type", default="doc", choices=["obsidian", "repo", "manual", "agent_proof", "doc"])
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--max-files", type=int, default=200)
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: path not found: {root}", file=sys.stderr)
        sys.exit(1)

    from .personal_memory import seed_if_missing
    seed_if_missing()

    # NOTE: this used to go through src.marius.brain_ingest.BrainIngest, which
    # writes to ~/.local/share/marius/brain/records.jsonl — a store that
    # brain_search/brain_reindex/brain_list_sources never read. This daily
    # timer (warden-brain-ingest-obsidian.timer) was reporting "N ingested"
    # every night for content that was never actually searchable. Fixed to
    # use the same vault + SQLite index that backs search, via ingest_generic.
    from .brain.ingest import ingest_generic
    from . import brain_embed, brain_vector_store

    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]

    files = collect_files(root, args.max_files) if root.is_dir() else [root]
    total = len(files)
    ok_count = 0
    skipped = 0

    for i, f in enumerate(files, 1):
        print(f"[{i}/{total}] {f.relative_to(root) if root.is_dir() else f.name}", end=" ", flush=True)
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"— unreadable: {exc}")
            skipped += 1
            continue

        result = ingest_generic(
            text=text,
            title=f.name,
            source_type=args.source_type,
            project=args.project,
            tags=tag_list,
        )
        if result.get("ok") and result.get("duplicate"):
            print(f"— duplicate of {result.get('duplicate_of')}")
            skipped += 1
            continue
        if result.get("ok"):
            embedding = brain_embed.get_embedding(text[:4000])
            if embedding:
                brain_vector_store.upsert(result["source_id"], embedding, {"project": args.project, "source": str(f)})
                print("✓ (embedded)")
            else:
                print("✓")
            ok_count += 1
        else:
            err = result.get("error", "skipped")
            print(f"— {err}")
            skipped += 1

    print(f"\nDone: {ok_count} ingested, {skipped} skipped out of {total} files.")
    sem = brain_embed.is_available()
    print(f"Semantic index: {'enabled' if sem else 'disabled (Ollama not available)'}")


if __name__ == "__main__":
    main()
