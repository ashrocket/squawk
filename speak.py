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
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEECH_LOCK = HERE / ".speech.lock"
REGISTRY = HERE / "voices.json"
REGISTRY_LOCK = HERE / ".voices.lock"

# The system default voice (no -v flag) is by far the best quality installed.
# Named compact voices are noticeably worse; Apple Premium/Enhanced voices match
# the default's quality once downloaded (System Settings > Accessibility >
# Spoken Content > System Voice > Manage Voices) and are auto-preferred here.
DEFAULT_VOICE = "default"
CURATED_BASIC = [
    "Karen", "Moira", "Tessa", "Rishi", "Tara", "Aman",
    "Eddy (English (US))", "Flo (English (US))", "Reed (English (UK))",
    "Rocko (English (US))", "Sandy (English (UK))", "Shelley (English (US))",
    "Samantha", "Daniel",
]
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
    """Best available voices, best first: default, Premium, Enhanced, curated basics."""
    voices = installed_english_voices()
    premium = sorted(v for v in voices if "(Premium)" in v)
    enhanced = sorted(v for v in voices if "(Enhanced)" in v)
    basics = [v for v in CURATED_BASIC if v in voices]
    return [DEFAULT_VOICE] + premium + enhanced + basics


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


def speak(text, agent="assistant", rate=None, voice=None, announce=False):
    """Speak text aloud; blocks until no other agent is talking."""
    voice = voice or voice_for(agent)
    if announce:
        text = f"{agent.replace('-', ' ')} here. {text}"
    with open(SPEECH_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cmd = ["say"] if voice == DEFAULT_VOICE else ["say", "-v", voice]
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
