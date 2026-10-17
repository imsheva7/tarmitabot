"""Configuration can be loaded without credentials, startup, or secret output."""
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from erpbot.core.settings import ConfigurationError, Settings


def test_load_without_bot_token_creates_no_files(tmp_path):
    directory = tmp_path / "not-created"
    settings = Settings.from_env({}, data_directory=directory)
    assert settings.bot_token is None
    assert settings.group_id == -1003619551361
    assert settings.database_path == str(directory / "enterprise_requests.db")
    assert settings.encryption_key_path == str(directory / "secret.key")
    assert not settings.enable_initial_staff_seed
    assert settings.bootstrap_admin_telegram_id is None
    assert not directory.exists()
    with pytest.raises(ConfigurationError, match="BOT_TOKEN"):
        settings.require_bot_token()


def test_configured_values_and_secrets_are_preserved_without_repr_leaks(tmp_path):
    token, key = "123456789:PRIVATE_TEST_TOKEN", "PRIVATE_TEST_KEY"
    settings = Settings.from_env({
        "BOT_TOKEN": token, "FERNET_KEY": key, "GROUP_ID": "-1001234567890",
        "ENCRYPTION_KEY_PATH": str(tmp_path / "custom.key"),
        "ENABLE_INITIAL_STAFF_SEED": "1", "BOOTSTRAP_ADMIN_TELEGRAM_ID": "202",
    }, data_directory=tmp_path)
    assert settings.require_bot_token() == token
    assert settings.fernet_key == key
    assert settings.group_id == -1001234567890
    assert settings.encryption_key_path == str(tmp_path / "custom.key")
    assert settings.enable_initial_staff_seed
    assert settings.bootstrap_admin_telegram_id == 202
    assert token not in repr(settings) and key not in repr(settings)
    with pytest.raises(FrozenInstanceError):
        settings.group_id = 1


@pytest.mark.parametrize("name", ["GROUP_ID", "BOOTSTRAP_ADMIN_TELEGRAM_ID"])
def test_invalid_integer_has_actionable_error_without_echoing_value(tmp_path, name):
    private_value = "PRIVATE_INVALID_VALUE"
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({name: private_value}, data_directory=tmp_path)
    assert name in str(error.value)
    assert private_value not in str(error.value)


def test_config_load_uses_injected_environment_without_changing_process(monkeypatch, tmp_path):
    monkeypatch.setenv("GROUP_ID", "-100111")
    first = Settings.from_env({"GROUP_ID": "-100222"}, data_directory=tmp_path)
    second = Settings.from_env(data_directory=tmp_path)
    assert first.group_id == -100222 and second.group_id == -100111


@pytest.mark.parametrize("seed", ["0", "true", "yes", ""])
def test_seed_requires_existing_explicit_opt_in(tmp_path, seed):
    settings = Settings.from_env({"ENABLE_INITIAL_STAFF_SEED": seed}, data_directory=tmp_path)
    assert not settings.enable_initial_staff_seed


def test_default_storage_paths_keep_legacy_rules(monkeypatch):
    from erpbot.core import settings as module
    monkeypatch.setattr(module.os.path, "exists", lambda path: path == "/data")
    monkeypatch.setattr(module.os.path, "isdir", lambda path: path == "/data")
    config = Settings.from_env({})
    assert config.database_directory == "/data"
    assert Path(config.database_path) == Path("/data/enterprise_requests.db")
    assert Path(config.encryption_key_path) == Path("/data/secret.key")


def test_without_volume_storage_paths_remain_local(monkeypatch):
    from erpbot.core import settings as module
    monkeypatch.setattr(module.os.path, "exists", lambda path: False)
    monkeypatch.setattr(module.os.path, "isdir", lambda path: False)
    config = Settings.from_env({})
    assert config.database_directory == "."
    assert Path(config.database_path) == Path("enterprise_requests.db")
    assert Path(config.encryption_key_path) == Path("secret.key")
