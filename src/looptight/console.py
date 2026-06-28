"""Minimal terminal output compatible with looptight's former Rich usage."""

from __future__ import annotations

import re
import sys
from typing import TextIO

_MARKUP = re.compile(r"\[/?(?:bold|red|green|yellow|cyan|dim)(?: [^\]]+)?\]")


class Console:
    """Small print facade; styling tags degrade cleanly to plain text."""

    def __init__(self, *, file: TextIO | None = None, **_ignored: object) -> None:
        self.file = file

    def print(
        self,
        *objects: object,
        sep: str = " ",
        end: str = "\n",
        style: str | None = None,
        **_ignored: object,
    ) -> None:
        del style
        text = _MARKUP.sub("", sep.join(str(value) for value in objects))
        print(text, end=end, file=self.file or sys.stdout)

    def write(self, text: object, *, end: str = "\n") -> None:
        """Print already-rendered content verbatim — no markup stripping.

        Use for content that is not a markup template (e.g. the status panel), so user strings
        it carries (a worker error or goal containing ``[red]``) are not mistaken for style tags.
        """
        print(str(text), end=end, file=self.file or sys.stdout)
