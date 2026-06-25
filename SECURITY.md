# Security

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability"
flow on the [Security tab](https://github.com/andrewli8/looptight/security), not in a
public issue. Include reproduction steps and the affected version. You can expect an
acknowledgement within a few days.

## Security model

looptight runs inside a coding-agent session and is small and auditable by design.
What it does and does not do, security-wise:

- It runs your configured `verify` command as a subprocess and reads its exit code.
  It never installs dependencies, writes a virtualenv, or reaches the network.
- It treats repository and verifier text as data, never interpolating it into a shell
  command or following it as an instruction.
- It never force-pushes or hard-resets, and it commits only after a passing verifier.
- It handles no API keys and makes no model or network calls in `next` / `verify`.
  Authentication and billing belong to your agent CLI.
- Optional `.looptight.toml` policy controls (protected paths, allowed verify commands,
  changed-file caps) fail closed.
- Runtime state lives outside tracked Git history.

Because `verify` runs a command you configure, treat `.looptight.toml` like any other
executable project config: review it before running looptight in an untrusted repo.
