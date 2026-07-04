#!/bin/bash
# Resolve and invoke the local Squawk speak CLI.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [[ -f "$PLUGIN_ROOT/.local.env" ]]; then
  # shellcheck source=/dev/null
  . "$PLUGIN_ROOT/.local.env"
fi

if [[ "${SQUAWK_DRY_RUN:-}" == "1" ]]; then
  printf 'squawk-speak'
  for arg in "$@"; do
    printf ' %q' "$arg"
  done
  printf '\n'
  exit 0
fi

candidates=()
if [[ -n "${SQUAWK_ROOT:-}" ]]; then
  candidates+=("$SQUAWK_ROOT")
fi
candidates+=(
  "$PLUGIN_ROOT/.."
  "$PLUGIN_ROOT"
  "/Users/ashrocket/ashcode/squawk"
)

for root in "${candidates[@]}"; do
  if [[ -x "$root/speak" ]]; then
    exec "$root/speak" "$@"
  fi
done

cat >&2 <<'ERROR'
Squawk speak CLI was not found.

Set SQUAWK_ROOT in claude-plugin/.local.env, for example:

SQUAWK_ROOT="/Users/ashrocket/ashcode/squawk"
ERROR
exit 127
