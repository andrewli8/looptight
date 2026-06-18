# Continuous Improve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `looptight improve` command that continuously discovers, verifies, commits, and optionally pushes improvements until interrupted, provider failure, or an optional session spend threshold.

**Architecture:** First make adapter failures observable in `RunResult`. Then add a focused `improve.py` orchestration module with injected run/proposal/Git collaborators. Finally wire the command into the CLI and document its safety and budget semantics.

**Tech Stack:** Python 3.11+, frozen dataclasses, argparse, subprocess, pytest, Ruff.

## Global Constraints

- Follow TDD for every behavior change.
- Add no runtime dependency.
- Keep ordinary `looptight run` finite and backward compatible.
- Require a clean Git tree before autonomous work.
- Commit only verified diffs; push only with `--push`.
- Run `uv run pytest -q` and `uv run ruff check` before each commit.

---

### Task 1: Treat adapter failure as loop failure

**Files:**
- Modify: `src/looptight/types.py`
- Modify: `src/looptight/loop.py`
- Modify: `src/looptight/adapters/base.py`
- Modify: `src/looptight/adapters/claude.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Produce: `RunResult.error: str | None`
- Produce: `Adapter.reports_cost_usd: bool` (`True` only for Claude)
- Preserve: `run_loop(...) -> RunResult`

- [ ] Add a configurable failed-iteration mode to `FakeAdapter`, then add supply and delegate tests where verification would pass but `IterationResult.ok` is false. Assert `StopReason.ERROR`, `passed is False`, and error text is preserved.
- [ ] Run the focused tests and confirm both fail because verification currently masks adapter failure.
- [ ] Add `error` to `RunResult`; in both loop paths, return/stop with `ERROR` before verification when the adapter result is not okay.
- [ ] Add `reports_cost_usd = False` to `Adapter` and `True` to `ClaudeAdapter`.
- [ ] Run `uv run pytest tests/test_loop.py tests/test_adapters.py -q`, then the full test and Ruff gates.
- [ ] Commit as `fix: propagate coding agent failures`.

### Task 2: Build the continuous orchestration engine

**Files:**
- Create: `src/looptight/improve.py`
- Create: `tests/test_improve.py`

**Interfaces:**
- Produce: `ImproveStopReason` enum with `SESSION_BUDGET`, `PROVIDER_STOP`, `INTERRUPTED`, and `GIT_ERROR`.
- Produce: frozen `ImproveResult(stop_reason, tasks_attempted, commits, total_cost_usd, error)`.
- Produce: `run_improve(workdir, run_task, *, propose_fn=propose, session_budget_usd=None, push=False, git_fn=_git, on_event=None) -> ImproveResult`.
- `run_task(goal: str, checkpointer: Checkpointer) -> RunResult`.

- [ ] Write tests using injected fake proposal, task-run, and Git functions for: dirty-tree refusal; one grounded candidate followed by an audit goal; verified-diff commit; `--push` behavior; verified no-op continuation; cumulative session spend stop; provider error stop; failed-task rollback and continuation; Git command failure; and `KeyboardInterrupt`.
- [ ] Run `uv run pytest tests/test_improve.py -q` and confirm import/behavior failures.
- [ ] Implement the minimal engine. Candidate keys are `(location, normalized title)` and are attempted once per session. Audit prompts include the audit number and recent outcomes. Commit subjects are sanitized, bounded, and prefixed `chore:`. Rollback uses the task's clean checkpoint, `git clean -fd`, and a final clean-tree check.
- [ ] Run focused tests, then full pytest and Ruff gates.
- [ ] Commit as `feat: add continuous improvement engine`.

### Task 3: Wire the CLI and user documentation

**Files:**
- Modify: `src/looptight/cli.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/STATUS.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produce command: `looptight improve [--agent NAME] [--verify CMD] [--max-iterations N] [--patience N] [--budget USD] [--no-reflect] [--native] [--push]`.
- `--budget` on `improve` is cumulative session spend; config `budget_usd` remains the per-task threshold.

- [ ] Add parser tests for `improve`, optional session budget, and `--push`; add command tests with injected `run_improve` for exit-code mapping and cost-unavailable warning.
- [ ] Run focused CLI tests and confirm failures because the command is absent.
- [ ] Wire `cmd_improve`: resolve agent and verify like `cmd_run`, preserve config per-task budget, build a `run_loop` closure, render concise events, warn when a requested session budget cannot be measured, and map interrupt/provider/Git stops to conventional exit codes.
- [ ] Document examples, continuous terminal conditions, clean-tree requirement, automatic local commits, opt-in push, per-task versus session budget, and unknown-cost adapter behavior. Add the command to architecture/status without duplicating run logs.
- [ ] Run focused tests, full pytest, Ruff, and `uv run looptight improve --help`.
- [ ] Commit as `feat: add continuous improve command` and push all commits to `origin/main`.

### Task 4: Dogfood the command

**Files:**
- Modify only files selected by `looptight improve` from concrete repository evidence.

**Interfaces:**
- Consume: `uv run looptight improve --push --budget <session-usd>`.

- [ ] Start from a clean tree and run the new command with `--push` and a small explicit session budget.
- [ ] Confirm at least one full discovery/run/verify/commit/push cycle or a truthful provider stop.
- [ ] Interrupt with Ctrl-C if the command remains active after sufficient verification; confirm it exits without corrupting the tree.
- [ ] Run final pytest, Ruff, Git status, and remote synchronization checks.
