"""Config load / merge / write (A3)."""

from __future__ import annotations

import pytest

from looptight.config import (
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_ITERATIONS,
    Config,
    ConfigError,
    load_config,
    write_config,
)


def test_defaults_are_safe():
    config = Config()
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert config.budget_usd == DEFAULT_BUDGET_USD
    assert config.reflect is False
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
    assert loaded.budget_usd == DEFAULT_BUDGET_USD  # deprecated field is not written
    assert loaded.reflect is False


def test_write_then_load_preserves_verify_command_with_toml_special_characters(tmp_path):
    verify = 'python -c "print(\\"C:\\\\tmp\\\\artifact\\")"\n# second check'

    path = write_config(Config(verify=verify), tmp_path)

    assert load_config(path).verify == verify


def test_load_config_raises_clear_error_on_malformed_toml(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "pytest"\nnot valid = = toml\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert str(path) in str(exc.value)


def test_load_config_raises_clear_error_on_non_numeric_value(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "pytest"\nmax_iterations = "lots"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert str(path) in str(exc.value)


@pytest.mark.parametrize("value", ["0", "-1", "true"])
def test_load_config_rejects_invalid_max_iterations(tmp_path, value):
    path = tmp_path / ".looptight.toml"
    path.write_text(f"max_iterations = {value}\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "max_iterations" in str(exc.value)


@pytest.mark.parametrize("field", ["reflect", "native", "hook"])
def test_load_config_rejects_string_boolean_values(tmp_path, field):
    path = tmp_path / ".looptight.toml"
    path.write_text(f'{field} = "false"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert field in str(exc.value)


@pytest.mark.parametrize("field", ["verify", "agent"])
def test_load_config_rejects_non_string_command_fields(tmp_path, field):
    path = tmp_path / ".looptight.toml"
    path.write_text(f"{field} = 42\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert field in str(exc.value)


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


def test_rendered_config_omits_deprecated_budget_and_reflection(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    assert "budget_usd" not in text
    assert "reflect" not in text
