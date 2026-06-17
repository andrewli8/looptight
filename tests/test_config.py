"""Config load / merge / write (A3)."""

from __future__ import annotations

from looptight.config import (
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_ITERATIONS,
    Config,
    load_config,
    write_config,
)


def test_defaults_are_safe():
    config = Config()
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert config.budget_usd == DEFAULT_BUDGET_USD
    assert config.reflect is True
    assert config.agent is None  # auto-detect


def test_merged_ignores_none_overrides():
    config = Config(verify="pytest -q", budget_usd=1.0)
    merged = config.merged(agent=None, budget_usd=5.0, verify=None)
    assert merged.verify == "pytest -q"  # None override left it alone
    assert merged.budget_usd == 5.0
    assert merged.agent is None


def test_write_then_load_roundtrip(tmp_path):
    config = Config(verify="npm test", agent="claude", max_iterations=4, budget_usd=2.5, reflect=False)
    path = write_config(config, tmp_path)
    assert path.name == ".looptight.toml"

    loaded = load_config(path)
    assert loaded.verify == "npm test"
    assert loaded.agent == "claude"
    assert loaded.max_iterations == 4
    assert loaded.budget_usd == 2.5
    assert loaded.reflect is False


def test_missing_config_returns_defaults(tmp_path):
    loaded = load_config(tmp_path / "nope.toml")
    assert loaded == Config()


def test_rendered_config_explains_verify(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    assert "verify" in text
    assert "No verify, no loop" in text
