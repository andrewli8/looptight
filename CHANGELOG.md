# Changelog

All notable changes to looptight are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims for
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

First release: a test-gated work loop that runs inside a coding agent's session.

- `next` and `verify`: the session-native loop, with no model or network calls.
- Grounded task discovery from real repo signals (TODO/FIXME, skipped tests, lint,
  the `## Next` list, configured task files); polyglot across Python and JS/TS.
- `goal` mode: a vision-driven 0-to-1 build, one verify-gated increment at a time.
- Unattended modes: `run`, `swarm`, and `daemon`, with a repo-private SQLite
  coordinator for sharing one queue across sessions.
- Observability: `status`, `status --watch`, `ui`, and `statusline`.
- Integrations: `install-skill`, `init --integrate`, a pre-commit hook, and a
  composite GitHub Action.
- Zero third-party runtime dependencies; the package runs on the standard library.
