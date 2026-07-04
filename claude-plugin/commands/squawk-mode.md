---
name: squawk-mode
description: Enable Squawk Mode for this Claude Code session with concise audible progress and completion updates.
arguments:
  - name: agent
    description: Optional voice identity to use for this Claude session.
    required: false
---

Enable Squawk Mode for this Claude Code session.

Run:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-mode.sh" on "$ARGUMENTS"
```

Then follow these rules for the rest of the session:

- Use Squawk for concise audible status on substantial work: start, meaningful
  blocker, verification result, and completion.
- Do not speak for routine file reads, every command, or minor internal steps.
- Keep each spoken update under about 180 characters.
- Use the same agent identity selected by `squawk-mode.sh`.
- When work is complete, the Squawk Stop hook may ask you to announce the final
  summary before stopping. Run that command once, then stop normally.

Report that Squawk Mode is enabled and include the agent name printed by the
script.
