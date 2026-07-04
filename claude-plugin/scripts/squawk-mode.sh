#!/bin/bash
# Enable/disable session-scoped Squawk Mode for Claude Code.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck source=/dev/null
. "$PLUGIN_ROOT/scripts/squawk-common.sh"

MODE="${1:-status}"
AGENT_ARG="${2:-}"
PROJECT="$(basename "$(pwd)")"
STATE_DIR="$(squawk_state_dir)"
STATE_FILE="$(squawk_state_file)"
mkdir -p "$STATE_DIR"
TMP_STATE=""

cleanup() {
  if [[ -n "${TMP_STATE:-}" ]]; then
    rm -f "$TMP_STATE"
  fi
  return 0
}
trap cleanup EXIT

default_agent() {
  local name="$PROJECT"
  [[ -n "$name" ]] || name="claude"
  printf 'claude-%s\n' "$name" | tr '[:upper:] /' '[:lower:]--' | tr -cd 'a-z0-9._-'
}

case "$MODE" in
  on|enable)
    AGENT="$AGENT_ARG"
    [[ -n "$AGENT" ]] || AGENT="$(default_agent)"
    TMP_STATE="${STATE_FILE}.$$"
    {
      printf 'enabled=1\n'
      printf 'agent=%s\n' "$(squawk_shell_quote "$AGENT")"
      printf 'project=%s\n' "$(squawk_shell_quote "$PROJECT")"
      printf 'started_at=%s\n' "$(squawk_shell_quote "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
    } > "$TMP_STATE"
    "$PLUGIN_ROOT/scripts/squawk-speak.sh" --as "$AGENT" "Squawk Mode enabled for $PROJECT."
    mv "$TMP_STATE" "$STATE_FILE"
    TMP_STATE=""
    rm -f "${STATE_FILE}.pending"
    printf 'Squawk Mode enabled. agent=%s state=%s\n' "$AGENT" "$STATE_FILE"
    ;;
  off|disable)
    if [[ -f "$STATE_FILE" ]]; then
      # shellcheck source=/dev/null
      . "$STATE_FILE"
      "$PLUGIN_ROOT/scripts/squawk-speak.sh" --as "${agent:-claude}" "Squawk Mode disabled." || true
    fi
    rm -f "$STATE_FILE" "${STATE_FILE}.pending"
    printf 'Squawk Mode disabled for this session.\n'
    ;;
  status)
    if [[ -f "$STATE_FILE" ]]; then
      # shellcheck source=/dev/null
      . "$STATE_FILE"
      printf 'Squawk Mode enabled. agent=%s state=%s\n' "${agent:-claude}" "$STATE_FILE"
    else
      printf 'Squawk Mode disabled for this session.\n'
    fi
    ;;
  *)
    printf 'Usage: %s [on [agent]|off|status]\n' "$0" >&2
    exit 2
    ;;
esac
