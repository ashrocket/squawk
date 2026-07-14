import importlib.util
import pathlib


def load_hook():
    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "claude-plugin"
        / "hooks"
        / "scripts"
        / "stop_speak_last.py"
    )
    spec = importlib.util.spec_from_file_location("stop_speak_last", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_hook_uses_plugin_speak_wrapper(monkeypatch):
    hook = load_hook()
    calls = []

    class FakeProc:
        def __init__(self):
            self.stdin = self

        def write(self, text):
            self.text = text

        def close(self):
            pass

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/tmp/plugin-root")
    monkeypatch.setattr(hook, "voice_active", lambda: False)
    monkeypatch.setattr(hook.subprocess, "Popen", fake_popen)

    hook.speak("claude-squawk", "Done.")

    args, kwargs = calls[0]
    assert args[:4] == [
        "bash",
        "/tmp/plugin-root/scripts/squawk-speak.sh",
        "--as",
        "claude-squawk",
    ]
    assert kwargs["stdin"] is hook.subprocess.PIPE
    assert kwargs["text"] is True
    assert kwargs["start_new_session"] is True


def test_stop_hook_relays_when_voice_conversation_is_active(monkeypatch):
    hook = load_hook()
    calls = []

    class FakeProc:
        def __init__(self):
            self.stdin = self

        def write(self, text):
            self.text = text

        def close(self):
            pass

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/tmp/plugin-root")
    monkeypatch.setattr(hook, "voice_active", lambda: True)
    monkeypatch.setattr(
        hook.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append(args) or FakeProc(),
    )

    hook.speak("claude-squawk", "Queued.")

    assert calls[0][:5] == [
        "bash",
        "/tmp/plugin-root/scripts/squawk-speak.sh",
        "--relay",
        "--as",
        "claude-squawk",
    ]
