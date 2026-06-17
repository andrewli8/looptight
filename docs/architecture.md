# Architecture

looptight is small on purpose. One idea (`verify`), one interface (the adapter),
and a loop that either delegates to the agent or supplies the loop itself.

## Data flow

```
CLI (cli.py)
  └─ load Config (config.py)  ←  autodetect (detect.py)
  └─ pick Adapter (adapters/)
  └─ loop.run_loop(native=?):
        native and adapter.supports_native_loop ?
          ├─ yes → adapter.drive_native_loop()   (e.g. Claude /goal), then verify once
          └─ no  → repeat under BudgetTracker (budget.py) & Checkpointer (checkpoint.py):
                     adapter.run_iteration()  →  run_verify() (verify.py)
        either path → on failure: reflect_on_failure() (reflect.py) → LessonStore.add() (lessons.py)
  └─ render summary (summary.py)
```

`run_verify` is run by looptight in **both** paths, so `verify` is always the
ground-truth oracle and the learning layer fires whether we supplied or
delegated. Everything returns the same `RunResult` (`types.py`), so the CLI and
the summary don't care which path ran (B4).

## The adapter is the seam (F1)

`adapters/base.py` defines one ABC. The model is a capability, not a fixed kind:

- **Every adapter supplies** — implement `run_iteration()` (one headless turn).
  This is the universal path; all three agents have a headless one-shot mode.
- **An adapter may also delegate** — set `supports_native_loop = True` and
  implement `drive_native_loop()` (drive the agent's own eval-gated loop). Opt in
  with `--native`. Today only Claude (`/goal`) does this.

It also names the agent's native `memory_filename` (`CLAUDE.md` / `AGENTS.md`),
which is where lessons land so they keep working when looptight isn't running.

### Adding an agent

1. Subclass `Adapter` in `adapters/<name>.py`.
2. Set `name`, `memory_filename`, implement `is_available()` and
   `run_iteration()`. If the agent has a drivable native loop, set
   `supports_native_loop = True` and implement `drive_native_loop()`.
3. Register it in `adapters/__init__.py`.

That's the whole extension surface. Nothing else in the codebase names a
specific agent — `detect.py` has the PATH lookup order and that's it.

## Testability

The loop takes its collaborators (adapter, verify fn, checkpointer, lesson
store, progress callback) as injected arguments, so `run_loop` is a pure control
flow you can drive with fakes (see `tests/conftest.py`). No test touches the
network or a real agent.

## Why no dashboard / DAG / plugin system

All three are explicit non-goals in the spec. The product's advantage is focus
plus the learning layer, not feature count. Terminal output is more gif-able and
zero-setup; the moment the surface grows past one page, the product is losing.
