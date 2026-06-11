# voice-chat

Two-way voice conversation with Claude on macOS. Fully local ears and voice:
whisper.cpp (Metal) for speech-to-text, macOS `say` for text-to-speech, and the
Claude Code CLI (`claude -p`) as the brain — no API key required.

## Run

```bash
cd ~/ashcode/voice-chat
.venv/bin/python voice_chat.py
```

Speak when you hear "Voice link ready." Say **"goodbye"** or **"stop listening"** to end.

Options: `--model sonnet` (smarter, slower), `--voice Samantha`, `--rate 210`,
`--whisper-model models/ggml-small.en.bin` (better accuracy, download separately).

## How it works

mic → energy-based voice detection → whisper-cli (ggml-base.en, Metal) →
`claude -p --resume <session>` with a voice-style system prompt → `say` → loop.

Transcripts are logged to `logs/`. See `docs/specs/2026-06-11-voice-chat-design.md`
for the design, research notes, and upgrade paths (Kokoro TTS, Agent SDK persistent
session, barge-in).

## Requirements

- `brew install whisper-cpp ffmpeg`
- `python3 -m venv .venv && .venv/bin/pip install sounddevice numpy`
- `models/ggml-base.en.bin` from huggingface.co/ggerganov/whisper.cpp
- Claude Code CLI logged in
