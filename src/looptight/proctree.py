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
