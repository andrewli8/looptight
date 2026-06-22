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

## Coordinator State

The initial schema contains:

- `runs`: run ID, process identity, kind, state, timestamps, and heartbeat.
- `tasks`: stable task fingerprint, grounded payload, state, and timestamps.
- `leases`: task ID, run ID, expiry, and attempt number.
- `proposals`: planner run ID, task fingerprint, payload, and disposition.
- `integrations`: FIFO sequence, run ID, task ID, branch, base commit, state,
  error, and timestamps.

Schema creation and migrations are transactional and versioned through
`PRAGMA user_version`. Payloads remain versioned JSON where Looptight already has
public JSON contracts; database rows are private implementation state.

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

Workers always receive distinct worktrees and branches. Existing scope checks,
provider timeouts, verification, retained failure worktrees, and interruption
cleanup remain in force.

## Integration

Completed workers enqueue branch metadata rather than merging directly. The
integrator first acquires `<git-common-dir>/looptight/integration.lock`, then
processes one record at a time:

1. Confirm the candidate lease and branch still belong to the submitting run.
2. Refresh the integration worktree and compare the recorded base with current
   target HEAD.
3. Attempt the merge without committing.
4. Run the full verifier.
5. Commit on success; abort and retain the worker worktree on conflict or failure.
6. Atomically record the outcome, release the task lease, and advance the queue.
7. Push only when explicitly requested; a non-fast-forward push refreshes and
   returns the integration to the queue rather than force-pushing.

Git integration remains intentionally serial per repository. Planning and worker
execution scale concurrently; merge, commit, and push do not.

## Failure and Recovery

- SQLite busy waits are bounded and reported distinctly from provider timeouts.
- Run heartbeats expose active and abandoned sessions without deciding task
  ownership by wall-clock state alone.
- Expired task leases are recoverable; completed integration records are durable.
- A crashed integrator releases its advisory lock automatically. On the next
  attempt, Git merge state is inspected and safely aborted before processing a
  queued item.
- Corrupt or unsupported coordinator schemas fail closed with recovery guidance;
  Looptight never deletes tracked files or force-pushes.
- The existing JSON status surface derives a backward-compatible projection from
  coordinator state.

## Compatibility and Rollout

The CLI remains unchanged for normal use. `next`, `status`, `swarm`, and the UI
open the repository coordinator automatically. Existing JSON fields remain
compatible; new run and queue metadata is additive.

Rollout is incremental:

1. Introduce the SQLite coordinator and replace file-based task claims.
2. Assign unique run IDs and expose coordinator-backed status.
3. Queue and serialize integrations across swarm processes.
4. Move planner proposals into the deduplicated coordinator queue.
5. Remove legacy private claim/state files only after compatibility tests prove
   migration; retained worker worktrees and branches are never removed by the
   migration.

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
- Conflicts, failed verification, and non-fast-forward pushes retain recoverable
  work and never force-push.
- Separate repositories do not share coordinator state.
- Existing CLI and JSON contract tests continue to pass.
