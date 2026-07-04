# Squawk × Claude Code — Voice Interaction Modes (Implementation Plan)

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. This is an *integration* plan (wiring an existing local system into Claude Code), not a greenfield build — most of the engine already exists. Each mode below is independently shippable.

**Goal:** Configure four voice-interaction modes between the user and Claude Code on top of the existing Squawk system (`~/ashcode/squawk`): (1) Claude narrates aloud while you type, (2) you speak and Claude reads it as input, (3) full spoken two-way conversation, (4) relay/queue, Pidgin fallback, phone delivery, and wake-word.

**Architecture:** Squawk is a fully-local macOS voice stack — `speak.py` (TTS box: lock + voice registry + lexicon + Kokoro dispatch) fronted by a resident `kokoro_daemon.py` over a Unix socket, and `voice_chat.py` (mic → whisper.cpp → `claude -p` → TTS). A Claude Code plugin (`claude-plugin/`) exposes `/squawk-mode`, `/squawk-off`, `/squawk-say`, a Stop hook, and `squawk-speak.sh`. Integration is done through Claude Code **hooks** (outbound) and Claude Code's **native voice input** (inbound), with **Pidgin** as the phone/watch fallback channel.

**Tech stack:** macOS, Python 3.14 venv (`~/ashcode/squawk/.venv`), `sounddevice`/`numpy`, `whisper-cli` (whisper.cpp, Metal) + `ggml-base.en.bin`, `kokoro-onnx` + `afplay`/macOS `say`, Claude Code hooks/skills/plugins, Pidgin CLI (`pidgin.sh` → APNs).

## Global Constraints

- **All paths are absolute and machine-specific** (`/Users/ashrocket/...`). Squawk repo root: `/Users/ashrocket/ashcode/squawk`. Plugin root: `/Users/ashrocket/ashcode/squawk/claude-plugin`.
- **`CLAUDE_PLUGIN_ROOT` is injected by Claude Code only for *installed plugins*.** Squawk is currently a skills-dir symlink, so it is **unset** for Squawk. Anything wired through `~/.claude/settings.json` (not the plugin) must use absolute paths, never `${CLAUDE_PLUGIN_ROOT}`.
- **`PIDGIN_URL`** is set in settings `env`; **`PIDGIN_API_KEY` lives only in `~/.zshrc:58`** — hooks inherit it only if Claude Code was launched from a shell that sourced `~/.zshrc`. Guard for its absence.
- **Squawk has no health command.** Availability must be inferred (`[ -x .../speak ]` + local-session check). Pidgin *does* have `pidgin.sh check` (exit-coded).
- **One global speech lock** (`.speech.lock`, `fcntl.flock`) serializes all TTS machine-wide. The Kokoro daemon idle-exits after 600 s and self-respawns on demand.
- Keep spoken text short (≤ ~240 chars / ~one to two sentences) — it is the difference between a 4 s and a 20 s utterance.

---

## TL;DR — the one thing to fix first

Mode 1 (outbound narration) feels "half working" because **the Stop hook never fires**: Squawk is installed via `~/.claude/skills/squawk → claude-plugin/`, and the skills-dir loader ignores `hooks/hooks.json`. The slash commands (`/squawk-mode`, `/squawk-say`) *are* available because skills/commands are discovered by directory; **only the hook is dormant.** Fix = add one `Stop` hook to `~/.claude/settings.json` with an **absolute** path (Mode 1, Step 2). Everything else is layered on top of that.

---

## Current State — grounded map of what exists today

### Outbound TTS (built, solid)
- `~/ashcode/squawk/speak` → 4-line bash wrapper → `.venv/bin/python speak.py`. **Not on `$PATH`**; called by absolute path. Flags: positional `text` (or **stdin**), `--as <agent>` (voice identity, default `assistant`), `--voice`, `--rate` (macOS `say` only), `--announce` (opt-in prefix with the agent name), `--teach WORD=PHONETIC`, `--relay` (queue, don't speak now). **Blocks until audio finishes** except `--relay` (returns immediately). Exit 0 on success/fallback; `127` from the plugin wrapper if `speak` not found.
- `kokoro_daemon.py` → resident neural TTS over Unix socket `~/ashcode/squawk/.kokoro.sock`. Idle-exits after `KOKORO_DAEMON_IDLE_S` (default 600 s); single-instance `flock`. **Started on-demand by `speak.py`** (no launchd). Returns a temp WAV path; the client plays via `afplay` then deletes it.
- Fallback chain: warm daemon → spawn+poll daemon (≤25 s cold load) → in-process Kokoro → macOS `say`. Kokoro failure never errors the command (degrades to `say`).
- **No real outbound queue** — only mutual exclusion. Concurrent callers block their own process; order is undefined.

### Inbound STT (built, but entangled)
- Lives in `voice_chat.py` (+ helpers from `speak.py`). Mic via `sounddevice` (16 kHz mono int16, 30 ms frames). STT via external **`whisper-cli`** (`/opt/homebrew/bin/whisper-cli`) on `models/ggml-base.en.bin` (~148 MB), **per-utterance** (no resident STT server). Turn-taking = **energy VAD** (adaptive noise floor, 1.1 s trailing silence, 45 s cap) — **no webrtcvad, no push-to-talk, no fixed duration**. Echo suppression by discarding mic input while the speech lock is held.
- **No standalone "transcribe one utterance → stdout" entry point** — only the full chat loop is exposed.
- **No wake word** anywhere (explicit roadmap `[ ]`).

### The Claude Code plugin (`claude-plugin/`, partially active)
- Manifest `‎.claude-plugin/plugin.json` (name `squawk` v0.2.0) — metadata only; relies on convention discovery.
- `/squawk-mode` → writes per-session state file + speaks confirmation; "mode" is mostly **behavioral prompting** of the model. `/squawk-off` → deletes state. `/squawk-say` → speaks `$ARGUMENTS` **unconditionally** (no gate).
- State file: `${XDG_STATE_HOME:-$HOME/.local/state}/squawk/claude-mode/<CLAUDE_CODE_SESSION_ID>.env` (gating is by **file existence**; `enabled=1` is written but never read).
- Stop hook `hooks/scripts/stop-announce.sh`: **does not read the transcript and does not speak** — it prints a prompt asking the *model* to compose a `<SUMMARY>` and call `squawk-speak.sh`. Gated on the state file; `.pending` loop-guard. **Only `Stop`** (no `SubagentStop`/`Notification`). **This hook is not loaded today** (skills-dir install).
- `scripts/squawk-speak.sh`: resolves `speak` via `$SQUAWK_ROOT` → `.local.env` → `$PLUGIN_ROOT/..` → hardcoded `/Users/ashrocket/ashcode/squawk`. `SQUAWK_DRY_RUN=1` echoes instead of speaking. **No enabled-gate.**
- Installed by `install.sh`: symlinks `~/.claude/skills/squawk → claude-plugin/` and writes `.local.env` (`SQUAWK_ROOT=...`). Plugin dir is **untracked in git**.

### Claude Code config & native voice
- `~/.claude/settings.json`: **no `hooks` block at all.** `env` has `PIDGIN_URL` (no `SQUAWK_*`). `enabledPlugins` has `pidgin@pidgin: true`; **squawk is absent** (not a plugin). `additionalDirectories` includes `/Users/ashrocket/ashcode` (Squawk is already a trusted dir). `permissions.allow` has `Bash(python *)` etc. but **no generic `Bash(bash *)`** — model-run `bash <script>` may prompt.
- **Native voice input is ON:** `"voice": { "enabled": true, "mode": "hold" }` and `"voiceEnabled": true`. `mode: hold` = push-to-talk dictation built into Claude Code. This is the zero-build answer for Mode 2.
- The **Pidgin plugin already registers its own `Stop` hook** (`stop-notify.sh`, `matcher: ""`). If Squawk's Stop hook is added too, both fire each turn (see *Cross-cutting* below).

### Pidgin (built, has health check)
- CLI: `/Users/ashrocket/ashcode/pidgin/scripts/pidgin.sh` (source; mirrored in the installed plugin cache). Send: `PIDGIN_URL=… PIDGIN_API_KEY=… bash pidgin.sh send --type <type> --title "…" --body "…" --project "…"`. Content types: `--body` (text), `--markdown`/`--markdown-file` (server-typeset document), `--html` (raw). `ask` = send + block-poll for a phone reply. **`pidgin.sh check`** verifies env + server `/health` and returns nonzero on failure (usable as a gate).

---

## Mode 1 — One-way outbound (Claude → you)

**You type normally; Claude narrates progress/results aloud. No mic.**

**Architecture:** two complementary triggers — (a) **mid-work narration**: the `squawk` SKILL already tells the model to call `squawk-speak.sh` at meaningful milestones (works now, model-driven); (b) **completion narration**: a Stop hook. We make (b) deterministic by speaking Claude's *actual* last message rather than prompting the model for a summary.

**What's already built**
- The entire TTS engine and `squawk-speak.sh` wrapper (self-healing daemon, `say` fallback).
- `/squawk-mode` / `/squawk-off` / `/squawk-say` slash commands (available in this session right now).
- The shipped Stop hook script + per-session state-file gate + `.pending` loop-guard.

**What's missing / broken**
- ❌ **Stop hook is not loaded** (skills-dir install ignores `hooks/hooks.json`). → completion narration never fires.
- ❌ The shipped hook is **indirect** (prompts the model; burns a turn; emits a literal `${CLAUDE_PLUGIN_ROOT}` that is unset outside plugin context → the model would run a broken `bash /scripts/squawk-speak.sh`).
- ❌ No `SubagentStop` / `Notification` hooks → subagent completions and "needs input" prompts are silent.
- ❌ Model-run `bash squawk-speak.sh` may hit a permission prompt (no `Bash(bash *)` allow).

**Minimal wiring**

- [ ] **Step 1 — Create the deterministic narrator** `‎/Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop_speak_last.py` (full content in **Appendix A.1**). It reads the Stop-hook JSON, checks the per-session state file (so it only speaks when `/squawk-mode` is on), extracts + cleans Claude's last assistant message, and fire-and-forget spawns `speak`. No model turn, no `CLAUDE_PLUGIN_ROOT` dependency.

- [ ] **Step 2 — Add the Stop hook to `~/.claude/settings.json`** (absolute path; see **Appendix B.1**):
```json
"hooks": {
  "Stop": [
    { "matcher": "", "hooks": [
      { "type": "command",
        "command": "python3 /Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop_speak_last.py",
        "timeout": 5 }
    ]}
  ]
}
```

- [ ] **Step 3 — Allow model-driven narration without a prompt** — add to `permissions.allow` in `~/.claude/settings.json` (**Appendix B.2**):
```json
"Bash(bash /Users/ashrocket/ashcode/squawk/claude-plugin/scripts/squawk-speak.sh *)"
```

- [ ] **Step 4 — Verify the narrator in isolation** (no Claude needed):
```bash
printf '{"transcript_path":"/dev/stdin"}' | true   # sanity
# enable mode for a throwaway session id, then dry-run:
CLAUDE_CODE_SESSION_ID=test bash /Users/ashrocket/ashcode/squawk/claude-plugin/scripts/squawk-mode.sh on
echo '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"All tests pass. Done."}]}}' > /tmp/t.jsonl
echo "{\"transcript_path\":\"/tmp/t.jsonl\"}" | CLAUDE_CODE_SESSION_ID=test python3 /Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop_speak_last.py
# Expected: you hear "All tests pass. Done." Then clean up:
CLAUDE_CODE_SESSION_ID=test bash /Users/ashrocket/ashcode/squawk/claude-plugin/scripts/squawk-mode.sh off
```

- [ ] **Step 5 — End-to-end:** start a new Claude Code session, run `/squawk-mode`, ask for a small task. You should hear the final message spoken when Claude stops. Run `/squawk-off` to silence.

**UX:** `/squawk-mode` to arm (per session), work normally, hear completions; mid-work the model speaks milestones per the SKILL rules. `/squawk-say "..."` for a manual one-off (works regardless of mode).

**Optional (keep the model-summary style instead of last-message):** if you prefer the shipped "model writes a crisp summary" behavior, point the Step-2 hook at `stop-announce.sh` instead and apply the one-line fix in **Appendix B.5** (emit the resolved absolute path, not `${CLAUDE_PLUGIN_ROOT}`). Trade-off: nicer phrasing, but one extra model turn and model-dependent.

---

## Mode 2 — One-way inbound (you → Claude)

**You speak; Claude Code receives transcribed text as input. No TTS.**

**Architecture (recommended): use Claude Code's native voice input** — it is already enabled (`"voice": {"mode": "hold"}`). Hold the push-to-talk key, speak, Claude transcribes into the prompt of your **current** session. This is the only path that feeds the *current interactive* session; Squawk's `voice_chat.py` deliberately spawns a *separate* `claude -p --resume` headless session, so it cannot inject into the session you're typing in.

**What's already built**
- ✅ Native push-to-talk dictation in Claude Code (zero build). This satisfies Mode 2 for interactive use today.
- ✅ Squawk's STT internals (`whisper-cli` + energy-VAD capture) — but only inside the full chat loop.

**What's missing**
- ❌ No Squawk "transcribe-once → stdout" command (the reusable internals return audio samples, are tied to focus/mic-lock state, and feed `claude -p` directly).
- ❌ No bridge from Squawk STT into the *current* Claude Code session's input (interactive TUI doesn't accept piped stdin as prompts mid-session).

**Minimal wiring**

- [ ] **Step 1 — Confirm native voice** is what you want: in a Claude Code session, check the push-to-talk keybinding (Settings / `/help`), hold it, speak. If the keybinding is unclear, ask the user to confirm it — don't guess. *For interactive Mode 2, stop here; nothing to build.*

- [ ] **Step 2 (only for headless/scripted dictation) — Create** `‎/Users/ashrocket/ashcode/squawk/stt-once.py` (full content in **Appendix A.2**): captures one utterance via the same energy-VAD and prints the transcription. Use it to drive a one-shot headless run:
```bash
claude -p "$(/Users/ashrocket/ashcode/squawk/.venv/bin/python /Users/ashrocket/ashcode/squawk/stt-once.py)"
```
- [ ] **Step 3 — Verify** the one-shot transcriber:
```bash
/Users/ashrocket/ashcode/squawk/.venv/bin/python /Users/ashrocket/ashcode/squawk/stt-once.py
# Speak a sentence; expect the recognized text printed to stdout, exit 0.
# Silence/junk → no output, exit 1.
```

**UX:** Interactive → native hold-to-talk into your live prompt. Scripted → `stt-once.py` piped into `claude -p` for "speak a one-shot task." Decide which you actually want before building Step 2 — native voice likely covers the day-to-day case.

---

## Mode 3 — Two-way (full voice conversation)

**You speak, Claude speaks back.**

**Architecture:** **already exists** as `voice_chat.py` (wrapper `~/ashcode/squawk/voice`): `mic → energy-VAD → whisper-cli → claude -p --resume <session> → strip markdown → Kokoro/say → back to mic`. The Kokoro daemon stays resident between turns (idle-exit 600 s). Turn-taking is **VAD-only** — end of turn after 1.1 s of trailing silence; **no push-to-talk**, barge-in is experimental (no echo cancellation). Multi-tab safe via window-focus + a mic file-lock; relay inbox drained between turns; spoken exit phrases ("goodbye", "stop listening") end it.

**Latency (per turn):** ~1.1 s end-of-speech detection + `whisper-cli` on `base.en` (fast, but reloaded each utterance) + the `claude -p` round-trip (defaults to **`haiku`** for speed) + near-instant warm-Kokoro TTS. The resident daemon is what keeps TTS off the critical path; the per-utterance whisper reload is the main avoidable cost.

**What's already built**
- ✅ The whole loop, resident TTS daemon, VAD turn-taking, barge-in v1, exit phrases, pronunciation teaching, multi-agent speech lock.

**What's missing**
- ❌ **Talks to a *separate* headless `claude -p` session, not your current interactive Claude Code session** (explicit roadmap gap). You get a parallel voice agent with its own context, not voice over the session you're working in.
- ❌ No wake word; no push-to-talk option; barge-in lacks echo cancellation.
- ❌ STT model reloads per utterance (no resident whisper server).

**Minimal wiring**

- [ ] **Step 1 — Use the dedicated voice agent as-is:**
```bash
/Users/ashrocket/ashcode/squawk/voice --model haiku   # add --device "MacBook Pro Microphone" if needed
```
Speak; it answers aloud. Say "stop listening" to end. *This works today* for a standalone voice agent.

- [ ] **Step 2 — For "voice over my *current* session", compose Mode 1 + Mode 2 instead of `voice`:** enable Mode 1 (Stop-hook narration) **and** use native push-to-talk input (Mode 2 native). That gives spoken output + spoken input *against the live session* — the practical substitute for the unbuilt "voice_chat against current session." No new code; it's the combination of the two modes above.

- [ ] **Step 3 (optional latency win) — keep whisper warm:** the single biggest per-turn cost is the per-utterance `whisper-cli` cold start. If turns feel laggy, switch `voice_chat.py`'s `transcribe()` to a resident transcriber (e.g. `whisper-cli` server mode or `faster-whisper` held in memory). This is a real change to `voice_chat.py`, not just wiring — treat as a follow-up, not part of initial setup.

**UX decision to make first:** "dedicated voice agent" (`voice`, its own context) vs "voice over my current session" (Mode 1 + native Mode 2). They're different products — pick per use-case. The dedicated agent is best for hands-free side-tasks; the composition is best for narrating/answering the work you're already doing.

---

## Mode 4 — Other configurations

### 4a. Relay / queue mode (don't interrupt an active voice call)

**What's built:** `speak --relay` writes `inbox/{ns}-{agent}.json`; `voice_chat.py` drains the inbox **in timestamp order between turns** — so background agents that use `--relay` never talk over an active conversation, and the global `.speech.lock` prevents overlap.
**What's missing:** when **no** voice conversation is running, relayed messages pile up unspoken (nothing drains the inbox). And without relay-aware routing, the Stop-hook narrator speaks immediately, so a completion during a live call would contend on the lock instead of queueing politely.

**Minimal wiring — make the narrator relay-aware** (so it queues during a live `voice` call, speaks otherwise). Add this to `stop_speak_last.py` (variant noted in **Appendix A.1**), choosing the path by whether `voice_chat.py` is running:
```bash
# bash equivalent of the check the narrator performs:
if pgrep -f '[v]oice_chat.py' >/dev/null 2>&1; then
  printf '%s' "$TEXT" | bash .../squawk-speak.sh --relay --as "$AGENT"   # queue; voice loop will read it
else
  printf '%s' "$TEXT" | bash .../squawk-speak.sh --as "$AGENT"           # speak now
fi
```
- [ ] **Step 1 — Add the `pgrep` branch** to the narrator (Appendix A.1, `RELAY_AWARE=1`).
- [ ] **Step 2 (optional) — Idle drainer:** if you want relayed messages spoken even with no live conversation, add a small launchd agent that runs a drainer every ~10 s when `pgrep voice_chat.py` is empty. *Defer unless you actually send `--relay` outside conversations.*
- [ ] **Verify:** start `voice` in one terminal; in another run `printf 'queued hi' | bash .../squawk-speak.sh --relay --as scout`. Expect it spoken at the next turn boundary, not mid-utterance.

### 4b. Pidgin-as-fallback (Squawk unavailable → phone notification)

**What's built:** Pidgin `send`/`check` (exit-coded health); `squawk-speak.sh` exits 127 when no `speak` binary is found. **No combined fallback script exists.**
**What's missing:** a single notifier that speaks when you're at the Mac and pushes to your phone when Squawk can't help (repo absent, headless/SSH session, no audio).

**Minimal wiring**
- [ ] **Step 1 — Create** `‎/Users/ashrocket/ashcode/squawk/claude-plugin/scripts/notify.sh` (full content in **Appendix A.3**): tries Squawk if `[ -x .../speak ]` **and** not in an SSH session **and** `afplay` exists; otherwise gates on `pidgin.sh check` and sends a Pidgin status push. Optional `SQUAWK_ALSO_PIDGIN=1` for dual delivery.
- [ ] **Step 2 — Route the narrator through it:** have `stop_speak_last.py` call `notify.sh` instead of `speak` directly (Appendix A.1, `USE_NOTIFY=1`). Now Mode 1 automatically degrades to phone when you're away.
- [ ] **Verify both branches:**
```bash
SQUAWK_PROJECT=test bash .../notify.sh "local test"        # expect: spoken
SSH_CONNECTION="x" SQUAWK_PROJECT=test bash .../notify.sh "remote test"  # expect: Pidgin push to phone
```

### 4c. Watch / phone delivery of spoken output via Pidgin

**What's built:** Pidgin supports rich delivery — `--type status` for a glanceable push, `--markdown`/`--markdown-file` for a typeset **document** to phone/watch, `--html` for raw. (Matches the known behavior: full HTML docs go as `type document`.)
**What's missing:** nothing structural — it's a delivery choice layered on 4b's `notify.sh`.

**Minimal wiring**
- [ ] **Step 1 — Always-also-phone:** set `SQUAWK_ALSO_PIDGIN=1` in the narrator's environment (or hardcode in `notify.sh`) to speak *and* push every completion — so the watch buzzes with the same summary you hear.
- [ ] **Step 2 — Rich end-of-run reports:** for long results, call Pidgin's document path directly from the model (it already has the `pidgin` skill): `bash <pidgin>/scripts/pidgin.sh send --type document --markdown "<report>" --project "<proj>"`. Reserve voice for the one-line status; send the detail to the phone.

### 4d. Wake-word activation

**What's built:** nothing (explicit roadmap `[ ]`). Turn-taking is VAD + window-focus, not a wake word.
**What's missing:** a wake-word detector gating the listen loop. This is the **largest lift** of the four sub-configs — a real feature, not wiring.

**Minimal path (lightest, fully local):** add **openWakeWord** (ONNX, no API key, ships ready-made models like `hey_jarvis`/`alexa`; a custom "hey squawk" needs training).
- [ ] **Step 1 —** `‎/Users/ashrocket/ashcode/squawk/.venv/bin/pip install openwakeword`
- [ ] **Step 2 — Create** `‎/Users/ashrocket/ashcode/squawk/wake.py` (skeleton in **Appendix A.4**): runs the detector on the 16 kHz mic frames and returns when the wake score crosses threshold.
- [ ] **Step 3 — Gate the loop:** in `voice_chat.py`, call `wait_for_wake()` before `listen_for_utterance()` so the mic only "opens" after the wake word. *Alternative with zero build:* Claude Code's native push-to-talk (`mode: hold`) is a hardware wake-substitute — press a key instead of speaking a word. Prefer that unless you specifically need hands-free activation.

---

## Cross-cutting: avoid double notifications

Both the Pidgin plugin **and** the new Squawk Stop hook fire on `Stop` with `matcher: ""`. If both stay active you'll get a phone push *and* speech every turn. Pick one source of truth:

- [ ] **Recommended:** make Squawk's narrator the single notifier (it speaks when present, pushes via Pidgin when away — 4b), and **silence Pidgin's own Stop hook** by creating `‎/Users/ashrocket/.claude/plugins/cache/pidgin/pidgin/1.0.0/.local.md` with `stop_notify: false` (template: `.local.md.example`). Then Mode 1 + 4b own all completion notifications.
- *Or* keep both intentionally (always speak locally *and* always push) — simpler, noisier.

---

## Recommended build order

1. **Mode 1** (Steps 1–5) — highest value, ~20 min. Makes outbound narration actually fire.
2. **Mode 4b** (`notify.sh`) + route the narrator through it, then **Cross-cutting** (silence Pidgin's hook). Now you're covered whether present or away.
3. **Mode 2** — confirm native voice (no build); add `stt-once.py` only if you want scripted dictation.
4. **Mode 3** — use `voice` as-is; rely on Mode 1 + native Mode 2 for "current-session" voice.
5. **Mode 4a** (relay-aware narrator), **4c** (dual delivery toggle) — small polish.
6. **Mode 4d** (wake word) — only if hands-free activation is a real requirement; otherwise native push-to-talk suffices.

---

## Appendix A — complete new files

### A.1 `‎/Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop_speak_last.py`

> Deterministic Stop-hook narrator. Set the three flags at the top to opt into relay-awareness (4a), the unified notifier (4b), or dual phone delivery (4c).

```python
#!/usr/bin/env python3
"""Squawk Stop hook: speak Claude's actual last message when Squawk Mode is on.

Reads the Stop-hook JSON on stdin: {transcript_path, session_id, stop_hook_active,...}.
Gated on the same per-session state file /squawk-mode writes. Fire-and-forget:
spawns the speaker detached so the hook returns instantly (no 8s-timeout pressure).
"""
import json, os, re, subprocess, sys

SQUAWK_ROOT = os.environ.get("SQUAWK_ROOT", "/Users/ashrocket/ashcode/squawk")
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
```

### A.2 `‎/Users/ashrocket/ashcode/squawk/stt-once.py`

> Standalone "capture one utterance → print transcription." Self-contained energy-VAD (mirrors `voice_chat.py` constants) + `whisper-cli`. Placed at repo root so the default model path resolves.

```python
#!/usr/bin/env python3
"""Capture ONE spoken utterance and print its transcription to stdout (exit 0).
Silence/junk -> no output, exit 1.  Run with the squawk venv python.
"""
import argparse, os, re, subprocess, sys, tempfile, wave
import numpy as np
import sounddevice as sd

SAMPLE_RATE, FRAME = 16000, 480                  # 30 ms mono int16 frames
SPEECH_START_FRAMES, TRAILING_SILENCE_S, MAX_UTTERANCE_S = 5, 1.1, 45
PRE_ROLL_FRAMES = 16
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "models", "ggml-base.en.bin")
JUNK = re.compile(r"^\s*(\[blank_audio\]|\(.*\))?\s*$", re.I)

def capture(device):
    voiced, pre_roll, floor = [], [], []
    in_speech, speech_frames, silent_run = False, 0, 0
    silence_needed = int(TRAILING_SILENCE_S * SAMPLE_RATE / FRAME)
    max_frames = int(MAX_UTTERANCE_S * SAMPLE_RATE / FRAME)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=FRAME, device=device) as stream:
        for _ in range(20):                       # ~0.6 s noise-floor calibration
            blk, _ = stream.read(FRAME)
            floor.append(np.sqrt(np.mean(blk.astype(np.float32) ** 2)))
        threshold = max(180.0, float(np.median(floor)) * 3.5)
        while True:
            blk, _ = stream.read(FRAME)
            frame = blk[:, 0].copy()
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            if not in_speech:
                pre_roll.append(frame)
                if len(pre_roll) > PRE_ROLL_FRAMES:
                    pre_roll.pop(0)
                speech_frames = speech_frames + 1 if rms > threshold else 0
                if speech_frames >= SPEECH_START_FRAMES:
                    in_speech, voiced, silent_run = True, list(pre_roll), 0
            else:
                voiced.append(frame)
                silent_run = silent_run + 1 if rms <= threshold else 0
                if silent_run >= silence_needed or len(voiced) >= max_frames:
                    return np.concatenate(voiced)

def transcribe(samples, model):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        path = tf.name
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
            w.writeframes(samples.tobytes())
        out = subprocess.run(["whisper-cli", "-m", model, "-f", path,
                              "--no-prints", "--no-timestamps"],
                             capture_output=True, text=True, timeout=60)
        return out.stdout.strip()
    finally:
        os.unlink(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    dev = int(a.device) if (a.device and a.device.isdigit()) else a.device
    text = transcribe(capture(dev), a.model)
    if not text or JUNK.match(text):
        return 1
    print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### A.3 `‎/Users/ashrocket/ashcode/squawk/claude-plugin/scripts/notify.sh`

```bash
#!/bin/bash
# Unified Claude-Code notifier: speak via Squawk when you're at the Mac,
# otherwise push to phone/watch via Pidgin. Message from $1 or stdin.
set -euo pipefail

AGENT="${SQUAWK_AGENT:-claude}"
PROJECT="${SQUAWK_PROJECT:-$(basename "$(pwd)")}"
MSG="${1:-$(cat)}"
[[ -n "${MSG//[[:space:]]/}" ]] || exit 0

SQUAWK_ROOT="${SQUAWK_ROOT:-/Users/ashrocket/ashcode/squawk}"
SQUAWK_SPEAK="$SQUAWK_ROOT/claude-plugin/scripts/squawk-speak.sh"
PIDGIN_CLI="${PIDGIN_CLI:-/Users/ashrocket/ashcode/pidgin/scripts/pidgin.sh}"

squawk_available() {
  [[ -x "$SQUAWK_ROOT/speak" ]]      || return 1   # repo present on this machine
  [[ -z "${SSH_CONNECTION:-}" ]]     || return 1   # only useful at the physical Mac
  command -v afplay >/dev/null 2>&1                 # macOS audio present
}

pidgin_send() {
  [[ -n "${PIDGIN_URL:-}" && -n "${PIDGIN_API_KEY:-}" ]] || return 1
  bash "$PIDGIN_CLI" check >/dev/null 2>&1 || return 1
  bash "$PIDGIN_CLI" send --type status --title "$PROJECT" \
       --body "$MSG" --project "$PROJECT" >/dev/null 2>&1
}

if squawk_available; then
  printf '%s' "$MSG" | bash "$SQUAWK_SPEAK" --as "$AGENT"
  [[ "${SQUAWK_ALSO_PIDGIN:-0}" == "1" ]] && pidgin_send || true   # 4c dual delivery
else
  pidgin_send || true
fi
```

### A.4 `‎/Users/ashrocket/ashcode/squawk/wake.py` (skeleton — Mode 4d)

```python
#!/usr/bin/env python3
"""Wake-word gate for the voice loop (openWakeWord, fully local, no API key).
Call wait_for_wake() before listen_for_utterance() in voice_chat.py.
Install: ~/ashcode/squawk/.venv/bin/pip install openwakeword
Custom 'hey squawk' needs a trained model; built-ins (hey_jarvis, alexa) ship ready.
"""
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE, BLOCK = 16000, 1280                 # 80 ms @ 16 kHz
_model = Model(wakeword_models=["hey_jarvis"])   # swap for a custom model path

def wait_for_wake(device=None, threshold=0.5):
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=BLOCK, device=device) as stream:
        while True:
            blk, _ = stream.read(BLOCK)
            scores = _model.predict(blk[:, 0].astype(np.int16))
            if scores and max(scores.values()) >= threshold:
                return                            # wake detected -> start STT
```

---

## Appendix B — exact config edits

### B.1 Add the Stop hook (top level of `~/.claude/settings.json`)
Insert a `"hooks"` key (none exists today) as a sibling of `"env"`/`"permissions"`:
```json
"hooks": {
  "Stop": [
    { "matcher": "", "hooks": [
      { "type": "command",
        "command": "python3 /Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop_speak_last.py",
        "timeout": 5 }
    ]}
  ]
}
```

### B.2 Permission allow (smooths model-driven narration)
Append to `permissions.allow` in `~/.claude/settings.json`:
```json
"Bash(bash /Users/ashrocket/ashcode/squawk/claude-plugin/scripts/squawk-speak.sh *)"
```

### B.3 (Optional) Pin `SQUAWK_ROOT` for hooks
Not required (scripts self-resolve), but explicit is safer. Add to the `env` block:
```json
"SQUAWK_ROOT": "/Users/ashrocket/ashcode/squawk"
```

### B.4 Silence Pidgin's own Stop hook (avoid double-notify — Cross-cutting)
Create `/Users/ashrocket/.claude/plugins/cache/pidgin/pidgin/1.0.0/.local.md`:
```markdown
stop_notify: false
```

### B.5 (Only if using the shipped model-summary hook instead of A.1)
In `‎/Users/ashrocket/ashcode/squawk/claude-plugin/hooks/scripts/stop-announce.sh`, the emitted prompt hardcodes `${CLAUDE_PLUGIN_ROOT}`, which is **unset** outside plugin context. Change the heredoc's command line to the resolved absolute path:
```bash
# was:  bash "${CLAUDE_PLUGIN_ROOT}/scripts/squawk-speak.sh" --as "$AGENT" "<SUMMARY>"
# use:  bash "$PLUGIN_ROOT/scripts/squawk-speak.sh" --as "$AGENT" "<SUMMARY>"
```
(`$PLUGIN_ROOT` is already resolved at the top of that script.)

### B.6 Alternative to B.1 — install Squawk as a real plugin
If you'd rather have `hooks/hooks.json` auto-load and `CLAUDE_PLUGIN_ROOT` injected (no settings.json hook, no B.5 edit), add a marketplace entry. The plugin lives in the `claude-plugin/` subdir, so the repo needs a root `.claude-plugin/marketplace.json` listing it; then `enabledPlugins` gets `squawk@…: true`. More moving parts than B.1 — only worth it if you want the plugin's own hook lifecycle. **B.1 is the faster, more controllable path** and is assumed by this plan.

---

## Appendix C — file / path reference

| Purpose | Path |
|---|---|
| Squawk repo root | `/Users/ashrocket/ashcode/squawk` |
| TTS CLI / engine | `…/speak`, `…/speak.py`, `…/kokoro_daemon.py` |
| Two-way loop | `…/voice`, `…/voice_chat.py` |
| Whisper model | `…/models/ggml-base.en.bin`; binary `/opt/homebrew/bin/whisper-cli` |
| Plugin root | `…/squawk/claude-plugin` |
| Speak wrapper / common / mode | `…/claude-plugin/scripts/{squawk-speak,squawk-common,squawk-mode}.sh` |
| Shipped Stop hook | `…/claude-plugin/hooks/{hooks.json,scripts/stop-announce.sh}` |
| Per-session state | `${XDG_STATE_HOME:-~/.local/state}/squawk/claude-mode/<CLAUDE_CODE_SESSION_ID>.env` |
| Locks / socket | `…/squawk/.speech.lock`, `.kokoro.sock`, `.voice_chat.lock` |
| **New** narrator (A.1) | `…/claude-plugin/hooks/scripts/stop_speak_last.py` |
| **New** one-shot STT (A.2) | `…/squawk/stt-once.py` |
| **New** unified notifier (A.3) | `…/claude-plugin/scripts/notify.sh` |
| **New** wake gate (A.4) | `…/squawk/wake.py` |
| Claude settings | `/Users/ashrocket/.claude/settings.json`, `settings.local.json` |
| Pidgin CLI | `/Users/ashrocket/ashcode/pidgin/scripts/pidgin.sh` (`send`/`ask`/`check`/`health`) |
| Pidgin env | `PIDGIN_URL` (settings `env`); `PIDGIN_API_KEY` (`~/.zshrc:58`) |

---

## Self-review notes
- **Mode 1** depends on B.1 (hook) + A.1 (script); B.2 only affects model-driven narration, not the hook. The hook is gated by the state file `/squawk-mode` writes, so it's silent until armed. ✓
- **Mode 2** interactive needs *no build* (native voice already enabled); A.2 is strictly for headless/scripted dictation — flagged as optional. ✓
- **Mode 3** "current session" is explicitly the unbuilt case; the plan substitutes Mode 1 + native Mode 2 rather than pretending `voice_chat.py` can target the live TUI. ✓
- **Mode 4** uses only verified surfaces: `--relay`/inbox (4a), `pidgin.sh check`/`send` (4b/4c), `pgrep` (macOS-safe, avoids the missing `flock` CLI), openWakeWord (4d). Wake word is honestly marked the biggest lift. ✓
- **Double-notify** (both Stop hooks) is addressed in Cross-cutting + B.4. ✓
```
