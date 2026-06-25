# Integrations

looptight is a single command with stable exit codes, so it drops into the places
you already gate changes: CI and pre-commit. `looptight verify` exits `0` on a pass,
`1` on a real failing verdict, and `2` on a config or runner error, so a gate fails
for the right reason.

## GitHub Actions

Run the same verifier in CI that the loop runs locally:

```yaml
# .github/workflows/verify.yml
name: verify
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install looptight
      - run: looptight verify --json
```

The `--json` verdict tells `pass`, `fail`, `timeout`, and `error` apart, so a crashed
runner never looks like failing code.

## Pre-commit

Run the verifier before every commit so a failing change never lands locally.

With [pre-commit](https://pre-commit.com):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: looptight-verify
        name: looptight verify
        entry: looptight verify
        language: system
        pass_filenames: false
```

Or a plain Git hook:

```bash
# .git/hooks/pre-commit
#!/bin/sh
exec looptight verify
```

## Claude Code

`looptight install-skill` lets Claude Code discover looptight in any session, and
`looptight init --integrate` wires the loop into a repository's `CLAUDE.md`. See
[usage.md](usage.md).
