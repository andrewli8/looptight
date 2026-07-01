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


def test_config_rejects_a_typo_of_a_known_key(tmp_path):
    # A near-miss of a real key (verfy -> verify) is silently dropped today, so the user thinks
    # they set a value that never took effect — the same footgun as a misplaced key.
    path = tmp_path / ".looptight.toml"
    path.write_text('verfy = "true"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    msg = str(exc.value)
    assert "verfy" in msg and "verify" in msg  # names the typo and the suggestion


def test_config_tolerates_an_unrelated_unknown_key(tmp_path):
    # Forward-compatible: an unknown key that is not a near-match of any field is left alone.
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "true"\nfuture_capability_xyz = 1\n', encoding="utf-8")
    assert load_config(path).verify == "true"


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


def test_blank_verify_is_treated_as_no_verify(tmp_path):
    # A whitespace-only verify in config is a no-op that would always pass; treat it as no verify
    # (None) so the user gets the "No verify command found" guidance, not a silent always-pass gate.
    for blank in ('verify = ""', 'verify = "   "', 'verify = "\\t"'):
        path = tmp_path / ".looptight.toml"
        path.write_text(blank + "\n", encoding="utf-8")
        assert load_config(path).verify is None
    # A real verify with incidental surrounding whitespace is trimmed, not dropped.
    (tmp_path / ".looptight.toml").write_text('verify = "  pytest -q  "\n', encoding="utf-8")
    assert load_config(tmp_path / ".looptight.toml").verify == "pytest -q"


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


def test_load_config_raises_config_error_for_unreadable_file(tmp_path, monkeypatch):
    # config.py:83's OSError arm: when read_text raises OSError (permission denied,
    # IsADirectoryError, etc.) the caller gets a ConfigError naming the file, not a
    # raw OS traceback.  A regression dropping OSError from the except would propagate.
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "pytest -q"\n', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.read_text", lambda *a, **k: (_ for _ in ()).throw(OSError("permission denied")))
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


def test_continue_through_backlog_round_trips_and_defaults_false(tmp_path):
    assert load_config(tmp_path / "missing.toml").continue_through_backlog is False
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "pytest -q"\ncontinue_through_backlog = true\n', encoding="utf-8")
    assert load_config(path).continue_through_backlog is True


def test_load_config_rejects_keys_nested_under_a_table(tmp_path):
    # The schema is flat; a [policy] table holding safety keys would be silently dropped
    # (status --json reports a "policy" object, inviting exactly this mistake). Fail fast.
    path = tmp_path / ".looptight.toml"
    path.write_text(
        'verify = "pytest -q"\n[policy]\nmax_changed_files = 3\nprotected_paths = ["x"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    message = str(exc.value)
    assert "policy" in message
    assert "max_changed_files" in message and "protected_paths" in message


def test_load_config_ignores_an_unknown_table_with_no_known_keys(tmp_path):
    # A table that shadows no recognized key is left alone, so the guard is forward-compatible
    # and does not reject benign/future sections.
    path = tmp_path / ".looptight.toml"
    path.write_text('verify = "pytest -q"\n[notes]\nauthor = "me"\n', encoding="utf-8")

    assert load_config(path).verify == "pytest -q"


def test_load_config_rejects_non_string_verify(tmp_path):
    path = tmp_path / ".looptight.toml"
    path.write_text("verify = 42\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        load_config(path)

    assert str(path) in str(exc.value)
    assert "verify" in str(exc.value)


def test_load_config_rejects_non_array_tasks(tmp_path):
    # A common mistake is `tasks = "TODO.md"` (a bare string, forgetting the array
    # brackets); _string_list must reject the non-array value, not silently iterate
    # the string's characters as task files.
    path = tmp_path / ".looptight.toml"
    path.write_text('tasks = "TODO.md"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "tasks" in str(exc.value)


def test_load_config_rejects_string_max_changed_files(tmp_path):
    # A quoted number (`max_changed_files = "5"`) is a string, not an int; the guard
    # must reject it rather than later comparing a str to an int at enforcement time.
    path = tmp_path / ".looptight.toml"
    path.write_text('max_changed_files = "5"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "max_changed_files" in str(exc.value)


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
        "continue_through_backlog",
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


def test_write_config_is_atomic(tmp_path, monkeypatch):
    # An interrupted write must leave no partial `.looptight.toml` (and no `.tmp`),
    # so a re-run of `init` -- which refuses to overwrite an existing file -- is not
    # left stuck with a corrupt config.
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)
    with pytest.raises(OSError):
        write_config(Config(verify="true"), tmp_path)
    assert not (tmp_path / CONFIG_NAME).exists()
    assert not (tmp_path / CONFIG_NAME).with_suffix(".tmp").exists()
