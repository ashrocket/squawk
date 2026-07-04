#!/bin/bash
# Stop hook: when /squawk-mode is enabled for this Claude session, ask Claude to
# speak one final concise summary before stopping.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# shellcheck source=/dev/null
. "$PLUGIN_ROOT/scripts/squawk-common.sh"

STATE_FILE="$(squawk_state_file)"
[[ -f "$STATE_FILE" ]] || exit 0

# Avoid a Stop hook loop: first stop emits the prompt, the follow-up stop exits.
PENDING_FILE="${STATE_FILE}.pending"
if [[ -f "$PENDING_FILE" ]]; then
  rm -f "$PENDING_FILE"
  exit 0
fi
touch "$PENDING_FILE"

# shellcheck source=/dev/null
. "$STATE_FILE"
AGENT="${agent:-claude}"
PROJECT="${project:-$(basename "$(pwd)")}"

cat <<PROMPT
Before stopping, announce the result with Squawk Mode.

Run this command once:

\`\`\`bash
bash "$PLUGIN_ROOT/scripts/squawk-speak.sh" --as "$AGENT" "<SUMMARY>"
\`\`\`

Replace <SUMMARY> with a concrete one-sentence summary of what you just completed
or why you are blocked in $PROJECT. Keep it under 180 characters. Then stop
normally.
PROMPT
