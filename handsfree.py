#!/usr/bin/env python3
"""Hands-free voice INTO your live agent session (via cmux).

The whole feature is one core pipeline with different ways to trigger it:

    capture one utterance -> whisper -> focused cmux agent pane -> cmux send + submit

Modes layer activation on that shared core:
    once     one utterance (or --text), inject once, exit       [core; no wake word]
    wake     say the wake word, capture one utterance, inject; repeat
    convo    wake once, then stay open for back-and-forth until silence / "that's all"
    listen   no wake word; capture continuously while an agent pane is focused

You HEAR replies through the Stop-hook narrator: turn on /squawk-mode in the
target pane. This module only handles the inbound (you -> agent) direction.

Run with the squawk venv:  ./handsfree [mode] [options]
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cmux_bridge as cx
from voice_chat import listen_for_utterance, transcribe

WHISPER_MODEL = HERE / "models" / "ggml-base.en.bin"
CONVO_IDLE_TIMEOUT_S = 75            # convo mode closes after this much silence
END_PHRASES = ("that's all", "thats all", "stop listening", "never mind",
               "nevermind", "we're done", "were done", "that is all", "over and out")


class _AlwaysFocused:
    """Focus stub: handsfree targets via cmux, not its own pane's focus state."""
    focused = True


def _eprint(*parts):
    print(*parts, file=sys.stderr, flush=True)


def parse_agent_kinds(value):
    """Parse a comma-separated cmux resume_binding.kind allowlist."""
    kinds = tuple(kind.strip() for kind in value.split(",") if kind.strip())
    if not kinds:
        raise argparse.ArgumentTypeError("expected at least one agent kind")
    return kinds


def capture_text(device):
    """Block until one utterance is spoken; return transcribed text or None."""
    samples = listen_for_utterance(device, _AlwaysFocused(), lambda: True)
    if samples is None:
        return None
    return transcribe(samples, str(WHISPER_MODEL))


def get_text(args):
    """The literal --text (for testing), or one captured spoken utterance."""
    if args.text is not None:
        return args.text
    if not args.quiet:
        _eprint("● listening… (speak, then pause)")
    return capture_text(args.device)


def _target_for(args):
    """Resolve where to inject: explicit --surface, else the focused cmux pane."""
    return cx.resolve_target(surface_ref=args.surface,
                             allowed_kinds=args.agent_kinds,
                             allow_any=args.any_pane)


def inject_text(args, text, target=None):
    """Send ``text`` to the target agent pane (resolving the focused one if needed)."""
    if not text:
        return None
    if target is None:
        target = _target_for(args)
    surface_id, kind = target
    label = f"{kind or 'pane'} {surface_id[:8]}"
    if args.dry_run:
        _eprint(f"  [dry-run] → {label}: {text!r}  "
                f"(method={args.submit_method}, {'no-submit' if args.no_submit else 'submit'})")
        return text
    cx.inject(surface_id, text, submit=not args.no_submit, method=args.submit_method)
    _eprint(f"  → {label}: {text!r}")
    return text


def mode_once(args):
    text = get_text(args)
    if not text:
        _eprint("  (nothing recognized)")
        return 1
    inject_text(args, text)
    return 0


def mode_wake(args):
    import wake                                   # lazy: needs openwakeword
    model = wake.load_model()
    _eprint(f"wake mode — say “{args.wake_word}”. Ctrl-C to stop.")
    while True:
        wake.wait_for_wake(device=args.device, threshold=args.threshold, model=model)
        _eprint("✔ wake")
        text = get_text(args)
        if not text:
            continue
        try:
            inject_text(args, text)
        except cx.CmuxError as exc:
            _eprint(f"  skipped: {exc}")


def mode_convo(args):
    import wake                                   # lazy: needs openwakeword
    model = wake.load_model()
    _eprint(f"convo mode — say “{args.wake_word}” to start. Ctrl-C to stop.")
    while True:
        wake.wait_for_wake(device=args.device, threshold=args.threshold, model=model)
        try:
            target = _target_for(args)
        except cx.CmuxError as exc:
            _eprint(f"  no target: {exc}")
            continue
        _eprint(f"✔ conversation open with {target[1] or 'pane'} {target[0][:8]} "
                f"(say “that's all” to close)")
        last = time.monotonic()
        while time.monotonic() - last < CONVO_IDLE_TIMEOUT_S:
            text = get_text(args)
            if not text:
                continue
            if any(p in text.lower() for p in END_PHRASES):
                _eprint("  conversation closed.")
                break
            inject_text(args, text, target=target)
            last = time.monotonic()
        else:
            _eprint("  conversation idle-closed.")


def mode_listen(args):
    _eprint("listen mode — speaking into whatever agent pane is focused. Ctrl-C to stop.")
    while True:
        text = get_text(args)
        if not text:
            continue
        try:
            inject_text(args, text)
        except cx.CmuxError as exc:
            _eprint(f"  skipped: {exc}")


MODES = {"once": mode_once, "wake": mode_wake, "convo": mode_convo, "listen": mode_listen}


def main():
    ap = argparse.ArgumentParser(
        description="Hands-free voice into your live agent session (via cmux).")
    ap.add_argument("mode", nargs="?", default="once", choices=list(MODES),
                    help="activation mode (default: once)")
    ap.add_argument("--text", default=None,
                    help="inject this literal text instead of listening (for testing)")
    ap.add_argument("--device", default=None, help="mic device name or index")
    ap.add_argument("--surface", default=None,
                    help="target a specific cmux surface id/ref instead of the focused pane")
    ap.add_argument("--agent-kinds", default=cx.DEFAULT_AGENT_KINDS,
                    type=parse_agent_kinds,
                    help="comma-separated cmux resume_binding kinds allowed by default "
                         "(default: claude,codex)")
    ap.add_argument("--wake-word", default="hey jarvis",
                    help="wake phrase label shown in prompts (wake/convo modes)")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="wake-word sensitivity 0-1 (wake/convo modes)")
    ap.add_argument("--submit-method", default="enter",
                    choices=["enter", "newline", "prompt_submit"],
                    help="how to submit the typed text (default: enter)")
    ap.add_argument("--no-submit", action="store_true",
                    help="type the text but do not press enter")
    ap.add_argument("--any-pane", action="store_true",
                    help="allow injecting into a non-agent or unverified pane")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the target and text without injecting")
    ap.add_argument("--quiet", action="store_true", help="less chatter on stderr")
    args = ap.parse_args()

    cmux_error = cx.availability_error()
    if cmux_error:
        _eprint("handsfree: no cmux socket reachable.\n"
                f"cmux said: {cmux_error}\n"
                "This feature injects into the live session via cmux. If this is "
                "running from a sandboxed agent, approve an unsandboxed run or start "
                "handsfree from a normal terminal.")
        return 2
    try:
        return MODES[args.mode](args)
    except KeyboardInterrupt:
        _eprint("\nstopped.")
        return 0
    except cx.CmuxError as exc:
        _eprint(f"handsfree: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
