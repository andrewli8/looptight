# Repository Coordinator Design

## Objective

Allow many Looptight sessions and swarm invocations to operate concurrently in
one local Git repository without duplicating tasks or concurrently mutating the
same integration worktree. Different repositories remain independent.

Coordination is local to one machine. Cross-machine and network-filesystem
coordination are explicitly out of scope.

## Design

Each Git repository owns one embedded SQLite coordinator at
`<git-common-dir>/looptight/coordinator.db`. SQLite is part of Python's standard
library, provides process-safe transactions, releases locks when a process dies,
and keeps runtime state outside tracked files.

Every Looptight process creates a unique run ID. Runs may concurrently plan in
isolated planner worktrees, lease distinct tasks, and execute workers in isolated
worker worktrees. They never edit the invoking primary worktree during those
parallel phases.

Shared Git mutations are submitted to a FIFO integration queue. Exactly one
integrator at a time may refresh the target branch, merge one candidate, run the
configured verifier, commit, and optionally push. A repository-local advisory
file lock protects this long-running Git boundary and is automatically released
when its process dies. SQLite transactions remain short, so task claims,
heartbeats, planning, and status reads continue while verification runs.

The supported coordination boundary is a local filesystem on POSIX and Windows.
POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking`. Network filesystems are
rejected because their lock and SQLite semantics are insufficient for this
protocol. Lock acquisition is interruptible, bounded by a configured timeout,
and reports a distinct coordination-timeout result.

## Coordinator State

The initial schema contains:

- `runs`: run ID, process identity, kind, state, timestamps, and heartbeat.
- `tasks`: stable task fingerprint, grounded payload, state, and timestamps.
- `leases`: task ID, run ID, expiry, and fencing generation.
- `proposals`: planner run ID, task fingerprint, payload, and disposition.
- `integrations`: FIFO sequence, integration UUID, run/task IDs, target ref,
  observed/candidate/result commits, state, error, and timestamps.
- `publications`: integration UUID, remote/ref, state, attempts, error, and
  timestamps; publication never replays local integration.

Schema creation and migrations are transactional and versioned through
`PRAGMA user_version`. Payloads remain versioned JSON where Looptight already has
public JSON contracts; database rows are private implementation state.

Foreign keys are enabled. Task fingerprints and integration UUIDs are unique;
each task has at most one active lease; state columns use checked values; and
FIFO sequence numbers are monotonic. Initialization selects WAL mode and a
bounded busy timeout. Claims use a short `BEGIN IMMEDIATE` transaction that
selects the oldest eligible task and inserts its lease with a compare-and-swap
generation. Contention retries are bounded and distinguish exhaustion from an
empty queue.

## Planning and Deduplication

Planner concurrency is bounded independently from worker concurrency, with a
small default such as two. Planners operate on isolated worktrees and submit
proposals transactionally.

Stable task fingerprints deduplicate equivalent proposals. A submitted proposal
is accepted only when its evidence still exists and no active, completed, or
already-proposed equivalent task supersedes it. Accepted proposals are published
to the bounded task queue only through the serialized integration path. A
planner based on an obsolete repository generation is refreshed and revalidated;
it does not overwrite the current queue.

## Task Execution

Task leasing uses one SQLite transaction. A run can renew its lease while active;
an expired lease may be reclaimed. The lease owner is the unique run ID, never
the worktree path, so two sessions opened in one directory cannot masquerade as
the same owner.

Every acquisition increments a monotonically increasing fencing generation.
Renewal, integration enqueue, completion, and release compare both run ID and
generation. A late worker whose lease was reassigned cannot publish results; its
worktree is retained with a `superseded` outcome for manual recovery.

Workers always receive distinct worktrees and branches. Existing scope checks,
provider timeouts, verification, retained failure worktrees, and interruption
cleanup remain in force.

## Integration

Completed workers enqueue branch metadata rather than merging directly. The
integrator first acquires `<git-common-dir>/looptight/integration.lock`, then
selects the globally oldest eligible record, not preferentially its own.

Each fully qualified target ref has one coordinator-owned, detached integration
worktree under `<git-common-dir>/looptight/integration/<target-hash>`. It is
created, validated, or repaired only while holding the lock. A missing worktree
is recreated from the target ref; a dirty or unexpected worktree fails closed
and is retained for inspection. User-created worktrees are never reset or
removed. Multiple target refs have separate detached worktrees but share the
repository integration lock because Git refs and objects are shared.

Integration uses the durable state machine
`queued → integrating → committed → complete` (or `conflict` / `failed`). Every
integration has a UUID recorded in SQLite and in the resulting commit's
`Looptight-Integration-ID` trailer. The record stores the target ref, observed
target SHA, candidate SHA, lease generation, and eventual result SHA.

For each record the integrator:

1. Confirms the fenced lease and candidate branch still belong to the submitting
   run, then records `integrating` with the observed target and candidate SHAs.
2. Refreshes the detached integration worktree at the observed target SHA and
   attempts the merge without committing.
3. Runs the full verifier and commits with the integration UUID trailer.
4. Advances the target ref with compare-and-swap `git update-ref`, requiring the
   observed target SHA, then records `committed` and the result SHA.
5. Atomically records `complete`, releases the fenced task lease, and advances
   the queue. Conflict or verification failure aborts the merge and retains the
   worker worktree.

Git and SQLite cannot share one atomic transaction, so lock acquisition always
reconciles `integrating` records before selecting new work. Reconciliation checks
the dedicated integration worktree HEAD and target-ref ancestry for the UUID
trailer and applies this decision matrix:

- No UUID commit exists: abort merge state and requeue the same integration UUID.
- The UUID commit exists and the target still equals the recorded observed SHA:
  compare-and-swap the target to the result SHA, then record `committed`.
- The target equals the result SHA or contains that exact result commit: record
  `committed` without another commit or ref update.
- The target advanced without the result: merge the candidate again from the new
  target, producing a new result attempt for the same UUID, verify it, and
  compare-and-swap from the newly observed target.
- Any compare-and-swap failure restarts reconciliation without marking the row
  `committed` or `complete`.

Only the result reachable from the target ref is the successful integration
commit. A superseded detached attempt may remain dangling for Git maintenance;
it is never treated as a second successful integration.

Every terminal integration outcome updates its integration row, fenced lease,
task state, attempt count, retry eligibility, and retained-worktree path in one
SQLite transaction. Success marks the task complete and releases the lease.
Conflict or verification failure releases the lease and requeues the task while
below its configured attempt cap; at the cap it marks the task failed. A stale
fencing generation records `superseded` without changing the current owner's
lease or task state.

Push is a separate publication state machine. After local integration, an
optional publication record pushes the committed result SHA to the configured
remote ref. On non-fast-forward, the publisher fetches under the integration
lock, reconciles local and remote history through the same non-destructive merge
and verification path, and retries publication. It never replays the candidate
merge and never force-pushes.

Publication records persist the publication UUID, observed local and remote SHAs,
the integration result SHA, and any reconciliation result SHA. After every crash,
the publisher fetches and reconciles before acting:

- If the remote ref equals or contains the recorded result, finalize publication
  without another merge or push.
- If a reconciliation commit exists locally but its database update is missing,
  recover it by its publication UUID trailer and resume from that result SHA.
- If remote or local history changed without containing the result, rebuild and
  verify reconciliation from the newly observed SHAs.
- Every local target-ref change uses compare-and-swap; failure restarts recovery.
- Push retries always name the exact result SHA and remote ref. A successful push
  followed by a crash is therefore detected by the first rule.

Git integration remains intentionally serial per repository. Planning and worker
execution scale concurrently; merge, commit, and push do not.

## Failure and Recovery

- SQLite busy waits are bounded and reported distinctly from provider timeouts.
- Run heartbeats expose active and abandoned sessions without deciding task
  ownership by wall-clock state alone.
- Expired task leases are recoverable; completed integration records are durable.
- A crashed integrator releases its advisory lock automatically. On the next
  attempt, the durable integration UUID and commit trailer reconcile every crash
  boundary before queued work continues.
- Corrupt or unsupported coordinator schemas fail closed with recovery guidance;
  Looptight never deletes tracked files or force-pushes.
- The existing JSON status surface derives a backward-compatible projection from
  coordinator state.

## Compatibility and Rollout

The CLI remains unchanged for normal use. `next`, `status`, `swarm`, and the UI
open the repository coordinator automatically. Existing JSON fields remain
compatible; new run and queue metadata is additive.

Rollout is incremental:

1. Add recognition of a repository coordinator-format marker to the legacy path;
   a marked repository fails closed instead of using JSON claims.
2. Introduce SQLite behind an opt-in migration that requires no live legacy
   claims or processes, serializes initialization, migrates durable state, and
   writes the format marker last.
3. Assign unique run IDs, replace file claims, and expose coordinator-backed status.
4. Queue and serialize integrations across swarm processes.
5. Move planner proposals into the deduplicated coordinator queue.
6. Remove legacy private claim/state files only after migration verification;
   retained worker worktrees and branches are never removed.

Concurrent mixed Looptight versions are unsupported. Migration refuses to start
while legacy activity is visible, and the format marker makes coordinator-aware
legacy code fail closed. Versions predating marker recognition must be stopped
and upgraded before activation; this prerequisite is reported explicitly.

## Testing and Acceptance

Tests use real temporary Git repositories and multiple processes, not only
threads or mocks. Acceptance requires:

- Ten or more concurrent claimers receive distinct tasks.
- Same-directory sessions have distinct run IDs and cannot receive one lease.
- Multiple swarm processes execute workers concurrently but never overlap Git
  integration critical sections.
- Concurrent planners merge and deduplicate grounded proposals without losing an
  accepted task or overwriting a newer queue.
- Killing a lease holder or integrator permits deterministic recovery.
- Crash injection before and after merge, commit, target-ref update, database
  update, and cleanup produces exactly one reachable successful integration result
  and consistent state.
- Expiry, reassignment, and late completion prove fencing rejects the stale owner
  while retaining its worktree.
- Conflicts, failed verification, and non-fast-forward pushes retain recoverable
  work and never force-push.
- Integration-worktree loss, dirtiness, and repair fail safely without touching
  user worktrees.
- SQLite contention timeout, migration races, and mixed-version markers fail
  closed with distinct diagnostics.
- Local-commit/remote-publication divergence reconciles without replaying the
  candidate merge.
- Separate repositories do not share coordinator state.
- Existing CLI and JSON contract tests continue to pass.
