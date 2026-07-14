#!/bin/bash
# Enable/disable session-scoped Squawk Mode for Claude Code.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck source=/dev/null
. "$PLUGIN_ROOT/scripts/squawk-common.sh"

MODE="${1:-status}"
AGENT_ARG="${2:-}"
SUBMODE_ARG="${3:-}"
if [[ -z "$SUBMODE_ARG" && "$AGENT_ARG" == *" "* ]]; then
  SUBMODE_ARG="${AGENT_ARG#* }"
  AGENT_ARG="${AGENT_ARG%% *}"
fi
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

safe_name() {
  printf '%s' "$1" | tr '[:upper:] /' '[:lower:]--' | tr -cd 'a-z0-9._-'
}

intro_dir() {
  printf '%s\n' "${SQUAWK_INTRO_DIR:-$PWD/.squawk}"
}

agent_intro_file() {
  printf '%s/intro-agent-%s.env\n' "$(intro_dir)" "$(safe_name "$1")"
}

session_intro_file() {
  printf '%s/intro-session-%s.env\n' "$(intro_dir)" "$(squawk_session_id)"
}

has_intro() {
  [[ -f "$(agent_intro_file "$1")" || -f "$(session_intro_file)" ]]
}

mark_intro() {
  local dir agent_file session_file now
  dir="$(intro_dir)"
  agent_file="$(agent_intro_file "$1")"
  session_file="$(session_intro_file)"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$dir"
  {
    printf 'agent=%s\n' "$(squawk_shell_quote "$1")"
    printf 'project=%s\n' "$(squawk_shell_quote "$PROJECT")"
    printf 'intro_at=%s\n' "$(squawk_shell_quote "$now")"
  } > "$agent_file"
  {
    printf 'agent=%s\n' "$(squawk_shell_quote "$1")"
    printf 'project=%s\n' "$(squawk_shell_quote "$PROJECT")"
    printf 'session=%s\n' "$(squawk_shell_quote "$(squawk_session_id)")"
    printf 'intro_at=%s\n' "$(squawk_shell_quote "$now")"
  } > "$session_file"
}

short_mode_message() {
  local submode="${1:-summarizing}"
  printf 'Squawk mode on - %s\n' "$submode"
}

case "$MODE" in
  on|enable)
    AGENT="$AGENT_ARG"
    [[ -n "$AGENT" ]] || AGENT="$(default_agent)"
    SUBMODE="${SUBMODE_ARG:-${SQUAWK_SUBMODE:-summarizing}}"
    if has_intro "$AGENT"; then
      SPOKEN_MESSAGE="$(short_mode_message "$SUBMODE")"
      INTRO_STATE="repeat"
    else
      SPOKEN_MESSAGE="Squawk Mode enabled for $PROJECT."
      INTRO_STATE="first"
    fi
    TMP_STATE="${STATE_FILE}.$$"
    {
      printf 'enabled=1\n'
      printf 'agent=%s\n' "$(squawk_shell_quote "$AGENT")"
      printf 'project=%s\n' "$(squawk_shell_quote "$PROJECT")"
      printf 'submode=%s\n' "$(squawk_shell_quote "$SUBMODE")"
      printf 'intro=%s\n' "$(squawk_shell_quote "$INTRO_STATE")"
      printf 'started_at=%s\n' "$(squawk_shell_quote "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
    } > "$TMP_STATE"
    "$PLUGIN_ROOT/scripts/squawk-speak.sh" --as "$AGENT" "$SPOKEN_MESSAGE"
    mv "$TMP_STATE" "$STATE_FILE"
    mark_intro "$AGENT"
    TMP_STATE=""
    rm -f "${STATE_FILE}.pending"
    printf 'Squawk Mode enabled. agent=%s submode=%s intro=%s state=%s\n' "$AGENT" "$SUBMODE" "$INTRO_STATE" "$STATE_FILE"
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
