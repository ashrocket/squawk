#!/usr/bin/env python3
"""Wake-word gate for hands-free mode (openWakeWord, fully local, no API key).

Run standalone to test:  .venv/bin/python wake.py   (say "hey jarvis")
Used by handsfree.py:    from wake import wait_for_wake
"""
import sys
import numpy as np
import sounddevice as sd

SAMPLE_RATE, BLOCK = 16000, 1280      # 80 ms @ 16 kHz (openWakeWord frame)
WAKE_MODEL = "hey_jarvis"             # built-in; custom "hey squawk" needs training

def crossed(scores, threshold):
    """Pure decision: did any wake score cross the threshold?"""
    return bool(scores) and max(scores.values()) >= threshold

def load_model():
    """Load the wake-word model once so callers can reuse it across turns."""
    from openwakeword.model import Model

    return Model(wakeword_models=[WAKE_MODEL])

def wait_for_wake(device=None, threshold=0.5, model=None):
    if model is None:
        model = load_model()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=BLOCK, device=device) as stream:
        while True:
            blk, _ = stream.read(BLOCK)
            if crossed(model.predict(blk[:, 0].astype(np.int16)), threshold):
                return

if __name__ == "__main__":
    print("Listening for 'hey jarvis'… (Ctrl-C to stop)", file=sys.stderr)
    wait_for_wake()
    print("WAKE")
