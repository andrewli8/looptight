"""Kill a spawned process and its descendants, cross-platform.

Both the verifier (``verify.py``) and the agent runner (``adapters/base.py``)
spawn a child in its own process group/session and must tear down the *whole*
tree on timeout — a shell that forked workers would otherwise leave them
orphaned. One implementation so the two cannot drift (they had, in the handling
of an already-dead process).
"""

from __future__ import annotations

import os
import signal
import subprocess


def new_process_group_kwargs() -> dict[str, object]:
    """``Popen`` kwargs that place the child in its own process group/session, so
    :func:`stop_process_tree` can later tear down the whole tree. The spawn half
    of the pair — keep them together so a child is never spawned ungrouped."""
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


def stop_process_tree(process: subprocess.Popen) -> None:
    """Terminate ``process`` and its descendants. Best-effort and never raises:
    the caller is already on an error/timeout path and must stay on its feet."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return  # already gone — nothing to kill
        except OSError:
            pass
    elif os.name == "nt":
        try:
            stopped = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
            if stopped.returncode == 0:
                return
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass
