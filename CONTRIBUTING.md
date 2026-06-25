# Contributing

Thanks for looking at looptight. The bar for a change is simple: does it keep the
product **legible and easy**? If a feature makes the surface bigger without
serving the one-idea (`verify`) mental model or the learning layer, it's
probably a no. See the deferred list in [`docs/SPEC.md`](docs/SPEC.md).

## Setup

```bash
git clone https://github.com/andrewli8/looptight
cd looptight
pip install -e ".[dev]"
pytest
```

Python 3.11+ (we use stdlib `tomllib`). There is no runtime dependency; the package
runs on the standard library.

## Layout

- `src/looptight/`: the package. Small, focused files; see
  [`docs/architecture.md`](docs/architecture.md).
- `tests/`: pure unit tests with injected fakes. No network, no real agent.

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

# Run it the way CI does, with no coding agent on PATH and no global git config,
# so an environment-dependent test fails here instead of going red on CI:
GIT_CONFIG_GLOBAL=/dev/null PATH="/usr/bin:/bin:$(dirname "$(command -v pytest)")" pytest
```

Keep PRs focused. A good PR is one idea, with tests.

## Releasing

The package builds with hatchling and has no runtime dependencies.

```bash
uv build            # writes an sdist and wheel to dist/
uv publish          # uploads to PyPI; needs a PyPI API token
```

For a dry run, publish to TestPyPI first:

```bash
uv publish --publish-url https://test.pypi.org/legacy/
```

A published version is permanent. You can yank a release but cannot reuse a version
number, so bump `version` in `pyproject.toml` for each release.

Once the PyPI trusted publisher is configured for the `looptight` project, releasing
is just a tag: bump the version, then `git tag v0.1.0 && git push --tags`. The
`release` workflow builds and publishes to PyPI over OIDC, with no token in the repo.
