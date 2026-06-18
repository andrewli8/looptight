# Checkpoint Failure Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a failed Git snapshot command from being reported as a valid restore point.

**Architecture:** Keep `Checkpointer` and its Git seam unchanged. Tighten `snapshot()` so it falls back to `HEAD` only after a successful, empty `git stash create`, and records a SHA only when the corresponding Git command succeeded.

**Tech Stack:** Python 3.11+, stdlib `subprocess`, pytest.

## Global Constraints

- Use TDD: add the regression test before changing implementation.
- Add no dependencies.
- Preserve the read-only/non-mutating behavior of `snapshot()`.
- Run `uv run pytest -q` and `uv run ruff check` before commit.
- Commit and push the coherent verified change directly to `main`.

---

### Task 1: Reject failed snapshot commands

**Files:**
- Modify: `tests/test_checkpoint.py`
- Modify: `src/looptight/checkpoint.py:44`

**Interfaces:**
- Consumes: `_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str>`
- Produces: `Checkpointer.snapshot() -> str | None`, returning `None` when `stash create` or the clean-tree `rev-parse HEAD` fallback fails.

- [ ] **Step 1: Add regression tests for both Git failure paths**

Add imports for `subprocess` (already present) and the module seam:

```python
import looptight.checkpoint as checkpoint_module
```

Append these tests:

```python
def test_snapshot_returns_none_when_stash_create_fails(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    calls = []

    def failing_git(args, cwd):
        calls.append(args)
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="failed")

    monkeypatch.setattr(checkpoint_module, "_git", failing_git)

    assert cp.snapshot() is None
    assert cp.snapshots == []
    assert calls == [["stash", "create", "looptight checkpoint"]]


def test_clean_snapshot_returns_none_when_head_lookup_fails(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    responses = iter(
        [
            subprocess.CompletedProcess(["git", "stash"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["git", "rev-parse"], 1, stdout="", stderr="failed"),
        ]
    )
    monkeypatch.setattr(checkpoint_module, "_git", lambda args, cwd: next(responses))

    assert cp.snapshot() is None
    assert cp.snapshots == []
```

- [ ] **Step 2: Run the focused tests and confirm the regression fails**

Run: `uv run pytest tests/test_checkpoint.py -q`

Expected: the stash-failure test fails because the implementation incorrectly calls `rev-parse HEAD` after `stash create` returns nonzero.

- [ ] **Step 3: Make snapshot success depend on Git exit status**

Replace the command-handling body of `snapshot()` with:

```python
        created = _git(["stash", "create", "looptight checkpoint"], self.cwd)
        if created.returncode != 0:
            return None

        sha = created.stdout.strip()
        if not sha:
            head = _git(["rev-parse", "HEAD"], self.cwd)
            if head.returncode != 0:
                return None
            sha = head.stdout.strip()

        if not sha:
            return None
        self.snapshots.append(sha)
        return sha
```

- [ ] **Step 4: Run focused and full verification**

Run: `uv run pytest tests/test_checkpoint.py -q`

Expected: all checkpoint tests pass.

Run: `uv run pytest -q && uv run ruff check`

Expected: the suite passes (with only the existing opt-in e2e skip) and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit and push**

```bash
git add tests/test_checkpoint.py src/looptight/checkpoint.py
git commit -m "fix: reject failed git checkpoints"
git push origin main
```
