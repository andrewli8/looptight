"""Config load / merge / write (A3)."""

from __future__ import annotations

import dataclasses

import pytest

from looptight.config import (
    Config,
    ConfigError,
    load_config,
    write_config,
)


def test_config_is_frozen_with_each_field_declared_once():
    field_names = [field.name for field in dataclasses.fields(Config)]

    # A field declared twice in the source collapses to a single dataclass field,
    # so a regression (re-adding the duplicate) shows up as the wrong default,
    # not a duplicate name. Pin both: unique names and the frozen contract.
    assert len(field_names) == len(set(field_names))
    assert field_names.count("direct_main") == 1

    config = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.direct_main = True  # type: ignore[misc]


def test_defaults_are_safe():
    config = Config()
    assert config.verify is None
    assert config.tasks == ()
    assert config.direct_main is False


def test_merged_ignores_none_overrides():
    config = Config(verify="pytest -q")
    merged = config.merged(agent=None, verify=None)
    assert merged.verify == "pytest -q"  # None override left it alone
    assert merged.agent is None


def test_write_then_load_roundtrip(tmp_path):
    config = Config(verify="npm test", tasks=("TODO.md", "docs/STATUS.md"), direct_main=True)
    path = write_config(config, tmp_path)
    assert path.name == ".looptight.toml"

    loaded = load_config(path)
    assert loaded == config


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


def test_load_config_rejects_string_direct_main(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text('direct_main = "false"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "direct_main" in str(exc.value)


def test_load_config_rejects_non_string_verify(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text("verify = 42\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "verify" in str(exc.value)


@pytest.mark.parametrize("value", ['"TODO.md"', '["TODO.md", 42]'])
def test_load_config_rejects_invalid_tasks(tmp_path, value):
    path = tmp_path / ".looptight.toml"
    path.write_text(f"tasks = {value}\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "tasks" in str(exc.value)


def test_missing_config_returns_defaults(tmp_path):
    loaded = load_config(tmp_path / "nope.toml")
    assert loaded == Config()


def test_legacy_orchestration_keys_are_ignored(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text(
        'verify = "pytest -q"\n'
        'agent = "claude"\nmax_iterations = 99\nnative = true\nhook = true\npatience = 9\n'
        'budget_usd = "legacy"\nreflect = "legacy"\n'
    )

    assert load_config(path) == Config(verify="pytest -q")


def test_rendered_config_explains_verify(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    assert "verify" in text
    assert "No verify, no loop" in text


def test_rendered_config_contains_only_supported_settings(tmp_path):
    text = write_config(Config(verify="pytest -q"), tmp_path).read_text()
    settings = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    assert settings == {"verify", "tasks", "direct_main"}
