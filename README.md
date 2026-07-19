# squawk

> 🌐 [squawk.raiteri.net](https://squawk.raiteri.net)

**Voices for your Claude Code agents on macOS.** Talk to Claude hands-free, and
let every agent in your [cmux](https://cmux.sh) setup speak to you — one at a
time, each with its own voice.

Fully local ears and voices: whisper.cpp (Metal) for speech-to-text, macOS
neural voices or Kokoro for text-to-speech, and the Claude Code CLI as the
brain. No API key, nothing leaves your Mac except what you already send to
Claude.

> 🚧 Built in public for Mac developers running multiple Claude Code agents.
> Watch the repo — this is moving fast.

## Why

Running several Claude Code agents in cmux means status lives in N terminal
tabs. squawk gives the whole crew one audio channel with rules a radio operator
would recognize:

- **Focus follows mic.** Run `voice` in as many cmux tabs as you like — each
  becomes a voice agent for that window's project, but only the *focused*
  window's agent listens. The rest stand by quietly, like tabs waiting for
  keystrokes. (Terminal focus reporting; works in Ghostty/cmux, iTerm2, xterm.)
- **Conversations hold the con.** An active exchange keeps the mic for 75s past
  the last turn, even if your focus drifts — nobody steals the channel mid-thought.
- **One talker.** All speech routes through `squawkd`, a central multiplexer
  daemon (the traffic cop): one priority queue, one voice at a time, urgent
  messages jump the line but never interrupt mid-utterance. Every message is
  tagged with its origin — Claude session id, terminal window, project — and
  the voice it should use.
- **Questions route back.** `speak --ask "Deploy to prod?"` speaks the
  question, parks it on the channel, and blocks until you answer — in
  Squawk.app's Channel tab or with `speak --answer latest "yes"`. The answer
  lands on the stdout of the exact session that asked, even with five agents
  talking.
- **Phone fallback.** With [Pidgin](https://pidginroost.com) signed in, a
  question still unanswered after a grace delay (10s) is forwarded to your
  phone; reply there and it routes back the same way. First responder wins —
  desk or phone, whichever answers first.
- **Barge-in (experimental).** Start talking over the assistant and it stops to listen.
- **Relay requests.** Background agents don't grab the speakers mid-conversation;
  `speak --relay "need a review on PR 12"` queues a message the active
  conversation reads aloud between turns.
- **Distinct voices.** Each agent name is auto-assigned its own voice, best
  available first: your system default, then Kokoro neural, then Apple Premium.
  Assignments persist in `voices.json`.
- **Radio protocol.** The assistant ends turns with "Over." Say "over and out"
  to sign off.

## Quick start

```bash
git clone https://github.com/ashrocket/squawk && cd squawk
./setup.sh
./voice --user YourName        # two-way conversation; speak when greeted
```

Say **"goodbye"**, **"stop listening"**, or **"over and out"** to end.

Run it per project window: `cd ~/code/my-project && ~/path/to/squawk/voice` —
the agent names itself after the directory, gets its own voice, and its brain
runs *in that directory*, so it can read the project's files when you ask about
them. Click into a window to talk to that project's agent.

Let any agent (any cmux tab, any script) report in:

```bash
./speak --as builder "Tests pass, deploy is live."
```

Ask the user something and wait for the routed answer (spoken aloud, answered
from Squawk.app or any shell):

```bash
./speak --as builder --ask "Tests are red on main. Fix forward or revert?"
./speak --answer latest "revert"        # e.g. from another terminal
```

Fire-and-forget and priority:

```bash
./speak --as builder --no-wait "Kicking off the long build."
./speak --as builder --priority urgent "Prod deploy failed."
```

The multiplexer daemon starts on demand with the first `speak` and exits after
15 idle minutes. `--local` (or `SQUAWK_NO_DAEMON=1`) bypasses it and speaks
directly behind the legacy speech lock, which the daemon also honors — the two
paths can't talk over each other.

Inspect the shared channel before talking:

```bash
./speak --status
./speak --status --json
```

Squawk publishes a machine-readable channel state: the current floor holder
(the active conversation that owns the channel), the current transmission, known
agents, assigned voices, enabled Squawk-mode sessions, and queued airtime
requests. If another conversation has the floor, queue a request instead of
interrupting it:

```bash
./speak --request --as builder "I have test results when the channel is free."
```

Speak into the live cmux agent you are already using:

```bash
./handsfree listen                 # continuous dictation into the focused agent
./handsfree convo                  # wake once, then stay open until "that's all"
./handsfree once                   # capture one utterance and submit it
```

`handsfree` injects only into known cmux agent panes by default
(`claude` or `codex`). Use `--surface <id-or-ref>` to pin a target instead of
following focus, or `--any-pane` when you intentionally want to type into a
non-agent pane. From a sandboxed Codex tool call, cmux socket access may be
blocked; run it from a normal cmux terminal or approve an unsandboxed run.

## Claude Code Squawk Mode

Install the Claude Code plugin once:

```bash
./claude-plugin/install.sh
```

If Claude Code is already open, reload plugins:

```text
/reload-plugins
```

Then opt a Claude session into audible updates:

```text
/squawk-mode
```

Squawk Mode announces the start of substantial work, meaningful blockers,
verification results, and completion. It is session-scoped and intentionally
quiet about routine file reads or small internal steps. Turn it off with:

```text
/squawk-off
```

For one-off speech from Claude Code:

```text
/squawk-say Build is green.
```

You can also load the plugin without installing it:

```bash
claude --plugin-dir /path/to/squawk/claude-plugin
```

## Squawk.app — installer & settings panel

Prefer clicking to shell scripts? Build the developer-focused mac app
(no App Store, ad-hoc signed):

```bash
./app/build_app.sh && open app/Squawk.app
```

- **Channel** — live view of the multiplexer: now playing, the queue, and
  pending questions with a reply box; answers route back to the session that
  asked.
- **Install** — the setup checks as live status rows, one-click install for
  anything missing (whisper.cpp, models, Python env, Kokoro).
- **Voices** — audition every installed voice and check the ones agents may
  use; selections persist to `pool.json`, which `speak` honors. Reassign
  agents, and jump to System Settings to delete unused system voices (they're
  SIP-protected, so only Apple's UI can remove them).
- **Lexicon** — view and teach pronunciations.

There's also a hover-to-audition web gallery: `python3 gallery/build.py &&
open gallery/index.html` — each voice picks up the poem where the last left off.

## Teach pronunciations (agents learn)

TTS butchers developer words. Fix them once, every agent learns instantly:

```bash
./speak --teach "cmux=sea mux"
```

Or just say it mid-conversation: *"pronounce cmux as sea mux."* Corrections
persist in `lexicon.json` and apply to all voices, including Kokoro.

## How it works

```
mic ──▶ voice detection ──▶ whisper.cpp (Metal) ──▶ claude -p --resume
                                                          │
speakers ◀── say / Kokoro ◀── lexicon ◀── speech lock ◀───┘
```

- `voice_chat.py` — the conversation loop (mic owner). Energy-based voice
  detection with noise-floor calibration; echo-proof: it ignores the mic while
  any agent holds the speech lock.
- `squawkd.py` — the multiplexer daemon (traffic cop): unix-socket JSON
  protocol, priority queue, origin tags, question/answer routing. Spawned on
  demand, exits when idle.
- `pidgin_bridge.py` — the long-range radio: forwards unanswered questions to
  your phone via pidginroost.com and posts the reply back to the daemon.
  Spawned by squawkd when a question arrives (needs the Pidgin app's keychain
  key or `PIDGIN_API_KEY`; `SQUAWK_NO_PIDGIN=1` disables). `--mirror` also
  sends spoken announcements as Pidgin notes.
- `speak.py` — the shared voice box and client: routes through `squawkd` by
  default; voice registry, pronunciation lexicon, Kokoro synthesis, legacy
  direct path. Also a CLI.
- `channel_state.py` — the shared radio state: floor holder, current
  transmission, known agents, voices, Squawk-mode sessions, and airtime queue.
- The brain is `claude -p` with session resume — conversation continuity with
  whatever model you choose (`--model sonnet` for smarter, slower replies).

## Requirements

macOS (Apple Silicon recommended), Homebrew, Python 3.10+, Claude Code CLI.
~150MB disk for whisper, +340MB optional for Kokoro. Runs comfortably on an
8GB M1.

## Roadmap (building in public)

- [x] Two-way voice loop, local STT/TTS
- [x] Multi-agent: speech lock, voice registry, `speak` CLI
- [x] Pronunciation lexicon agents learn (`--teach`, or by voice)
- [x] Window-aware: one agent per cmux tab, focus follows mic, conversations hold the con
- [x] Relay queue: background agents message the active conversation
- [x] Barge-in v1 (experimental; bleed-aware thresholding, no echo cancellation yet)
- [x] STT-side pronunciation learning (recognize taught words in *your* speech)
- [x] Kokoro daemon: model stays resident, spawned on demand, exits after 10 idle minutes
- [x] Claude Code Squawk Mode plugin: session-scoped audible status updates
- [x] Talk to your *current* cmux Claude/Codex agent session, not a fresh one
- [x] Wake-word-gated handsfree input mode
- [x] Multiplexer daemon: central priority queue, origin-tagged messages,
      `--ask`/`--answer` routing, live Channel tab in Squawk.app
- [x] Pidgin phone bridge: unanswered questions escalate to your phone,
      replies route back to the asking session
- [ ] Demo video


MIT © Ashley Raiteri
