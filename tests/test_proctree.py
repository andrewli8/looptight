"""The shared cross-platform process-tree killer."""

from __future__ import annotations

import subprocess
import sys

import pytest

from looptight.proctree import stop_process_tree


@pytest.mark.skipif(sys.platform == "win32", reason="posix process-group semantics")
def test_stop_process_tree_kills_a_running_process():
    process = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        stop_process_tree(process)
        # Terminated promptly: wait returns a code rather than raising TimeoutExpired.
        assert process.wait(timeout=5) is not None
    finally:
        if process.poll() is None:
            process.kill()


def test_stop_process_tree_tolerates_an_already_finished_process():
    process = subprocess.Popen(["true"] if sys.platform != "win32" else ["cmd", "/c", "exit"])
    process.wait()
    stop_process_tree(process)  # must not raise on an already-reaped process


def test_stop_process_tree_uses_taskkill_when_os_is_nt(monkeypatch):
    # The Windows branch shells out to taskkill /F /T; exercise it on any OS by
    # faking os.name so the nt path is covered, not only on a Windows runner.
    calls = []

    class FakeProcess:
        pid = 123
        killed = False

        def kill(self):
            self.killed = True

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("looptight.proctree.os.name", "nt")
    monkeypatch.setattr("looptight.proctree.subprocess.run", fake_run)
    process = FakeProcess()
    stop_process_tree(process)  # type: ignore[arg-type]
    assert calls == [["taskkill", "/F", "/T", "/PID", "123"]]
    assert not process.killed  # taskkill succeeded, so the fallback kill is unused
