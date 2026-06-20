from __future__ import annotations

from io import StringIO

from looptight.console import Console


def test_console_strips_known_style_tags_but_preserves_data_brackets():
    output = StringIO()

    Console(file=output).print("[bold]PASS[/bold] [task-123]")

    assert output.getvalue() == "PASS [task-123]\n"
