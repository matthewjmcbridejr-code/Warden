"""CLI: python -m warden.brain_curate_cli [--limit 5] [--dry-run]

Unattended wiki curation. Meant to run on a timer (see
warden-brain-curate.timer/.service, same pattern as
warden-brain-ingest-obsidian.timer): first sorts anything sitting in the
warden-drop dropzone into the vault, then asks the Marius model gateway
(Ollama-first, OpenRouter fallback — same routing every other agent call
uses) to distill a small batch of un-distilled, promoted notes into wiki
pages.

Deliberately conservative defaults (--limit 5): this hits the model gateway
once per source, sequentially, so a bad run doesn't burn through a large
batch before anyone notices something's wrong with the output.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(description="Curate the Warden Brain wiki via the model gateway")
    parser.add_argument("--limit", type=int, default=5, help="Max sources to distill this run")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be distilled without calling the model")
    parser.add_argument("--skip-dropzone", action="store_true", help="Skip sorting warden-drop before curating")
    args = parser.parse_args()

    if not args.skip_dropzone:
        from .brain.dropzone import sort_drop_folder
        drop_result = sort_drop_folder(dry_run=args.dry_run)
        processed = len(drop_result.get("processed", []))
        skipped = len(drop_result.get("skipped", []))
        print(f"Dropzone: {processed} sorted into vault, {skipped} skipped.")

    from .brain.curator import curate_vault

    result = asyncio.run(curate_vault(limit=args.limit, dry_run=args.dry_run))

    if result.get("dry_run"):
        print(f"Would distill {result['scanned']} source(s):")
        for path in result.get("would_distill", []):
            print(f"  - {path}")
        return

    distilled = result.get("distilled", [])
    errors = result.get("errors", [])
    print(f"\nCurated {len(distilled)} wiki page(s) from {result.get('scanned', 0)} candidate source(s).")
    for page in distilled:
        action = "updated" if page.get("updated") else "created"
        print(f"  ✓ {action} {page['path']} <- {page['source_path']}")
    for err in errors:
        print(f"  ✗ {err['path']}: {err['error']}", file=sys.stderr)

    if errors and not distilled:
        sys.exit(1)


if __name__ == "__main__":
    main()
