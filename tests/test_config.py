"""Config load / merge / write (A3)."""

from __future__ import annotations

import dataclasses

import pytest

from looptight.config import (
    CONFIG_NAME,
    Config,
    ConfigError,
    find_config,
    load_config,
    render_config,
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


def test_load_config_tolerates_utf8_bom(tmp_path):
    # Windows editors commonly prepend a UTF-8 BOM. tomllib rejects it, so the
    # raw bytes must be decoded BOM-tolerantly or the file fails to parse.
    path = tmp_path / ".looptight.toml"
    path.write_bytes(b"\xef\xbb\xbf" + b'verify = "pytest -q"\nagent = "codex"\n')
    assert load_config(path).verify == "pytest -q"


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


def test_load_config_rejects_negative_max_changed_files(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text("max_changed_files = -1\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "max_changed_files" in str(exc.value)


def test_load_config_rejects_bool_for_max_changed_files(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text("max_changed_files = true\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "max_changed_files" in str(exc.value)


def test_load_config_rejects_empty_string_in_protected_paths(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text('protected_paths = [""]\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "protected_paths" in str(exc.value)


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
    assert settings == {
        "verify",
        "tasks",
        "direct_main",
        "idea_generation",
        "protected_paths",
        "no_direct_push",
        "allowed_verify_commands",
    }


def test_write_then_load_preserves_idea_generation(tmp_path):
    config = Config(verify="pytest -q", idea_generation=False)
    path = write_config(config, tmp_path)
    assert load_config(path) == config


def test_idea_generation_defaults_on_and_rejects_non_boolean(tmp_path):
    assert Config().idea_generation is True

    path = tmp_path / ".looptight.toml"
    path.write_text('idea_generation = "no"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "idea_generation" in str(exc.value)


def test_find_config_locates_config_in_parent_directory(tmp_path):
    (tmp_path / CONFIG_NAME).write_text('verify = "pytest -q"\n', encoding="utf-8")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)

    found = find_config(nested)

    assert found == tmp_path / CONFIG_NAME


def test_find_config_returns_none_when_no_config_exists(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_config(nested) is None


def test_render_config_includes_verify_tasks_and_direct_main():
    text = render_config(
        Config(verify="npm test", tasks=("TODO.md", "docs/STATUS.md"), direct_main=True)
    )

    assert 'verify = "npm test"' in text
    assert 'tasks = ["TODO.md", "docs/STATUS.md"]' in text
    assert "direct_main = true" in text
