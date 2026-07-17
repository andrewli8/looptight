"""Doc-accuracy checks: documented surfaces match the CLI."""

from __future__ import annotations

from pathlib import Path

_DAEMON_DOC = Path(__file__).resolve().parent.parent / "docs" / "daemon.md"
_README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_does_not_overclaim_json_support():
    # `--json` is defined on nine subcommands; init/revert/improve/statusline/ui
    # and the hook/install commands reject it, so the README must not claim every
    # command takes it (a user trying `init --json` per the old text would error).
    text = _README.read_text(encoding="utf-8")
    assert "Every command takes `--json`" not in text
    assert "take `--json`" in text  # it does name the machine-facing commands


def test_readme_surfaces_the_hands_off_stop_hook_loop():
    # install-hook / the hands-off Stop-hook loop is a real capability; the README's "What it
    # can do" should surface it like the other modes.
    text = _README.read_text(encoding="utf-8")
    assert "install-hook" in text, "README does not surface the hands-off Stop-hook loop"


def test_readme_documents_the_revert_recovery_command():
    # revert is a user-facing safety command (undo the agent's uncommitted edits);
    # its peers (init/next/verify/status/propose/goal/doctor) are all in the README
    # Commands list, so revert must be too or a stuck user cannot find their undo.
    text = _README.read_text(encoding="utf-8")
    assert "looptight revert" in text, "README Commands list omits the revert command"


def test_daemon_doc_documents_on_fault_hook():
    text = _DAEMON_DOC.read_text(encoding="utf-8")
    assert "--on-fault" in text
    for field in ("cycle", "reason", "backoff_s", "last_error"):
        assert field in text, f"daemon.md does not name the {field!r} payload field"


_README = Path(__file__).resolve().parent.parent / "README.md"
_DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_usage_doc_local_view_covers_the_session_loop_not_only_swarm():
    # ui/status/statusline now represent the default session loop (claimed task + verify result)
    # and goal mode, not only the swarm; the Local view docs must say so.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    local = text.split("## Local view", 1)[1].split("\n## ", 1)[0]
    assert "claimed task" in local, "Local view docs still describe the UI as swarm-only"
    assert "verify result" in local, "Local view docs do not mention the verify verdict"


def test_usage_doc_local_view_shows_the_verdict_in_goal_mode_and_statusline():
    # The verify verdict now shows in goal mode and is appended to the session statusline; the
    # Local view docs must reflect both so they stay honest about what the surfaces show.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    local = text.split("## Local view", 1)[1].split("\n## ", 1)[0]
    assert "modes the last verify result" in local, "docs tie the verdict to the default loop only"
    assert "· pass" in local, "statusline example omits the appended verify verdict"


def test_usage_doc_documents_the_stop_hook_loop():
    # install-hook + the continue_through_backlog opt-in are real user-facing features; usage.md
    # must document them (they had no docs at all before).
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "install-hook" in text, "usage.md does not document the Stop hook (install-hook)"
    assert "continue_through_backlog" in text, "usage.md does not document the backlog opt-in"


def test_usage_doc_documents_polyglot_discovery():
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "__tests__" in text, "usage.md does not mention colocated JS/TS test discovery"
    assert "it.skip" in text, "usage.md does not mention JS/TS skip discovery"
    # The discovery scope was broadened; the doc must keep up so it does not mislead
    # users about what is supported (a code-vs-doc gap).
    assert ".mts" in text, "usage.md does not mention the .mts/.cts TS module extensions"
    assert ".cy." in text, "usage.md does not mention Cypress .cy. test files"
    assert ".gitignore" in text, "usage.md does not mention .gitignore-aware discovery"


def test_usage_doc_teaches_the_task_authoring_format():
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "Writing your own tasks" in text, "usage.md does not teach task authoring"
    assert "Evidence:" in text and "Acceptance:" in text, "usage.md lacks the task fields"


def test_usage_doc_explains_optional_migrate():
    # doctor hints `migrate` as an optional cross-session step (a solo loop is
    # ready without it); the setup guide must explain what the coordinator is.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "migrate" in text, "usage.md never explains the optional migrate step"
    assert "coordinator" in text, "usage.md does not say what migrate activates"


def test_usage_doc_describes_the_coordinator_claim_model_accurately():
    # The code claims through the SQLite coordinator in ANY git repo from the first
    # `next` (tasks.py); `migrate` fences the legacy file-claim mechanism, it does not
    # switch the store on. usage.md must not say the solo loop runs on "file-based
    # claims" until migrate — that contradicts the code and architecture.md.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "using file-based claims" not in text, (
        "usage.md still claims the solo loop runs on file-based claims; the "
        "coordinator is the claim store in any git repo (see architecture.md)"
    )
    assert "fence" in text.lower(), "usage.md must say migrate fences legacy file claims"


def test_usage_doc_task_example_shows_all_contract_keys():
    # tasks.py always emits idea_id and suggested_verify on every task payload (SPEC lists
    # them in the next contract). The worked task example must show them, or it teaches a
    # task shape narrower than the one the code returns.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert '"idea_id"' in text, "usage.md task example omits the always-present idea_id key"
    assert '"suggested_verify"' in text, (
        "usage.md task example omits the always-present suggested_verify key"
    )


def test_usage_doc_empty_queue_example_matches_default_directive_behaviour():
    # tasks.py returns no_work WITH a generate_ideas directive by default (idea_generation
    # on); a bare {"status": "no_work", "task": null} is only emitted under --no-ideas. The
    # worked example must show the command whose output it prints, or it teaches a contract
    # the default never produces.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    bare = '{"command": "next", "schema_version": 1, "status": "no_work", "task": null}'
    if bare in text:
        before = text.split(bare, 1)[0]
        command_line = before.rsplit("looptight next", 1)[1].split("\n", 1)[0]
        assert "--no-ideas" in command_line, (
            "usage.md prints a bare no_work (no directive) but the command above it omits "
            "--no-ideas; the default emits a generate_ideas directive (tasks.py)"
        )


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


def test_spec_does_not_overclaim_json_support():
    # Only the nine machine-facing commands take --json (init/revert/etc error), so
    # the SPEC must not claim "every primary command" supports it — the same
    # code-vs-doc overclaim already corrected in the README.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert "Every primary command supports" not in spec, "SPEC overclaims --json support"
    assert "machine-facing" in spec, "SPEC does not name the machine-facing --json commands"


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


def test_spec_output_contract_documents_propose_json_bare_list():
    # propose --json is the one machine-facing command that emits a bare ranked
    # candidate list (no schema-version envelope), preserved byte-for-byte. The
    # Output contract must name this exception so it does not read as an oversight.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("## ", 1)[0]
    assert "propose --json" in output_contract
    assert "bare ranked candidate list" in output_contract


def test_spec_output_contract_documents_verify_patience_stall():
    # The session-native value-aware stopping signal must be documented: verify
    # --patience and the additive stall object, with the default contract unchanged.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("## ", 1)[0]
    assert "verify --patience" in output_contract
    assert "stall" in output_contract


def test_spec_output_contract_documents_verify_command():
    # verify --json always emits verify_command (protocol_commands.py); the spec
    # must say so or an agent implementing a client from the spec won't know to use it.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "verify_command" in output_contract


def test_spec_output_contract_verify_command_covers_policy_error_case():
    # verify_command is present in policy-error responses (the command was resolved but
    # blocked), not only in success responses. The SPEC must say so or a consumer
    # implementing a client from the spec will assume verify_command is null in error cases
    # and miss the blocked command. The phrase "blocked by policy" anchors this contract.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "blocked by policy" in output_contract


def test_spec_output_contract_documents_verify_command_in_status():
    # status --json should expose the resolved verify_command alongside verify --json;
    # the SPEC must document this additive field so a consumer knows to read it.
    # Removing "verify_command" from the status JSON description in SPEC must fail this.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "status" in output_contract and "verify_command" in output_contract


def test_spec_output_contract_documents_current_quality_and_idea_quality():
    # SPEC.md:287,290 documents current_quality (additive on no_work next) and
    # idea_quality (additive on status --json); neither has a doc-test lock, so a
    # SPEC edit dropping either field name passes silently.
    # Split on "\n## " (with newline) so backtick-wrapped `## Next` inside the
    # section text doesn't truncate the extract before idea_quality appears.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "current_quality" in output_contract
    assert "idea_quality" in output_contract


def test_spec_output_contract_documents_doctor_json():
    # doctor --json (commands.py cmd_doctor) emits schema_version, command, agent,
    # verify, and readiness; the output contract must name them so integrators
    # know the shape without reading the source.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "doctor --json" in output_contract, "SPEC output contract omits doctor --json"
    assert "readiness" in output_contract, "SPEC output contract omits doctor readiness field"


def test_changelog_unreleased_does_not_claim_solo_loop_runs_on_file_claims():
    # The coordinator is the claim store in any Git repo (tasks.py), per the Fix-B
    # model now in usage.md/architecture.md. The CHANGELOG [Unreleased] must not carry
    # the stale "runs on file claims" mental model the other docs were corrected away
    # from, or the release notes contradict the code.
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    _, _, after = changelog.partition("## [Unreleased]")
    unreleased, _, _ = after.partition("## [0.1.0]")
    assert "runs on file claims" not in unreleased, (
        "CHANGELOG [Unreleased] still claims the solo loop runs on file claims; the "
        "coordinator is the store in any git repo"
    )


def test_unattended_doc_documents_patience_and_escalation():
    # The value-aware stopping control is off by default; the unattended guide must
    # document --patience and what the escalation report surfaces, or the feature
    # is undiscoverable.
    text = (_DOCS / "unattended.md").read_text(encoding="utf-8")
    assert "--patience" in text
    assert "escalation" in text


def test_unattended_doc_shows_model_for_run_or_swarm():
    # --model is available for `run` (cli.py:341) and `swarm` (cli.py:200) but was
    # only documented for `daemon`. Users running a one-off headless session have no
    # docs hint. The unattended guide must show --model in at least one run or swarm
    # example so the flag is discoverable without reading the source.
    text = (_DOCS / "unattended.md").read_text(encoding="utf-8")
    run_and_swarm_section, _, _ = text.partition("## A daemon")
    assert "--model" in run_and_swarm_section, (
        "docs/unattended.md does not show --model in the run or swarm section; "
        "add an example so users can discover the flag without reading source"
    )


def test_usage_doc_names_all_propose_source_values():
    # propose --source accepts exactly five values (cli.py:166); usage.md names them
    # so users can triage the queue without reading source. A test lock keeps the
    # docs in sync if a source name is ever renamed in the argparse definition.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    for value in ("todo", "lint", "skipped-test", "status-next", "task-file"):
        assert value in text, (
            f"docs/usage.md does not mention propose --source value '{value}'; "
            "update the triage paragraph to match cli.py choices"
        )


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


def test_usage_doc_lists_autodetected_ecosystems():
    # init auto-detects the verify command for many ecosystems; usage.md line 12 says
    # only "detects your test command" without naming them. A user with a Rust, JVM,
    # or .NET project cannot tell whether they need to set `verify` manually. The doc
    # must list the detected runners so the surface is honest and discoverable.
    # The assertion covers all runners that detect_verify auto-selects without user
    # intervention; removing any one from usage.md would silently leave a user of that
    # ecosystem without confirmation that looptight will auto-configure their project.
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    for runner in (
        "cargo test",    # detect.py: Cargo.toml
        "gradle test",   # detect.py: build.gradle / build.gradle.kts
        "dotnet test",   # detect.py: *.sln / *.csproj / *.fsproj / *.vbproj
        "crystal spec",  # detect.py: shard.yml — added last; most likely to be dropped
        "swift test",    # detect.py: Package.swift
        "mix test",      # detect.py: mix.exs (Elixir)
    ):
        assert runner in text, f"usage.md does not list the auto-detected runner {runner!r}"


def test_architecture_doc_lists_coordinator_module():
    # docs/architecture.md:23 — the Core modules table lists claims.py as the
    # claim-prevention mechanism but omits coordinator.py, which is now the
    # primary claim store in any Git repo. A reader consulting the table gets an
    # inaccurate model of how the system works.
    text = (_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    core_section = text.split("## Core modules")[1].split("##")[0]
    assert "coordinator.py" in core_section, (
        "docs/architecture.md Core modules table must list coordinator.py "
        "(the primary SQLite claim store for every Git worktree)"
    )


def test_changelog_records_evidence_refs_grounding_gate_fix():
    # Two root causes of the grounding-gate regression must be in [Unreleased]:
    # 1. _EVIDENCE_RE lookbehind: backtick code spans containing `Evidence:` were
    #    captured as false anchors and silently dropped valid tasks.
    # 2. from_task_file pre-Acceptance scoping: the grounding check now covers only
    #    the task text before Acceptance:, so a path in the acceptance criterion
    #    cannot veto an otherwise-valid task.
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    _, _, after = changelog.partition("## [Unreleased]")
    unreleased, _, _ = after.partition("## [0.1.0]")
    assert "_EVIDENCE_RE" in unreleased, (
        "CHANGELOG [Unreleased] does not document the _EVIDENCE_RE lookbehind fix "
        "that prevented backtick code spans from yielding false grounding-gate anchors"
    )
    assert "pre-Acceptance" in unreleased, (
        "CHANGELOG [Unreleased] does not document the from_task_file pre-Acceptance "
        "scoping fix that prevented acceptance-criterion paths from dropping valid tasks"
    )


def test_daemon_doc_cycle_example_uses_unicode_arrow():
    # commands.py prints cycle output with Unicode → (U+2192); the daemon.md example
    # must match so a user comparing terminal output to docs sees the same separator.
    # Dropping → from the example or keeping " -> " must fail this test.
    text = _DAEMON_DOC.read_text(encoding="utf-8")
    cycle_line = next(
        (ln for ln in text.splitlines() if "cycle" in ln and ("→" in ln or " -> " in ln)),
        None,
    )
    assert cycle_line is not None, "daemon.md has no cycle example line"
    assert "→" in cycle_line, "daemon.md cycle example does not use Unicode → (U+2192)"
    assert " -> " not in cycle_line, "daemon.md cycle example uses ASCII -> instead of →"


def test_spec_output_contract_documents_goal_check_json():
    # protocol_commands.py:1057 emits {"schema_version":1,"command":"goal","action":"check",
    # "status":<done|pending|no_goal|no_done_check>}; the SPEC output contract must name all
    # four status values so an integrator building `/loop until: looptight goal check` knows
    # the full shape without reading source. Removing any value must fail this test.
    spec = (_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    output_contract = spec.split("## Output contract", 1)[1].split("\n## ", 1)[0]
    assert "goal check" in output_contract, "SPEC output contract does not mention goal check --json"
    for status in ("done", "pending", "no_goal", "no_done_check"):
        assert status in output_contract, (
            f"SPEC output contract missing goal check status value: {status!r}"
        )
