"""Doc-accuracy checks: documented surfaces match the CLI."""

from __future__ import annotations

from pathlib import Path

_DAEMON_DOC = Path(__file__).resolve().parent.parent / "docs" / "daemon.md"


def test_daemon_doc_documents_on_fault_hook():
    text = _DAEMON_DOC.read_text(encoding="utf-8")
    assert "--on-fault" in text
    for field in ("cycle", "reason", "backoff_s", "last_error"):
        assert field in text, f"daemon.md does not name the {field!r} payload field"


_README = Path(__file__).resolve().parent.parent / "README.md"
_DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_usage_doc_documents_polyglot_discovery():
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "__tests__" in text, "usage.md does not mention colocated JS/TS test discovery"
    assert "it.skip" in text, "usage.md does not mention JS/TS skip discovery"


def test_usage_doc_teaches_the_task_authoring_format():
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "Writing your own tasks" in text, "usage.md does not teach task authoring"
    assert "Evidence:" in text and "Acceptance:" in text, "usage.md lacks the task fields"


def test_usage_doc_explains_migrate_that_doctor_prompts():
    # doctor/readiness surface `run looptight migrate` as setup; the setup guide must
    # explain it (what the coordinator is, and that the loop also runs without it).
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "migrate" in text, "usage.md never explains the migrate step doctor prompts"
    assert "coordinator" in text, "usage.md does not say what migrate activates"


def test_goal_doc_documents_the_goal_command():
    text = (_DOCS / "goal.md").read_text(encoding="utf-8")
    assert "looptight goal" in text, "goal.md does not document the goal command"
    for flag in ("--done", "--continuous", "--max-iterations"):
        assert flag in text, f"goal.md does not document goal's {flag}"
    assert "/loop until: looptight goal check" in text, "goal.md lacks the continuous recipe"


def test_readme_links_to_the_moved_docs():
    text = _README.read_text(encoding="utf-8")
    for link in ("docs/usage.md", "docs/goal.md", "docs/unattended.md", "docs/integrations.md"):
        assert link in text, f"README does not link to {link}"


def test_integrations_doc_documents_ci_and_pre_commit():
    text = (_DOCS / "integrations.md").read_text(encoding="utf-8")
    assert "looptight verify" in text, "integrations.md lacks the verify command"
    assert "GitHub Actions" in text, "integrations.md lacks the GitHub Actions recipe"
    assert "pre-commit" in text, "integrations.md lacks the pre-commit recipe"
    assert "looptight doctor" in text, "integrations.md lacks the doctor readiness gate"


_ROOT = Path(__file__).resolve().parent.parent


def test_pre_commit_hook_definition_is_shipped():
    text = (_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "id: looptight-verify" in text, "missing the looptight-verify hook id"
    assert "entry: looptight verify" in text, "hook does not run looptight verify"


def test_composite_action_is_shipped():
    text = (_ROOT / "action.yml").read_text(encoding="utf-8")
    assert "using: composite" in text, "action.yml is not a composite action"
    assert "looptight verify" in text, "action.yml does not run looptight verify"


def test_release_workflow_publishes_on_a_tag():
    text = (_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text, "release workflow does not trigger on version tags"
    assert "uv publish" in text, "release workflow does not publish to PyPI"
    assert "id-token: write" in text, "release workflow lacks OIDC trusted-publishing permission"


def test_spec_output_contract_names_all_next_task_fields():
    # idea_id and suggested_verify are in every next task dict (tasks.py), so the
    # output contract must name them or integrators cannot discover the full shape.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    for field in ("idea_id", "suggested_verify"):
        assert field in spec, f"SPEC output contract does not document {field!r}"


def test_spec_output_contract_documents_goal_next_fields():
    # goal next --json emits these fields (goal.py GoalDecision.as_dict); the output
    # contract must name them so integrators know the goal-loop shape.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("## ", 1)[0]
    for field in ("schema_version", "command", "status", "iteration", "directive", "reason"):
        assert field in output_contract, f"SPEC output contract omits goal next {field!r}"


def test_spec_output_contract_documents_run_json_and_escalation():
    # run --json (RunResult.as_dict) is the lone command that lacked a JSON contract;
    # the output contract must name it and the additive escalation object.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("## ", 1)[0]
    assert "run --json" in output_contract
    assert "escalation" in output_contract


def test_spec_output_contract_documents_verify_patience_stall():
    # The session-native value-aware stopping signal must be documented: verify
    # --patience and the additive stall object, with the default contract unchanged.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("## ", 1)[0]
    assert "verify --patience" in output_contract
    assert "stall" in output_contract


def test_unattended_doc_documents_patience_and_escalation():
    # The value-aware stopping control is off by default; the unattended guide must
    # document --patience and what the escalation report surfaces, or the feature
    # is undiscoverable.
    text = (_DOCS / "unattended.md").read_text(encoding="utf-8")
    assert "--patience" in text
    assert "escalation" in text


def test_changelog_names_the_current_version():
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.1.0"' in pyproject, "pyproject version changed; update the changelog"
    assert "0.1.0" in changelog, "CHANGELOG does not document the current version"
    assert "Unreleased" in changelog, "CHANGELOG lacks an Unreleased section"


def test_changelog_covers_documented_commands_and_unreleased_changes():
    # The changelog must mention every top-level command the README documents, and
    # the Unreleased section must not be an empty placeholder once changes ship.
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for command in ("doctor", "propose"):
        assert command in changelog, f"CHANGELOG does not mention the {command} command"

    _, _, after_unreleased = changelog.partition("## [Unreleased]")
    unreleased, _, _ = after_unreleased.partition("## [0.1.0]")
    assert unreleased.strip(), "CHANGELOG [Unreleased] section is empty"


def test_license_file_matches_declared_metadata():
    # A publishable package needs a LICENSE file that matches its declared license.
    license_text = (_ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "MIT License" in license_text, "LICENSE is not the MIT license"
    assert 'license = { text = "MIT" }' in pyproject, "pyproject no longer declares MIT"
    assert "Andrew Li" in license_text, "LICENSE is missing the copyright holder"
    assert 'name = "Andrew Li"' in pyproject, "pyproject author drifted from the LICENSE holder"


_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_SRC = Path(__file__).resolve().parent.parent / "src"


def test_readme_dependency_claim_matches_zero_runtime_deps():
    # The package ships with no third-party runtime dependency (pyproject declares an
    # empty `dependencies`, and the stdlib Console replaced rich). The README must not
    # claim a `rich` (or any) runtime dependency, or it contradicts the core principle.
    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject, "pyproject no longer declares zero runtime deps"

    src_imports_rich = any(
        ("import rich" in path.read_text(encoding="utf-8"))
        or ("from rich" in path.read_text(encoding="utf-8"))
        for path in _SRC.rglob("*.py")
    )
    assert not src_imports_rich, "src/ imports rich; the README claim would be accurate again"

    readme = _README.read_text(encoding="utf-8")
    assert "beyond `rich`" not in readme, "README still claims a stale `rich` runtime dependency"
    assert "no third-party runtime" in readme, "README should state there are no runtime deps"


def test_security_policy_documents_reporting_and_model():
    text = (_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Reporting" in text or "report" in text.lower(), "SECURITY.md lacks a reporting path"
    assert "verify" in text, "SECURITY.md does not describe the verify subprocess model"
    assert "force-push" in text, "SECURITY.md does not state the no-force-push guarantee"


def test_bug_report_template_collects_diagnostics():
    text = (_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").read_text(encoding="utf-8")
    assert "looptight --version" in text, "bug template does not ask for the version"
    assert "looptight doctor --json" in text, "bug template does not ask for doctor output"


def test_pull_request_template_reinforces_the_gate():
    text = (_ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "looptight verify" in text, "PR template does not remind contributors to verify"
    assert "ruff check" in text, "PR template does not mention the lint gate"
