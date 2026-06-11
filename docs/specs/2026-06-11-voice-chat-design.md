# Voice Chat — Two-Way Voice Interface for Claude

**Date:** 2026-06-11
**Status:** v1 built autonomously per /loop request; design decisions documented for review.

## Goal

Hands-free spoken conversation with Claude on this Mac: speak into the mic, Claude
answers out loud. Fully local STT/TTS (no API key needed); Claude Code CLI is the brain.

## Constraints discovered

- Apple M1, **8 GB RAM** — rules out heavyweight torch-based models.
- Python 3.14 (pyenv) — new enough that ML wheel coverage is spotty; minimize Python ML deps.
- No `ANTHROPIC_API_KEY` — use `claude -p` headless mode (v2.1.173 present).
- ffmpeg + Homebrew available; mic = "MacBook Pro Microphone" (device 0).

## Research summary (2026-06-11)

- **STT:** On Apple Silicon, whisper.cpp with Metal is ~3–6x faster than faster-whisper
  (which is CPU-only on Mac). mlx-whisper and Parakeet-MLX are faster still in benchmarks
  (mac-whisper-speedtest), but require Python ML wheels — risky on 3.14, and whisper.cpp
  via brew is dependency-free. Whisper remains the accuracy leader per 2026 comparisons.
- **TTS:** Kokoro-82M is the 2026 quality/size consensus winner (used by voicemode);
  Piper is lighter; macOS `say` is built-in and instant. v1 uses `say`; Kokoro is the
  documented upgrade path.
- **Prior art:** `mbailey/voicemode` (MCP server, whisper.cpp + Kokoro),
  `Ashton-Sidhu/claude-whisper` (push-to-talk), `enesbasbug/voice-to-claude`
  (dictation plugin). We built lean and custom instead: fewer moving parts on 8 GB,
  fully inspectable, and the user asked to build.

## Approaches considered

1. **Install voicemode plugin** — mature but heavy (uv, MCP server, service manager); opaque.
2. **Python ML stack (faster-whisper/mlx)** — wheel risk on Py3.14; faster-whisper slow on Mac.
3. **Lean custom pipeline (chosen)** — brew whisper.cpp + sounddevice + `claude -p` + `say`.

## Architecture

```
mic (sounddevice, 16 kHz mono)
  → energy VAD (noise-floor calibration, speech start/stop detection)
  → wav → whisper-cli (ggml-base.en, Metal)
  → claude -p --resume <session> --append-system-prompt <voice style>
  → say (macOS TTS)
  → loop
```

- **voice_chat.py** — single file, ~250 lines. Modes: continuous VAD loop (default).
- **Session continuity:** first turn captures `session_id` from `--output-format json`;
  later turns pass `--resume`.
- **Voice style:** system prompt forces short, markdown-free, speakable replies.
- **Exit:** say "goodbye" / "stop listening".
- **Logging:** every transcript + reply appended to `logs/` with timestamps.

## Error handling

- Blank/junk transcripts (e.g. `[BLANK_AUDIO]`) are dropped silently.
- `claude -p` failure or 120 s timeout → spoken apology, loop continues.
- VAD threshold adapts to measured noise floor at startup.

## Trade-offs accepted in v1

- ~5–8 s brain latency per turn (`claude -p` cold start). Upgrade path: Agent SDK
  persistent session.
- No barge-in (can't interrupt Claude mid-sentence; mic is ignored while speaking —
  also avoids echo).
- `say` voice quality < Kokoro. Upgrade path: `--tts kokoro` via kokoro-onnx or mlx-audio.

## Testing performed

- 1 s mic capture: permission OK, ambient RMS ≈ 118.
- Live 5 s record + whisper-cli transcription: accurate, sub-second on Metal.
- `claude -p` round trip 5.6 s (haiku), session id captured.
- `say` audible (user confirmed: "i heard it").
