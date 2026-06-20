# Status

Tracks the spec ([`SPEC.md`](SPEC.md)) against what's actually built.

The table below records the v0.1 implementation. The v0.2 product direction
deliberately retires several completed experiments instead of treating their
existence as a reason to keep them.

## v0.2 validation protocol

| Feature | Status |
|---------|--------|
| Versioned `verify --json` verdict | ✅ schema v1 |
| Distinct pass/fail/timeout/error outcomes | ✅ |
| Reject internally contradictory verdicts | ✅ |
| Versioned `next --json` task contract | ✅ schema v1 |
| Task evidence and claim validation | ⏳ |
| Pre-commit claim + passing-verdict validation | ⏳ |

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
| D1 | Hard iteration cap + post-iteration spend threshold | ✅ |
| D2 | Live counter | ✅ |
| D3 | Cheap-model routing for reflection | ✅ (Claude: haiku) |
| D4 | Per-iteration tracked-file git checkpoint + revert | ✅ |
| E1 | Readable run summary | ✅ |
| E2 | Gif-able output | ✅ |
| F1 | Adapter interface (3 agents registered) | ✅ |
| F2 | Auth-neutral | ✅ |
| F3 | ACP transport | ⏳ post-v1 (deferred) |
| G1 | Continuous autonomous improvement (`improve`) | ✅ |
| G2 | Verified auto-commit + opt-in push | ✅ |
| G3 | Provider-limit default + optional session spend threshold | ✅ |

## Correction to the spec (June 2026)

The spec predates Claude Code's `/goal` (shipped ~May 2026), so it treated only
Codex as having a native loop. Reality:

- **Claude Code** has `/goal`, drivable headlessly via `claude -p "/goal …"`.
  looptight drives it with `--native`.
- **Codex** runs headless via `codex exec`. Its `/goal` (the stable `goals`
  feature, default-on in Codex 0.141.0) is *not* an eval-gated loop: it's an
  interactive objective + token-budget tracker the model self-manages via
  `create_goal`/`update_goal`. The tool takes only `objective` and
  `token_budget` (no verify command), gates on a token budget and a
  self-assessed status, and is a TUI slash command — the headless entry,
  `codex exec`, takes a prompt, not slash commands. Driving it as a native loop
  would mean self-grading, which principle 3 forbids, so we keep supplying the
  loop around `codex exec` and `supports_native_loop` stays `False`.
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
iteration cap rather than the dollar ceiling. We will not estimate Codex USD
cost from tokens: the observed event has no billed cost, and the adapter neither
selects nor observes a pricing-stable model, so a local price table could make a
budget silently inaccurate. Cheap-model reflection (D3) is wired for Claude
(`haiku`) and falls back to the default model elsewhere.

## Next

1. Move runtime history out of tracked files and add atomic task claims.
2. Add thin native-session instructions for Codex, Claude Code, and OpenCode.
3. Make all agent-spawning paths explicitly headless, then remove duplicated
   reflection, cost, and continuous-orchestration machinery.
