import subprocess
from pathlib import Path
from unittest.mock import patch

from looptight.experience import (
    Model,
    landed_category_counts,
    landed_counts,
    reweight_factor,
    summary_text,
    suppressed,
)


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


def test_landed_counts_excludes_unmerged_branch(tmp_path):
    root = _repo(tmp_path)
    default = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=root, capture_output=True, text=True).stdout.strip()
    _run(root, "checkout", "-b", "feature")
    (root / "f.txt").write_text("branch")
    _run(root, "commit", "-aqm", "branch\n\nLooptight-Outcome: idea-c landed")
    _run(root, "checkout", default)
    assert "idea-c" not in landed_counts(Path(root), "HEAD")


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


def test_reweight_factor_equal_split_returns_midpoint():
    m = Model(category_landed={"lint": 1}, category_failed={"lint": 1})
    assert reweight_factor("lint", m, lo=0.5, hi=1.5) == 1.0


def test_summary_text_bounded_and_empty_when_no_data():
    assert summary_text(Model()) == ""
    m = Model(landed={"a": 3, "b": 1}, failed={"x": 2})
    text = summary_text(m, k=5)
    assert "x" in text  # avoid list mentions the failed idea
    assert text.count("\n") <= 6  # bounded


def test_summary_text_returns_empty_when_only_category_failed_is_set():
    # category_failed feeds reweight_factor but NOT the planner note: the guard
    # at experience.py:115 checks failed/category_landed/category_failure_reasons,
    # intentionally omitting category_failed which is advisory-only.
    assert summary_text(Model(category_failed={"lint": 2})) == ""


def test_summary_text_keeps_only_the_top_k_failed_ideas_by_count():
    # With more failed ideas than k, the avoid list is bounded to the k
    # highest-count ideas, in descending order. The existing bounded-test uses
    # fewer than k ideas, so the truncation/ordering at experience.py:115 was
    # never exercised; a regression that dropped `[:k]` or broke the sort would
    # flood or misrank the planner note unnoticed.
    failed = {"a": 70, "b": 60, "c": 50, "d": 40, "e": 30, "f": 20, "g": 10}
    text = summary_text(Model(failed=failed), k=5)
    avoid_line = next(line for line in text.splitlines() if line.startswith("Recently-failed"))
    names = [n.strip(" .") for n in avoid_line.split(":", 1)[1].split(",")]
    assert names == ["a", "b", "c", "d", "e"]  # top-5 by count, descending
    assert "f" not in names and "g" not in names  # the two lowest are dropped


def test_summary_text_names_paid_off_sources_not_opaque_ids():
    # The positive-signal line must name actionable task SOURCES the planner can steer
    # toward (favor status-next), not 12-hex idea_id hashes it has no mapping for.
    m = Model(
        landed={"a3f2c1": 9},  # opaque per-idea ids must NOT drive the prose note
        category_landed={"status-next": 5, "todo": 2},
    )
    text = summary_text(m)
    line = next(line for line in text.splitlines() if "paid off" in line)
    assert "status-next" in line and "todo" in line
    assert line.index("status-next") < line.index("todo")  # descending by count
    assert "a3f2c1" not in text  # opaque idea id never reaches the planner prose


def test_summary_text_surfaces_failure_modes_by_source():
    # Attribution capture: the note names WHY a source tends to fail, so the host can
    # avoid the failure mode (e.g. "scope") rather than just an opaque idea id.
    m = Model(category_failure_reasons={"status-next": "scope", "lint": "timeout"})
    text = summary_text(m)
    assert "status-next" in text and "scope" in text
    assert "timeout" in text
    assert text.count("\n") <= 6  # still bounded


def test_summary_text_with_all_three_conditions():
    # experience.py:113 — each condition (failed, category_landed, category_failure_reasons)
    # is tested in isolation but never all three non-empty together. A regression that adds an
    # early `return` or short-circuits the loop after the first branch would be invisible to
    # the existing suite. This test requires all three output lines to be present.
    m = Model(
        failed={"idea-x": 3},
        category_landed={"todo": 4},
        category_failure_reasons={"lint": "timeout"},
    )
    text = summary_text(m)
    assert "idea-x" in text               # failed branch
    assert "todo" in text                 # category_landed branch
    assert "timeout" in text              # category_failure_reasons branch
    assert text.count("\n") == 2          # exactly three lines (two separating newlines)


def test_build_model_populates_category_landed_from_trailers(tmp_path):
    from looptight.experience import build_model

    root = _repo(tmp_path)
    _run(root, "commit", "--allow-empty", "-qm", "w1\n\nLooptight-Outcome: idea-a landed lint")
    _run(root, "commit", "--allow-empty", "-qm", "w2\n\nLooptight-Outcome: idea-b landed lint")
    _run(root, "commit", "--allow-empty", "-qm", "w3\n\nLooptight-Outcome: idea-c landed todo")
    model = build_model(Path(root), "HEAD", None, cooldown_s=1000.0)
    assert model.category_landed == {"lint": 2, "todo": 1}  # boost signal by source
    assert model.landed == {"idea-a": 1, "idea-b": 1, "idea-c": 1}  # per-idea still parsed


class _FakeCoord:
    def recent_failures(self, *, window_s, now=None):
        return {}

    def failure_counts(self):
        return {}

    def failure_reasons(self):
        return {"status-next": "scope"}


def test_build_model_populates_failure_reasons_from_coordinator(tmp_path):
    from looptight.experience import build_model

    root = _repo(tmp_path)
    model = build_model(Path(root), "HEAD", _FakeCoord(), cooldown_s=1000.0)
    assert model.category_failure_reasons == {"status-next": "scope"}


def test_reweight_boosts_a_high_yield_category_from_built_model(tmp_path):
    from looptight.experience import build_model, reweight_factor

    root = _repo(tmp_path)
    _run(root, "commit", "--allow-empty", "-qm", "w\n\nLooptight-Outcome: idea-a landed lint")
    model = build_model(Path(root), "HEAD", None, cooldown_s=1000.0)
    assert reweight_factor("lint", model) > 1.0  # landed, no failures => boost


def test_build_model_coordinator_none_produces_empty_failure_dicts(tmp_path):
    from looptight.experience import build_model

    root = _repo(tmp_path)
    model = build_model(Path(root), "HEAD", None, cooldown_s=1000.0)
    assert model.failed == {}
    assert model.category_failed == {}
    assert model.category_failure_reasons == {}


def test_landed_category_counts_skips_trailer_without_source(tmp_path):
    # A trailer value with only 2 tokens ("idea-a landed") has no source; it must
    # be skipped by landed_category_counts while landed_counts still sees the idea.
    root = _repo(tmp_path)
    _run(root, "commit", "--allow-empty", "-qm",
         "w\n\nLooptight-Outcome: idea-a landed")
    assert landed_category_counts(Path(root), "HEAD") == {}
    assert landed_counts(Path(root), "HEAD") == {"idea-a": 1}


def test_landed_counts_ignores_non_landed_outcome_trailers(tmp_path):
    # experience.py:47 — the guard `parts[1] != "landed"` must exclude "failed"
    # and other non-landing outcomes so coordinator-recorded failures written as
    # trailers are never counted as landed. A mutation inverting the filter would
    # count "idea-x failed" as a land and not be caught without this test.
    root = _repo(tmp_path)
    _run(root, "commit", "--allow-empty", "-qm",
         "w1\n\nLooptight-Outcome: idea-x failed lint")
    _run(root, "commit", "--allow-empty", "-qm",
         "w2\n\nLooptight-Outcome: idea-y skipped")
    # Neither "failed" nor "skipped" outcome should appear in landed counts.
    counts = landed_counts(Path(root), "HEAD")
    assert "idea-x" not in counts
    assert "idea-y" not in counts
    # landed_category_counts (experience.py:66) has the symmetric guard; also verify.
    cat_counts = landed_category_counts(Path(root), "HEAD")
    assert cat_counts == {}


def test_reweight_factor_is_neutral_for_unknown_category():
    # A category with no landed/failed history (total == 0) yields the neutral 1.0.
    assert reweight_factor("unknown-source", Model()) == 1.0


def test_landed_counts_returns_empty_when_git_not_found(tmp_path):
    # When git is not on PATH, _git() catches OSError and returns returncode=127;
    # landed_counts must silently return {} rather than propagating the error.
    with patch("looptight.experience.subprocess.run", side_effect=OSError("git not found")):
        assert landed_counts(tmp_path, "HEAD") == {}


def test_landed_category_counts_returns_empty_when_git_not_found(tmp_path):
    # When git is not on PATH, _git() catches OSError and returns returncode=127;
    # the returncode != 0 guard at experience.py:61 must return {} without propagating.
    with patch("looptight.experience.subprocess.run", side_effect=OSError("git not found")):
        assert landed_category_counts(tmp_path, "HEAD") == {}


def test_landed_category_counts_returns_empty_on_nonzero_returncode(tmp_path):
    # experience.py:61 guard: when git exits non-zero (e.g. bad ref → 128),
    # landed_category_counts must return {} without raising.
    with patch(
        "looptight.experience.subprocess.run",
        return_value=subprocess.CompletedProcess(["git"], 128, stdout="", stderr=""),
    ):
        assert landed_category_counts(tmp_path, "bad-ref") == {}


def test_landed_counts_returns_empty_on_nonzero_returncode(tmp_path):
    # experience.py:42 guard: when git exits non-zero (e.g. bad ref → 128),
    # landed_counts must return {} without raising.
    # Mirror of test_landed_category_counts_returns_empty_on_nonzero_returncode.
    with patch(
        "looptight.experience.subprocess.run",
        return_value=subprocess.CompletedProcess(["git"], 128, stdout="", stderr=""),
    ):
        assert landed_counts(tmp_path, "bad-ref") == {}


def test_experience_git_sets_terminal_prompt_env(tmp_path):
    # _git() in experience.py must pass GIT_TERMINAL_PROMPT=0 so a headless
    # git log call cannot hang waiting for a credential prompt.
    import looptight.experience as exp

    captured_kwargs: dict = {}

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(exp.subprocess, "run", fake_run):
        exp._git(tmp_path, "log")

    assert "env" in captured_kwargs, "_git must pass an explicit env"
    assert captured_kwargs["env"].get("GIT_TERMINAL_PROMPT") == "0"


def test_landed_counts_ignores_bare_landed_token(tmp_path):
    # A one-token trailer line "landed" passes the "landed" in line guard but
    # line.split()[0] would yield "landed" as the idea key — a synthetic key that
    # could skew proposal ranking. The function must ignore it (return {}).
    with patch(
        "looptight.experience.subprocess.run",
        return_value=subprocess.CompletedProcess(["git"], 0, stdout="landed\n", stderr=""),
    ):
        assert landed_counts(tmp_path, "HEAD") == {}
