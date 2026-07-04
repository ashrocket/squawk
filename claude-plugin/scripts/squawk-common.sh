#!/bin/bash
# Shared helpers for the Squawk Claude plugin.

squawk_plugin_root() {
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    printf '%s\n' "$CLAUDE_PLUGIN_ROOT"
  else
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
  fi
}

squawk_session_id() {
  local raw="${CLAUDE_CODE_SESSION_ID:-global}"
  printf '%s' "$raw" | tr -c 'A-Za-z0-9._-' '_'
}

squawk_state_dir() {
  local base="${XDG_STATE_HOME:-$HOME/.local/state}"
  printf '%s\n' "$base/squawk/claude-mode"
}

squawk_state_file() {
  printf '%s/%s.env\n' "$(squawk_state_dir)" "$(squawk_session_id)"
}

squawk_shell_quote() {
  local value="$1"
  printf "'%s'" "${value//\'/\'\\\'\'}"
}
