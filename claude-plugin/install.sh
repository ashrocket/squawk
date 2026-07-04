#!/bin/bash
# Install the Squawk Claude plugin as a user-level Claude Code skill/plugin.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
SQUAWK_ROOT="$(cd "$PLUGIN_ROOT/.." && pwd)"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
TARGET="$SKILLS_DIR/squawk"

mkdir -p "$SKILLS_DIR"

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo "Refusing to replace non-symlink path: $TARGET" >&2
  echo "Move it aside or set CLAUDE_SKILLS_DIR to another directory." >&2
  exit 1
fi

printf 'SQUAWK_ROOT=%q\n' "$SQUAWK_ROOT" > "$PLUGIN_ROOT/.local.env"
ln -sfn "$PLUGIN_ROOT" "$TARGET"

if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$PLUGIN_ROOT" >/dev/null
fi

cat <<EOF
Installed Squawk Claude plugin:
  $TARGET -> $PLUGIN_ROOT

In an existing Claude Code session, run:
  /reload-plugins

Then enable voice updates with:
  /squawk-mode

Disable them with:
  /squawk-off
EOF
