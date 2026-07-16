"""Idempotent Stop-hook install/uninstall in a Claude settings.json."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_install_preserves_stop_entry_with_non_list_hooks(tmp_path):
    path = tmp_path / "settings.json"
    malformed_entry = {"matcher": "legacy", "hooks": None}
    path.write_text(json.dumps({"hooks": {"Stop": [malformed_entry]}}))

    assert install(path) is True

    stop = _read(path)["hooks"]["Stop"]
    assert stop[0] == malformed_entry
    assert stop[1]["hooks"][0]["command"] == HOOK_COMMAND


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


def test_uninstall_prunes_emptied_stop_and_hooks(tmp_path):
    # When looptight's was the only Stop hook, uninstall must restore the file to its pre-install
    # shape — no dangling "Stop": [] or empty "hooks": {} — symmetric with install creating them.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "opus"}))  # no hooks at all

    assert install(path) is True
    assert uninstall(path) == 1
    assert _read(path) == {"model": "opus"}  # fully restored, no residual keys

    # But a sibling hook type is preserved (only the emptied Stop list is pruned).
    path.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}))
    install(path)
    assert uninstall(path) == 1
    data = _read(path)
    assert "Stop" not in data["hooks"] and "PreToolUse" in data["hooks"]


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


def test_install_refuses_non_dict_json_settings_file(tmp_path):
    # Valid JSON that is not an object (e.g. a top-level array) must be refused, not
    # overwritten: settings.json is always an object, so a non-dict file is foreign
    # and editing it would corrupt the user's data. Distinct from malformed JSON.
    path = tmp_path / "settings.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        install(path)
    assert path.read_text() == "[]"  # left exactly as it was


def test_install_refuses_when_hooks_is_not_an_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": ["not", "an", "object"]}))
    # A clear, actionable error naming `hooks` — not a cryptic dict() crash.
    with pytest.raises(ValueError, match="hooks"):
        install(path)


@pytest.mark.parametrize("edit", [install, uninstall])
def test_refuses_when_stop_hooks_is_not_an_array(tmp_path, edit):
    path = tmp_path / "settings.json"
    original = json.dumps({"hooks": {"Stop": {"hooks": []}}})
    path.write_text(original)

    with pytest.raises(ValueError, match="Stop"):
        edit(path)

    assert path.read_text() == original


def test_uninstall_returns_zero_when_no_looptight_hooks_present(tmp_path):
    # settings.py:106 — when a settings file exists but has no looptight Stop hooks,
    # removed == 0 and the `if removed:` branch is False; the file must be left unchanged.
    path = tmp_path / "settings.json"
    content = json.dumps({"model": "opus", "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "make lint"}]}]}}) + "\n"
    path.write_text(content, encoding="utf-8")
    removed = uninstall(path)
    assert removed == 0
    assert path.read_text(encoding="utf-8") == content  # file untouched


def test_uninstall_refuses_when_hooks_is_not_an_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": ["not", "an", "object"]}))
    with pytest.raises(ValueError, match="hooks"):
        uninstall(path)


def test_write_is_atomic_and_preserves_original_on_failure(tmp_path, monkeypatch):
    # Editing the user's settings.json must be atomic: if the rename fails, the
    # original file is left intact and no stale .tmp is leaked.
    path = tmp_path / "settings.json"
    original = json.dumps({"model": "opus"}) + "\n"
    path.write_text(original, encoding="utf-8")

    def boom(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)

    with pytest.raises(OSError):
        install(path)

    assert path.read_text(encoding="utf-8") == original  # original untouched
    assert not (tmp_path / "settings.tmp").exists()  # no leaked temp


def test_load_does_not_propagate_oserror_from_read_text(tmp_path, monkeypatch):
    # settings.py:33 — path.read_text() can raise OSError (e.g. permission denied).
    # The guard must catch it and surface a clean ValueError, not a raw OSError.
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")

    _real_read_text = Path.read_text

    def raise_oserror(self, *args, **kwargs):
        if self == path:
            raise OSError("permission denied")
        return _real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raise_oserror)

    with pytest.raises(ValueError):
        install(path)


def test_settings_path_helpers_and_absent_file_uninstall(tmp_path):
    from pathlib import Path

    from looptight.settings import project_settings_path, uninstall, user_settings_path

    assert user_settings_path() == Path.home() / ".claude" / "settings.json"
    assert project_settings_path(tmp_path) == tmp_path / ".claude" / "settings.json"
    # Uninstalling from a non-existent settings file removes nothing and does not raise.
    assert uninstall(tmp_path / "missing.json") == 0
