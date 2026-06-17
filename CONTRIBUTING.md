# Contributing

Thanks for looking at looptight. The bar for a change is simple: does it keep the
product **legible and easy**? If a feature makes the surface bigger without
serving the one-idea (`verify`) mental model or the learning layer, it's
probably a no — see the deferred list in [`docs/SPEC.md`](docs/SPEC.md).

## Setup

```bash
git clone https://github.com/andrewli8/looptight
cd looptight
pip install -e ".[dev]"
pytest
```

Python 3.11+ (we use stdlib `tomllib`). The only runtime dependency is `rich`.

## Layout

- `src/looptight/` — the package. Small, focused files; see
  [`docs/architecture.md`](docs/architecture.md).
- `tests/` — pure unit tests with injected fakes. No network, no real agent.

## Conventions

- **Immutable data.** Return new objects; don't mutate. Shared types live in
  `types.py` and are frozen dataclasses.
- **The loop stays pure.** New behaviour should be injectable so it's testable
  without an agent.
- **One concept stays one concept.** Don't add a second mandatory config idea.
- **Adapters are the only place that names an agent.** Adding support for an
  agent should not require touching the loop.

## Adding an agent

See [Adding an agent](docs/architecture.md#adding-an-agent). PRs that add an
adapter (especially driving a native loop) are very welcome.

## Before you open a PR

```bash
pytest
```

Keep PRs focused. A good PR is one idea, with tests.
