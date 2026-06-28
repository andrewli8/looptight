"""Stable task identity contracts."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from looptight.propose import Candidate
from looptight.tasks import _has_dirty_git_worktree, _summary_and_evidence, next_task


def test_has_dirty_git_worktree_sets_terminal_prompt_env(tmp_path):
    # _has_dirty_git_worktree's `git status` must pass GIT_TERMINAL_PROMPT=0 so a headless
    # `looptight next` can never block waiting on a git credential prompt.
    import looptight.tasks as tasks_mod

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(tasks_mod.subprocess, "run", fake_run):
        _has_dirty_git_worktree(tmp_path)

    assert "env" in captured, "_has_dirty_git_worktree must pass an explicit env"
    assert captured["env"].get("GIT_TERMINAL_PROMPT") == "0"


def _candidate(title: str, detail: str) -> Candidate:
    return Candidate(
        title=title,
        source="status-next",
        location="docs/STATUS.md:5",
        suggested_verify=None,
        score=0.0,
        detail=detail,
        acceptance="it passes.",
    )


def test_summary_and_evidence_splits_inline_evidence():
    candidate = _candidate(
        "Cover the parser. Evidence: src/p.py:3",
        "Cover the parser. Evidence: src/p.py:3; Acceptance: it passes.",
    )
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "Cover the parser"  # refs stripped from the summary
    assert evidence == "Evidence: src/p.py:3"


def test_summary_and_evidence_strips_markdown_emphasis_around_marker():
    # A bold marker (**Evidence:**) leaves '**' straddling the split: the opening
    # in the summary, the closing in the evidence. Neither should leak.
    candidate = _candidate(
        "Add a docstring. **Evidence:** `src/p.py:3`",
        "Add a docstring. **Evidence:** `src/p.py:3`; Acceptance: it passes.",
    )
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "Add a docstring"
    assert evidence == "Evidence: `src/p.py:3`"


def test_summary_and_evidence_preserves_multiple_refs():
    candidate = _candidate(
        "Do the thing. Evidence: src/a.py:1; Evidence: tests/test_a.py:2",
        "Do the thing. Evidence: src/a.py:1; Evidence: tests/test_a.py:2; Acceptance: it passes.",
    )
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "Do the thing"
    assert evidence == "Evidence: src/a.py:1; Evidence: tests/test_a.py:2"


def test_summary_and_evidence_falls_back_to_detail_without_marker():
    # Ad-hoc signals (todo/lint) carry no inline marker; their detail is the evidence.
    candidate = _candidate("# TODO: fix the timeout", "# TODO: fix the timeout")
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "# TODO: fix the timeout"
    assert evidence == "# TODO: fix the timeout"


def test_next_task_attaches_idea_id(tmp_path):
    cand = Candidate(title="fix E501: line too long", source="lint",
                     location="src/looptight/foo.py:10", suggested_verify=None,
                     score=60.0, detail="line too long", acceptance="ruff clean")

    def fake_propose(workdir, limit=0):
        return [cand]

    result = next_task(tmp_path, propose_fn=fake_propose)
    assert result.status == "task"
    from looptight.idea_identity import idea_id
    assert result.task["idea_id"] == idea_id(cand)


def test_task_id_is_stable_when_discovery_route_changes(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # One logical session (stable run id) re-claims its own lease, so the second
    # call returns the same task and we can assert fingerprint stability across
    # discovery routes rather than tripping over the coordinator's distinct-run fencing.
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "stable-session")

    def candidate(source):
        return Candidate(
            title="Fix the same task",
            source=source,
            location="docs/STATUS.md:10",
            suggested_verify=None,
            score=0.0,
            detail="same evidence",
            acceptance="same acceptance",
        )

    first = next_task(tmp_path, propose_fn=lambda root, limit: [candidate("status-next")])
    second = next_task(tmp_path, propose_fn=lambda root, limit: [candidate("task-file")])

    assert first.task is not None and second.task is not None
    assert first.task["id"] == second.task["id"]
    assert second.task["source"] == "task-file"


def test_curated_claim_id_is_stable_across_status_line_drift(tmp_path):
    # status-next/task-file live in docs/STATUS.md, whose line numbers shift as the
    # Validated section grows. The claim id must NOT change with the line, or a
    # re-queued task gets a fresh fingerprint each rewrite and is silently skipped.
    from looptight.discovery import Candidate
    from looptight.tasks import next_task

    def candidate(line):
        return [
            Candidate(
                title="Finish the experience reweighting",
                source="status-next",
                location=f"docs/STATUS.md:{line}",
                suggested_verify=None,
                score=65.0,
                detail="Finish reweighting. Evidence: src/looptight/experience.py:1",
                acceptance="boost works and is covered by a test",
            )
        ]

    id_a = next_task(tmp_path, propose_fn=lambda w, limit=0: candidate(10)).task["id"]
    id_b = next_task(tmp_path, propose_fn=lambda w, limit=0: candidate(412)).task["id"]
    assert id_a == id_b  # same curated task, different line => same claim fingerprint


def test_curated_claim_id_differs_by_title(tmp_path):
    from looptight.discovery import Candidate
    from looptight.tasks import next_task

    def candidate(title):
        return [
            Candidate(title=title, source="status-next", location="docs/STATUS.md:10",
                      suggested_verify=None, score=65.0, detail=f"{title}. Evidence: x:1",
                      acceptance="done")
        ]

    a = next_task(tmp_path, propose_fn=lambda w, limit=0: candidate("Task A")).task["id"]
    b = next_task(tmp_path, propose_fn=lambda w, limit=0: candidate("Task B")).task["id"]
    assert a != b


def _leaked_candidate():
    return [
        Candidate(
            title="Do the leaked task",
            source="status-next",
            location="docs/STATUS.md:10",
            suggested_verify=None,
            score=65.0,
            detail="Do it. Evidence: src/x.py:1",
            acceptance="done",
        )
    ]


def test_next_task_reclaims_abandoned_run_lease(tmp_path):
    # A one-shot `next` that claims a task then exits leaves the lease held by an
    # abandoned run. The lease's 24h TTL has not expired, so without reaping the loop
    # would stall for a full day. A later `next` must reclaim it WITHOUT that wait.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    probe = next_task(tmp_path, propose_fn=lambda w, limit=0: _leaked_candidate(), run_id="probe")
    assert probe.status == "task"

    # Simulate the probe process dying: its heartbeat falls far behind the reap
    # deadline while the long lease still looks live to the TTL check.
    from looptight.coordinator import Coordinator

    coord = Coordinator.open(tmp_path)
    coord.connection.execute("UPDATE runs SET heartbeat = 0 WHERE id = 'probe'")
    coord.close()

    reclaimed = next_task(tmp_path, propose_fn=lambda w, limit=0: _leaked_candidate(), run_id="loop")
    assert reclaimed.status == "task"  # abandoned lease reaped, task reclaimed
    assert reclaimed.task["id"] == probe.task["id"]


def test_next_task_does_not_reap_a_fresh_live_lease(tmp_path):
    # Active-lease fencing for live runs is unchanged: a run that just claimed keeps
    # its lease (heartbeat is fresh, not past the reap deadline), so a concurrent run
    # cannot steal the same task out from under it.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    owner = next_task(tmp_path, propose_fn=lambda w, limit=0: _leaked_candidate(), run_id="owner")
    assert owner.status == "task"

    other = next_task(tmp_path, propose_fn=lambda w, limit=0: _leaked_candidate(), run_id="other")
    assert other.status == "no_work"  # fresh lease spared; the other run gets nothing
    # Busy, not empty: a candidate exists but is leased, so do not prompt idea
    # generation — that would inflate the queue with duplicate tasks.
    assert other.directive is None


def test_next_task_skips_candidate_with_empty_acceptance(tmp_path):
    # Every claimable task must carry an observable acceptance criterion, so a
    # candidate with empty acceptance is not runnable and must be filtered out.
    bad = Candidate(
        title="Do a thing", source="status-next", location="docs/STATUS.md:5",
        suggested_verify=None, score=0.0, detail="Do a thing.", acceptance="",
    )
    result = next_task(tmp_path, propose_fn=lambda w, limit=0: [bad])
    assert result.status == "no_work"  # acceptance-less candidate is not surfaced


def test_next_keeps_idea_directive_when_queue_is_genuinely_empty(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    result = next_task(tmp_path, propose_fn=lambda w, limit=0: [])
    assert result.status == "no_work"
    assert result.directive is not None  # no candidates at all -> generate ideas


def test_idea_directive_carries_quality_feedback(tmp_path):
    from looptight.tasks import _idea_directive

    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# a\n", encoding="utf-8")
    (docs / "STATUS.md").write_text(
        "## Next\n\n1. Harden a. Evidence: src/a.py:1; Acceptance: it passes.\n",
        encoding="utf-8",
    )
    directive = _idea_directive(tmp_path)
    assert directive["current_quality"]["size"] == 1
    assert directive["current_quality"]["groundedness"] == 1.0

    # An empty queue carries a null feedback signal, not a missing key.
    (docs / "STATUS.md").write_text("## Next\n\n_drained_\n", encoding="utf-8")
    assert _idea_directive(tmp_path)["current_quality"] is None


def test_has_dirty_git_worktree_returns_false_on_oserror(tmp_path, monkeypatch):
    # When the git subprocess cannot be launched (OSError), _has_dirty_git_worktree
    # must return False rather than propagating the exception, so next_task can
    # proceed outside environments with git on PATH.
    import looptight.tasks as tasks_module

    monkeypatch.setattr(
        tasks_module.subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("git not found")),
    )
    assert _has_dirty_git_worktree(tmp_path) is False


def test_has_dirty_git_worktree_returns_false_on_nonzero_returncode(tmp_path, monkeypatch):
    # When git status exits non-zero (e.g. 128 outside a repo), the function
    # must return False via the `returncode == 0` short-circuit at tasks.py:90.
    import looptight.tasks as tasks_module

    monkeypatch.setattr(
        tasks_module.subprocess,
        "run",
        lambda *a, **kw: __import__("subprocess").CompletedProcess(
            a[0], 128, stdout="", stderr="not a git repo"
        ),
    )
    assert _has_dirty_git_worktree(tmp_path) is False
