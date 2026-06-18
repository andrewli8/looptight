# Status

Tracks the spec ([`SPEC.md`](SPEC.md)) against what's actually built.

| Group | Feature | Status |
|-------|---------|--------|
| A1 | Single-command install (`uvx`/`pipx`/`pip`) | ✅ packaged |
| A2 | Zero-config first run (autodetect agent + verify) | ✅ |
| A3 | One concept: `verify` (`init` writes + explains) | ✅ |
| A4 | Auth-neutral (use the agent's existing auth) | ✅ by design |
| B1 | Drive the native loop where it exists (`--native`) | ✅ Claude `/goal` |
| B2 | Supply the loop (all three agents) | ✅ |
| B3 | Verify is the ground-truth oracle | ✅ |
| B4 | Normalized surface across backends | ✅ (`RunResult`) |
| C1 | Reflection on failure → one specific lesson | ✅ |
| C2 | Persist lessons into the agent's memory file | ✅ |
| C3 | Lessons compound across runs/goals | ✅ |
| C4 | Lesson hygiene (scope, dedupe, prune) | ✅ |
| D1 | Hard iteration cap + cost ceiling | ✅ |
| D2 | Live counter | ✅ |
| D3 | Cheap-model routing for reflection | ✅ (Claude: haiku) |
| D4 | Per-iteration git checkpoint + revert | ✅ |
| E1 | Readable run summary | ✅ |
| E2 | Gif-able output | ✅ |
| F1 | Adapter interface (3 agents registered) | ✅ |
| F2 | Auth-neutral | ✅ |
| F3 | ACP transport | ⏳ post-v1 (deferred) |

## Correction to the spec (June 2026)

The spec predates Claude Code's `/goal` (shipped ~May 2026), so it treated only
Codex as having a native loop. Reality:

- **Claude Code** has `/goal`, drivable headlessly via `claude -p "/goal …"`.
  looptight drives it with `--native`.
- **Codex** runs headless via `codex exec`; driving its interactive `/goal`
  headlessly is unconfirmed, so we supply the loop around `codex exec` rather
  than fake a delegate path.
- **opencode** runs headless via `opencode run`; no goal primitive → supply.

The design absorbed this cleanly: `verify` is always the ground-truth oracle, so
supply and delegate produce identical summaries and both write lessons.

## What's wired

All three adapters are real and shell out to their confirmed headless commands
(`claude -p` / `codex exec` / `opencode run`); Claude additionally drives `/goal`
under `--native`. The whole control flow is unit-tested with injected fakes (no
agent, no network); the opt-in `tests/e2e_test.py` exercises a real agent.

Known limitations: Codex JSON output reports token usage, not USD cost, and
opencode JSON output is still unobserved here. Those runs are bounded by the
iteration cap rather than the dollar ceiling unless a model/pricing conversion
is added; cheap-model reflection (D3) is wired for Claude (`haiku`) and falls
back to the default model elsewhere.

## Next

1. Confirm whether Codex `/goal` can be driven headlessly; if so, flip
   `supports_native_loop` on and add `drive_native_loop`.
2. Decide whether to add token-to-USD pricing for observed `codex exec --json`
   usage events; observe `opencode run -f json` before attempting opencode cost
   parsing.
3. Record the flagship gif: the same command across agents, then a second task
   that benefits from a lesson written in the first run.
