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
- **One talker.** A global speech lock — agents queue, never talk over each other.
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
./speak --as builder --announce "Tests pass, deploy is live."
```

## Squawk.app — installer & settings panel

Prefer clicking to shell scripts? Build the developer-focused mac app
(no App Store, ad-hoc signed):

```bash
./app/build_app.sh && open app/Squawk.app
```

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
- `speak.py` — the shared voice box: speech lock, voice registry, pronunciation
  lexicon, Kokoro synthesis. Also a CLI.
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
- [ ] Talk to your *current* Claude Code session, not a fresh one
- [ ] Wake word / push-to-talk modes
- [ ] Demo video

MIT © Ashley Raiteri
