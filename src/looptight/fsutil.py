"""Small filesystem helpers shared across modules.

``atomic_write_text`` is the one invariant several state writers depend on
(goal, ui, settings, trajectory, integration): a partial or interrupted write
must never corrupt the file it replaces. One implementation so that guarantee is
defined and tested in a single place rather than re-derived per module.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically.

    Write a temp sibling, then ``os.replace`` it into place; if either step
    fails, remove the temp and re-raise so a half-written file never lands on the
    target. The parent directory is created if missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)  # never leave a stale temp behind
        raise
