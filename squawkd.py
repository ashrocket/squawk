#!/usr/bin/env python3
"""Squawk multiplexer daemon — the traffic cop for the shared audio channel.

Instead of every process grabbing the speakers behind a file lock, clients send
their messages here. Each arrives tagged with its origin — Claude session id,
terminal source, project — and the voice it should use. The daemon plays them
one at a time from a priority queue (urgent jumps the line but never talks over
the current utterance), keeps an inspectable view of playing/queued/pending,
and routes answers typed in Squawk.app back to the exact client that asked.

Protocol: one JSON request line per connection on a unix socket, one JSON
reply line back. Blocking ops hold the connection open until done:

    {"op": "speak", "text": ..., "agent": ..., "wait": true, ...}
    {"op": "ask", "text": ..., "agent": ..., "timeout": 600, ...}
    {"op": "answer", "id": "<question id>|latest", "text": "..."}
    {"op": "status"} | {"op": "ping"} | {"op": "shutdown"}

Spawned on demand by speak.py (like kokoro_daemon); exits after an idle period.
Playback goes through speak.speak(), so the legacy speech lock still applies —
direct speakers and voice conversations can't collide with the multiplexer.
"""
import collections
import fcntl
import itertools
import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import speak as speech

HERE = Path(__file__).resolve().parent
SOCKET_PATH = HERE / ".squawkd.sock"
DAEMON_LOCK = HERE / ".squawkd.lock"
HISTORY_LOG = HERE / "logs" / "squawkd-history.jsonl"
IDLE_TIMEOUT_S = float(os.environ.get("SQUAWKD_IDLE_S", "900"))
ASK_TIMEOUT_S = 600.0
PLAYBACK_WAIT_S = 1800.0

PRIORITY_NORMAL = 0
PRIORITY_URGENT = 10


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _preview(text, limit=160):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


class Daemon:
    def __init__(self, socket_path=SOCKET_PATH, history_path=HISTORY_LOG,
                 play=None, voice_for=None, idle_timeout=IDLE_TIMEOUT_S,
                 spawn_bridge=True):
        self.socket_path = Path(socket_path)
        self.history_path = Path(history_path)
        self.play = play or self._play_default
        self.voice_for = voice_for or speech.voice_for
        self.idle_timeout = idle_timeout
        self.stop = threading.Event()
        self.state = threading.Lock()
        self.queue = queue.PriorityQueue()
        self.seq = itertools.count()
        self.items = {}  # id -> live item: queued, playing, or awaiting an answer
        self.history = collections.deque(maxlen=50)
        self.now_playing = None
        self.connections = 0
        self.started_at = _now()
        self.last_activity = time.time()
        self.spawn_bridge = spawn_bridge
        self._bridge_spawned_at = 0.0

    # ---- playback ----

    def _play_default(self, item):
        speech.speak(item["text"], agent=item["agent"], rate=item.get("rate"),
                     voice=item.get("voice"), announce=item.get("announce", False))

    def _player_loop(self):
        while not self.stop.is_set():
            try:
                _, _, item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.state:
                if item["status"] != "queued":
                    continue  # timed out / cancelled before its turn
                if item["kind"] == "ask" and item["answered"].is_set():
                    continue  # answered from the app before it was even spoken
                item["status"] = "playing"
                item["started_at"] = _now()
                self.now_playing = item
            try:
                self.play(item)
            except Exception as exc:
                with self.state:
                    item["error"] = str(exc)
            finally:
                with self.state:
                    self.now_playing = None
                    item["played_at"] = _now()
                    if item["kind"] == "ask":
                        item["status"] = "awaiting_answer"
                    else:
                        item["status"] = "failed" if "error" in item else "played"
                        self._finish_locked(item)
                item["done"].set()

    # ---- bookkeeping (self.state held) ----

    def _touch_locked(self):
        self.last_activity = time.time()

    def _finish_locked(self, item):
        self.items.pop(item["id"], None)
        record = self._public(item)
        self.history.append(record)
        try:
            self.history_path.parent.mkdir(exist_ok=True)
            with open(self.history_path, "a") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass

    def _public(self, item):
        data = {key: item.get(key) for key in (
            "id", "kind", "agent", "voice", "session", "source", "project",
            "priority", "status", "error",
            "submitted_at", "started_at", "played_at", "answered_at")}
        data["text_preview"] = _preview(item.get("text"))
        if item.get("kind") == "ask":
            data["text"] = item.get("text")
            data["answer"] = item.get("answer")
        return {k: v for k, v in data.items() if v is not None}

    def _idle_expired(self):
        with self.state:
            busy = self.items or self.connections or self.now_playing
            return not busy and time.time() - self.last_activity > self.idle_timeout

    # ---- ops ----

    def _submit(self, request, kind):
        text = (request.get("text") or "").strip()
        if not text:
            raise ValueError("empty text")
        agent = request.get("agent") or "assistant"
        item = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "seq": next(self.seq),
            "text": text,
            "agent": agent,
            "voice": request.get("voice") or self.voice_for(agent),
            "rate": request.get("rate"),
            "announce": bool(request.get("announce")),
            "session": request.get("session"),
            "source": request.get("source"),
            "project": request.get("project"),
            "priority": int(request.get("priority") or PRIORITY_NORMAL),
            "status": "queued",
            "submitted_at": _now(),
            "done": threading.Event(),
            "answered": threading.Event(),
            "answer": None,
        }
        with self.state:
            self.items[item["id"]] = item
            self._touch_locked()
        self.queue.put((-item["priority"], item["seq"], item))
        return item

    def _op_speak(self, request):
        item = self._submit(request, kind="speak")
        if not request.get("wait", True):
            return {"ok": True, "id": item["id"], "status": "queued"}
        done = item["done"].wait(float(request.get("wait_timeout") or PLAYBACK_WAIT_S))
        reply = {"ok": bool(done), "id": item["id"], "status": item["status"]}
        if not done:
            reply["error"] = "timed out waiting for playback"
        return reply

    def _ensure_bridge(self):
        """Launch the Pidgin phone bridge so remote-you can answer too.

        Cheap to call: the bridge holds a singleton flock and exits on its own
        when unconfigured or when this daemon goes away, so a periodic respawn
        attempt is all the supervision it needs.
        """
        if not self.spawn_bridge or os.environ.get("SQUAWK_NO_PIDGIN"):
            return
        if time.time() - self._bridge_spawned_at < 60:
            return
        self._bridge_spawned_at = time.time()
        logs = HERE / "logs"
        logs.mkdir(exist_ok=True)
        with open(logs / "pidgin-bridge.log", "a") as out:
            subprocess.Popen([sys.executable, str(HERE / "pidgin_bridge.py")],
                             stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)

    def _op_ask(self, request):
        item = self._submit(request, kind="ask")
        self._ensure_bridge()
        answered = item["answered"].wait(float(request.get("timeout") or ASK_TIMEOUT_S))
        with self.state:
            item["status"] = "answered" if answered else "timed_out"
            self._finish_locked(item)
            self._touch_locked()
        if answered:
            return {"ok": True, "id": item["id"], "answer": item["answer"],
                    "answered_by": item.get("answered_by")}
        return {"ok": True, "id": item["id"], "answer": None, "timed_out": True}

    def _op_answer(self, request):
        qid = request.get("id")
        text = (request.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "empty answer"}
        with self.state:
            item = self.items.get(qid)
            if item is None and qid in (None, "", "latest"):
                pending = sorted(
                    (i for i in self.items.values()
                     if i["kind"] == "ask" and not i["answered"].is_set()),
                    key=lambda i: i["seq"])
                item = pending[0] if pending else None
            if (item is None or item["kind"] != "ask" or item["answered"].is_set()):
                return {"ok": False, "error": "no such pending question"}
            item["answer"] = text
            item["answered_by"] = request.get("from") or "app"
            item["answered_at"] = _now()
            item["answered"].set()
            self._touch_locked()
        return {"ok": True, "id": item["id"]}

    def _op_status(self):
        with self.state:
            queued = sorted((i for i in self.items.values() if i["status"] == "queued"),
                            key=lambda i: (-i["priority"], i["seq"]))
            questions = sorted(
                (i for i in self.items.values()
                 if i["kind"] == "ask" and not i["answered"].is_set()),
                key=lambda i: i["seq"])
            return {"ok": True, "multiplexer": {
                "pid": os.getpid(),
                "started_at": self.started_at,
                "now_playing": self._public(self.now_playing) if self.now_playing else None,
                "queue": [self._public(i) for i in queued],
                "questions": [self._public(i) for i in questions],
                "history": list(self.history),
            }}

    def _dispatch(self, request):
        op = request.get("op")
        if op == "ping":
            return {"ok": True, "pid": os.getpid()}
        if op == "speak":
            return self._op_speak(request)
        if op == "ask":
            return self._op_ask(request)
        if op == "answer":
            return self._op_answer(request)
        if op == "status":
            return self._op_status()
        if op == "shutdown":
            self.stop.set()
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # ---- server ----

    def _handle(self, conn):
        with self.state:
            self.connections += 1
            self._touch_locked()
        try:
            with conn:
                conn.settimeout(30)
                request = json.loads(conn.makefile().readline())
                conn.settimeout(None)  # blocking ops hold the line until played/answered
                reply = self._dispatch(request)
                conn.sendall((json.dumps(reply) + "\n").encode())
        except Exception as exc:
            try:
                conn.sendall((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
            except OSError:
                pass
        finally:
            with self.state:
                self.connections -= 1
                self._touch_locked()

    def serve(self):
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen(64)  # status pollers are chatty; don't refuse under burst
        server.settimeout(1.0)
        threading.Thread(target=self._player_loop, daemon=True).start()
        print(f"squawkd ready (idle timeout {self.idle_timeout:.0f}s)", flush=True)
        try:
            while not self.stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    if self._idle_expired():
                        print("idle timeout, exiting", flush=True)
                        break
                    continue
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        finally:
            self.stop.set()
            server.close()
            self.socket_path.unlink(missing_ok=True)


def main():
    lock = open(DAEMON_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("squawkd already running, exiting", flush=True)
        return
    daemon = Daemon()
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop.set())
    daemon.serve()


if __name__ == "__main__":
    main()
