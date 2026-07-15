#!/usr/bin/env bash
set -euo pipefail

repo="$(git rev-parse --show-toplevel)"
cd "$repo"

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "gitleaks is required (https://github.com/gitleaks/gitleaks/releases)." >&2
  exit 2
fi

scan_root="$(mktemp -d)"
trap 'rm -rf "$scan_root"' EXIT

while IFS= read -r -d '' file; do
  mkdir -p "$scan_root/$(dirname "$file")"
  cp -a "$file" "$scan_root/$file"
done < <(git ls-files -z)

echo "Scanning tracked working-tree files with redacted output..."
gitleaks dir "$scan_root" --redact --no-banner

echo "Checking for tracked desktop dependencies, packages, and session/run data..."
if git ls-files | grep -E '(^|/)(node_modules|dist-electron|Partitions|Session Storage|runs)(/|$)|(^|/)(Cookies|Login Data)$|\.deb$|\.AppImage$'; then
  echo "Public artifact audit failed: generated or private runtime data is tracked." >&2
  exit 1
fi

echo "Public release audit passed."
