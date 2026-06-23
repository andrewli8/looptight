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


def test_landed_counts_excludes_unmerged_branch(tmp_path):
    root = _repo(tmp_path)
    default = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=root, capture_output=True, text=True).stdout.strip()
    _run(root, "checkout", "-b", "feature")
    (root / "f.txt").write_text("branch")
    _run(root, "commit", "-aqm", "branch\n\nLooptight-Outcome: idea-c landed")
    _run(root, "checkout", default)
    assert "idea-c" not in landed_counts(Path(root), "HEAD")
