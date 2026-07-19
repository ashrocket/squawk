"""The multiplexer daemon: serialization, priority, tags, and answer routing."""
import json
import pathlib
import shutil
import socket
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import squawkd


class FakeSpeaker:
    """Records what would have been spoken and detects overlapping playback."""

    def __init__(self):
        self.spoken = []
        self.overlapped = False
        self.gates = {}  # agent -> Event playback blocks on
        self._busy = threading.Lock()

    def play(self, item):
        if not self._busy.acquire(blocking=False):
            self.overlapped = True
            self._busy.acquire()
        try:
            gate = self.gates.get(item["agent"])
            if gate:
                gate.wait(5)
            else:
                time.sleep(0.02)
            self.spoken.append((item["agent"], item["text"]))
        finally:
            self._busy.release()


def call(sock_path, payload, timeout=10.0):
    for attempt in range(3):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(str(sock_path))
            sock.sendall((json.dumps(payload) + "\n").encode())
            return json.loads(sock.makefile().readline())
        except ConnectionError:
            if attempt == 2:
                raise
            time.sleep(0.05)
        finally:
            sock.close()


def wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def daemon(tmp_path):
    speaker = FakeSpeaker()
    # AF_UNIX socket paths are capped around 104 chars on macOS; pytest's
    # tmp_path is far longer, so the socket alone lives under /tmp.
    sock_dir = pathlib.Path(tempfile.mkdtemp(prefix="sqd-", dir="/tmp"))
    d = squawkd.Daemon(socket_path=sock_dir / "s",
                       history_path=tmp_path / "history.jsonl",
                       play=speaker.play,
                       voice_for=lambda agent: f"voice-of-{agent}",
                       idle_timeout=60,
                       spawn_bridge=False)
    thread = threading.Thread(target=d.serve, daemon=True)
    thread.start()
    assert wait_until(lambda: d.socket_path.exists())
    yield d, speaker
    d.stop.set()
    thread.join(3)
    shutil.rmtree(sock_dir, ignore_errors=True)


def test_speaks_serially_in_order(daemon):
    d, speaker = daemon
    replies = []

    def submit(text):
        replies.append(call(d.socket_path, {
            "op": "speak", "text": text, "agent": "worker", "wait": True}))

    threads = [threading.Thread(target=submit, args=(f"update {n}",)) for n in range(3)]
    for t in threads:
        t.start()
        time.sleep(0.05)  # deterministic arrival order
    for t in threads:
        t.join(5)

    assert [r["status"] for r in replies] == ["played"] * 3
    assert [text for _, text in speaker.spoken] == ["update 0", "update 1", "update 2"]
    assert not speaker.overlapped


def test_urgent_jumps_queue_but_never_interrupts(daemon):
    d, speaker = daemon
    speaker.gates["blocker"] = threading.Event()
    call(d.socket_path, {"op": "speak", "text": "long story", "agent": "blocker",
                         "wait": False})
    assert wait_until(lambda: d.now_playing is not None)
    call(d.socket_path, {"op": "speak", "text": "routine", "agent": "worker",
                         "wait": False, "priority": 0})
    call(d.socket_path, {"op": "speak", "text": "fire alarm", "agent": "worker",
                         "wait": False, "priority": 10})
    speaker.gates["blocker"].set()

    assert wait_until(lambda: len(speaker.spoken) == 3)
    assert [text for _, text in speaker.spoken] == ["long story", "fire alarm", "routine"]
    assert not speaker.overlapped


def test_ask_routes_answer_back_to_asker(daemon):
    d, speaker = daemon
    result = {}

    def ask():
        result["reply"] = call(d.socket_path, {
            "op": "ask", "text": "Deploy to prod?", "agent": "claude-squawk",
            "session": "sess-1", "source": "cmux:tab-9", "timeout": 10}, timeout=15)

    asker = threading.Thread(target=ask)
    asker.start()

    # answer only after the question has been spoken; answering while it is
    # still queued legitimately cancels playback
    assert wait_until(lambda: any(
        q.get("status") == "awaiting_answer"
        for q in call(d.socket_path, {"op": "status"})["multiplexer"]["questions"]))
    status = call(d.socket_path, {"op": "status"})["multiplexer"]
    question = status["questions"][0]
    assert question["text"] == "Deploy to prod?"
    assert question["session"] == "sess-1"
    assert question["source"] == "cmux:tab-9"

    answer = call(d.socket_path, {"op": "answer", "id": question["id"],
                                  "text": "yes, ship it"})
    assert answer["ok"]
    asker.join(5)
    assert result["reply"]["answer"] == "yes, ship it"

    # question is spoken aloud and leaves the pending list once answered
    assert ("claude-squawk", "Deploy to prod?") in speaker.spoken
    assert call(d.socket_path, {"op": "status"})["multiplexer"]["questions"] == []


def test_answer_latest_and_unknown_ids(daemon):
    d, _ = daemon
    assert not call(d.socket_path, {"op": "answer", "id": "nope", "text": "hi"})["ok"]

    result = {}
    asker = threading.Thread(target=lambda: result.update(reply=call(
        d.socket_path, {"op": "ask", "text": "Which branch?", "agent": "a",
                        "timeout": 10}, timeout=15)))
    asker.start()
    assert wait_until(lambda: call(
        d.socket_path, {"op": "status"})["multiplexer"]["questions"] != [])
    assert call(d.socket_path, {"op": "answer", "id": "latest", "text": "main"})["ok"]
    asker.join(5)
    assert result["reply"]["answer"] == "main"


def test_status_carries_origin_tags_and_voice(daemon):
    d, speaker = daemon
    speaker.gates["blocker"] = threading.Event()
    call(d.socket_path, {"op": "speak", "text": "hold", "agent": "blocker", "wait": False})
    assert wait_until(lambda: d.now_playing is not None)
    call(d.socket_path, {"op": "speak", "text": "tagged update", "agent": "worker",
                         "wait": False, "session": "sess-42", "source": "tty-3",
                         "project": "squawk"})

    status = call(d.socket_path, {"op": "status"})["multiplexer"]
    queued = status["queue"][0]
    assert queued["session"] == "sess-42"
    assert queued["source"] == "tty-3"
    assert queued["project"] == "squawk"
    assert queued["voice"] == "voice-of-worker"
    assert status["now_playing"]["agent"] == "blocker"
    speaker.gates["blocker"].set()

    assert wait_until(lambda: len(speaker.spoken) == 2)
    assert wait_until(
        lambda: len(call(d.socket_path, {"op": "status"})["multiplexer"]["history"]) == 2)
