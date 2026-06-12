#!/usr/bin/env python3
"""Serialized per-agent text-to-speech for the whole machine.

Any process (e.g. a Claude Code agent in another cmux tab) can say something with:

    ~/ashcode/voice-chat/speak --as my-agent-name "Build finished, all tests pass."

A global lock guarantees only one voice talks at a time; voices.json maps each
agent name to its own macOS voice, assigned from a pool on first use.
"""
import argparse
import fcntl
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEECH_LOCK = HERE / ".speech.lock"
INBOX = HERE / "inbox"
REGISTRY = HERE / "voices.json"
REGISTRY_LOCK = HERE / ".voices.lock"
LEXICON = HERE / "lexicon.json"
LEXICON_LOCK = HERE / ".lexicon.lock"

# The system default voice (no -v flag) is by far the best quality installed.
# Named compact voices are noticeably worse; Apple Premium/Enhanced voices match
# the default's quality once downloaded (System Settings > Accessibility >
# Spoken Content > System Voice > Manage Voices) and are auto-preferred here.
DEFAULT_VOICE = "default"
KOKORO_MODEL = HERE / "models" / "kokoro-v1.0.onnx"
KOKORO_VOICES_BIN = HERE / "models" / "voices-v1.0.bin"
# Local neural TTS (kokoro-onnx); distinct US/GB voices, female/male alternating.
KOKORO_VOICES = [
    "kokoro:af_heart", "kokoro:am_michael", "kokoro:bf_emma", "kokoro:bm_george",
    "kokoro:af_nicole", "kokoro:am_puck", "kokoro:bf_isabella", "kokoro:bm_lewis",
]
# Optional explicit pool written by the Squawk settings app; ordered, best first.
POOL_FILE = HERE / "pool.json"
# Decent compact voices that ship with macOS; last-resort fallback so agents
# stay distinct on a fresh machine with nothing downloaded yet.
FALLBACK_BASICS = ["Samantha", "Daniel", "Karen", "Moira", "Tessa", "Rishi"]
VOICE_LINE = re.compile(r"^(.*?)\s+en[_-][A-Z]{2}\s+#")


def installed_english_voices():
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                             timeout=10).stdout
    except OSError:
        return []
    return [m.group(1).strip() for line in out.splitlines()
            if (m := VOICE_LINE.match(line))]


def build_pool():
    """Best available voices, best first: default, Kokoro, Premium.

    Per Ashley's 2026-06 full-pool listening test: all eight Kokoro voices
    approved (above Premium), Premiums all kept, and the Enhanced and
    basic/compact tiers dropped entirely ("robotic").

    A pool.json (written by the Squawk settings app) overrides the computed
    pool; entries no longer available on this machine are dropped.
    """
    voices = installed_english_voices()
    if POOL_FILE.exists():
        kokoro_ok = KOKORO_MODEL.exists() and KOKORO_VOICES_BIN.exists()
        chosen = json.loads(POOL_FILE.read_text())
        return [v for v in chosen
                if v == DEFAULT_VOICE
                or (v.startswith("kokoro:") and kokoro_ok and v in KOKORO_VOICES)
                or v in voices]
    premium = sorted(v for v in voices if "(Premium)" in v)
    kokoro = KOKORO_VOICES if KOKORO_MODEL.exists() and KOKORO_VOICES_BIN.exists() else []
    pool = [DEFAULT_VOICE] + kokoro + premium
    if len(pool) < 4:  # fresh machine: nothing downloaded; keep agents distinct
        pool += sorted(v for v in voices if "(Enhanced)" in v)
    if len(pool) < 4:
        pool += [v for v in FALLBACK_BASICS if v in voices]
    return pool


KOKORO_SOCKET = HERE / ".kokoro.sock"


def _kokoro_daemon_request(text, kokoro_voice, timeout=45):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(KOKORO_SOCKET))
        sock.sendall((json.dumps({"text": text, "voice": kokoro_voice}) + "\n").encode())
        response = json.loads(sock.makefile().readline())
    finally:
        sock.close()
    if "wav" in response:
        return response["wav"]
    raise RuntimeError(response.get("error", "kokoro daemon error"))


def _synthesize_in_process(text, kokoro_voice):
    import tempfile
    import wave

    import numpy as np
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES_BIN))
    samples, sr = kokoro.create(text, voice=kokoro_voice, speed=1.0)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return tmp.name


def synthesize_kokoro(text, kokoro_voice):
    """Render text to a temp wav; prefers the resident daemon, spawning it on demand.

    The daemon keeps the model loaded for instant synthesis and exits itself
    after 10 idle minutes. Falls back to in-process synthesis if it won't start.
    """
    try:
        return _kokoro_daemon_request(text, kokoro_voice)
    except (OSError, RuntimeError, json.JSONDecodeError):
        pass

    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "kokoro-daemon.log", "a") as out:
        subprocess.Popen([sys.executable, str(HERE / "kokoro_daemon.py")],
                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            return _kokoro_daemon_request(text, kokoro_voice)
        except (OSError, json.JSONDecodeError):
            time.sleep(0.3)
        except RuntimeError:
            break  # daemon answered with an error; don't retry it
    return _synthesize_in_process(text, kokoro_voice)


def voice_for(agent):
    """Return the agent's assigned voice, assigning the next free one if new."""
    with open(REGISTRY_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
        if agent not in registry:
            pool = build_pool()
            used = set(registry.values())
            registry[agent] = next(
                (v for v in pool if v not in used),
                pool[sum(agent.encode()) % len(pool)],
            )
            REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
        return registry[agent]


def load_lexicon():
    return json.loads(LEXICON.read_text()) if LEXICON.exists() else {}


def teach(word, phonetic):
    """Persist a pronunciation fix; every agent picks it up on its next sentence."""
    with open(LEXICON_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        lexicon = load_lexicon()
        lexicon[word.strip().lower()] = phonetic.strip()
        LEXICON.write_text(json.dumps(lexicon, indent=2) + "\n")


def apply_lexicon(text):
    """Rewrite words the TTS mispronounces (lexicon.json: word -> phonetic spelling)."""
    for word, phonetic in load_lexicon().items():
        text = re.sub(rf"\b{re.escape(word)}\b", phonetic, text, flags=re.IGNORECASE)
    return text


def reverse_lexicon(text):
    """STT side: map phonetic spellings the recognizer heard back to canonical words.

    Longer phonetics first so 'sea mux deluxe' wins over 'sea mux'. Tokens may be
    joined by spaces or hyphens in the transcript.
    """
    for word, phonetic in sorted(load_lexicon().items(), key=lambda kv: -len(kv[1])):
        tokens = [re.escape(t) for t in phonetic.split()]
        if not tokens:
            continue
        pattern = r"\b" + r"[\s\-]+".join(tokens) + r"\b"
        text = re.sub(pattern, word, text, flags=re.IGNORECASE)
    return text


def lexicon_words():
    """Canonical taught words, for biasing the speech recognizer's vocabulary."""
    return list(load_lexicon().keys())


def relay(text, agent="agent"):
    """Queue a short message for the active voice conversation to read aloud."""
    INBOX.mkdir(exist_ok=True)
    (INBOX / f"{time.time_ns()}-{agent}.json").write_text(
        json.dumps({"from": agent.replace("-", " "), "text": text}))


def speak(text, agent="assistant", rate=None, voice=None, announce=False, interrupt_check=None):
    """Speak text aloud; blocks until no other agent is talking.

    interrupt_check: optional callable polled during playback; return True to cut
    the speech off. Returns False if playback was interrupted, True otherwise.
    """
    voice = voice or voice_for(agent)
    if announce:
        text = f"{agent.replace('-', ' ')} here. {text}"
    text = apply_lexicon(text)

    wav = None
    if voice.startswith("kokoro:"):
        try:
            wav = synthesize_kokoro(text, voice.split(":", 1)[1])  # before the lock: don't block other talkers
        except Exception as exc:
            print(f"kokoro failed ({exc}); falling back to say", file=sys.stderr)
            voice = DEFAULT_VOICE

    with open(SPEECH_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if wav:
            cmd = ["afplay", wav]
        else:
            cmd = ["say"] if voice == DEFAULT_VOICE else ["say", "-v", voice]
            if rate:
                cmd += ["-r", str(rate)]
            cmd.append(text)
        proc = subprocess.Popen(cmd)
        completed = True
        if interrupt_check is None:
            proc.wait()
        else:
            while proc.poll() is None:
                if interrupt_check():
                    proc.terminate()
                    completed = False
                    break
                time.sleep(0.08)
            proc.wait()
        if wav:
            Path(wav).unlink(missing_ok=True)
        return completed


def main():
    ap = argparse.ArgumentParser(description="Speak aloud, one agent at a time, distinct voices")
    ap.add_argument("--as", dest="agent", default="assistant",
                    help="agent identity; determines the voice (default: assistant)")
    ap.add_argument("--rate", type=int, default=None, help="speech rate wpm")
    ap.add_argument("--voice", default=None, help="override the assigned voice")
    ap.add_argument("--announce", action="store_true",
                    help="prefix speech with the agent's name")
    ap.add_argument("--teach", action="append", metavar="WORD=PHONETIC",
                    help='fix a pronunciation, e.g. --teach "cmux=sea mux"')
    ap.add_argument("--relay", action="store_true",
                    help="don't speak now; queue the message for the active voice "
                         "conversation to read aloud between turns")
    ap.add_argument("text", nargs="*", help="text to speak (or pipe via stdin)")
    args = ap.parse_args()

    for pair in args.teach or []:
        word, _, phonetic = pair.partition("=")
        teach(word, phonetic)
        print(f"learned: {word.strip().lower()} -> {phonetic.strip()}")

    text = " ".join(args.text) if args.text else ("" if args.teach else sys.stdin.read())
    text = text.strip()
    if not text:
        sys.exit(0)
    if args.relay:
        relay(text, agent=args.agent)
        print("queued for relay (delivered when a voice conversation is active)")
        return
    speak(text, agent=args.agent, rate=args.rate, voice=args.voice, announce=args.announce)


if __name__ == "__main__":
    main()
