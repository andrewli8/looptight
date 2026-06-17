# looptight

**Your coding agent on autopilot — across Claude Code, Codex, and opencode — that gets smarter every run.**

looptight is a thin, portable learning layer for coding agents. It runs on the
agent you already have, drives the native loop where one exists, supplies one
where it doesn't, and makes every run teach the next.

Two things no single agent does today:

1. **One consistent interface across agents.** The same command works on Claude
   Code, Codex, and opencode. Switch agents without relearning anything.
2. **Durable lessons that compound.** Every failed-then-fixed run leaves a
   short, specific lesson in your agent's own memory file (`CLAUDE.md` /
   `AGENTS.md` / opencode config). Lessons survive across runs, across goals,
   and even when looptight isn't running.

It does **not** reinvent the loop. Where your agent already ships an eval-gated
loop (Codex `/goal`), looptight drives it. Where it doesn't, looptight supplies
one. Building on top, not around.

## Quickstart (three lines)

```bash
uvx looptight init                       # writes a minimal config, explains `verify`
uvx looptight "fix the failing tests"    # runs your agent until verify passes
uvx looptight lessons                    # see what it learned for next time
```

No services. No DAG to author. No migration. If your repo has tests, you are
about 90 seconds from your first green loop.

> Prefer `pipx install looptight` or `pip install looptight` if you don't use
> [uv](https://github.com/astral-sh/uv).

## The one concept you have to learn: `verify`

`verify` is a command that decides pass/fail. **No verify, no loop.** That's the
whole mental model.

```toml
# .looptight.toml
verify = "pytest -q"      # exit 0 = pass; non-zero = keep going
```

`looptight init` auto-detects this from your project (`pytest`, `npm test`,
`go test`, `cargo test`, `make test`), so most repos need no config at all.
Everything else — the agent, the budget, the iteration cap — has a safe default
and is just an override.

## What a run looks like

```
looptight · agent: claude (supplying loop) · verify: pytest -q · budget: $1.00

iteration 1 → verify: FAIL  (3 failing)   $0.04
iteration 2 → verify: FAIL  (1 failing)   $0.09
iteration 3 → verify: PASS                $0.13

✓ done in 3 iterations · $0.13 · lesson saved to CLAUDE.md
```

## Why looptight

- **vs a single agent's native loop (Codex `/goal`, Claude `/goal`):** not locked
  to one agent or one auth — it works on API-key *or* subscription auth, on all
  three agents, with one interface. And it adds compounding lessons that a
  per-thread goal primitive structurally can't. Where an agent *has* a native
  loop, looptight drives it (`--native`) instead of fighting it.
- **vs heavy frameworks (DAG/orchestration):** no graph to author, no migration.
  Runs on the agent you already have in under two minutes, and it's eval-gated,
  so it never loops pointlessly.
- **vs raw headless mode:** adds the learning, the safety rails (hard caps, cost
  ceiling, per-iteration git checkpoints), and one consistent interface — the
  part everyone otherwise hand-rolls badly.

## What this is / isn't

**It is:**
- A portability + learning layer above your coding agent.
- Eval-gated: the `verify` command is the ground-truth oracle.
- Safe by default: low iteration cap, a cost ceiling you can't exceed without
  `--budget`, and a git checkpoint before every iteration so you can always get
  your repo back.

**It isn't:**
- A replacement for native loops. **Where your agent has its own eval-gated loop,
  looptight drives it, it does not replace it.**
- A multi-agent / DAG orchestrator.
- A web dashboard. Terminal output is more gif-able and zero-setup.
- A new model or a fine-tuner. It's a wrapper around the agent you already run.

## Supported agents

| Agent | Headless command | Native loop | Status |
|-------|------------------|-------------|--------|
| Claude Code (`claude`) | `claude -p` | `/goal` — drive it with `--native` | ✅ working |
| Codex (`codex`) | `codex exec` | supply (driving `/goal` headlessly is unconfirmed) | ✅ working |
| opencode (`opencode`) | `opencode run` | supply (no goal primitive) | ✅ working |

By default looptight **supplies** the loop on all three — the same command, the
same `verify`-gated behaviour everywhere. Pass `--native` to **drive the agent's
own loop** where it has one (Claude `/goal` today); `verify` still gates the
result and a lesson is still written, so the learning layer works either way.

Adding an agent is one adapter (see [`docs/architecture.md`](docs/architecture.md)).

## Safety

- **Hard iteration cap + cost ceiling**, both with low defaults. A default run
  cannot exceed the cost ceiling without an explicit `--budget`.
- **Per-iteration git checkpoint.** Each iteration is a restore point; revert
  with `looptight revert`.
- **Cheap-model routing for reflection.** The bookkeeping step (writing the
  lesson) uses a smaller model than the coding step. Cost goes to the work.
- Runs inside your agent's existing sandbox / approval mode.

## Install for development

```bash
git clone https://github.com/andrewli8/looptight
cd looptight
pip install -e ".[dev]"
pytest
```

## License

[MIT](LICENSE)
