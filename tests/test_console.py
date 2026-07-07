from __future__ import annotations

from io import StringIO

from looptight.console import Console


def test_console_strips_known_style_tags_but_preserves_data_brackets():
    output = StringIO()

    Console(file=output).print("[bold]PASS[/bold] [task-123]")

    assert output.getvalue() == "PASS [task-123]\n"


def test_console_write_prints_rendered_content_verbatim():
    # write() is for already-rendered content (e.g. the status panel): it must NOT strip style
    # tokens, so a worker error or goal containing "[red]" survives instead of being eaten.
    output = StringIO()

    Console(file=output).write("  #1 failed t1  [tool said [red] then died]")

    assert output.getvalue() == "  #1 failed t1  [tool said [red] then died]\n"


def test_console_joins_multiple_objects_with_sep():
    output = StringIO()

    Console(file=output).print("a", "b", "c", sep=", ")

    assert output.getvalue() == "a, b, c\n"


def test_console_respects_custom_end():
    output = StringIO()

    Console(file=output).print("x", end="")

    assert output.getvalue() == "x"


def test_console_write_respects_custom_end():
    output = StringIO()

    Console(file=output).write("hello", end="")

    assert output.getvalue() == "hello"
