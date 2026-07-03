#!/usr/bin/env bash
# Interactively collect Namecheap API credentials and persist them to your
# shell profile as exports — so any new shell (including the one this
# Claude Code session's tools spawn, since it initializes from your
# profile) picks them up automatically.
#
# Values are read with `read -s` (no terminal echo) and are never printed
# by this script, logged, or written anywhere except your own profile file.
# Run this yourself, in your own terminal — don't paste secrets in chat.

set -euo pipefail

VARS=(NAMECHEAP_API_USER NAMECHEAP_API_KEY NAMECHEAP_USERNAME NAMECHEAP_CLIENT_IP)

# Pick a profile file to persist into.
if [ -n "${ZSH_VERSION:-}" ] || [ "${SHELL:-}" = "/bin/zsh" ] || [ "${SHELL:-}" = "/usr/bin/zsh" ]; then
  PROFILE="$HOME/.zshrc"
else
  PROFILE="$HOME/.bashrc"
fi

echo "This will prompt for 4 Namecheap API values and store them as exports in:"
echo "  $PROFILE"
echo "Nothing you type here will be echoed to the terminal, printed, or logged."
echo

declare -A VALUES

for var in "${VARS[@]}"; do
  read -r -s -p "Enter value for ${var}: " value
  echo
  if [ -z "$value" ]; then
    echo "Skipped ${var} (empty input)."
    continue
  fi
  VALUES[$var]="$value"
done

if [ ${#VALUES[@]} -eq 0 ]; then
  echo "No values entered. Nothing written."
  exit 0
fi

# Back up the profile once per run before editing it.
cp "$PROFILE" "${PROFILE}.bak.$(date +%Y%m%dT%H%M%S)" 2>/dev/null || true

for var in "${!VALUES[@]}"; do
  # Remove any existing export line for this var, then append the new one.
  if [ -f "$PROFILE" ]; then
    grep -v "^export ${var}=" "$PROFILE" > "${PROFILE}.tmp" 2>/dev/null || true
    mv "${PROFILE}.tmp" "$PROFILE"
  fi
  printf 'export %s=%q\n' "$var" "${VALUES[$var]}" >> "$PROFILE"
  chmod 600 "$PROFILE" 2>/dev/null || true
  echo "Stored ${var} in ${PROFILE} (value not shown)."
done

echo
echo "Done. Open a new terminal (or run: source ${PROFILE}) to load these."
echo "Then tell Claude 'credentials are set' and it will re-check presence only — never values."
