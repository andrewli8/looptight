# Repository Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate many local Looptight sessions per Git repository while parallelizing planning and worker execution and serializing only Git integration.

**Architecture:** A repository-private SQLite database provides short transactional task leases, run identity, proposal deduplication, and durable integration/publication queues. A repository-private advisory lock protects one coordinator-owned detached integration worktree while Git refs are updated with compare-and-swap.

**Tech Stack:** Python 3.11+ standard library (`sqlite3`, `uuid`, `fcntl`/`msvcrt`, `subprocess`), Git worktrees/refs, pytest.

## Global Constraints

- Coordination is local to one machine and one local filesystem; reject unsupported network filesystems.
- Keep the runtime standard-library-only and all coordinator state under the Git common directory.
- Preserve existing CLI and JSON fields; new coordinator metadata is additive.
- Never edit, reset, or remove user-created worktrees; never force-push.
- Use TDD for every behavior change and run `looptight verify --json` before every commit.
- Mixed coordinator/legacy operation fails closed after repository activation.

---

### Task 1: SQLite Coordinator Foundation

**Files:**
- Create: `src/looptight/coordinator.py`
- Create: `tests/test_coordinator.py`
- Modify: `src/looptight/__init__.py`

**Interfaces:**
- Produces: `coordinator_path(workdir: Path) -> Path | None`
- Produces: `Coordinator.open(workdir: Path) -> Coordinator | None`
- Produces: `Coordinator.transaction(immediate: bool = False)` context manager
- Produces: `Coordinator.close() -> None`

- [ ] **Step 1: Write failing path/isolation/schema tests**

```python
def test_coordinator_lives_in_git_common_dir_and_isolated_by_repo(tmp_path):
    first, second = make_repo(tmp_path / "a"), make_repo(tmp_path / "b")
    a = Coordinator.open(first)
    b = Coordinator.open(second)
    assert a.path == first / ".git" / "looptight" / "coordinator.db"
    assert b.path != a.path
    assert a.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

def test_schema_has_unique_task_and_integration_identity(repo):
    coordinator = Coordinator.open(repo)
    coordinator.connection.execute("INSERT INTO tasks(fingerprint,payload,state) VALUES('x','{}','queued')")
    with pytest.raises(sqlite3.IntegrityError):
        coordinator.connection.execute("INSERT INTO tasks(fingerprint,payload,state) VALUES('x','{}','queued')")
```

- [ ] **Step 2: Run the tests and confirm import/schema failures**

Run: `.venv/bin/pytest -q tests/test_coordinator.py`
Expected: FAIL because `looptight.coordinator` does not exist.

- [ ] **Step 3: Implement schema v1 and bounded transactions**

```python
SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE runs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
                  pid INTEGER NOT NULL, heartbeat REAL NOT NULL);
CREATE TABLE tasks(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                   payload TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE leases(task_id INTEGER PRIMARY KEY REFERENCES tasks(id), run_id TEXT NOT NULL REFERENCES runs(id),
                    generation INTEGER NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE proposals(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                       fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                       UNIQUE(run_id, fingerprint));
CREATE TABLE integrations(sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                          run_id TEXT NOT NULL, task_id INTEGER NOT NULL, lease_generation INTEGER NOT NULL,
                          target_ref TEXT NOT NULL, observed_sha TEXT, candidate_sha TEXT NOT NULL,
                          result_sha TEXT, state TEXT NOT NULL, error TEXT, retained_worktree TEXT);
CREATE TABLE publications(id TEXT PRIMARY KEY, integration_id TEXT NOT NULL REFERENCES integrations(id),
                          remote TEXT NOT NULL, remote_ref TEXT NOT NULL, observed_local_sha TEXT,
                          observed_remote_sha TEXT, result_sha TEXT NOT NULL,
                          reconciliation_sha TEXT, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                          error TEXT);
"""
```

Open with `timeout=5`, enable foreign keys, select WAL, set `PRAGMA user_version=1`, and use explicit commit/rollback context management.

- [ ] **Step 4: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_coordinator.py && .venv/bin/looptight verify --json`
Expected: coordinator tests pass and verifier returns `"status": "pass"`.

- [ ] **Step 5: Commit**

```bash
git add src/looptight/coordinator.py src/looptight/__init__.py tests/test_coordinator.py
git commit -m "feat: add repository-local coordinator database"
```

### Task 2: Unique Runs and Fenced Task Leases

**Files:**
- Modify: `src/looptight/coordinator.py`
- Modify: `src/looptight/tasks.py`
- Modify: `src/looptight/protocol_commands.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_claims.py`

**Interfaces:**
- Consumes: `Coordinator.open`, `Coordinator.transaction`
- Produces: `Coordinator.start_run(kind: str, now: float | None = None) -> Run`
- Produces: `Coordinator.claim(tasks: list[dict], run_id: str, ttl_s: float, now: float | None = None) -> Lease | None`
- Produces: `Coordinator.renew(lease: Lease, ttl_s: float, now: float | None = None) -> bool`
- Produces: immutable `Run(id: str, kind: str)` and `Lease(task_id: str, run_id: str, generation: int, payload: dict)`

- [ ] **Step 1: Write failing multiprocess and fencing tests**

```python
def claim_once(repo, task_payloads, output):
    db = Coordinator.open(repo)
    run = db.start_run("test")
    lease = db.claim(task_payloads, run.id, ttl_s=60)
    output.put((run.id, lease.task_id if lease else None, lease.generation if lease else None))

def test_ten_same_directory_claimers_get_distinct_tasks(repo):
    output = multiprocessing.Queue()
    processes = [multiprocessing.Process(target=claim_once, args=(repo, TASKS, output)) for _ in range(10)]
    for process in processes: process.start()
    for process in processes: process.join()
    rows = [output.get() for _ in processes]
    assert len({row[0] for row in rows}) == 10
    assert len({row[1] for row in rows}) == 10

def test_expired_owner_cannot_renew_or_complete_reassigned_lease(repo):
    first = db.claim([TASK], run1.id, ttl_s=1, now=0)
    second = db.claim([TASK], run2.id, ttl_s=1, now=2)
    assert second.generation == first.generation + 1
    assert not db.renew(first, ttl_s=1, now=2)
```

- [ ] **Step 2: Confirm failures against file-based owner identity**

Run: `.venv/bin/pytest -q tests/test_coordinator.py -k 'claimers or expired'`
Expected: FAIL because coordinator leasing APIs are absent.

- [ ] **Step 3: Implement UUID runs and `BEGIN IMMEDIATE` claim CAS**

Use `uuid.uuid4().hex` for every run, upsert task fingerprints inside one immediate transaction, expire old leases, increment the task attempt/generation, and insert exactly one lease. Renewal updates with `WHERE task_id=? AND run_id=? AND generation=?` and succeeds only when `rowcount == 1`.

- [ ] **Step 4: Route `next` and `status` through coordinator leases**

Replace worktree-path ownership in `next_task` with a run ID passed from the command/session environment. Preserve the current JSON schema and derive `claimed_task`/`active_claims` from SQLite. Add `LOOPTIGHT_RUN_ID` reuse only when explicitly supplied; otherwise generate a unique ID per command invocation.

- [ ] **Step 5: Run focused, compatibility, and full tests**

Run: `.venv/bin/pytest -q tests/test_coordinator.py tests/test_claims.py tests/test_cli.py && .venv/bin/looptight verify --json`
Expected: all pass; existing `next` and `status` JSON keys are unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/looptight/coordinator.py src/looptight/tasks.py src/looptight/protocol_commands.py tests/test_coordinator.py tests/test_claims.py tests/test_cli.py
git commit -m "feat: coordinate unique fenced task leases"
```

### Task 3: Repository Integration Lock and Dedicated Worktree

**Files:**
- Create: `src/looptight/integration_queue.py`
- Create: `tests/test_integration_queue.py`
- Modify: `src/looptight/swarm.py`

**Interfaces:**
- Produces: `IntegrationLock.acquire(common_dir: Path, timeout_s: float) -> IntegrationLock`
- Produces: `integration_worktree(root: Path, target_ref: str) -> Path`
- Produces: `prepare_integration_worktree(root: Path, target_ref: str) -> tuple[Path, str]`

- [ ] **Step 1: Write failing cross-process exclusion/worktree tests**

```python
def hold_lock(common, entered, release):
    with IntegrationLock.acquire(common, timeout_s=2):
        entered.set(); release.wait(2)

def test_second_process_cannot_enter_integration_lock(repo):
    entered, release = multiprocessing.Event(), multiprocessing.Event()
    process = multiprocessing.Process(target=hold_lock, args=(git_common(repo), entered, release))
    process.start(); assert entered.wait(2)
    with pytest.raises(CoordinationTimeout):
        IntegrationLock.acquire(git_common(repo), timeout_s=0.05)
    release.set(); process.join()

def test_integration_worktree_is_detached_and_not_user_worktree(repo):
    path, sha = prepare_integration_worktree(repo, "refs/heads/main")
    assert path.is_relative_to(git_common(repo) / "looptight" / "integration")
    assert git(path, "symbolic-ref", "-q", "HEAD").returncode != 0
```

- [ ] **Step 2: Run and observe missing lock/worktree APIs**

Run: `.venv/bin/pytest -q tests/test_integration_queue.py -k 'lock or worktree'`
Expected: FAIL on missing module/interfaces.

- [ ] **Step 3: Implement POSIX/Windows advisory locking**

Poll nonblocking `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on POSIX and `msvcrt.locking(fd, LK_NBLCK, 1)` on Windows until timeout; close the descriptor in `__exit__` so crashes release the lock. Raise `CoordinationTimeout` distinctly.

- [ ] **Step 4: Implement coordinator-owned detached worktree validation**

Hash the fully qualified target ref for the path, create it with `git worktree add --detach`, verify it belongs to the same common directory, refuse dirtiness, and never reset/remove a path not under the coordinator integration directory.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest -q tests/test_integration_queue.py tests/test_swarm.py && .venv/bin/looptight verify --json`
Expected: pass.

```bash
git add src/looptight/integration_queue.py src/looptight/swarm.py tests/test_integration_queue.py
git commit -m "feat: serialize repository integration safely"
```

### Task 4: Durable Integration Queue and Swarm Handoff

**Files:**
- Modify: `src/looptight/coordinator.py`
- Modify: `src/looptight/integration_queue.py`
- Modify: `src/looptight/swarm.py`
- Modify: `tests/test_integration_queue.py`
- Modify: `tests/test_swarm.py`

**Interfaces:**
- Produces: `Coordinator.enqueue_integration(lease: Lease, target_ref: str, candidate_sha: str) -> str`
- Produces: `Integrator.run_next(root: Path, verify: str) -> IntegrationOutcome | None`
- Produces: `Coordinator.finish_integration(id: str, outcome: IntegrationOutcome) -> None`

- [ ] **Step 1: Write failing FIFO, stale-fence, and concurrent-swarm tests**

```python
def test_oldest_integration_runs_first(repo):
    first = db.enqueue_integration(lease1, "refs/heads/main", sha1)
    second = db.enqueue_integration(lease2, "refs/heads/main", sha2)
    assert Integrator(db).next_id() == first

def test_stale_fence_is_superseded_without_releasing_new_owner(repo):
    outcome = Integrator(db).run_record(old_integration)
    assert outcome.status == "superseded"
    assert db.current_lease(task_id).run_id == new_owner.id
```

- [ ] **Step 2: Confirm failures before routing swarm integration**

Run: `.venv/bin/pytest -q tests/test_integration_queue.py -k 'oldest or stale'`
Expected: FAIL on missing queue APIs.

- [ ] **Step 3: Implement enqueue and terminal state transactions**

Enqueue only when `(task_id, run_id, generation)` matches the active lease. Globally select the oldest `queued` sequence under the lock. For success atomically mark integration complete, task complete, and delete the fenced lease. For conflict/verify failure increment attempts, release the fenced lease, requeue below cap or fail at cap, and persist the retained worktree.

- [ ] **Step 4: Change swarm workers to enqueue instead of merging directly**

Keep worker execution concurrent. After `_run_worker` verifies/commits its branch, enqueue it. Drain eligible integration records through `Integrator.run_next`; populate existing `Worker.status/error` and `SwarmResult` fields without changing JSON keys.

- [ ] **Step 5: Run multiprocess swarm and full verification**

Run: `.venv/bin/pytest -q tests/test_integration_queue.py tests/test_swarm.py && .venv/bin/looptight verify --json`
Expected: two swarm managers can execute concurrently; instrumented critical sections never overlap.

- [ ] **Step 6: Commit**

```bash
git add src/looptight/coordinator.py src/looptight/integration_queue.py src/looptight/swarm.py tests/test_integration_queue.py tests/test_swarm.py
git commit -m "feat: queue verified swarm integrations"
```

### Task 5: Idempotent Crash Recovery and Publication

**Files:**
- Modify: `src/looptight/coordinator.py`
- Modify: `src/looptight/integration_queue.py`
- Modify: `src/looptight/swarm.py`
- Modify: `tests/test_integration_queue.py`

**Interfaces:**
- Produces: `Integrator.reconcile() -> tuple[IntegrationOutcome, ...]`
- Produces: `Coordinator.enqueue_publication(integration_id: str, remote: str, remote_ref: str) -> str`
- Produces: `Publisher.run_next(root: Path) -> PublicationOutcome | None`

- [ ] **Step 1: Write a parameterized crash-boundary test**

```python
@pytest.mark.parametrize("boundary", ["after_merge", "after_commit", "after_update_ref", "after_db_update"])
def test_recovery_has_one_reachable_result(repo, boundary):
    integrator = Integrator(db, crash_after=boundary)
    with pytest.raises(InjectedCrash): integrator.run_next(repo, "exit 0")
    Integrator(db).reconcile()
    reachable = commits_with_trailer(repo, "Looptight-Integration-ID", integration_id)
    assert len(reachable) == 1
    assert db.integration(integration_id).state == "complete"
```

- [ ] **Step 2: Write failing push-success/crash and non-fast-forward tests**

```python
def test_remote_already_contains_result_finalizes_without_second_push(repo, remote):
    publisher.push_then_crash(record)
    calls = []
    Publisher(db, push=lambda *a: calls.append(a)).run_next(repo)
    assert calls == []
    assert db.publication(record.id).state == "complete"
```

- [ ] **Step 3: Implement UUID trailers and reconciliation matrix**

Before Git mutation persist observed/candidate SHAs and `integrating`. Commit with `Looptight-Integration-ID: <uuid>`. Reconcile no-commit, detached-commit, already-updated-ref, externally-advanced-ref, and CAS-failure cases exactly as specified; only mark complete after the result is reachable from the target ref.

- [ ] **Step 4: Implement separate publication state**

Persist local/remote observed SHAs and exact result SHA. Fetch before retry. If remote contains result, finalize. Otherwise reconcile histories under the lock, verify, CAS-update local target, and push the exact SHA/ref. Never replay the candidate or force-push.

- [ ] **Step 5: Verify crash matrix and commit**

Run: `.venv/bin/pytest -q tests/test_integration_queue.py && .venv/bin/looptight verify --json`
Expected: every crash boundary and publication replay test passes.

```bash
git add src/looptight/coordinator.py src/looptight/integration_queue.py src/looptight/swarm.py tests/test_integration_queue.py
git commit -m "feat: recover coordinator integration idempotently"
```

### Task 6: Planner Deduplication, Status Projection, Migration, and Acceptance

**Files:**
- Modify: `src/looptight/coordinator.py`
- Modify: `src/looptight/swarm.py`
- Modify: `src/looptight/protocol_commands.py`
- Modify: `src/looptight/ui.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/SPEC.md`
- Create: `tests/test_coordinator_multiprocess.py`
- Modify: `tests/test_ui.py`
- Modify: `tests/test_swarm.py`

**Interfaces:**
- Produces: `Coordinator.submit_proposals(run_id: str, candidates: list[Candidate], generation: str) -> tuple[str, ...]`
- Produces: `Coordinator.status(run_id: str | None = None) -> dict[str, object]`
- Produces: `Coordinator.activate_from_legacy() -> None`

- [ ] **Step 1: Write failing concurrent planner deduplication test**

```python
def test_concurrent_planners_preserve_distinct_and_dedupe_equivalent(repo):
    submit_in_processes(repo, [[A, B], [B, C]])
    assert coordinator_task_fingerprints(repo) == {A.id, B.id, C.id}
```

- [ ] **Step 2: Write failing migration/status tests**

```python
def test_activation_refuses_live_legacy_claims(repo):
    write_legacy_claim(repo, "task-a")
    with pytest.raises(MigrationBlocked, match="legacy"):
        Coordinator.open(repo, activate=True)

def test_status_keeps_v1_keys_and_adds_coordinator_counts(repo, capsys):
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert V1_STATUS_KEYS <= payload.keys()
    assert payload["coordinator"]["queued_integrations"] == 0
```

- [ ] **Step 3: Implement transactional proposal deduplication and bounded planners**

Fingerprint grounded candidates with the existing stable task identity. Insert proposals/tasks using uniqueness constraints, validate evidence against current generation, and cap active planner runs at two by default.

- [ ] **Step 4: Implement migration marker and compatibility projection**

Serialize schema activation; refuse live legacy claims; migrate durable claim data; verify SQLite state; write `<git-common-dir>/looptight/coordinator-format.json` last. Make legacy claim code fail closed when the marker exists. Project coordinator counts into existing status/UI output additively.

- [ ] **Step 5: Run 10-process acceptance and full verification**

Run: `.venv/bin/pytest -q tests/test_coordinator_multiprocess.py tests/test_coordinator.py tests/test_integration_queue.py tests/test_swarm.py tests/test_ui.py && .venv/bin/looptight verify --json`
Expected: 10+ claimers receive distinct tasks, planners deduplicate, integration sections never overlap, crash recovery is deterministic, separate repositories are isolated, and full verification passes.

- [ ] **Step 6: Update documentation and commit**

Document the simple model: multiple sessions → shared task queue → isolated worktrees → verify → one-at-a-time Git integration. Document local-filesystem scope, migration prerequisite, lock timeout, retained work, and additive JSON fields.

```bash
git add src/looptight/coordinator.py src/looptight/swarm.py src/looptight/protocol_commands.py src/looptight/ui.py README.md docs/architecture.md docs/SPEC.md tests/test_coordinator_multiprocess.py tests/test_ui.py tests/test_swarm.py
git commit -m "feat: complete multi-session repository coordination"
```

