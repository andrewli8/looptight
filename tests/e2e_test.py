"""Opt-in end-to-end eval — the one test that proves the product claim.

This is the real thing: a deliberately-broken repo, a real coding agent, and the
assertion that looptight loops it to green. It needs an installed agent and live
auth, costs money, and is slow, so it is NOT part of the default test run.

Run it manually before a release:

    LOOPTIGHT_E2E=1 pytest tests/e2e_test.py -s

Everything in regular CI stays offline and sub-second.
"""

from __future__ import annotations

import os

import pytest

from looptight.cli import main
from looptight.detect import detect_agent

pytestmark = pytest.mark.skipif(
    not os.environ.get("LOOPTIGHT_E2E"),
    reason="real-agent eval; set LOOPTIGHT_E2E=1 to run",
)

# A tiny repo with one obvious bug (subtraction where addition is meant) and a
# test that pins the intended behaviour. The agent has to fix mathx.py.
_BUG = "def add(a, b):\n    return a - b  # bug: should add\n"
_TEST = "from mathx import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def test_loops_a_broken_repo_to_green(tmp_path, monkeypatch):
    agent = detect_agent()
    if agent is None:
        pytest.skip("no coding agent on PATH")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "e2e"\nversion = "0"\n')
    (tmp_path / "mathx.py").write_text(_BUG)
    (tmp_path / "test_mathx.py").write_text(_TEST)
    monkeypatch.chdir(tmp_path)

    # Low caps keep the eval cheap and bounded.
    exit_code = main(
        ["run", "--headless", "make the failing test pass", "--max-iterations", "4"]
    )

    assert exit_code == 0, "looptight did not reach a passing verify"
