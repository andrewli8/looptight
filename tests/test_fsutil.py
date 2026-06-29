"""Direct unit tests for fsutil.atomic_write_text.

The module docstring promises "defined and tested in a single place rather
than re-derived per module", but the only coverage had been indirect, via
test_goal, test_ui, test_settings, test_integration, and test_trajectory.
These tests own the contract at the source.
"""

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
    tmp_file = target.with_suffix(".tmp")

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


def test_atomic_write_text_cleans_up_when_write_text_fails(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "out.txt"
    tmp_file = target.with_suffix(".tmp")

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
