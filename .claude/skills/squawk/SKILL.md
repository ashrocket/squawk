---
name: squawk
description: Speak to the user aloud through squawk — status announcements, relay messages to an active voice conversation, and pronunciation teaching. Use when asked to say something out loud, announce build/test results audibly, or fix how a word is pronounced.
---

# squawk: voices for Claude Code agents

All commands run from the squawk repo root. Speech is serialized by a global
lock — never worry about talking over another agent; calls block until the
channel is free.

## Speak

```bash
./speak --as <agent-name> --announce "Tests pass, deploy is live."
```

- `--as <name>` picks the agent identity; each name is auto-assigned a distinct
  voice from the pool (persisted in `voices.json`).
- `--announce` prefixes speech with the agent's name — use it for status
  reports so the user knows who is talking.
- `--voice <voice>` overrides the voice one-off (e.g. `kokoro:af_heart`,
  `"Ava (Premium)"`, `default`).

## Relay (don't interrupt a conversation)

If the user is mid voice-conversation, background agents must not grab the
speakers. Queue a short message instead; the active conversation reads it
aloud between turns:

```bash
./speak --relay --as builder "need a review on PR 12"
```

## Teach pronunciations

When the user corrects how something is said (or you hear TTS butcher a
developer word), persist the fix once for every agent and every voice:

```bash
./speak --teach "cmux=sea mux"
```

## Configuration

- `pool.json` — ordered voice pool (managed by Squawk.app; hand-editable).
- `voices.json` — agent → voice assignments.
- `lexicon.json` — pronunciation fixes, applied to all voices including Kokoro.
- `app/Squawk.app` — installer + settings panel (build with `app/build_app.sh`).
