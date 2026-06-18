"""Autodetection of agent and verify command (A2)."""

from __future__ import annotations

import shutil

from looptight import detect


def test_detect_verify_python_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect.detect_verify(tmp_path) == "pytest -q"


def test_detect_verify_go(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    assert detect.detect_verify(tmp_path) == "go test ./..."


def test_detect_verify_npm_only_with_test_script(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    assert detect.detect_verify(tmp_path) == "npm test"


def test_detect_verify_npm_without_test_script_falls_through(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}')
    assert detect.detect_verify(tmp_path) is None


def test_detect_verify_setup_cfg(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = x\n")
    assert detect.detect_verify(tmp_path) == "pytest -q"


def test_detect_verify_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    assert detect.detect_verify(tmp_path) == "cargo test"


def test_detect_verify_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    assert detect.detect_verify(tmp_path) == "make test"


def test_detect_verify_none(tmp_path):
    assert detect.detect_verify(tmp_path) is None


def test_detect_agent_prefers_known_order(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    assert detect.detect_agent() == "codex"


def test_detect_agent_honors_preferred(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert detect.detect_agent("opencode") == "opencode"


def test_detect_agent_none_when_absent(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert detect.detect_agent() is None
