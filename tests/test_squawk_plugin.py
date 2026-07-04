import os
import shlex
import subprocess


def test_squawk_mode_confirmation_does_not_announce_agent_name(tmp_path):
    env = {
        **os.environ,
        "CLAUDE_CODE_SESSION_ID": "test-session",
        "SQUAWK_DRY_RUN": "1",
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
