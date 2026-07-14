#!/usr/bin/env python3
"""Two-way voice interface to Claude: listen on the mic, think with claude -p, talk back.

Window-aware: run one instance per cmux tab. Only the focused window's instance
listens (terminal focus reporting, mode 1004); the others stand by quietly. An
active conversation keeps the mic - "holds the con" - even if focus drifts for a
moment. Other agents can queue short relay requests (speak --relay) that the
con-holder reads aloud between turns. Experimental barge-in: start talking over
the assistant and it stops to listen.
"""
import argparse
import datetime
import fcntl
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

import channel_state as channel
from speak import (INBOX, SPEECH_LOCK, lexicon_words, reverse_lexicon,
                   speak as speak_serialized, teach, voice_for)

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PRE_ROLL_FRAMES = 16          # ~0.5 s of audio kept from before speech starts
SPEECH_START_FRAMES = 5       # ~150 ms above threshold to count as speech
TRAILING_SILENCE_S = 1.1      # silence that ends an utterance
MAX_UTTERANCE_S = 45
CLAUDE_TIMEOUT_S = 150
ECHO_GRACE_S = 0.7            # ignore mic this long after any agent stops talking
CONVO_GRACE_S = 75            # conversation "holds the con" this long after the last exchange
BARGE_BASELINE_FRAMES = 25    # ~0.75 s of playback bleed sampled before arming barge-in
BARGE_SUSTAIN_FRAMES = 12     # ~0.36 s of loud input to count as an interruption

HERE = Path(__file__).resolve().parent
MIC_LOCK = HERE / ".voice_chat.lock"
EXIT_PHRASES = ("goodbye", "good bye", "stop listening", "shut down",
                "exit now", "quit now", "over and out")
JUNK_PATTERNS = re.compile(r"^[\s\[\(\.\,\!\?]*(\[BLANK_AUDIO\]|\(.*?\)|\[.*?\])?[\s\.\,\!\?]*$")
PRONOUNCE_RE = re.compile(
    r"\b(?:pronounce|pronounced?|say)\s+(.{1,40}?)\s+(?:as|like)\s+(.{1,60}?)[.!?]*$", re.IGNORECASE)

VOICE_SYSTEM_PROMPT_TEMPLATE = (
    "You are {agent}, a voice agent in the squawk project. {user} speaks to you through "
    "a microphone and your replies are read aloud by text-to-speech. Keep replies short "
    "and conversational: one to three sentences unless {user} asks for detail. Never use "
    "markdown, bullet points, code blocks, URLs, or emoji - plain speakable sentences "
    "only. The transcript may contain small speech-to-text errors; infer the intent. "
    "You are attached to the project directory {cwd} and may read its files to answer "
    "questions about it. {user} runs multiple Claude Code agents in cmux; each window "
    "can run its own squawk voice agent, but only the focused window listens, and an "
    "active conversation holds the voice channel. Other agents can queue short relay "
    "messages that you pass along aloud between turns. If {user} wants a word "
    "pronounced differently they can say: pronounce WORD as PHONETIC. To end the "
    "conversation {user} can say goodbye, stop listening, or over and out."
)


def log_line(log_file, role, text):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {role}: {text}"
    print(line, flush=True)
    with open(log_file, "a") as f:
        f.write(line + "\n")


class FocusTracker:
    """Tracks whether this terminal pane has focus via xterm mode 1004 reports.

    Works in Ghostty (and therefore cmux), iTerm2, and xterm.js. Without a tty
    (or with --no-focus) it reports always-focused, restoring the old behavior.
    """

    def __init__(self, enabled=True):
        self.focused = True
        self.supported = enabled and sys.stdin.isatty()
        self._old_attrs = None
        if self.supported:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self._old_attrs = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            sys.stdout.write("\x1b[?1004h")
            sys.stdout.flush()
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        buf = b""
        while True:
            try:
                chunk = os.read(self.fd, 64)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while True:
                i = buf.find(b"\x1b[")
                if i < 0:
                    buf = b""
                    break
                if len(buf) < i + 3:
                    buf = buf[i:]
                    break
                code = buf[i + 2:i + 3]
                if code == b"I":
                    self.focused = True
                elif code == b"O":
                    self.focused = False
                buf = buf[i + 3:]

    def restore(self):
        if self.supported:
            import termios
            sys.stdout.write("\x1b[?1004l")
            sys.stdout.flush()
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._old_attrs)


class MicLock:
    """The talking-stick for ears: whoever holds it is the listening instance."""

    def __init__(self):
        self.handle = open(MIC_LOCK, "w")
        self.held = False

    def try_acquire(self):
        if self.held:
            return True
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.held = True
        except OSError:
            pass
        return self.held

    def release(self):
        if self.held:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.held = False


class BargeInMonitor:
    """Watches the mic while the assistant talks; trips when the user talks over it.

    The first ~0.75 s of playback establishes the speaker-bleed baseline; sustained
    input well above that baseline counts as an interruption.
    """

    def __init__(self, device=None):
        self.q = queue.Queue()
        self.baseline = []
        self.threshold = None
        self.loud = 0
        self.triggered = False
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=FRAME_SAMPLES, device=device,
            callback=lambda d, *_: self.q.put(d[:, 0].copy()))

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *_):
        self.stream.stop()
        self.stream.close()

    def interrupted(self):
        while not self.q.empty():
            frame = self.q.get()
            rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
            if self.threshold is None:
                self.baseline.append(rms)
                if len(self.baseline) >= BARGE_BASELINE_FRAMES:
                    self.threshold = max(float(np.median(self.baseline)) * 3.0, 500.0)
            else:
                self.loud = self.loud + 1 if rms > self.threshold else 0
                if self.loud >= BARGE_SUSTAIN_FRAMES:
                    self.triggered = True
        return self.triggered


def another_agent_talking():
    """True while any agent holds the global speech lock (i.e. audio is playing)."""
    try:
        with open(SPEECH_LOCK, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


def calibrate_noise(stream_q, frames=20):
    """Measure ambient RMS over ~0.6 s to set the speech threshold."""
    levels = []
    while len(levels) < frames:
        frame = stream_q.get()
        levels.append(float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))))
    floor = float(np.median(levels))
    return max(180.0, floor * 3.5)


def listen_for_utterance(device, focus, in_convo):
    """Capture one utterance; returns int16 samples, or None if we should yield the mic."""
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
        lock_seen_at = 0.0

        while True:
            if not in_speech and not focus.focused and not in_convo():
                return None  # window lost attention and no conversation holds the con
            frame = stream_q.get()
            if another_agent_talking():
                # That's a speaker, not the user - drop everything heard so far.
                lock_seen_at = time.monotonic()
                pre_roll, voiced, speech_frames, silent_run = [], [], 0, 0
                in_speech = False
                continue
            if not in_speech and time.monotonic() - lock_seen_at < ECHO_GRACE_S:
                continue
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
    vocab = "Claude Code, Claude agents, zsh, whisper, Kokoro, MCP, repo, squawk"
    taught = [w for w in lexicon_words() if w.lower() not in vocab.lower()]
    if taught:
        vocab += ", " + ", ".join(taught)
    result = subprocess.run(
        ["whisper-cli", "-m", str(whisper_model), "-f", wav_path,
         "--no-prints", "--no-timestamps", "--prompt", vocab],
        capture_output=True, text=True, timeout=60,
    )
    Path(wav_path).unlink(missing_ok=True)
    text = result.stdout.strip()
    if not text or JUNK_PATTERNS.match(text):
        return None
    return reverse_lexicon(text)


def ask_claude(prompt, session_id, model, system_prompt):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--append-system-prompt", system_prompt]
    if session_id:
        cmd += ["--resume", session_id]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=CLAUDE_TIMEOUT_S, cwd=os.getcwd())
        data = json.loads(result.stdout)
        return data.get("result") or "I came back empty on that one.", data.get("session_id", session_id)
    except subprocess.TimeoutExpired:
        return "Sorry, that one took too long and I gave up. Try again?", session_id
    except (json.JSONDecodeError, OSError):
        return "Sorry, I hit an error talking to my brain. Try again?", session_id


def strip_for_speech(text):
    text = re.sub(r"[*_`#>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def drain_inbox():
    if not INBOX.exists():
        return []
    messages = []
    for path in sorted(INBOX.glob("*.json")):
        try:
            messages.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
        path.unlink(missing_ok=True)
    return messages


def main():
    ap = argparse.ArgumentParser(description="Two-way voice chat with Claude (window-aware)")
    ap.add_argument("--as", dest="agent", default=None,
                    help="agent identity; determines the voice (default: project dir name)")
    ap.add_argument("--user", default="the user", help="how the assistant should refer to you")
    ap.add_argument("--model", default="haiku", help="claude model for replies (default: haiku)")
    ap.add_argument("--whisper-model", default=str(HERE / "models" / "ggml-base.en.bin"))
    ap.add_argument("--voice", default=None, help="override the assigned voice")
    ap.add_argument("--rate", default=190, type=int, help="speech rate wpm")
    ap.add_argument("--device", default=None, help="input device name or index")
    ap.add_argument("--no-focus", action="store_true",
                    help="always listen; ignore window focus (old single-instance behavior)")
    ap.add_argument("--no-barge-in", action="store_true",
                    help="disable interrupting the assistant by talking over it")
    ap.add_argument("--greeting", default=None)
    args = ap.parse_args()

    cwd = Path.cwd()
    if args.agent is None:
        args.agent = "assistant" if cwd == HERE else cwd.name
    channel_voice = args.voice or voice_for(args.agent)
    system_prompt = VOICE_SYSTEM_PROMPT_TEMPLATE.format(
        agent=args.agent, user=args.user, cwd=cwd)
    greeting = args.greeting or "I'm listening while this window has your attention."

    logs_dir = HERE / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / f"chat-{args.agent}-{datetime.datetime.now():%Y%m%d-%H%M%S}.log"

    def speak_out(text):
        """Speak; returns False if the user barged in."""
        if args.no_barge_in:
            speak_serialized(text, agent=args.agent, voice=args.voice, rate=args.rate)
            return True
        with BargeInMonitor(args.device) as monitor:
            return speak_serialized(text, agent=args.agent, voice=args.voice, rate=args.rate,
                                    interrupt_check=monitor.interrupted)

    focus = FocusTracker(enabled=not args.no_focus)
    mic = MicLock()
    convo_until = 0.0
    in_convo = lambda: time.monotonic() < convo_until
    session_id = None
    greeted = False

    log_line(log_file, "system",
             f"starting: agent={args.agent} model={args.model} cwd={cwd} "
             f"focus={'on' if focus.supported else 'off (always listening)'}")

    try:
        while True:
            should_hold = focus.focused or in_convo()

            if should_hold and not mic.held:
                if mic.try_acquire():
                    channel.set_floor(agent=args.agent, voice=channel_voice,
                                      project=str(cwd), mode="conversation",
                                      detail="listening")
                    log_line(log_file, "system", "* listening (window focused)")
                    if not greeted:
                        greeted = True
                        speak_out(greeting)
                else:
                    time.sleep(0.3)
                    continue
            elif not should_hold and mic.held:
                mic.release()
                channel.clear_floor(agent=args.agent)
                log_line(log_file, "system", "- standing by (window unfocused)")

            if not mic.held:
                time.sleep(0.3)
                continue

            for msg in drain_inbox():
                relay = f"Relay from {msg.get('from', 'an agent')}: {msg.get('text', '')}"
                log_line(log_file, "relay", relay)
                speak_out(relay)
                convo_until = time.monotonic() + CONVO_GRACE_S

            samples = listen_for_utterance(args.device, focus, in_convo)
            if samples is None:
                continue
            text = transcribe(samples, args.whisper_model)
            if not text:
                continue
            log_line(log_file, "you", text)
            convo_until = time.monotonic() + CONVO_GRACE_S

            if any(p in text.lower() for p in EXIT_PHRASES):
                speak_out("Goodbye. Ending the voice link.")
                log_line(log_file, "system", "exit phrase heard, shutting down")
                break

            pronounce = PRONOUNCE_RE.search(text)
            if pronounce:
                word, phonetic = pronounce.group(1).strip(" ,.'\""), pronounce.group(2).strip(" ,.'\"")
                if word.lower() == phonetic.lower():
                    # reverse_lexicon already canonicalized the phonetic - nothing new to learn
                    speak_out(f"{word} already sounds like that to me.")
                    continue
                teach(word, phonetic)
                squashed = re.sub(r"[\s\-.]+", "", word)
                if squashed.lower() != word.lower():
                    teach(squashed, phonetic)  # whisper often hears compound names with spaces
                log_line(log_file, "system", f"learned pronunciation: {word} -> {phonetic}")
                speak_out(f"Learned. {word} now sounds like this: {word}.")
                continue

            had_session = session_id
            reply, session_id = ask_claude(text, session_id, args.model, system_prompt)
            if session_id and not had_session:
                log_line(log_file, "system", f"claude session: {session_id}")
            reply = strip_for_speech(reply)
            log_line(log_file, "claude", reply)
            if not speak_out(reply):
                log_line(log_file, "system", "barge-in: stopped talking to listen")
    except KeyboardInterrupt:
        log_line(log_file, "system", "interrupted, exiting")
    finally:
        mic.release()
        channel.clear_floor(agent=args.agent)
        focus.restore()


if __name__ == "__main__":
    main()
