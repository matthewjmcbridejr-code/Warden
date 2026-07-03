import sys
from pathlib import Path
from src.marius.search_export import rebuild_brain_exports

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    print(f"Rebuilding brain exports from {repo_root}...")
    files = rebuild_brain_exports(repo_root)
    for f in files:
        print(f"  - {f}")
    print("Done.")
