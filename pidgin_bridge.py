#!/usr/bin/env python3
"""Bridge squawk questions to the phone via Pidgin (pidginroost.com).

The multiplexer (squawkd) is the traffic cop; this sidecar is its long-range
radio. It watches the daemon's pending questions, forwards any still unanswered
after a grace delay to the phone as a Pidgin question, and posts the phone's
reply back to the daemon — so the answer lands on the stdout of the session
that asked, no matter where in the world it was typed. First responder wins:
if the question gets answered locally (Squawk.app, `speak --answer`) first,
the bridge simply stops polling for the phone reply.

Spawned on demand by squawkd when a question arrives; exits once the
multiplexer goes away. Auth: $PIDGIN_API_KEY, or the key the Pidgin macOS app
stores in the login keychain at sign-in. With --mirror it also forwards spoken
announcements as Pidgin notes, so remote-you reads what home-you would hear.
"""
import argparse
import calendar
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import speak as speech

HERE = Path(__file__).resolve().parent
BRIDGE_LOCK = HERE / ".pidgin_bridge.lock"
PIDGIN_URL = os.environ.get("PIDGIN_URL", "https://api.pidginroost.com")
KEYCHAIN_SERVICE = "com.pidginroost.pidgin"
KEYCHAIN_ACCOUNT = "pidgin_sk"
POLL_INTERVAL_S = 3.0
FORWARD_DELAY_S = float(os.environ.get("SQUAWK_PIDGIN_DELAY", "10"))
MAX_STATUS_FAILURES = 10  # squawkd gone this many ticks in a row -> exit


def resolve_api_key():
    key = os.environ.get("PIDGIN_API_KEY")
    if key:
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except OSError:
        return None


class PidginClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _request(self, method, path, payload=None, timeout=15):
        req = urllib.request.Request(
            f"{self.url}{path}", method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     # Cloudflare bans urllib's default UA (error 1010)
                     "User-Agent": "squawk-pidgin-bridge/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def send_question(self, title, body, project=None, urgent=False):
        """Post a question message; returns its id (reply arrives out of band)."""
        payload = {
            "type": "question",
            "title": title,
            "body": body,
            "priority": "urgent" if urgent else "normal",
            "instance": {"model": "squawk", "session_id": "squawk-bridge",
                         "project": project or "squawk", "source": "squawk"},
        }
        reply = self._request("POST", "/api/messages", payload)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "pidgin send failed"))
        return reply["data"]["id"]

    def send_note(self, title, body, project=None):
        payload = {
            "type": "text",
            "title": title,
            "body": body,
            "priority": "normal",
            "instance": {"model": "squawk", "session_id": "squawk-bridge",
                         "project": project or "squawk", "source": "squawk"},
        }
        self._request("POST", "/api/messages", payload)

    def fetch_reply(self, msg_id):
        """The user's phone reply to a question, or None while unanswered."""
        try:
            reply = self._request("GET", f"/api/replies/{msg_id}", timeout=10)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        return (reply.get("data") or {}).get("reply") or None


def _age_seconds(iso_ts):
    try:
        return time.time() - calendar.timegm(
            time.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0.0


def _question_body(question):
    origin = " · ".join(tag for tag in (
        question.get("agent"),
        question.get("project"),
        question.get("source"),
        (question.get("session") or "")[:8] or None) if tag)
    return (f"From {origin}.\n"
            "Reply here to answer — it routes back to the session that asked. "
            "First responder wins (Squawk.app can answer it too).")


class Bridge:
    """One tick: forward due questions, relay arrived replies, mirror speech.

    Pure logic over injected callables so tests need no network and no daemon:
    status_call() -> multiplexer status dict, answer_call(id, text) -> reply.
    """

    def __init__(self, pidgin, status_call, answer_call,
                 delay=FORWARD_DELAY_S, mirror=False):
        self.pidgin = pidgin
        self.status_call = status_call
        self.answer_call = answer_call
        self.delay = delay
        self.mirror = mirror
        self.forwarded = {}   # question id -> pidgin message id
        self.mirrored = None  # history ids already sent (None until seeded)

    def run_once(self):
        status = self.status_call()
        pending = {q["id"]: q for q in status.get("questions") or []}

        # answered/expired elsewhere: stop watching, never send a stale reply
        for qid in list(self.forwarded):
            if qid not in pending:
                del self.forwarded[qid]

        for qid, question in pending.items():
            if qid in self.forwarded:
                continue
            if _age_seconds(question.get("submitted_at")) < self.delay:
                continue
            try:
                self.forwarded[qid] = self.pidgin.send_question(
                    title=question.get("text", ""),
                    body=_question_body(question),
                    project=question.get("project"),
                    urgent=(question.get("priority") or 0) > 0)
            except Exception as exc:  # pidgin blip: log, retry next tick
                print(f"pidgin send failed for {qid}: {exc}", flush=True)
                continue
            print(f"forwarded question {qid} -> pidgin {self.forwarded[qid]}",
                  flush=True)

        for qid, msg_id in list(self.forwarded.items()):
            try:
                answer = self.pidgin.fetch_reply(msg_id)
            except Exception as exc:
                print(f"pidgin reply poll failed for {qid}: {exc}", flush=True)
                continue
            if answer:
                del self.forwarded[qid]
                reply = self.answer_call(qid, answer)
                print(f"phone answered {qid}: {reply.get('ok')}", flush=True)

        if self.mirror:
            self._mirror(status.get("history") or [])

    def _mirror(self, history):
        if self.mirrored is None:  # first tick: don't replay old history
            self.mirrored = {item.get("id") for item in history}
            return
        for item in history:
            if item.get("id") in self.mirrored or item.get("kind") != "speak":
                continue
            self.mirrored.add(item.get("id"))
            origin = " · ".join(tag for tag in (
                item.get("project"), (item.get("session") or "")[:8] or None) if tag)
            try:
                self.pidgin.send_note(
                    title=f"{item.get('agent', 'agent')} said",
                    body=f"{item.get('text_preview', '')}\n({origin})",
                    project=item.get("project"))
            except Exception as exc:
                print(f"pidgin mirror failed: {exc}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Forward squawk questions to Pidgin")
    ap.add_argument("--delay", type=float, default=FORWARD_DELAY_S,
                    help="seconds a question stays local-only before the phone "
                         "is pinged (default 10)")
    ap.add_argument("--interval", type=float, default=POLL_INTERVAL_S)
    ap.add_argument("--mirror", action="store_true",
                    help="also forward spoken announcements as Pidgin notes")
    ap.add_argument("--once", action="store_true", help="single tick, for debugging")
    args = ap.parse_args()

    api_key = resolve_api_key()
    if not api_key:
        print("no Pidgin API key (env or keychain); bridge idle, exiting", flush=True)
        return

    lock = open(BRIDGE_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("pidgin bridge already running, exiting", flush=True)
        return

    pidgin = PidginClient(PIDGIN_URL, api_key)
    bridge = Bridge(
        pidgin,
        status_call=lambda: speech.squawkd_call(
            {"op": "status"}, timeout=5.0, spawn=False)["multiplexer"],
        answer_call=lambda qid, text: speech.squawkd_call(
            {"op": "answer", "id": qid, "text": text, "from": "pidgin"},
            timeout=5.0, spawn=False),
        delay=args.delay, mirror=args.mirror)

    print(f"pidgin bridge up (delay {args.delay:.0f}s, mirror={args.mirror})",
          flush=True)
    failures = 0
    while True:
        try:
            bridge.run_once()
            failures = 0
        except (OSError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            failures += 1
            print(f"tick failed ({failures}/{MAX_STATUS_FAILURES}): {exc}", flush=True)
            if failures >= MAX_STATUS_FAILURES:
                print("multiplexer unreachable; exiting", flush=True)
                return
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
