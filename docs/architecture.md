# Architecture

Looptight is a provider-neutral task and validation protocol around a native
coding-agent session.

```text
project evidence → propose → next + atomic claim → native agent edits
                                             ↓
commit ← passing verdict ← verify command ← review
```

## Decision boundaries

- `discovery.py` reads concrete repository signals into candidate tasks.
- `ranking.py` dedupes and orders those candidates by a transparent heuristic.
- `propose.py` composes discovery and ranking into the public candidate list.
- `tasks.py` turns the first available candidate into versioned `next` output.
- `claims.py` prevents duplicate work across Git worktrees using private atomic
  files under the repository's common Git directory.
- `verify.py` executes the project contract and distinguishes a valid pass/fail
  verdict from timeout or launch errors.
- `commands.py` exposes the protocol as text and versioned JSON.
- `integration.py` installs the same small loop instruction for Codex, Claude
  Code, and OpenCode.

These modules make no agent or network calls. Provider authentication, model
selection, context, and usage limits remain inside the active agent CLI.

## Optional headless path

`loop.py` and `adapters/` remain as an explicit `run --headless` compatibility
path. They launch one provider CLI iteration, run the same verifier, and repeat
under an iteration cap. They do not reflect, generate lessons, estimate costs,
or select repository work.

The deprecated `improve` command is a migration message only; there is no
second continuous-loop engine.

## Validation order

1. Validate configuration and task evidence.
2. Atomically claim the task when Git-private state is available.
3. Let the native agent implement it.
4. Require the verifier to execute normally.
5. Treat only exit zero as pass.
6. Review the diff and commit; remove completed evidence from the bounded plan.

Heuristics can rank tasks or identify stalled progress. They cannot grant a
passing verdict.
