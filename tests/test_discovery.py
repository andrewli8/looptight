"""Tests for src/looptight/discovery.py."""

from __future__ import annotations

from looptight.discovery import _all_js_files, _all_py_files, _js_test_files


def test_all_py_files_skips_prune_dirs(tmp_path):
    prune = tmp_path / "node_modules"
    prune.mkdir()
    bad = prune / "bad.py"
    bad.write_text("x = 1\n")
    result = _all_py_files(tmp_path)
    assert bad not in result


def test_all_js_files_skips_prune_dirs(tmp_path):
    prune = tmp_path / "node_modules"
    prune.mkdir()
    bad = prune / "bad.js"
    bad.write_text("const x = 1;\n")
    result = _all_js_files(tmp_path)
    assert bad not in result


def test_js_test_files_skips_prune_dirs(tmp_path):
    prune = tmp_path / "node_modules"
    prune.mkdir()
    bad = prune / "bad.test.js"
    bad.write_text("it('x', () => {});\n")
    result = _js_test_files(tmp_path)
    assert bad not in result
