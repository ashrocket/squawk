import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import channel_state as channel


def use_temp_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(channel, "CHANNEL_STATE", tmp_path / "channel.json")
    monkeypatch.setattr(channel, "CHANNEL_LOCK", tmp_path / ".channel.lock")
    monkeypatch.setattr(channel, "SPEECH_LOCK", tmp_path / ".speech.lock")
    monkeypatch.setattr(channel, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(channel, "REGISTRY", tmp_path / "voices.json")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_floor_and_transmission_are_visible(tmp_path, monkeypatch):
    use_temp_channel(tmp_path, monkeypatch)

    channel.set_floor("codex-squawk", voice="kokoro:af_heart", project="squawk")
    channel.set_transmission("codex-squawk", voice="kokoro:af_heart", text="A short update")
    data = channel.snapshot(available_voices=["default", "kokoro:af_heart"])

    assert data["floor"]["agent"] == "codex-squawk"
    assert data["transmission"]["text_preview"] == "A short update"
    assert data["agents"] == [
        {
            "agent": "codex-squawk",
            "voice": None,
            "has_floor": True,
            "transmitting": True,
            "queued": 0,
        }
    ]


def test_airtime_requests_are_identifiable_and_ordered(tmp_path, monkeypatch):
    use_temp_channel(tmp_path, monkeypatch)

    first = channel.request_airtime("Need to report tests.", agent="agent-a", voice="default")
    second = channel.request_airtime("Need to report deploy.", agent="agent-b", voice="Ava")
    queued = channel.pending_requests()

    assert [item["id"] for item in queued] == [first["id"], second["id"]]
    assert queued[0]["from"] == "agent a"
    assert queued[0]["voice"] == "default"
    assert queued[1]["agent"] == "agent-b"


def test_snapshot_lists_voice_assignments_requests_and_squawk_modes(tmp_path, monkeypatch):
    use_temp_channel(tmp_path, monkeypatch)
    channel.REGISTRY.write_text(json.dumps({
        "agent-a": "default",
        "agent-b": "kokoro:bf_emma",
    }))
    state_dir = tmp_path / "state" / "squawk" / "claude-mode"
    state_dir.mkdir(parents=True)
    (state_dir / "session-1.env").write_text(
        "agent='agent-c'\nproject='squawk'\nstarted_at='2026-07-05T12:00:00Z'\n"
    )
    channel.request_airtime("queued", agent="agent-b", voice="kokoro:bf_emma")

    data = channel.snapshot(available_voices=["default", "kokoro:bf_emma"])

    assert data["voice_assignments"]["agent-a"] == "default"
    assert data["requests"][0]["agent"] == "agent-b"
    assert data["squawk_modes"][0]["agent"] == "agent-c"
    assert {agent["agent"] for agent in data["agents"]} == {
        "agent-a",
        "agent-b",
        "agent-c",
    }


def test_format_snapshot_names_floor_and_requests(tmp_path, monkeypatch):
    use_temp_channel(tmp_path, monkeypatch)
    channel.set_floor("agent-a", voice="default", mode="conversation")
    channel.request_airtime("Please let me speak next.", agent="agent-b", voice="Ava")

    text = channel.format_snapshot(channel.snapshot())

    assert "Floor: agent-a (default)" in text
    assert "agent-b: Please let me speak next." in text
