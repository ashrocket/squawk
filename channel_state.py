#!/usr/bin/env python3
"""Shared Squawk channel state.

The speech lock is the physical audio mutex. This module adds the inspectable
radio layer around it: who has the floor, who is transmitting, which agents have
voices, and which agents are waiting to speak.
"""
import fcntl
import json
import os
import shlex
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANNEL_STATE = HERE / "channel.json"
CHANNEL_LOCK = HERE / ".channel.lock"
SPEECH_LOCK = HERE / ".speech.lock"
INBOX = HERE / "inbox"
REGISTRY = HERE / "voices.json"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(value):
    cleaned = "".join(c if c.isalnum() or c in "._-" else "-" for c in value)
    return cleaned.strip("-") or "agent"


def _preview(text, limit=160):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, data):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _empty_state():
    return {
        "version": 1,
        "updated_at": now_iso(),
        "floor": None,
        "transmission": None,
    }


def _normalized_state():
    state = _read_json(CHANNEL_STATE, _empty_state())
    base = _empty_state()
    if isinstance(state, dict):
        for key in base:
            if key in state:
                base[key] = state[key]
    return base


def _locked_update(mutator):
    with open(CHANNEL_LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        state = _normalized_state()
        result = mutator(state)
        state["updated_at"] = now_iso()
        _write_json(CHANNEL_STATE, state)
        return result if result is not None else state


def set_floor(agent, voice=None, project=None, mode="conversation", detail=None):
    """Declare the current floor holder.

    "Floor" is the push-to-talk group-call term for the right to use the shared
    channel. A voice conversation holds the floor between individual utterances.
    """
    entry = {
        "agent": agent,
        "voice": voice,
        "project": project,
        "mode": mode,
        "detail": detail,
        "pid": os.getpid(),
        "since": now_iso(),
    }

    def mutate(state):
        state["floor"] = entry
        return entry

    return _locked_update(mutate)


def clear_floor(agent=None, pid=None):
    pid = os.getpid() if pid is None else pid

    def mutate(state):
        floor = state.get("floor")
        if not floor:
            return False
        if agent is not None and floor.get("agent") != agent:
            return False
        if pid is not None and floor.get("pid") != pid:
            return False
        state["floor"] = None
        return True

    return _locked_update(mutate)


def set_transmission(agent, voice=None, text=None, kind="speech"):
    entry = {
        "agent": agent,
        "voice": voice,
        "kind": kind,
        "text_preview": _preview(text),
        "pid": os.getpid(),
        "started_at": now_iso(),
    }

    def mutate(state):
        state["transmission"] = entry
        return entry

    return _locked_update(mutate)


def clear_transmission(agent=None, pid=None):
    pid = os.getpid() if pid is None else pid

    def mutate(state):
        tx = state.get("transmission")
        if not tx:
            return False
        if agent is not None and tx.get("agent") != agent:
            return False
        if pid is not None and tx.get("pid") != pid:
            return False
        state["transmission"] = None
        return True

    return _locked_update(mutate)


def speech_busy():
    try:
        with open(SPEECH_LOCK, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lk, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def request_airtime(text, agent="agent", voice=None, project=None, kind="relay"):
    """Queue a request for the current floor holder to read between turns."""
    INBOX.mkdir(exist_ok=True)
    request_id = f"{time.time_ns()}-{_safe(agent)}"
    payload = {
        "id": request_id,
        "kind": kind,
        "agent": agent,
        "from": agent.replace("-", " "),
        "voice": voice,
        "project": project,
        "text": text,
        "requested_at": now_iso(),
        "pid": os.getpid(),
    }
    _write_json(INBOX / f"{request_id}.json", payload)
    return payload


def pending_requests():
    if not INBOX.exists():
        return []
    requests = []
    for path in sorted(INBOX.glob("*.json")):
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            continue
        payload = dict(payload)
        payload.setdefault("id", path.stem)
        payload["queue_file"] = path.name
        requests.append(payload)
    return requests


def voice_assignments():
    data = _read_json(REGISTRY, {})
    return data if isinstance(data, dict) else {}


def _state_base_dir():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def _parse_env_value(raw):
    try:
        parsed = shlex.split(raw, posix=True)
        if parsed:
            return parsed[0]
    except ValueError:
        pass
    return raw.strip().strip("'\"")


def _read_mode_file(path):
    values = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _parse_env_value(value)
    return values


def squawk_modes():
    state_dir = _state_base_dir() / "squawk" / "claude-mode"
    if not state_dir.exists():
        return []
    modes = []
    for path in sorted(state_dir.glob("*.env")):
        values = _read_mode_file(path)
        if not values:
            continue
        modes.append({
            "session": path.stem,
            "agent": values.get("agent", "claude"),
            "project": values.get("project"),
            "started_at": values.get("started_at"),
            "state_file": str(path),
        })
    return modes


def snapshot(available_voices=None):
    state = _normalized_state()
    assignments = voice_assignments()
    requests = pending_requests()
    modes = squawk_modes()
    names = set(assignments)
    for item in (state.get("floor"), state.get("transmission")):
        if item and item.get("agent"):
            names.add(item["agent"])
    for req in requests:
        if req.get("agent"):
            names.add(req["agent"])
    for mode in modes:
        if mode.get("agent"):
            names.add(mode["agent"])

    agents = []
    for agent in sorted(names):
        agents.append({
            "agent": agent,
            "voice": assignments.get(agent),
            "has_floor": bool(state.get("floor") and state["floor"].get("agent") == agent),
            "transmitting": bool(state.get("transmission") and state["transmission"].get("agent") == agent),
            "queued": sum(1 for req in requests if req.get("agent") == agent),
        })

    return {
        "version": 1,
        "updated_at": now_iso(),
        "speech_busy": speech_busy(),
        "floor": state.get("floor"),
        "transmission": state.get("transmission"),
        "agents": agents,
        "voice_assignments": assignments,
        "available_voices": available_voices,
        "requests": requests,
        "squawk_modes": modes,
    }


def format_snapshot(data):
    lines = []
    channel_busy = data.get("speech_busy") or data.get("floor") or data.get("transmission")
    lines.append(f"Channel: {'busy' if channel_busy else 'idle'}")

    floor = data.get("floor")
    if floor:
        lines.append(
            f"Floor: {floor.get('agent')} ({floor.get('voice') or 'unassigned'})"
            f" mode={floor.get('mode')} since={floor.get('since')}"
        )
    else:
        lines.append("Floor: none")

    tx = data.get("transmission")
    if tx:
        lines.append(
            f"Transmitting: {tx.get('agent')} ({tx.get('voice') or 'unassigned'})"
            f" since={tx.get('started_at')}"
        )
        if tx.get("text_preview"):
            lines.append(f"  {tx['text_preview']}")
    else:
        lines.append("Transmitting: none")

    agents = data.get("agents") or []
    lines.append(f"Agents: {len(agents)}")
    for item in agents:
        markers = []
        if item.get("has_floor"):
            markers.append("floor")
        if item.get("transmitting"):
            markers.append("talking")
        if item.get("queued"):
            markers.append(f"queued={item['queued']}")
        suffix = f" [{' '.join(markers)}]" if markers else ""
        lines.append(f"  {item.get('agent')} -> {item.get('voice') or 'unassigned'}{suffix}")

    requests = data.get("requests") or []
    lines.append(f"Requests: {len(requests)}")
    for req in requests:
        lines.append(
            f"  {req.get('agent') or req.get('from')}: "
            f"{_preview(req.get('text', ''), 90)}"
        )

    modes = data.get("squawk_modes") or []
    lines.append(f"Squawk modes: {len(modes)}")
    for mode in modes:
        project = f" project={mode.get('project')}" if mode.get("project") else ""
        lines.append(f"  {mode.get('agent')} session={mode.get('session')}{project}")

    if "multiplexer" in data:
        mux = data.get("multiplexer")
        if not mux:
            lines.append("Multiplexer: not running")
        else:
            lines.append(f"Multiplexer: pid={mux.get('pid')} "
                         f"queue={len(mux.get('queue') or [])} "
                         f"questions={len(mux.get('questions') or [])}")
            def origin(item):
                tags = [t for t in (item.get("project"), item.get("source"),
                                    item.get("session")) if t]
                return f" [{' '.join(tags)}]" if tags else ""
            playing = mux.get("now_playing")
            if playing:
                lines.append(f"  playing: {playing.get('agent')} "
                             f"({playing.get('voice')}){origin(playing)} "
                             f"{playing.get('text_preview', '')}")
            for item in mux.get("queue") or []:
                lines.append(f"  queued p{item.get('priority', 0)}: {item.get('agent')}"
                             f"{origin(item)} {item.get('text_preview', '')}")
            for item in mux.get("questions") or []:
                lines.append(f"  question {item.get('id')} from {item.get('agent')}"
                             f"{origin(item)}: {item.get('text', '')}")

    return "\n".join(lines)
