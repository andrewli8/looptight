"""Direct unit tests for fsutil.atomic_write_text.

The module docstring promises "defined and tested in a single place rather
than re-derived per module", but the only coverage had been indirect, via
test_goal, test_ui, test_settings, test_integration, and test_trajectory.
These tests own the contract at the source.
"""

import os

from looptight.fsutil import atomic_write_text


def test_atomic_write_text_happy_path(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_atomic_write_text_creates_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "out.txt"
    atomic_write_text(target, "world\n")
    assert target.read_text(encoding="utf-8") == "world\n"


def test_atomic_write_text_removes_tmp_and_reraises_on_os_replace_failure(
    tmp_path, monkeypatch
):
    target = tmp_path / "out.txt"
    tmp_file = target.parent / (target.name + f".{os.getpid()}.tmp")

    def boom(src, dst):
        raise OSError("injected failure")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)

    try:
        atomic_write_text(target, "data\n")
    except OSError:
        pass
    else:
        raise AssertionError("OSError should have been re-raised")

    assert not tmp_file.exists(), "stale .tmp must be removed on failure"
    assert not target.exists(), "target must not exist after a failed write"


def test_atomic_write_text_tmp_target_temp_differs_from_target(tmp_path, monkeypatch):
    """When target ends in .tmp, the temp file must be distinct from the target."""
    target = tmp_path / "state.tmp"
    temps_seen = []
    real_replace = os.replace

    def capture_replace(src, dst):
        temps_seen.append(src)
        return real_replace(src, dst)

    monkeypatch.setattr("looptight.fsutil.os.replace", capture_replace)
    atomic_write_text(target, "content\n")
    assert len(temps_seen) == 1
    assert str(temps_seen[0]) != str(target), "temp file must differ from target"


def test_atomic_write_text_cleans_up_when_write_text_fails(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "out.txt"
    tmp_file = target.parent / (target.name + f".{os.getpid()}.tmp")

    def fail_write_text(self, *args, **kwargs):
        raise OSError("injected write_text failure")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    try:
        atomic_write_text(target, "data\n")
    except OSError:
        pass
    else:
        raise AssertionError("OSError should have been re-raised")

    assert not tmp_file.exists(), "missing_ok=True keeps cleanup safe when .tmp was never created"
    assert not target.exists(), "target must not exist after a failed write"
