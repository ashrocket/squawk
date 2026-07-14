#!/usr/bin/env python3
"""Bridge to the cmux terminal multiplexer.

cmux owns the PTY of every pane, so we can type a transcribed utterance straight
into a *live* interactive agent session: ``cmux send`` writes the text and
``cmux send-key enter`` submits it. No new headless ``claude -p`` or ``codex`` -
the words land in the session you are already working in.

Targeting: the focused surface (``cmux rpc surface.current``). A surface is a
real coding agent when its ``resume_binding.kind`` is a known agent kind; we
refuse to inject into anything else unless explicitly allowed, so voice never
lands in a plain shell by accident.
"""
import json
import os
import shutil
import subprocess

DEFAULT_CMUX = "/Applications/cmux.app/Contents/Resources/bin/cmux"
DEFAULT_AGENT_KINDS = ("claude", "codex")


class CmuxError(RuntimeError):
    """cmux is unavailable, or a cmux command failed."""


def cmux_bin():
    """Path to the cmux CLI: $CMUX_BIN, then $PATH, then the app bundle default."""
    return os.environ.get("CMUX_BIN") or shutil.which("cmux") or DEFAULT_CMUX


def _run(args, timeout=10):
    try:
        return subprocess.run([cmux_bin(), *args], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CmuxError(f"could not run cmux: {exc}") from exc


def _rpc(method, params=None):
    args = ["rpc", method]
    if params is not None:
        args.append(json.dumps(params))
    out = _run(args)
    if out.returncode != 0:
        raise CmuxError(out.stderr.strip() or f"cmux rpc {method} failed")
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise CmuxError(f"cmux rpc {method} returned non-JSON: "
                        f"{out.stdout[:160]!r}") from exc


def ping():
    """Raise CmuxError unless the cmux socket is reachable."""
    out = _run(["ping"])
    if out.returncode != 0:
        raise CmuxError(out.stderr.strip() or "cmux ping failed")
    return True


def available():
    """True when a cmux socket is reachable."""
    try:
        return ping()
    except CmuxError:
        return False


def availability_error():
    """Return the cmux ping error string, or None when cmux is reachable."""
    try:
        ping()
    except CmuxError as exc:
        return str(exc)
    return None


def focused():
    """The focused surface: dict with surface_id, surface_ref, workspace_id, ..."""
    return _rpc("surface.current")


def _matches_surface(surface, target):
    return target in (surface.get("id"), surface.get("ref"))


def _kind_of(surface_ref, workspace_id=None):
    """resume_binding.kind for a surface ('claude', 'codex', ...) or None.

    ``surface.list`` with no argument returns the focused workspace's surfaces,
    which is where the focused target lives; we also try an explicit workspace
    scope in case a cmux build needs it.
    """
    for params in ({"workspace": workspace_id} if workspace_id else None, None):
        try:
            data = _rpc("surface.list", params)
        except CmuxError:
            continue
        for surface in data.get("surfaces", []):
            if _matches_surface(surface, surface_ref):
                return (surface.get("resume_binding") or {}).get("kind")
    return None


def _format_allowed(allowed_kinds):
    return ", ".join(sorted(allowed_kinds))


def _validate_kind(surface_ref, kind, allowed_kinds):
    if kind in allowed_kinds:
        return
    if kind is None:
        raise CmuxError(f"could not verify cmux surface {surface_ref!r}; "
                        "use --any-pane to override")
    raise CmuxError(f"target pane is not an allowed agent "
                    f"(kind={kind!r}; allowed={_format_allowed(allowed_kinds)}); "
                    "use --any-pane to override")


def resolve_target(surface_ref=None, allowed_kinds=DEFAULT_AGENT_KINDS, allow_any=False):
    """Return (surface_ref, kind) for the target pane.

    Raises CmuxError if cmux has no target surface, or if the target is not a
    known agent pane and ``allow_any`` is false.
    """
    workspace_id = None
    if surface_ref is None:
        cur = focused()
        surface_ref = cur.get("surface_id")
        workspace_id = cur.get("workspace_id")
        if not surface_ref:
            raise CmuxError("no focused cmux surface")
    kind = _kind_of(surface_ref, workspace_id)
    if not allow_any:
        _validate_kind(surface_ref, kind, set(allowed_kinds))
    return surface_ref, kind


def inject(surface_id, text, submit=True, method="enter"):
    """Type ``text`` into a surface and optionally submit it.

    method:
      enter         - send the text, then a discrete ``enter`` key (best for TUIs)
      newline       - one send with a trailing newline
      prompt_submit - cmux's workspace.prompt_submit RPC
    """
    text = text.strip()
    if not text:
        return
    if method == "prompt_submit":
        _rpc("workspace.prompt_submit", {"surface": surface_id, "text": text})
        return
    if method == "newline":
        out = _run(["send", "--surface", surface_id, "--", text + "\n"])
        if out.returncode != 0:
            raise CmuxError(out.stderr.strip() or "cmux send failed")
        return
    out = _run(["send", "--surface", surface_id, "--", text])
    if out.returncode != 0:
        raise CmuxError(out.stderr.strip() or "cmux send failed")
    if submit:
        out = _run(["send-key", "--surface", surface_id, "enter"])
        if out.returncode != 0:
            raise CmuxError(out.stderr.strip() or "cmux send-key failed")
