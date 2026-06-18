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
    assert config.hook is False  # Stop-hook auto-loop is opt-in


def test_hook_flag_roundtrips(tmp_path):
    path = write_config(Config(verify="pytest -q", hook=True), tmp_path)
    assert load_config(path).hook is True


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


def test_write_then_load_preserves_verify_command_with_toml_special_characters(tmp_path):
    verify = 'python -c "print(\\"C:\\\\tmp\\\\artifact\\")"\n# second check'

    path = write_config(Config(verify=verify), tmp_path)

    assert load_config(path).verify == verify


def test_missing_config_returns_defaults(tmp_path):
    loaded = load_config(tmp_path / "nope.toml")
    assert loaded == Config()


def test_patience_roundtrips(tmp_path):
    path = write_config(Config(verify="pytest -q", patience=3), tmp_path)
    assert load_config(path).patience == 3


def test_rendered_config_explains_verify(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    assert "verify" in text
    assert "No verify, no loop" in text


def test_rendered_config_frames_budget_as_spend_threshold(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    # Cost is only known after each agent call, so budget_usd is a post-iteration
    # spend stop, not an unexceedable ceiling — one iteration can overshoot it.
    assert "ceiling" not in text
    assert "never exceeded" not in text
    assert "spend" in text
    assert "overshoot" in text
