"""Multi-process acceptance: distinct claims and planner deduplication.

Every wait here is bounded (drain queues before joining, join with a timeout,
terminate stragglers) so a stuck child can never hang the verify gate.
"""

from __future__ import annotations

import subprocess
from multiprocessing import get_context
from pathlib import Path

from looptight.coordinator import Coordinator

TASKS = [{"id": f"t{i}"} for i in range(10)]
_JOIN_TIMEOUT_S = 30


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    return path


def _drain(output, count):
    """Collect ``count`` results, bounded, so a missing child fails rather than hangs."""
    return [output.get(timeout=_JOIN_TIMEOUT_S) for _ in range(count)]


def _stop(procs):
    for process in procs:
        process.join(_JOIN_TIMEOUT_S)
        if process.is_alive():  # pragma: no cover - straggler safety net
            process.terminate()
            process.join(5)


def _claim_distinct(repo_str, output):
    db = Coordinator.open(Path(repo_str))
    run = db.start_run("acceptance")
    lease = db.claim(TASKS, run.id, ttl_s=60)
    output.put((run.id, lease.task_id if lease else None))
    db.close()


def test_ten_same_directory_claimers_get_distinct_tasks(tmp_path):
    repo = _repo(tmp_path / "r")
    ctx = get_context()
    output = ctx.Queue()
    procs = [ctx.Process(target=_claim_distinct, args=(str(repo), output)) for _ in range(10)]
    for process in procs:
        process.start()
    try:
        rows = _drain(output, len(procs))  # drain BEFORE joining to avoid feeder deadlock
    finally:
        _stop(procs)
    assert len({row[0] for row in rows}) == 10  # ten distinct runs
    assert len({row[1] for row in rows}) == 10  # each got a distinct task


def _submit(repo_str, candidates, done):
    db = Coordinator.open(Path(repo_str))
    run = db.start_run("planner")
    db.submit_proposals(run.id, candidates, "gen-1")
    db.close()
    done.put(True)


def test_concurrent_planners_preserve_distinct_and_dedupe_equivalent(tmp_path):
    repo = _repo(tmp_path / "r")
    ctx = get_context()
    done = ctx.Queue()
    procs = [
        ctx.Process(target=_submit, args=(str(repo), candidates, done))
        for candidates in ([{"id": "A"}, {"id": "B"}], [{"id": "B"}, {"id": "C"}])
    ]
    for process in procs:
        process.start()
    try:
        _drain(done, len(procs))
    finally:
        _stop(procs)

    db = Coordinator.open(repo)
    fingerprints = {
        row[0] for row in db.connection.execute("SELECT fingerprint FROM tasks").fetchall()
    }
    assert fingerprints == {"A", "B", "C"}  # equivalent proposals deduped to one task each
