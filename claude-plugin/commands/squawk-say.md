---
name: squawk-say
description: Say a short message aloud through Squawk.
arguments:
  - name: message
    description: Message to speak. If omitted, infer a brief useful status from the current conversation.
    required: false
---

Say a short message aloud through Squawk.

If `$ARGUMENTS` is not empty, speak it directly:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --as claude "$ARGUMENTS"
```

If `$ARGUMENTS` is empty, infer a concise useful status from the current
conversation, then run:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --as claude "<brief status>"
```

Report whether the message was spoken.
