---
name: squawk
description: Speak to the user aloud through Squawk. Use when asked to say something out loud, announce status, relay a message to an active voice conversation, teach pronunciation, or enable/disable Squawk Mode for a Claude Code session.
---

# Squawk

Squawk gives Claude Code an audible voice through the local Squawk repo. Speech
is serialized by Squawk's global lock, so commands may block briefly until the
audio channel is free.

Use the helper script from this plugin instead of calling `speak` directly:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --as claude "Tests pass."
```

The helper resolves the Squawk repo from `SQUAWK_ROOT`, from this repo when the
plugin is loaded in-place, or from `/Users/ashrocket/ashcode/squawk`.

## Speak

Use this for direct user requests like "say this out loud" or "announce that
the build passed":

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --as <agent-name> "<short status>"
```

- `--as <name>` picks the voice identity; Squawk persists voice assignments in
  `voices.json`.
- Speech does not include the agent name by default. Use `--announce` only when
  the spoken identity is more useful than the extra words.
- Keep spoken updates short. Prefer one useful sentence over narration.

## Relay

If the user may be in an active voice conversation and asks you not to interrupt
it, queue the message instead:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --relay --as <agent-name> "<message>"
```

## Teach Pronunciations

When the user corrects pronunciation, persist it once:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --teach "cmux=sea mux"
```

## Squawk Mode

Use `/squawk-mode` to opt the current Claude Code session into audible status
updates. Use `/squawk-off` to disable it.

While Squawk Mode is enabled:

- Announce when starting substantial work.
- Announce blockers or failures when they change what the user needs to know.
- Announce completion with a concise summary.
- Do not announce every file read, command, or minor step.
- Prefer relay only when the user explicitly wants queued audio instead of
  immediate speech.
