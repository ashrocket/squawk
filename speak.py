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
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEECH_LOCK = HERE / ".speech.lock"
REGISTRY = HERE / "voices.json"
REGISTRY_LOCK = HERE / ".voices.lock"

# Ordered for maximum distinctness: US, GB, AU, IE, ZA, IN accents first.
VOICE_POOL = [
    "Samantha", "Daniel", "Karen", "Moira", "Tessa", "Rishi", "Tara", "Aman",
    "Eddy (English (US))", "Flo (English (US))", "Reed (English (UK))",
    "Rocko (English (US))", "Sandy (English (UK))", "Shelley (English (US))",
]


def voice_for(agent):
    """Return the agent's assigned voice, assigning the next free one if new."""
    with open(REGISTRY_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
        if agent not in registry:
            used = set(registry.values())
            registry[agent] = next(
                (v for v in VOICE_POOL if v not in used),
                VOICE_POOL[sum(agent.encode()) % len(VOICE_POOL)],
            )
            REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
        return registry[agent]


def speak(text, agent="assistant", rate=None, voice=None, announce=False):
    """Speak text aloud; blocks until no other agent is talking."""
    voice = voice or voice_for(agent)
    if announce:
        text = f"{agent.replace('-', ' ')} here. {text}"
    with open(SPEECH_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cmd = ["say", "-v", voice]
        if rate:
            cmd += ["-r", str(rate)]
        cmd.append(text)
        subprocess.run(cmd, check=False)


def main():
    ap = argparse.ArgumentParser(description="Speak aloud, one agent at a time, distinct voices")
    ap.add_argument("--as", dest="agent", default="assistant",
                    help="agent identity; determines the voice (default: assistant)")
    ap.add_argument("--rate", type=int, default=None, help="speech rate wpm")
    ap.add_argument("--voice", default=None, help="override the assigned voice")
    ap.add_argument("--announce", action="store_true",
                    help="prefix speech with the agent's name")
    ap.add_argument("text", nargs="*", help="text to speak (or pipe via stdin)")
    args = ap.parse_args()

    text = " ".join(args.text) if args.text else sys.stdin.read()
    text = text.strip()
    if not text:
        sys.exit(0)
    speak(text, agent=args.agent, rate=args.rate, voice=args.voice, announce=args.announce)


if __name__ == "__main__":
    main()
