"""Regression tests for claude-hooks/install_hooks.py's settings.json merge logic.

Covers two bugs in HookInstaller.configure_claude_settings():

1. The opt-out path used to delete the entire "PreToolUse" key from an
   existing settings.json instead of only permission-request.js's own
   group, wiping out any other PreToolUse hook a user had registered
   (their own, or a different tool's) on every non-interactive reinstall
   -- install_permission_hook defaults to False when the prompt can't be
   asked (stdin isn't a TTY), so this fired on every unattended sync.

2. The per-hook-type merge check was all-or-nothing rather than
   per-group: appending a new group to an existing hook_type checked
   whether ALL new groups' commands were already present as one set, so
   as soon as one group in a batch was new, every group in that batch
   -- including ones already registered -- got re-appended, duplicating
   them.
"""

import importlib.util
import json
from pathlib import Path

import pytest


def _load_install_hooks_module():
    repo_root = Path(__file__).resolve().parents[2]
    install_hooks_py = repo_root / "claude-hooks" / "install_hooks.py"
    spec = importlib.util.spec_from_file_location("install_hooks", install_hooks_py)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installer(monkeypatch, tmp_path):
    module = _load_install_hooks_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    inst = module.HookInstaller()
    inst.claude_hooks_dir = tmp_path / ".claude" / "hooks"
    (inst.claude_hooks_dir / "core").mkdir(parents=True, exist_ok=True)
    (inst.claude_hooks_dir / "core" / "permission-request.js").write_text("// stub\n")
    (inst.claude_hooks_dir / "statusline.sh").write_text("#!/bin/sh\n")
    return inst


def _pretooluse_groups(settings_path):
    settings = json.loads(settings_path.read_text())
    return settings.get("hooks", {}).get("PreToolUse", [])


def test_opt_out_removes_only_permission_request_group(installer):
    """A user's own PreToolUse hook must survive opting out of permission-request."""
    settings_path = installer.claude_hooks_dir.parent / "settings.json"
    settings_path.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "mcp__",
                    "hooks": [{"type": "command", "command": str(
                        installer.claude_hooks_dir / "core" / "permission-request.js"
                    )}],
                },
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "some-users-own-hook"}],
                },
            ]
        }
    }))

    ok = installer.configure_claude_settings(install_permission_hook=False)
    assert ok

    groups = _pretooluse_groups(settings_path)
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert "some-users-own-hook" in commands
    assert not any("permission-request.js" in c for c in commands)


def test_reinstall_does_not_duplicate_existing_groups(installer):
    """Running the installer twice must not duplicate any PreToolUse group.

    This installer's own hook_config currently only ever produces one
    PreToolUse group per run, so it does not exercise the all-or-nothing
    vs. per-group distinction directly (that only matters once a
    hook_type's new-groups batch contains more than one group at a
    time). What this does verify: reinstalling doesn't duplicate a
    pre-existing group that the installer doesn't own, and the merge
    correctly treats "already registered" per-group rather than
    dropping/duplicating based on the whole hook_type's state."""
    settings_path = installer.claude_hooks_dir.parent / "settings.json"
    settings_path.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "some-users-own-hook"}],
                }
            ]
        }
    }))

    for _ in range(2):
        ok = installer.configure_claude_settings(install_permission_hook=True)
        assert ok

    groups = _pretooluse_groups(settings_path)
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert commands.count("some-users-own-hook") == 1
    assert sum("permission-request.js" in c for c in commands) == 1
    assert len(groups) == 2


def test_opt_out_preserves_own_hook_sharing_a_group(installer):
    """A user's own hook sharing permission-request.js's matcher group must
    survive opting out -- group-level filtering used to drop it too, and
    the "other PreToolUse hooks preserved" message falsely claimed it
    hadn't."""
    settings_path = installer.claude_hooks_dir.parent / "settings.json"
    settings_path.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "mcp__",
                    "hooks": [
                        {"type": "command", "command": str(
                            installer.claude_hooks_dir / "core" / "permission-request.js"
                        )},
                        {"type": "command", "command": "some-users-own-hook"},
                    ],
                },
            ]
        }
    }))

    ok = installer.configure_claude_settings(install_permission_hook=False)
    assert ok

    groups = _pretooluse_groups(settings_path)
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert "some-users-own-hook" in commands
    assert not any("permission-request.js" in c for c in commands)
