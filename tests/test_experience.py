import subprocess
from pathlib import Path

from looptight.experience import (
    Model,
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


def test_summary_text_bounded_and_empty_when_no_data():
    assert summary_text(Model()) == ""
    m = Model(landed={"a": 3, "b": 1}, failed={"x": 2})
    text = summary_text(m, k=5)
    assert "x" in text  # avoid list mentions the failed idea
    assert text.count("\n") <= 6  # bounded
