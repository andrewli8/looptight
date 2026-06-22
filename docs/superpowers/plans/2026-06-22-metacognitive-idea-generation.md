# Metacognitive Idea Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make looptight's idea generation learn from outcomes: record each idea's real result, build a self-model, and feed it back so the loop avoids dead ideas and leans toward high-yield work.

**Architecture:** A monitor -> self-model -> control loop. The verify-gated integrator records `landed` as a commit trailer on the existing integration commit (shared via git history, verified structurally by scanning from the target ref) and records `failed` in the repo-private coordinator database. A self-model unions verified-landed counts with local failed counts, keyed by a separate lossy idea identity. Control suppresses recently-failed ideas on a bounded cooldown, reweights ranking by category yield under the existing source weights, and injects a token-bounded experience summary into the planning prompt.

**Tech Stack:** Python 3.11+, standard library only (`json`, `hashlib`, `sqlite3`, `subprocess`), pytest, ruff. No new runtime dependencies.

## Global Constraints

- No new runtime dependencies. Standard library only (`json`, `hashlib`).
- `verify` is the only thing that authorizes a commit; outcomes derive from verify results and merge facts, never agent self-report.
- The self-model is advisory: missing, empty, or unreadable experience state must degrade to today's exact behavior (discovery, ranking, and prompt unchanged).
- Immutable data: build new objects, never mutate `Candidate` or task dicts in place.
- Files stay small and single-responsibility; commit after each task with both pytest and ruff green.
- `landed` is the only outcome that crosses a repository boundary; `failed` is local-only.

**Execution batches:** Tasks 1-6 build the data foundation (identity, storage, self-model) with no change to generation behavior. Tasks 7-11 wire the control feedback and update docs. Each task is independently testable; the two batches are natural review checkpoints.

---

### Task 1: Lossy idea identity

**Files:**
- Create: `src/looptight/idea_identity.py`
- Test: `tests/test_idea_identity.py`

**Interfaces:**
- Consumes: `discovery.Candidate` (fields `title`, `source`, `location`, ...).
- Produces: `idea_id(candidate: Candidate) -> str` — a stable, deliberately lossy 12-char hex identity, distinct from the line-precise claim fingerprint in `tasks.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_idea_identity.py
from looptight.discovery import Candidate
from looptight.idea_identity import idea_id


def _c(source, location, title):
    return Candidate(title=title, source=source, location=location,
                     suggested_verify=None, score=0.0, detail="d", acceptance="a")


def test_lint_identity_ignores_line_and_message():
    a = _c("lint", "src/looptight/foo.py:10", "fix E501: line too long")
    b = _c("lint", "src/looptight/foo.py:42", "fix E501: line too long (88 > 79)")
    assert idea_id(a) == idea_id(b)  # same file + rule => same idea


def test_lint_identity_differs_by_rule():
    a = _c("lint", "src/looptight/foo.py:10", "fix E501: line too long")
    b = _c("lint", "src/looptight/foo.py:10", "fix F401: unused import")
    assert idea_id(a) != idea_id(b)


def test_todo_identity_ignores_line_keeps_text():
    a = _c("todo", "src/looptight/foo.py:10", "handle the empty case")
    b = _c("todo", "src/looptight/foo.py:99", "handle the empty case")
    assert idea_id(a) == idea_id(b)


def test_status_next_identity_uses_normalized_title():
    a = _c("status-next", "docs/STATUS.md:12", "Cover  the  retry path")
    b = _c("task-file", "docs/STATUS.md:5", "cover the retry path")
    # title normalization matches; source class (curated) is shared
    assert idea_id(a) == idea_id(b)


def test_identity_is_twelve_char_hex():
    v = idea_id(_c("lint", "src/looptight/foo.py:10", "fix E501: x"))
    assert len(v) == 12 and all(ch in "0123456789abcdef" for ch in v)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_idea_identity.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'looptight.idea_identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/looptight/idea_identity.py
"""A stable, deliberately lossy identity for an idea (a discovery candidate).

Distinct from the line-precise claim fingerprint in tasks.py. Outcomes are keyed
on this so that the same idea proposed again is recognized even when a line moves
or a tool's message is reworded, while different ideas stay distinct. Both the
write path (recording outcomes) and the read path (the self-model) compute it
here so the two cannot drift.
"""

from __future__ import annotations

import hashlib
import re

from .discovery import Candidate

_LINT_RULE_RE = re.compile(r"\bfix\s+([A-Z]+[0-9]+)\b", re.IGNORECASE)
_CURATED = {"status-next", "task-file"}


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _path(location: str | None) -> str:
    if not location:
        return ""
    return location.rsplit(":", 1)[0]  # drop a trailing :line if present


def _identity_tuple(candidate: Candidate) -> tuple[str, ...]:
    source, location, title = candidate.source, candidate.location, candidate.title
    if source == "lint":
        match = _LINT_RULE_RE.search(title)
        rule = match.group(1).upper() if match else _normalized(title)
        return ("lint", _path(location), rule)
    if source == "todo":
        return ("todo", _path(location), _normalized(title))
    if source == "skipped-test":
        return ("skipped-test", _normalized(title))
    if source in _CURATED:
        return ("curated", _normalized(title))
    return (source, _path(location), _normalized(title))


def idea_id(candidate: Candidate) -> str:
    """Return the lossy idea identity for a candidate (12-char hex)."""
    joined = "\0".join(_identity_tuple(candidate))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_idea_identity.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/idea_identity.py tests/test_idea_identity.py
git commit -m "feat: lossy per-source idea identity for outcome keying"
```

---

### Task 2: Thread idea_id into task payloads

**Files:**
- Modify: `src/looptight/tasks.py` (the task-dict construction near line 109)
- Test: `tests/test_tasks.py` (add a test; create if absent)

**Interfaces:**
- Consumes: `idea_identity.idea_id`, `discovery.Candidate`.
- Produces: every task dict gains an `"idea_id"` key. It is carried verbatim into `coordinator.tasks.payload` and surfaced on `Lease.payload`, so the integrator can read it later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tasks.py  (append; imports at top if new file)
from pathlib import Path

from looptight.discovery import Candidate
from looptight.tasks import build_tasks  # see Step 3 note


def test_build_tasks_attaches_idea_id(monkeypatch):
    cand = Candidate(title="fix E501: line too long", source="lint",
                     location="src/looptight/foo.py:10", suggested_verify=None,
                     score=60.0, detail="line too long", acceptance="ruff clean")

    def fake_propose(workdir, limit=0):
        return [cand]

    tasks = build_tasks(Path("."), propose_fn=fake_propose)
    assert tasks and tasks[0]["idea_id"]
    # stable: same candidate on a different line yields the same idea_id
    from looptight.idea_identity import idea_id
    assert tasks[0]["idea_id"] == idea_id(cand)
```

Note: if the task-building function in `tasks.py` is not named `build_tasks` or does not accept `propose_fn`, adjust the test import and call to the actual function discovered while implementing. The behavior asserted (each task dict has a correct `idea_id`) is what matters.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tasks.py -q`
Expected: FAIL with `KeyError: 'idea_id'`

- [ ] **Step 3: Write minimal implementation**

In `src/looptight/tasks.py`, import the identity and add the key to the task dict built in the loop (the block that currently sets `"id"`, `"source"`, `"location"`, `"goal"`, `"evidence"`, `"acceptance"`, `"suggested_verify"`):

```python
from .idea_identity import idea_id  # add to imports

# inside the candidate loop, in the appended dict:
        tasks.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:12],
                "idea_id": idea_id(candidate),
                "source": candidate.source,
                "location": candidate.location,
                "goal": _grounded_goal(summary, candidate.location),
                "evidence": evidence,
                "acceptance": candidate.acceptance,
                "suggested_verify": candidate.suggested_verify,
            }
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tasks.py tests/test_cli.py -q`
Expected: PASS (the new test plus unchanged existing task/next tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/tasks.py tests/test_tasks.py
git commit -m "feat: carry idea_id in task payloads so outcomes can be keyed"
```

---

### Task 3: Coordinator experience table (failed + cooldown)

**Files:**
- Modify: `src/looptight/coordinator.py` (schema, `SCHEMA_VERSION`, `_initialize_schema`, new methods)
- Test: `tests/test_coordinator.py` (append)

**Interfaces:**
- Produces on `Coordinator`:
  - `record_failure(idea_id: str, category: str, *, now: float | None = None) -> None`
  - `recent_failures(*, window_s: float, now: float | None = None) -> dict[str, int]` — `{idea_id: failure_count}` for ideas whose most recent failure is within `window_s`.
  - `failure_counts() -> dict[str, int]` — total failures per `category` (for yield stats).
- Schema bumps to version 2 with a v1->v2 migration that adds the `experience` table.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coordinator.py  (append)
from looptight.coordinator import Coordinator


def test_experience_records_failures_and_cooldown(tmp_path, _git_repo):  # reuse repo fixture
    coord = Coordinator.open(tmp_path)
    assert coord is not None
    coord.record_failure("idea-a", "lint", now=1000.0)
    coord.record_failure("idea-a", "lint", now=1100.0)
    coord.record_failure("idea-b", "todo", now=1100.0)

    # within window: both recent; idea-a counted twice
    recent = coord.recent_failures(window_s=500.0, now=1200.0)
    assert recent == {"idea-a": 2, "idea-b": 1}

    # outside window: idea-a's last failure (1100) is older than now-50
    assert coord.recent_failures(window_s=50.0, now=1200.0) == {}

    assert coord.failure_counts() == {"lint": 2, "todo": 1}
    coord.close()
```

If `tests/test_coordinator.py` has no repo fixture, construct a git repo inline as the other coordinator tests do (look at the top of that file) and drop the `_git_repo` parameter.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coordinator.py -k experience -q`
Expected: FAIL with `AttributeError: 'Coordinator' object has no attribute 'record_failure'`

- [ ] **Step 3: Write minimal implementation**

In `coordinator.py`, bump the version and add the table to the schema script:

```python
SCHEMA_VERSION = 2
```

Add this table inside `_SCHEMA` (before `PRAGMA user_version`), and set the pragma to 2:

```sql
CREATE TABLE IF NOT EXISTS experience (
    id INTEGER PRIMARY KEY,
    idea_id TEXT NOT NULL,
    category TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('failed')),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS experience_idea ON experience(idea_id);
PRAGMA user_version = 2;
```

In `_initialize_schema`, add a v1->v2 migration branch before the `version != SCHEMA_VERSION` raise:

```python
            if version == 0:
                connection.executescript(_SCHEMA)
            elif version == 1:
                connection.executescript(
                    """BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS experience (
                        id INTEGER PRIMARY KEY,
                        idea_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        outcome TEXT NOT NULL CHECK (outcome IN ('failed')),
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS experience_idea ON experience(idea_id);
                    PRAGMA user_version = 2;
                    COMMIT;"""
                )
            elif version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported coordinator schema {version}; expected {SCHEMA_VERSION}"
                )
```

Add the methods to the `Coordinator` class:

```python
    def record_failure(self, idea_id: str, category: str, *, now: float | None = None) -> None:
        """Record one local 'failed' outcome for an idea. Never pushed."""
        timestamp = time.time() if now is None else now
        with self.transaction(immediate=True):
            self.connection.execute(
                "INSERT INTO experience(idea_id, category, outcome, created_at) "
                "VALUES (?, ?, 'failed', ?)",
                (idea_id, category, timestamp),
            )

    def recent_failures(self, *, window_s: float, now: float | None = None) -> dict[str, int]:
        """Failure counts per idea whose most recent failure is within window_s."""
        timestamp = time.time() if now is None else now
        cutoff = timestamp - window_s
        rows = self.connection.execute(
            """SELECT idea_id, COUNT(*), MAX(created_at) FROM experience
               WHERE outcome = 'failed' GROUP BY idea_id"""
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows if float(r[2]) >= cutoff}

    def failure_counts(self) -> dict[str, int]:
        """Total failures per category (for yield statistics)."""
        rows = self.connection.execute(
            "SELECT category, COUNT(*) FROM experience WHERE outcome = 'failed' GROUP BY category"
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_coordinator.py -q`
Expected: PASS (new experience test plus all existing coordinator tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/coordinator.py tests/test_coordinator.py
git commit -m "feat: coordinator experience table for local failed outcomes + cooldown reads"
```

---

### Task 4: Record landed (trailer) and failed (DB) in the integrator

**Files:**
- Modify: `src/looptight/integration_queue.py` (`Integrator._run`, `Integrator._apply`)
- Test: `tests/test_integration_queue.py` (append)

**Interfaces:**
- Consumes: `Lease.payload["idea_id"]`, `coordinator.record_failure`.
- Produces: a `Looptight-Outcome: <idea_id> landed` trailer on the integration commit (the carrying commit's sha is the result sha); a `record_failure(idea_id, category)` call on a `failed` or `conflict` integration. `category` is the task's `source`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integration_queue.py  (append; reuse this file's existing repo/coordinator helpers)
def test_landed_writes_outcome_trailer(tmp_path):
    # Build on the existing helper that runs a successful integration. After a
    # 'complete' outcome, the carrying commit must hold the idea's outcome trailer.
    env = _make_integration_env(tmp_path, idea_id="idea-xyz")  # see note
    outcome = env.integrator.run_next(env.root, env.verify)
    assert outcome.status == "complete"
    body = _git(env.root, "log", env.target_ref, "-1", "--pretty=%B").stdout
    assert "Looptight-Outcome: idea-xyz landed" in body


def test_failed_integration_records_failure(tmp_path):
    env = _make_integration_env(tmp_path, idea_id="idea-bad", failing_verify=True)
    outcome = env.integrator.run_next(env.root, env.verify)
    assert outcome.status == "failed"
    assert env.coordinator.recent_failures(window_s=10_000.0) == {"idea-bad": 1}
```

Note: `tests/test_integration_queue.py` already constructs repos, coordinators, leases, and queued integrations. Reuse those existing helpers rather than `_make_integration_env`; the two assertions (trailer present on `complete`; `record_failure` called on `failed`) are the contract. Ensure the claimed task's payload includes `"idea_id"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_integration_queue.py -k "landed or failed_integration" -q`
Expected: FAIL (trailer absent / no failure recorded)

- [ ] **Step 3: Write minimal implementation**

In `_run`, after the lease fetch, derive the idea id from the lease payload and pass it to `_apply`:

```python
    def _run(self, record, root, verify):
        lease = self.coordinator.current_lease(record.task_id)
        if lease is None or lease.run_id != record.run_id or lease.generation != record.lease_generation:
            return self._finish(record, "superseded", error="lease superseded by a newer owner")
        if root is None or verify is None:
            raise ValueError("root and verify are required to integrate a non-superseded record")
        idea = str(lease.payload.get("idea_id") or "")
        category = str(lease.payload.get("source") or "")
        worktree, observed = prepare_integration_worktree(root, record.target_ref)
        self.coordinator.begin_integration(record.id, observed)
        return self._apply(record, root, verify, worktree, observed, idea, category)
```

Change `_apply`'s signature and body. Add `idea` and `category`, write the outcome trailer into the commit message on the success path, and record a failure on the `failed` and `conflict` paths:

```python
    def _apply(self, record, root, verify, worktree, observed, idea="", category=""):
        merged = _git(worktree, "merge", "--no-commit", "--no-ff", record.candidate_sha)
        if merged.returncode != 0:
            _git(worktree, "merge", "--abort")
            if idea:
                self.coordinator.record_failure(idea, category)
            return self._finish(record, "conflict", error=merged.stderr.strip() or "merge conflict", retained=worktree)
        verdict = run_verify(verify, worktree)
        if not verdict.passed:
            _git(worktree, "reset", "--hard", observed)
            if idea:
                self.coordinator.record_failure(idea, category)
            return self._finish(record, "failed", error=f"integration verify: {verdict.status}", retained=worktree)
        self._maybe_crash("after_merge")
        outcome_trailer = f"\nLooptight-Outcome: {idea} landed" if idea else ""
        message = (
            f"merge: looptight integration {record.id}\n\n"
            f"{_TRAILER_KEY}: {record.id}{outcome_trailer}"
        )
        committed = _git(worktree, "commit", "-m", message)
        if committed.returncode != 0:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(record, "failed", error=committed.stderr.strip() or "integration commit failed", retained=worktree)
        self._maybe_crash("after_commit")
        result_sha = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        updated = _git(root, "update-ref", record.target_ref, result_sha, observed)
        if updated.returncode != 0:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(
                record, "conflict",
                error=updated.stderr.strip() or "target advanced; integration superseded", retained=worktree,
            )
        self._maybe_crash("after_update_ref")
        outcome = self._finish(record, "complete", result_sha=result_sha)
        self._maybe_crash("after_db_update")
        return outcome
```

Update `_reconcile_one`'s `self._apply(record, root, verify, fresh_worktree, fresh_observed)` call to remain valid (it omits `idea`/`category`, which now default to `""`). To preserve the trailer on reconciled re-applies, fetch the lease there too:

```python
        lease = self.coordinator.current_lease(record.task_id)
        idea = str(lease.payload.get("idea_id") or "") if lease else ""
        category = str(lease.payload.get("source") or "") if lease else ""
        return self._apply(record, root, verify, fresh_worktree, fresh_observed, idea, category)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_integration_queue.py -q`
Expected: PASS (new tests plus all existing integration-queue tests, including crash/reconcile)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/integration_queue.py tests/test_integration_queue.py
git commit -m "feat: record landed (commit trailer) and failed (coordinator) at integration"
```

---

### Task 5: Self-model reader

**Files:**
- Create: `src/looptight/experience.py`
- Test: `tests/test_experience.py`

**Interfaces:**
- Consumes: git (`subprocess` via a local `_git`), `Coordinator.recent_failures`, `Coordinator.failure_counts`.
- Produces:
  - `landed_counts(root: Path, target_ref: str, *, limit: int = 500) -> dict[str, int]` — verified-landed counts per `idea_id`, by scanning trailers reachable from `target_ref`.
  - `@dataclass(frozen=True) Model` with `landed: dict[str, int]`, `failed: dict[str, int]` (recent, per idea), `category_landed: dict[str, int]`, `category_failed: dict[str, int]`.
  - `build_model(root, target_ref, coordinator, *, cooldown_s, now=None, limit=500) -> Model`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experience.py
import subprocess
from pathlib import Path

from looptight.experience import landed_counts


def _run(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def _repo(tmp_path):
    root = tmp_path
    _run(root, "init", "-q")
    _run(root, "config", "user.email", "t@t")
    _run(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x")
    _run(root, "add", ".")
    _run(root, "commit", "-qm", "base")
    return root


def test_landed_counts_reads_reachable_trailers(tmp_path):
    root = _repo(tmp_path)
    (root / "f.txt").write_text("y")
    _run(root, "commit", "-aqm", "work\n\nLooptight-Outcome: idea-a landed")
    (root / "f.txt").write_text("z")
    _run(root, "commit", "-aqm", "work2\n\nLooptight-Outcome: idea-a landed")
    (root / "f.txt").write_text("w")
    _run(root, "commit", "-aqm", "work3\n\nLooptight-Outcome: idea-b landed")

    counts = landed_counts(Path(root), "HEAD")
    assert counts == {"idea-a": 2, "idea-b": 1}


def test_landed_counts_empty_when_no_trailers(tmp_path):
    root = _repo(tmp_path)
    assert landed_counts(Path(root), "HEAD") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_experience.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'looptight.experience'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/looptight/experience.py
"""The self-model: what looptight has learned from past idea outcomes.

Positive signal (`landed`) is read from git history, structurally verified: only
commits reachable from the target ref are scanned, so a trailer on an unmerged
commit never counts. Negative signal (`failed`) is read from the repo-private
coordinator. The model is advisory; callers degrade to default behavior if it is
empty or unavailable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_OUTCOME_KEY = "Looptight-Outcome:"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=str(root),
                              capture_output=True, text=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def landed_counts(root: Path, target_ref: str, *, limit: int = 500) -> dict[str, int]:
    """Verified-landed counts per idea_id, from trailers reachable from target_ref."""
    result = _git(
        root, "log", target_ref, f"-n{limit}", f"--grep={_OUTCOME_KEY}",
        "--pretty=%(trailers:key=Looptight-Outcome,valueonly)",
    )
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "landed" not in line:
            continue
        idea = line.split()[0]
        counts[idea] = counts.get(idea, 0) + 1
    return counts


@dataclass(frozen=True)
class Model:
    landed: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    category_landed: dict[str, int] = field(default_factory=dict)
    category_failed: dict[str, int] = field(default_factory=dict)


def build_model(
    root: Path, target_ref: str, coordinator, *,
    cooldown_s: float, now: float | None = None, limit: int = 500,
) -> Model:
    """Union verified-landed (git) and recent local failures (coordinator)."""
    landed = landed_counts(root, target_ref, limit=limit)
    failed = coordinator.recent_failures(window_s=cooldown_s, now=now) if coordinator else {}
    category_failed = coordinator.failure_counts() if coordinator else {}
    return Model(landed=landed, failed=failed, category_failed=category_failed)
```

Note: `category_landed` stays empty in the MVP (per-category landed by source would require the source in the trailer; deferred). `failed`/`category_failed` drive cooldown and reweighting; `landed` drives the prompt summary. Keep the field for forward compatibility.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_experience.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/experience.py tests/test_experience.py
git commit -m "feat: experience self-model reader (verified landed + local failed)"
```

---

### Task 6: Control helpers (cooldown, reweight, summary)

**Files:**
- Modify: `src/looptight/experience.py`
- Test: `tests/test_experience.py` (append)

**Interfaces:**
- Consumes: `Model`.
- Produces:
  - `suppressed(model: Model, *, max_failures: int = 2) -> set[str]` — idea_ids in cooldown (recent failures at or above `max_failures`).
  - `reweight_factor(category: str, model: Model, *, lo: float = 0.5, hi: float = 1.5) -> float` — yield-based multiplier clamped to `[lo, hi]`, `1.0` when there is no data.
  - `summary_text(model: Model, *, k: int = 5) -> str` — a bounded, plain-text experience note for the planner, or `""` when the model is empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experience.py  (append)
from looptight.experience import Model, reweight_factor, summary_text, suppressed


def test_suppressed_returns_ideas_at_or_above_threshold():
    m = Model(failed={"a": 2, "b": 1, "c": 3})
    assert suppressed(m, max_failures=2) == {"a", "c"}


def test_reweight_clamped_and_neutral_without_data():
    assert reweight_factor("lint", Model()) == 1.0
    # a category that mostly fails is damped, but never below lo
    m = Model(category_landed={"lint": 0}, category_failed={"lint": 50})
    f = reweight_factor("lint", m, lo=0.5, hi=1.5)
    assert f == 0.5
    # a category that mostly lands is boosted, but never above hi
    m2 = Model(category_landed={"lint": 50}, category_failed={"lint": 0})
    assert reweight_factor("lint", m2, lo=0.5, hi=1.5) == 1.5


def test_summary_text_bounded_and_empty_when_no_data():
    assert summary_text(Model()) == ""
    m = Model(landed={"a": 3, "b": 1}, failed={"x": 2})
    text = summary_text(m, k=5)
    assert "x" in text  # avoid list mentions the failed idea
    assert text.count("\n") <= 6  # bounded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_experience.py -k "suppressed or reweight or summary" -q`
Expected: FAIL with `ImportError: cannot import name 'suppressed'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/looptight/experience.py`:

```python
def suppressed(model: Model, *, max_failures: int = 2) -> set[str]:
    """Idea ids whose recent failures reached the cooldown threshold."""
    return {idea for idea, n in model.failed.items() if n >= max_failures}


def reweight_factor(category: str, model: Model, *, lo: float = 0.5, hi: float = 1.5) -> float:
    """Clamped yield multiplier for a category; 1.0 when there is no data."""
    landed = model.category_landed.get(category, 0)
    failed = model.category_failed.get(category, 0)
    total = landed + failed
    if total == 0:
        return 1.0
    yield_rate = landed / total  # in [0, 1]
    return lo + (hi - lo) * yield_rate


def summary_text(model: Model, *, k: int = 5) -> str:
    """A bounded experience note for the planner, or '' when there is nothing useful."""
    if not model.failed and not model.landed:
        return ""
    lines: list[str] = []
    if model.failed:
        avoid = sorted(model.failed, key=lambda i: model.failed[i], reverse=True)[:k]
        lines.append("Recently-failed ideas to avoid re-proposing: " + ", ".join(avoid) + ".")
    if model.landed:
        top = sorted(model.landed, key=lambda i: model.landed[i], reverse=True)[:k]
        lines.append("Recently-landed idea kinds that paid off: " + ", ".join(top) + ".")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_experience.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/looptight/experience.py tests/test_experience.py
git commit -m "feat: experience control helpers (cooldown, clamped reweight, summary)"
```

---

### Task 7: Suppress cooled-down ideas in proposal

**Files:**
- Modify: `src/looptight/propose.py`
- Test: `tests/test_propose.py` (append)

**Interfaces:**
- Consumes: `idea_identity.idea_id`, `experience.suppressed`, `Coordinator`, `experience.build_model`.
- Produces: `propose` drops candidates whose `idea_id` is in cooldown, but only when a coordinator is available and the model is non-empty. With no coordinator (outside Git) or no experience, the returned list is byte-for-byte unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_propose.py  (append)
from looptight.discovery import Candidate
from looptight.experience import Model
from looptight.idea_identity import idea_id
from looptight.propose import _apply_cooldown  # pure helper, see Step 3


def _c(title):
    return Candidate(title=title, source="lint", location="src/a.py:1",
                     suggested_verify=None, score=60.0, detail="d", acceptance="a")


def test_apply_cooldown_filters_suppressed_ideas():
    keep = _c("fix E501: x")
    drop = _c("fix F401: y")
    model = Model(failed={idea_id(drop): 2})
    out = _apply_cooldown([keep, drop], model, max_failures=2)
    assert out == [keep]


def test_apply_cooldown_noop_without_model():
    cands = [_c("fix E501: x")]
    assert _apply_cooldown(cands, Model(), max_failures=2) == cands
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_propose.py -k cooldown -q`
Expected: FAIL with `ImportError: cannot import name '_apply_cooldown'`

- [ ] **Step 3: Write minimal implementation**

In `propose.py`, add the pure helper and wire it in only when a coordinator and a non-empty model exist:

```python
from .coordinator import Coordinator
from .experience import Model, build_model, suppressed
from .idea_identity import idea_id

_COOLDOWN_S = 24 * 3600.0
_MAX_FAILURES = 2


def _apply_cooldown(candidates: list[Candidate], model: Model, *, max_failures: int) -> list[Candidate]:
    """Drop candidates whose idea is in cooldown. Pure; no-op on an empty model."""
    blocked = suppressed(model, max_failures=max_failures)
    if not blocked:
        return candidates
    return [c for c in candidates if idea_id(c) not in blocked]


def propose(root: Path, *, limit: int = 10) -> list[Candidate]:
    """Scan all signals, dedupe, rank, suppress cooled-down ideas, return the top N."""
    config_path = find_config(root)
    config = load_config(config_path) if config_path else Config()
    discovery_root = config_path.parent if config_path else root
    ranked = rank(dedupe(discover(discovery_root, task_files=config.tasks)))

    coordinator = Coordinator.open(discovery_root)
    if coordinator is not None:
        try:
            model = build_model(discovery_root, "HEAD", coordinator, cooldown_s=_COOLDOWN_S)
            ranked = _apply_cooldown(ranked, model, max_failures=_MAX_FAILURES)
        finally:
            coordinator.close()

    return ranked[:limit] if limit and limit > 0 else ranked
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_propose.py tests/test_cli.py -q`
Expected: PASS (cooldown tests plus unchanged propose/next output tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/propose.py tests/test_propose.py
git commit -m "feat: suppress cooled-down failed ideas in proposal (advisory)"
```

---

### Task 8: Reweight ranking by category yield

**Files:**
- Modify: `src/looptight/ranking.py`
- Test: `tests/test_propose.py` or `tests/test_ranking.py` (append; match where ranking tests live)

**Interfaces:**
- Consumes: `experience.Model`, `experience.reweight_factor`, `_SOURCE_WEIGHT`.
- Produces: `rank_with_model(candidates, model) -> list[Candidate]` — scores each candidate as `_SOURCE_WEIGHT[source] * reweight_factor(source, model)`, clamped so a curated source never sorts below a non-curated one. Existing `rank(candidates)` stays unchanged (it equals `rank_with_model(candidates, Model())`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_propose.py  (append)
from looptight.discovery import Candidate
from looptight.experience import Model
from looptight.ranking import _SOURCE_WEIGHT, rank, rank_with_model


def _c(source, title):
    return Candidate(title=title, source=source, location="x:1",
                     suggested_verify=None, score=0.0, detail="d", acceptance="a")


def test_rank_with_empty_model_matches_plain_rank():
    cs = [_c("lint", "a"), _c("task-file", "b"), _c("todo", "c")]
    assert [c.title for c in rank_with_model(cs, Model())] == [c.title for c in rank(cs)]


def test_reweight_never_inverts_curated_over_automated():
    cs = [_c("task-file", "curated"), _c("lint", "auto")]
    # lint lands a lot, task-file has no data: lint is boosted but must stay below curated
    model = Model(category_landed={"lint": 100}, category_failed={"lint": 0})
    ordered = [c.source for c in rank_with_model(cs, model)]
    assert ordered[0] == "task-file"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_propose.py -k "rank_with_model or reweight_never" -q`
Expected: FAIL with `ImportError: cannot import name 'rank_with_model'`

- [ ] **Step 3: Write minimal implementation**

In `ranking.py`, add the model-aware ranker. Clamp the factor band so the boosted automated weight cannot reach the next curated tier (the gap between `lint`=60 and `status-next`=65 means `hi` must keep `60*hi < 65`, i.e. `hi <= 1.0833`; use a tight per-tier-safe band):

```python
from .experience import Model, reweight_factor  # add import

_REWEIGHT_LO = 0.5
_REWEIGHT_HI = 1.08  # keep a boosted automated source below the next curated tier


def rank_with_model(candidates: list[Candidate], model: Model) -> list[Candidate]:
    """Stable sort by source weight, scaled by clamped category yield. Heuristic."""
    scored = [
        Candidate(**{**c.__dict__, "score": float(_SOURCE_WEIGHT.get(c.source, 0))
                     * reweight_factor(c.source, model, lo=_REWEIGHT_LO, hi=_REWEIGHT_HI)})
        for c in candidates
    ]
    return sorted(scored, key=lambda c: c.score, reverse=True)
```

Then have `propose` use `rank_with_model` when it has a model. Update Task 7's `propose` body so the model (already built) feeds ranking too:

```python
    coordinator = Coordinator.open(discovery_root)
    if coordinator is not None:
        try:
            model = build_model(discovery_root, "HEAD", coordinator, cooldown_s=_COOLDOWN_S)
            base = dedupe(discover(discovery_root, task_files=config.tasks))
            ranked = _apply_cooldown(rank_with_model(base, model), model, max_failures=_MAX_FAILURES)
        finally:
            coordinator.close()
    else:
        ranked = rank(dedupe(discover(discovery_root, task_files=config.tasks)))
```

Import `rank_with_model` in `propose.py` and remove the now-duplicated initial `ranked = rank(...)` line so discovery runs once per branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_propose.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/looptight/ranking.py src/looptight/propose.py tests/test_propose.py
git commit -m "feat: clamped category-yield reweighting under source weights"
```

---

### Task 9: Inject the experience summary into the planning prompt

**Files:**
- Modify: `src/looptight/prompts.py` (add a builder; keep `PLANNING_GOAL` constant intact)
- Test: `tests/test_prompts.py` (append)

**Interfaces:**
- Consumes: `experience.Model`, `experience.summary_text`, `PLANNING_GOAL`.
- Produces: `planning_goal(model: Model | None = None) -> str` — `PLANNING_GOAL` with a bounded experience note inserted *before* the final grounding-rail sentence, so the rail stays last. With `None`/empty model it returns `PLANNING_GOAL` unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py  (append; create file if absent)
from looptight.experience import Model
from looptight.prompts import PLANNING_GOAL, planning_goal


def test_planning_goal_unchanged_without_model():
    assert planning_goal(None) == PLANNING_GOAL
    assert planning_goal(Model()) == PLANNING_GOAL


def test_planning_goal_injects_summary_before_grounding_rail():
    m = Model(failed={"idea-x": 2})
    text = planning_goal(m)
    assert "idea-x" in text
    # the grounding rail stays the final instruction
    assert text.rstrip().endswith("make no changes.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: FAIL with `ImportError: cannot import name 'planning_goal'`

- [ ] **Step 3: Write minimal implementation**

In `prompts.py`, keep `PLANNING_GOAL` as-is and add:

```python
from .experience import Model, summary_text  # add import

_RAIL = "If no necessary improvement is supported by repository evidence, make no changes."


def planning_goal(model: Model | None = None) -> str:
    """PLANNING_GOAL, optionally with a bounded experience note before the rail."""
    note = summary_text(model) if model is not None else ""
    if not note:
        return PLANNING_GOAL
    head = PLANNING_GOAL[: PLANNING_GOAL.rindex(_RAIL)].rstrip()
    return f"{head}\n\nLearned from past runs:\n{note}\n\n{_RAIL}"
```

Note: `PLANNING_GOAL` ends with the `_RAIL` sentence (verify by reading the constant). If the exact wording differs, set `_RAIL` to match the constant's final sentence verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/looptight/prompts.py tests/test_prompts.py
git commit -m "feat: inject bounded experience summary into planning prompt, rail last"
```

---

### Task 10: Use the experience-aware prompt in the swarm planner

**Files:**
- Modify: `src/looptight/swarm.py` (the planner invocation that uses `PLANNING_GOAL`, near line 498)
- Test: `tests/test_swarm.py` (append)

**Interfaces:**
- Consumes: `experience.build_model`, `prompts.planning_goal`, `Coordinator`.
- Produces: `plan_next_tasks` builds the planner goal from `planning_goal(model)` when a coordinator is available, else from `planning_goal(None)` (equals `PLANNING_GOAL`). No signature change observable to callers.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm.py  (append)
def test_planner_goal_includes_experience_when_available(monkeypatch, tmp_path):
    # Arrange a coordinator with a recent failure, then assert the goal handed to
    # the planner adapter contains the experience note. Capture the goal by
    # monkeypatching the adapter's run_iteration to record its first arg.
    captured = {}

    class _Adapter:
        def run_iteration(self, goal, context, workdir, model=None):
            captured["goal"] = goal
            class _R:
                stop_reason = None
                error = None
            return _R()

    # Use the file's existing repo/coordinator setup helpers; record a failure
    # for some idea_id, then call plan_next_tasks with _Adapter().
    # assert "Learned from past runs" in captured["goal"]
```

Note: complete this test against `test_swarm.py`'s existing planner harness (it already stubs adapters and builds repos). The contract: when the coordinator has experience, the planner goal contains the injected note; otherwise it equals `PLANNING_GOAL`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_swarm.py -k planner_goal_includes_experience -q`
Expected: FAIL (goal lacks the note)

- [ ] **Step 3: Write minimal implementation**

In `swarm.py`, where `plan_next_tasks` calls the adapter with `PLANNING_GOAL` (currently `outcome = adapter.run_iteration(PLANNING_GOAL, "", worktree)`), build the goal from the model:

```python
from .experience import build_model
from .prompts import planning_goal  # replace direct PLANNING_GOAL use here

# inside plan_next_tasks, before invoking the adapter:
    coordinator = Coordinator.open(root)
    goal = PLANNING_GOAL
    if coordinator is not None:
        try:
            model = build_model(root, "HEAD", coordinator, cooldown_s=24 * 3600.0)
            goal = planning_goal(model)
        finally:
            coordinator.close()
    outcome = adapter.run_iteration(goal, "", worktree)
```

Keep importing `PLANNING_GOAL` for the fallback. If `Coordinator` is not already imported in `swarm.py`, add it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_swarm.py -q`
Expected: PASS (new test plus all existing swarm tests)

- [ ] **Step 5: Commit**

```bash
git add src/looptight/swarm.py tests/test_swarm.py
git commit -m "feat: swarm planner uses the experience-aware planning goal"
```

---

### Task 11: Documentation and final gate

**Files:**
- Modify: `docs/architecture.md` (the idea-generation / metacognition section)
- Modify: `docs/STATUS.md` (Validated entries by replacement)

- [ ] **Step 1: Document the Phase 2 loop in architecture.md**

Under the idea-generation section, add a short paragraph describing the monitor -> self-model -> control loop: `landed` recorded as a verifiable commit trailer (shared via git history, verified by scanning from the target ref), `failed` kept local in the coordinator, the lossy idea identity in `idea_identity.py`, and the advisory control (cooldown suppression, clamped yield reweight, bounded prompt summary). State the deliberate asymmetry: shared positive learning, local negative learning. Avoid em dashes.

- [ ] **Step 2: Record outcomes in STATUS.md by replacement**

Add Validated entries for: the lossy idea identity; landed-trailer plus local-failed recording; the self-model reader; the advisory control (suppression, reweight, prompt summary). Keep the section bounded; do not append a changelog.

- [ ] **Step 3: Run the full gate**

Run: `uv run pytest -q && uv run ruff check`
Expected: PASS, "All checks passed!"

- [ ] **Step 4: Verify via the project contract**

Run: `uv run looptight verify --json`
Expected: `"status": "pass"`

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md docs/STATUS.md
git commit -m "docs: document Phase 2 metacognitive idea generation; record outcomes"
```

---

## Self-Review

**Spec coverage:**
- Lossy idea identity (spec "Idea Identity") -> Task 1, used in Tasks 2, 4, 7.
- Monitor write path: `landed` trailer + `failed` in coordinator (spec "Monitor") -> Tasks 3, 4.
- Self-model union + structural verification + bounded scan (spec "Self-model") -> Task 5.
- Control: cooldown suppression, clamped reweight, prompt summary (spec "Control") -> Tasks 6, 7, 8, 9, 10.
- Multi-dev asymmetry (positive shared, negative local) -> structurally enforced by Tasks 4 and 5; documented in Task 11.
- Advisory degradation -> Tasks 7, 8, 9 each test the no-data / no-coordinator no-op.
- Deferred (churn, shared-negative, session-native writes, EVOC) -> not implemented by design; recorded in the spec.

**Placeholder scan:** Two tasks (4, 10) intentionally defer test scaffolding to the target file's existing harness rather than duplicating large fixtures; the asserted contract is stated explicitly in each. All implementation steps carry complete code. No "TBD"/"add error handling"/"similar to Task N".

**Type consistency:** `idea_id(candidate)` is used identically in Tasks 1, 2, 4 (via lease payload), 7. `Model` fields (`landed`, `failed`, `category_landed`, `category_failed`) are produced in Task 5 and consumed unchanged in Tasks 6, 7, 8, 9. `build_model(root, target_ref, coordinator, *, cooldown_s, now, limit)` and `planning_goal(model)` signatures match across Tasks 5, 7, 9, 10. `reweight_factor` band `[lo, hi]` is `[0.5, 1.08]` in Task 8 to keep boosted automated sources below the next curated tier (`lint`=60, `status-next`=65).

**Risk note for the implementer:** confirm `PLANNING_GOAL`'s final sentence matches `_RAIL` in Task 9 before running; confirm the task-building function name in `tasks.py` for Task 2; reuse existing repo/coordinator harnesses in Tasks 4 and 10 rather than inventing fixtures.
