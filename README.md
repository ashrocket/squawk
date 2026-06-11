# squawk

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

- **One listener.** Exactly one process owns the microphone (lock-enforced).
- **One talker.** A global speech lock — agents queue, never talk over each other.
- **Distinct voices.** Each agent name is auto-assigned its own voice, best
  available first: your system default, then Apple Premium, then Kokoro neural,
  then Apple Enhanced. Assignments persist in `voices.json`.
- **Radio protocol.** The assistant ends turns with "Over." Say "over and out"
  to sign off.

## Quick start

```bash
git clone https://github.com/ashrocket/squawk && cd squawk
./setup.sh
./voice --user YourName        # two-way conversation; speak when greeted
```

Say **"goodbye"**, **"stop listening"**, or **"over and out"** to end.

Let any agent (any cmux tab, any script) report in:

```bash
./speak --as builder --announce "Tests pass, deploy is live."
```

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
- [ ] Talk to your *current* Claude Code session, not a fresh one
- [ ] Barge-in (interrupt the assistant mid-sentence)
- [ ] Kokoro daemon for instant neural synthesis
- [ ] Wake word / push-to-talk modes
- [ ] Demo video

MIT © Ashley Raiteri
