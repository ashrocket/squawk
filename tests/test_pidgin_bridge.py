"""The Pidgin bridge: forwarding, grace delay, reply routing, first-responder."""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pidgin_bridge import Bridge


def iso(seconds_ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


class FakePidgin:
    def __init__(self):
        self.questions = []   # (msg_id, title, body, project, urgent)
        self.notes = []
        self.replies = {}     # msg_id -> reply text

    def send_question(self, title, body, project=None, urgent=False):
        msg_id = f"msg-{len(self.questions)}"
        self.questions.append((msg_id, title, body, project, urgent))
        return msg_id

    def send_note(self, title, body, project=None):
        self.notes.append((title, body, project))

    def fetch_reply(self, msg_id):
        return self.replies.get(msg_id)


class FakeDaemon:
    def __init__(self):
        self.questions = []
        self.history = []
        self.answers = []

    def status(self):
        return {"questions": list(self.questions), "history": list(self.history)}

    def answer(self, qid, text):
        self.answers.append((qid, text))
        self.questions = [q for q in self.questions if q["id"] != qid]
        return {"ok": True, "id": qid}


def make_bridge(daemon, pidgin, delay=0.0, mirror=False):
    return Bridge(pidgin, status_call=daemon.status, answer_call=daemon.answer,
                  delay=delay, mirror=mirror)


def test_forwards_question_once_and_routes_reply_back():
    daemon, pidgin = FakeDaemon(), FakePidgin()
    daemon.questions = [{"id": "q1", "text": "Deploy?", "agent": "claude-squawk",
                         "project": "squawk", "session": "sess-12345678",
                         "source": "cmux:tab", "priority": 10,
                         "submitted_at": iso(30)}]
    bridge = make_bridge(daemon, pidgin)

    bridge.run_once()
    bridge.run_once()  # second tick must not re-send
    assert len(pidgin.questions) == 1
    msg_id, title, body, project, urgent = pidgin.questions[0]
    assert title == "Deploy?"
    assert "claude-squawk" in body and "sess-123" in body
    assert project == "squawk"
    assert urgent

    pidgin.replies[msg_id] = "yes ship it"
    bridge.run_once()
    assert daemon.answers == [("q1", "yes ship it")]
    assert bridge.forwarded == {}


def test_grace_delay_keeps_fresh_questions_local():
    daemon, pidgin = FakeDaemon(), FakePidgin()
    daemon.questions = [{"id": "q1", "text": "Now?", "submitted_at": iso(2)}]
    bridge = make_bridge(daemon, pidgin, delay=10)

    bridge.run_once()
    assert pidgin.questions == []

    daemon.questions[0]["submitted_at"] = iso(30)
    bridge.run_once()
    assert len(pidgin.questions) == 1


def test_locally_answered_question_stops_the_phone_poll():
    daemon, pidgin = FakeDaemon(), FakePidgin()
    daemon.questions = [{"id": "q1", "text": "Deploy?", "submitted_at": iso(30)}]
    bridge = make_bridge(daemon, pidgin)
    bridge.run_once()
    assert "q1" in bridge.forwarded

    daemon.questions = []  # answered in Squawk.app / timed out
    pidgin.replies["msg-0"] = "too late"
    bridge.run_once()
    assert bridge.forwarded == {}
    assert daemon.answers == []  # stale phone reply never routed


def test_mirror_sends_new_announcements_but_not_old_history():
    daemon, pidgin = FakeDaemon(), FakePidgin()
    daemon.history = [{"id": "h1", "kind": "speak", "agent": "scout",
                       "text_preview": "old news", "project": "squawk"}]
    bridge = make_bridge(daemon, pidgin, mirror=True)

    bridge.run_once()  # first tick seeds; nothing replayed
    assert pidgin.notes == []

    daemon.history.append({"id": "h2", "kind": "speak", "agent": "scout",
                           "text_preview": "tests green", "project": "squawk",
                           "session": "sess-12345678"})
    daemon.history.append({"id": "h3", "kind": "ask", "agent": "scout",
                           "text_preview": "a question", "answer": "x"})
    bridge.run_once()
    bridge.run_once()
    assert len(pidgin.notes) == 1  # the ask isn't mirrored, h2 only once
    title, body, project = pidgin.notes[0]
    assert title == "scout said"
    assert "tests green" in body
