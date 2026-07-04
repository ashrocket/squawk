#!/usr/bin/env python3
"""Squawk Stop hook: speak Claude's actual last message when Squawk Mode is on.

Reads the Stop-hook JSON on stdin: {transcript_path, session_id, stop_hook_active,...}.
Gated on the same per-session state file /squawk-mode writes. Fire-and-forget:
spawns the speaker detached so the hook returns instantly (no 8s-timeout pressure).
"""
import json, os, re, subprocess, sys

def default_squawk_root():
    if os.environ.get("SQUAWK_ROOT"):
        return os.environ["SQUAWK_ROOT"]
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return os.path.dirname(os.environ["CLAUDE_PLUGIN_ROOT"])
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

SQUAWK_ROOT = default_squawk_root()
PLUGIN_ROOT = os.path.join(SQUAWK_ROOT, "claude-plugin")
MAX_CHARS = 240

# --- opt-in feature flags ---
RELAY_AWARE = True    # 4a: queue (--relay) if a voice_chat.py conversation is live
USE_NOTIFY  = False   # 4b: route through notify.sh (speak local / Pidgin when away)
# notify.sh itself reads SQUAWK_ALSO_PIDGIN for 4c dual delivery.

def state_file():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    sid = re.sub(r"[^A-Za-z0-9._-]", "_", os.environ.get("CLAUDE_CODE_SESSION_ID", "global"))
    return os.path.join(base, "squawk", "claude-mode", f"{sid}.env")

def read_agent(path):
    agent = "claude"
    try:
        with open(path) as fh:
            for line in fh:
                m = re.match(r"\s*agent=(.+?)\s*$", line)
                if m:
                    agent = m.group(1).strip().strip("'\"")
    except OSError:
        pass
    return agent

def last_assistant_text(transcript_path):
    text = ""
    try:
        with open(transcript_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                msg = obj.get("message") or {}
                if obj.get("type") == "assistant" or msg.get("role") == "assistant":
                    content = msg.get("content")
                    if isinstance(content, list):
                        parts = [b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text"]
                        joined = " ".join(p for p in parts if p).strip()
                        if joined:
                            text = joined
                    elif isinstance(content, str) and content.strip():
                        text = content.strip()
    except OSError:
        return ""
    return text

def clean(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)       # code fences
    text = re.sub(r"`[^`]*`", " ", text)                      # inline code
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)    # links / images -> label
    text = re.sub(r"https?://\S+", " ", text)                 # bare urls
    text = re.sub(r"[#>*_~|`-]+", " ", text)                  # md punctuation
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        dot = cut.rfind(". ")
        text = (cut[:dot + 1] if dot > 60 else cut).strip()
    return text

def voice_active():
    try:
        return subprocess.run(["pgrep", "-f", "[v]oice_chat.py"],
                              capture_output=True).returncode == 0
    except OSError:
        return False

def speak(agent, text):
    if USE_NOTIFY:
        cmd = ["bash", os.path.join(PLUGIN_ROOT, "scripts", "notify.sh"), text]
        try:
            subprocess.Popen(cmd, start_new_session=True,
                             env={**os.environ, "SQUAWK_AGENT": agent})
        except OSError:
            pass
        return
    args = [os.path.join(SQUAWK_ROOT, "speak"), "--as", agent]
    if RELAY_AWARE and voice_active():
        args.insert(1, "--relay")
    if not os.access(args[0], os.X_OK):
        return
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, text=True,
                                start_new_session=True)
        proc.stdin.write(text)
        proc.stdin.close()
    except OSError:
        pass

def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not os.path.isfile(state_file()):           # Squawk Mode off -> silent
        return 0
    tp = payload.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        return 0
    spoken = clean(last_assistant_text(tp))
    if spoken:
        speak(read_agent(state_file()), spoken)
    return 0

if __name__ == "__main__":
    sys.exit(main())
