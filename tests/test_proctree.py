"""The shared cross-platform process-tree killer."""

from __future__ import annotations

import subprocess
import sys

import pytest

from looptight.proctree import new_process_group_kwargs, stop_process_tree


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
    # Returns None (its void contract) rather than raising on an already-reaped
    # process; reaching the assertion proves no exception was raised.
    assert stop_process_tree(process) is None
    assert process.poll() is not None  # still reaped, not resurrected


def test_stop_process_tree_falls_back_to_kill_when_killpg_raises_oserror(monkeypatch):
    # A killpg failure that is not ProcessLookupError (e.g. EPERM) must fall
    # through to process.kill() rather than give up — only the already-reaped
    # ProcessLookupError path returns early; a generic OSError should still kill.
    class FakeProcess:
        pid = 456
        killed = False

        def kill(self):
            self.killed = True

    def raise_oserror(pid, sig):
        raise OSError("operation not permitted")

    monkeypatch.setattr("looptight.proctree.os.name", "posix")
    monkeypatch.setattr("looptight.proctree.os.killpg", raise_oserror)
    process = FakeProcess()
    assert stop_process_tree(process) is None  # type: ignore[arg-type]
    assert process.killed  # fell through to the final process.kill()


def test_stop_process_tree_swallows_a_final_kill_oserror(monkeypatch):
    # Best-effort teardown never raises: if killpg falls through AND the final
    # process.kill() also raises OSError (an already-reaped race), it is swallowed.
    class FakeProcess:
        pid = 789

        def kill(self):
            raise OSError("already gone")

    def raise_oserror(pid, sig):
        raise OSError("operation not permitted")

    monkeypatch.setattr("looptight.proctree.os.name", "posix")
    monkeypatch.setattr("looptight.proctree.os.killpg", raise_oserror)
    assert stop_process_tree(FakeProcess()) is None  # type: ignore[arg-type]


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


def test_new_process_group_kwargs_fallback_for_unknown_os(monkeypatch):
    monkeypatch.setattr("looptight.proctree.os.name", "other")
    assert new_process_group_kwargs() == {}


def test_stop_process_tree_taskkill_oserror_falls_through_to_kill(monkeypatch):
    class FakeProcess:
        pid = 789
        killed = False

        def kill(self):
            self.killed = True

    def raise_oserror(command, **kwargs):
        raise OSError("no taskkill")

    monkeypatch.setattr("looptight.proctree.os.name", "nt")
    monkeypatch.setattr("looptight.proctree.subprocess.run", raise_oserror)
    process = FakeProcess()
    stop_process_tree(process)  # type: ignore[arg-type]
    assert process.killed  # taskkill failed with OSError; fell through to process.kill()


