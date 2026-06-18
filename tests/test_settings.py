"""Idempotent Stop-hook install/uninstall in a Claude settings.json."""

from __future__ import annotations

import json

import pytest

from looptight.settings import HOOK_COMMAND, install, uninstall


def _read(path):
    return json.loads(path.read_text())


def test_install_into_missing_file_creates_it(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    assert install(path) is True
    data = _read(path)
    commands = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert HOOK_COMMAND in commands


def test_install_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    assert install(path) is True
    assert install(path) is False  # second time is a no-op
    stop = _read(path)["hooks"]["Stop"]
    assert len(stop) == 1


def test_install_preserves_existing_settings_and_hooks(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "Stop": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "make lint"}]}
                    ]
                },
            }
        )
    )
    assert install(path) is True
    data = _read(path)
    assert data["model"] == "opus"  # untouched
    commands = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert "make lint" in commands  # the user's own hook survives
    assert HOOK_COMMAND in commands


def test_uninstall_removes_only_ours(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "make lint"}]}]}}
        )
    )
    install(path)
    removed = uninstall(path)
    assert removed == 1
    commands = [h["command"] for e in _read(path)["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == ["make lint"]


def test_uninstall_preserves_commands_that_only_contain_ours(tmp_path):
    path = tmp_path / "settings.json"
    user_command = f"echo {HOOK_COMMAND} disabled"
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": user_command}],
                        }
                    ]
                }
            }
        )
    )

    install(path)
    assert uninstall(path) == 1
    commands = [h["command"] for e in _read(path)["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == [user_command]


def test_refuses_to_clobber_malformed_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not valid json")
    with pytest.raises(ValueError):
        install(path)
    # the broken file is left exactly as it was
    assert path.read_text() == "{ this is not valid json"
