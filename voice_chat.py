#!/usr/bin/env python3
"""Two-way voice interface to Claude: listen on the mic, think with claude -p, talk back with say."""
import argparse
import datetime
import json
import queue
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PRE_ROLL_FRAMES = 16          # ~0.5 s of audio kept from before speech starts
SPEECH_START_FRAMES = 5       # ~150 ms above threshold to count as speech
TRAILING_SILENCE_S = 1.1      # silence that ends an utterance
MAX_UTTERANCE_S = 45
CLAUDE_TIMEOUT_S = 150

HERE = Path(__file__).resolve().parent
EXIT_PHRASES = ("goodbye", "good bye", "stop listening", "shut down", "exit now", "quit now")
JUNK_PATTERNS = re.compile(r"^[\s\[\(\.\,\!\?]*(\[BLANK_AUDIO\]|\(.*?\)|\[.*?\])?[\s\.\,\!\?]*$")

VOICE_SYSTEM_PROMPT = (
    "You are a voice assistant. The user speaks to you through a microphone and your "
    "replies are read aloud by text-to-speech. Keep replies short and conversational: "
    "one to three sentences unless the user asks for detail. Never use markdown, "
    "bullet points, code blocks, URLs, or emoji - plain speakable sentences only. "
    "The transcript may contain small speech-to-text errors; infer the intent. "
    "The user is Ashley, working in ~/ashcode on a Mac."
)


def log_line(log_file, role, text):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {role}: {text}"
    print(line, flush=True)
    with open(log_file, "a") as f:
        f.write(line + "\n")


def speak(text, voice=None, rate=None):
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    if rate:
        cmd += ["-r", str(rate)]
    cmd.append(text)
    subprocess.run(cmd, check=False)


def calibrate_noise(stream_q, frames=20):
    """Measure ambient RMS over ~0.6 s to set the speech threshold."""
    levels = []
    while len(levels) < frames:
        frame = stream_q.get()
        levels.append(float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))))
    floor = float(np.median(levels))
    return max(180.0, floor * 3.5)


def listen_for_utterance(device=None):
    """Block until a complete spoken utterance is captured; return int16 samples."""
    stream_q = queue.Queue()

    def callback(indata, _frames, _time, status):
        stream_q.put(indata[:, 0].copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=FRAME_SAMPLES, device=device, callback=callback):
        threshold = calibrate_noise(stream_q)
        pre_roll, voiced, speech_frames = [], [], 0
        silence_frames_needed = int(TRAILING_SILENCE_S * 1000 / FRAME_MS)
        max_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_MS)
        silent_run = 0
        in_speech = False

        while True:
            frame = stream_q.get()
            rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

            if not in_speech:
                pre_roll.append(frame)
                if len(pre_roll) > PRE_ROLL_FRAMES:
                    pre_roll.pop(0)
                speech_frames = speech_frames + 1 if rms > threshold else 0
                if speech_frames >= SPEECH_START_FRAMES:
                    in_speech = True
                    voiced = list(pre_roll)
                    silent_run = 0
            else:
                voiced.append(frame)
                silent_run = silent_run + 1 if rms <= threshold else 0
                if silent_run >= silence_frames_needed or len(voiced) >= max_frames:
                    return np.concatenate(voiced)


def transcribe(samples, whisper_model):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    result = subprocess.run(
        ["whisper-cli", "-m", str(whisper_model), "-f", wav_path,
         "--no-prints", "--no-timestamps"],
        capture_output=True, text=True, timeout=60,
    )
    Path(wav_path).unlink(missing_ok=True)
    text = result.stdout.strip()
    if not text or JUNK_PATTERNS.match(text):
        return None
    return text


def ask_claude(prompt, session_id, model):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--append-system-prompt", VOICE_SYSTEM_PROMPT]
    if session_id:
        cmd += ["--resume", session_id]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=CLAUDE_TIMEOUT_S, cwd=HERE)
        data = json.loads(result.stdout)
        return data.get("result") or "I came back empty on that one.", data.get("session_id", session_id)
    except subprocess.TimeoutExpired:
        return "Sorry, that one took too long and I gave up. Try again?", session_id
    except (json.JSONDecodeError, OSError):
        return "Sorry, I hit an error talking to my brain. Try again?", session_id


def strip_for_speech(text):
    text = re.sub(r"[*_`#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def main():
    ap = argparse.ArgumentParser(description="Two-way voice chat with Claude")
    ap.add_argument("--model", default="haiku", help="claude model for replies (default: haiku)")
    ap.add_argument("--whisper-model", default=str(HERE / "models" / "ggml-base.en.bin"))
    ap.add_argument("--voice", default=None, help="say voice, e.g. Samantha")
    ap.add_argument("--rate", default=190, type=int, help="speech rate wpm")
    ap.add_argument("--device", default=None, help="input device name or index")
    ap.add_argument("--greeting", default="Voice link ready. I'm listening. Say goodbye when you're done.")
    args = ap.parse_args()

    logs_dir = HERE / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / f"chat-{datetime.datetime.now():%Y%m%d-%H%M%S}.log"

    session_id = None
    log_line(log_file, "system", f"starting: model={args.model} whisper={Path(args.whisper_model).name}")
    speak(args.greeting, args.voice, args.rate)

    while True:
        try:
            samples = listen_for_utterance(args.device)
        except KeyboardInterrupt:
            log_line(log_file, "system", "interrupted, exiting")
            break
        text = transcribe(samples, args.whisper_model)
        if not text:
            continue
        log_line(log_file, "you", text)

        if any(p in text.lower() for p in EXIT_PHRASES):
            speak("Goodbye. Ending the voice link.", args.voice, args.rate)
            log_line(log_file, "system", "exit phrase heard, shutting down")
            break

        reply, session_id = ask_claude(text, session_id, args.model)
        reply = strip_for_speech(reply)
        log_line(log_file, "claude", reply)
        speak(reply, args.voice, args.rate)


if __name__ == "__main__":
    main()
