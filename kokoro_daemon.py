#!/usr/bin/env python3
"""Keeps the Kokoro TTS model resident for instant neural synthesis.

Spawned on demand by speak.py; exits after an idle timeout so the ~500MB of
RAM is only spent while neural voices are actively in use (8GB-friendly).

Protocol: one JSON line per connection on a unix socket:
    {"text": "...", "voice": "af_heart", "speed": 1.0}
    -> {"wav": "/tmp/....wav"} or {"error": "..."}
The client plays and deletes the wav; the speech lock stays client-side.
"""
import fcntl
import json
import os
import socket
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SOCKET_PATH = HERE / ".kokoro.sock"
DAEMON_LOCK = HERE / ".kokoro_daemon.lock"
IDLE_TIMEOUT_S = float(os.environ.get("KOKORO_DAEMON_IDLE_S", "600"))


def main():
    lock = open(DAEMON_LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("kokoro daemon already running, exiting", flush=True)
        return

    from kokoro_onnx import Kokoro
    kokoro = Kokoro(str(HERE / "models" / "kokoro-v1.0.onnx"),
                    str(HERE / "models" / "voices-v1.0.bin"))

    SOCKET_PATH.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    server.listen(4)
    server.settimeout(IDLE_TIMEOUT_S)
    print(f"kokoro daemon ready (idle timeout {IDLE_TIMEOUT_S:.0f}s)", flush=True)

    try:
        while True:
            try:
                conn, _ = server.accept()
            except TimeoutError:
                print("idle timeout, exiting", flush=True)
                break
            with conn:
                try:
                    request = json.loads(conn.makefile().readline())
                    samples, sr = kokoro.create(
                        request["text"],
                        voice=request.get("voice", "af_heart"),
                        speed=request.get("speed", 1.0))
                    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    with wave.open(tmp.name, "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(sr)
                        w.writeframes(pcm.tobytes())
                    conn.sendall((json.dumps({"wav": tmp.name}) + "\n").encode())
                except Exception as exc:
                    try:
                        conn.sendall((json.dumps({"error": str(exc)}) + "\n").encode())
                    except OSError:
                        pass
    finally:
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
