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
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import channel_state as channel

HERE = Path(__file__).resolve().parent
SPEECH_LOCK = channel.SPEECH_LOCK
INBOX = channel.INBOX
REGISTRY = channel.REGISTRY
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


SQUAWKD_SOCKET = HERE / ".squawkd.sock"
PRIORITIES = {"normal": 0, "urgent": 10}


def detect_session():
    """The Claude Code session id, when running inside one."""
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def detect_source():
    """Best available identifier for the terminal window this speaker runs in."""
    explicit = os.environ.get("SQUAWK_SOURCE")
    if explicit:
        return explicit
    shim = os.environ.get("CMUX_CLAUDE_WRAPPER_SHIM_ROOT")
    if shim:
        return f"cmux:{Path(shim).name}"
    iterm = os.environ.get("ITERM_SESSION_ID")
    if iterm:
        return f"iterm:{iterm}"
    try:
        if sys.stdin.isatty():
            return os.ttyname(sys.stdin.fileno())
    except OSError:
        pass
    return os.environ.get("TERM_PROGRAM")


def _squawkd_call(payload, timeout):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(SQUAWKD_SOCKET))
        sock.sendall((json.dumps(payload) + "\n").encode())
        line = sock.makefile().readline()
    finally:
        sock.close()
    if not line:
        raise RuntimeError("squawkd closed the connection")
    return json.loads(line)


def squawkd_call(payload, timeout=10.0, spawn=True):
    """Send one request to the multiplexer daemon, spawning it on demand."""
    try:
        return _squawkd_call(payload, timeout)
    except (OSError, RuntimeError, json.JSONDecodeError):
        if not spawn:
            raise

    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "squawkd.log", "a") as out:
        subprocess.Popen([sys.executable, str(HERE / "squawkd.py")],
                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            return _squawkd_call(payload, timeout)
        except (OSError, json.JSONDecodeError):
            time.sleep(0.3)
    raise RuntimeError("squawk multiplexer daemon did not start")


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


def relay(text, agent="agent", kind="relay"):
    """Queue a short message for the active voice conversation to read aloud."""
    voice = voice_for(agent)
    return channel.request_airtime(text, agent=agent, voice=voice, kind=kind)


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
        channel.set_transmission(agent=agent, voice=voice, text=text)
        try:
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
            return completed
        finally:
            channel.clear_transmission(agent=agent)
            if wav:
                Path(wav).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Speak aloud, one agent at a time, distinct voices")
    ap.add_argument("--as", dest="agent", default="assistant",
                    help="agent identity; determines the voice (default: assistant)")
    ap.add_argument("--rate", type=int, default=None, help="speech rate wpm")
    ap.add_argument("--voice", default=None, help="override the assigned voice")
    ap.add_argument("--announce", action="store_true",
                    help="opt in to prefixing speech with the agent's name")
    ap.add_argument("--teach", action="append", metavar="WORD=PHONETIC",
                    help='fix a pronunciation, e.g. --teach "cmux=sea mux"')
    ap.add_argument("--relay", action="store_true",
                    help="don't speak now; queue the message for the active voice "
                         "conversation to read aloud between turns")
    ap.add_argument("--request", action="store_true",
                    help="request airtime on the shared channel instead of speaking now")
    ap.add_argument("--ask", action="store_true",
                    help="speak a question, then block until the user answers it "
                         "(in Squawk.app or via --answer); prints the answer")
    ap.add_argument("--answer", metavar="ID",
                    help="answer a pending question by id ('latest' targets the "
                         "oldest unanswered one); the text is the answer")
    ap.add_argument("--no-wait", action="store_true",
                    help="queue on the multiplexer and return immediately")
    ap.add_argument("--priority", choices=sorted(PRIORITIES), default="normal",
                    help="urgent jumps the queue (but never interrupts mid-utterance)")
    ap.add_argument("--timeout", type=float, default=600.0,
                    help="seconds to wait for an answer with --ask (default 600)")
    ap.add_argument("--local", action="store_true",
                    help="bypass the multiplexer daemon and speak from this process")
    ap.add_argument("--session", default=None,
                    help="origin session tag (default: $CLAUDE_CODE_SESSION_ID)")
    ap.add_argument("--source", default=None,
                    help="origin terminal tag (default: auto-detected)")
    ap.add_argument("--project", default=None,
                    help="origin project tag (default: current directory name)")
    ap.add_argument("--status", action="store_true",
                    help="show the shared Squawk channel, agents, voices, and queue")
    ap.add_argument("--json", action="store_true",
                    help="with --status, emit machine-readable JSON")
    ap.add_argument("text", nargs="*", help="text to speak (or pipe via stdin)")
    args = ap.parse_args()

    if args.status:
        status = channel.snapshot(available_voices=build_pool())
        try:
            status["multiplexer"] = squawkd_call(
                {"op": "status"}, timeout=3.0, spawn=False).get("multiplexer")
        except (OSError, RuntimeError, json.JSONDecodeError):
            status["multiplexer"] = None
        if args.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print(channel.format_snapshot(status))
        return

    for pair in args.teach or []:
        word, _, phonetic = pair.partition("=")
        teach(word, phonetic)
        print(f"learned: {word.strip().lower()} -> {phonetic.strip()}")

    text = " ".join(args.text) if args.text else ("" if args.teach else sys.stdin.read())
    text = text.strip()

    if args.answer:
        if not text:
            sys.exit("an answer needs text")
        try:
            reply = squawkd_call({"op": "answer", "id": args.answer, "text": text,
                                  "from": args.agent}, timeout=5.0, spawn=False)
        except (OSError, RuntimeError, json.JSONDecodeError):
            sys.exit("no multiplexer daemon running (so no pending questions)")
        if not reply.get("ok"):
            sys.exit(reply.get("error", "answer failed"))
        print(f"answered {reply['id']}")
        return

    if not text:
        sys.exit(0)
    if args.relay or args.request:
        request = relay(text, agent=args.agent,
                        kind="request" if args.request else "relay")
        print(f"queued for channel ({request['id']})")
        return

    use_daemon = not args.local and not os.environ.get("SQUAWK_NO_DAEMON")
    if args.ask or use_daemon:
        payload = {
            "op": "ask" if args.ask else "speak",
            "text": text,
            "agent": args.agent,
            "voice": args.voice,
            "rate": args.rate,
            "announce": args.announce,
            "session": args.session or detect_session(),
            "source": args.source or detect_source(),
            "project": args.project or Path.cwd().name,
            "priority": PRIORITIES[args.priority],
            "wait": not args.no_wait,
            "timeout": args.timeout,
        }
        socket_timeout = args.timeout + 60 if args.ask else (1800 if not args.no_wait else 20)
        try:
            reply = squawkd_call(payload, timeout=socket_timeout)
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            if args.ask:
                sys.exit(f"multiplexer unavailable, can't ask: {exc}")
            print(f"multiplexer unavailable ({exc}); speaking locally", file=sys.stderr)
            speak(text, agent=args.agent, rate=args.rate, voice=args.voice,
                  announce=args.announce)
            return
        if args.ask:
            if reply.get("timed_out") or not reply.get("ok"):
                sys.exit(f"no answer within {args.timeout:.0f}s")
            print(reply.get("answer", ""))
        elif args.no_wait:
            print(f"queued ({reply.get('id')})")
        return

    speak(text, agent=args.agent, rate=args.rate, voice=args.voice, announce=args.announce)


if __name__ == "__main__":
    main()
