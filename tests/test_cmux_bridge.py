import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import cmux_bridge as cx


def test_resolve_target_allows_codex_by_default(monkeypatch):
    monkeypatch.setattr(
        cx,
        "focused",
        lambda: {"surface_id": "codex-surface", "workspace_id": "workspace-1"},
    )
    monkeypatch.setattr(
        cx,
        "_kind_of",
        lambda surface_ref, workspace_id=None: "codex",
    )

    assert cx.resolve_target() == ("codex-surface", "codex")


def test_resolve_target_rejects_non_agent_by_default(monkeypatch):
    monkeypatch.setattr(
        cx,
        "focused",
        lambda: {"surface_id": "shell-surface", "workspace_id": "workspace-1"},
    )
    monkeypatch.setattr(
        cx,
        "_kind_of",
        lambda surface_ref, workspace_id=None: "shell",
    )

    with pytest.raises(cx.CmuxError, match="not an allowed agent"):
        cx.resolve_target()


def test_resolve_target_can_override_non_agent_guard(monkeypatch):
    monkeypatch.setattr(
        cx,
        "focused",
        lambda: {"surface_id": "shell-surface", "workspace_id": "workspace-1"},
    )
    monkeypatch.setattr(
        cx,
        "_kind_of",
        lambda surface_ref, workspace_id=None: "shell",
    )

    assert cx.resolve_target(allow_any=True) == ("shell-surface", "shell")


def test_explicit_surface_ref_is_validated_against_surface_list(monkeypatch):
    def fake_rpc(method, params=None):
        assert method == "surface.list"
        return {
            "surfaces": [
                {
                    "id": "claude-surface-id",
                    "ref": "surface:98",
                    "resume_binding": {"kind": "claude"},
                }
            ]
        }

    monkeypatch.setattr(cx, "_rpc", fake_rpc)

    assert cx.resolve_target(surface_ref="surface:98") == ("surface:98", "claude")


def test_unverified_explicit_surface_requires_override(monkeypatch):
    monkeypatch.setattr(cx, "_rpc", lambda method, params=None: {"surfaces": []})

    with pytest.raises(cx.CmuxError, match="could not verify"):
        cx.resolve_target(surface_ref="surface:missing")
