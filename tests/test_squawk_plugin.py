import os
import shlex
import subprocess


def test_squawk_mode_confirmation_does_not_announce_agent_name(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CODE_SESSION_ID": "test-session",
        "SQUAWK_DRY_RUN": "1",
        "SQUAWK_INTRO_DIR": str(tmp_path / ".squawk"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    result = subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )

    dry_run_args = shlex.split(result.stdout.splitlines()[0])
    assert dry_run_args == [
        "squawk-speak",
        "--as",
        "claude-test",
        "Squawk Mode enabled for squawk.",
    ]


def test_squawk_mode_repeat_confirmation_is_terse(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CODE_SESSION_ID": "test-session",
        "SQUAWK_DRY_RUN": "1",
        "SQUAWK_INTRO_DIR": str(tmp_path / ".squawk"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    result = subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )

    dry_run_args = shlex.split(result.stdout.splitlines()[0])
    assert dry_run_args == [
        "squawk-speak",
        "--as",
        "claude-test",
        "Squawk mode on - summarizing",
    ]
    assert "intro=repeat" in result.stdout


def test_squawk_mode_repeat_can_name_submode(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CODE_SESSION_ID": "test-session",
        "SQUAWK_DRY_RUN": "1",
        "SQUAWK_INTRO_DIR": str(tmp_path / ".squawk"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test", "listening"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    result = subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test", "listening"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )

    dry_run_args = shlex.split(result.stdout.splitlines()[0])
    assert dry_run_args[-1] == "Squawk mode on - listening"


def test_squawk_mode_single_argument_can_include_submode(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CODE_SESSION_ID": "test-session",
        "SQUAWK_DRY_RUN": "1",
        "SQUAWK_INTRO_DIR": str(tmp_path / ".squawk"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test listening"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    result = subprocess.run(
        ["bash", "claude-plugin/scripts/squawk-mode.sh", "on", "claude-test listening"],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )

    dry_run_args = shlex.split(result.stdout.splitlines()[0])
    assert dry_run_args == [
        "squawk-speak",
        "--as",
        "claude-test",
        "Squawk mode on - listening",
    ]
    assert "submode=listening" in result.stdout
