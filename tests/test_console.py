from __future__ import annotations

from io import StringIO

from looptight.console import Console


def test_console_strips_known_style_tags_but_preserves_data_brackets():
    output = StringIO()

    Console(file=output).print("[bold]PASS[/bold] [task-123]")

    assert output.getvalue() == "PASS [task-123]\n"


def test_console_joins_multiple_objects_with_sep():
    output = StringIO()

    Console(file=output).print("a", "b", "c", sep=", ")

    assert output.getvalue() == "a, b, c\n"


def test_console_respects_custom_end():
    output = StringIO()

    Console(file=output).print("x", end="")

    assert output.getvalue() == "x"
