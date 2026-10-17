"""Key continuity and fail-closed startup, using only temporary files."""
from dataclasses import replace
import logging

from cryptography.fernet import Fernet
import pytest

from erpbot.core.encryption import decrypt_text, encrypt_text, load_cipher
from erpbot.core.settings import Settings


def config(tmp_path):
    return Settings.from_env({}, data_directory=tmp_path)


def test_existing_key_decrypts_existing_ciphertext_without_modifying_files(tmp_path):
    key = Fernet.generate_key()
    settings = config(tmp_path)
    path = tmp_path / "secret.key"
    path.write_bytes(key + b"\n")
    ciphertext = Fernet(key).encrypt("اطلاعات آزمایشی".encode()).decode()
    cipher = load_cipher(settings)
    assert decrypt_text(cipher, ciphertext) == "اطلاعات آزمایشی"
    assert decrypt_text(cipher, encrypt_text(cipher, "متن جدید")) == "متن جدید"
    assert path.read_bytes() == key + b"\n"
    assert not (tmp_path / "enterprise_requests.db").exists()


def test_new_key_is_created_once_and_reused_on_next_start(tmp_path):
    settings = config(tmp_path)
    cipher = load_cipher(settings)
    key = (tmp_path / "secret.key").read_bytes()
    ciphertext = encrypt_text(cipher, "persist across starts")
    again = load_cipher(settings)
    assert decrypt_text(again, ciphertext) == "persist across starts"
    assert (tmp_path / "secret.key").read_bytes() == key
    assert sorted(path.name for path in tmp_path.iterdir()) == ["secret.key"]


def test_missing_key_for_existing_database_fails_without_rotating_or_modifying(tmp_path):
    database = tmp_path / "enterprise_requests.db"
    database.write_bytes(b"existing database fixture")
    with pytest.raises(RuntimeError, match="Encryption key missing"):
        load_cipher(config(tmp_path))
    assert database.read_bytes() == b"existing database fixture"
    assert not (tmp_path / "secret.key").exists()


def test_environment_key_takes_precedence_without_overwriting_file(tmp_path):
    file_key, env_key = Fernet.generate_key(), Fernet.generate_key()
    (tmp_path / "secret.key").write_bytes(file_key)
    settings = replace(config(tmp_path), fernet_key=env_key.decode())
    cipher = load_cipher(settings)
    ciphertext = Fernet(env_key).encrypt(b"environment ciphertext").decode()
    assert decrypt_text(cipher, ciphertext) == "environment ciphertext"
    assert (tmp_path / "secret.key").read_bytes() == file_key


@pytest.mark.parametrize("invalid", [b"", b"broken-key"])
def test_invalid_existing_key_is_never_replaced(tmp_path, invalid):
    path = tmp_path / "secret.key"
    path.write_bytes(invalid)
    with pytest.raises(ValueError, match="Invalid encryption key configuration"):
        load_cipher(config(tmp_path))
    assert path.read_bytes() == invalid


@pytest.mark.parametrize("invalid", ["PRIVATE_INVALID_KEY", "کلید نامعتبر"])
def test_invalid_environment_key_does_not_fall_back_or_expose_value(tmp_path, invalid):
    key = Fernet.generate_key()
    (tmp_path / "secret.key").write_bytes(key)
    with pytest.raises(ValueError) as error:
        load_cipher(replace(config(tmp_path), fernet_key=invalid))
    assert invalid not in str(error.value)
    assert (tmp_path / "secret.key").read_bytes() == key


def test_decryption_failure_does_not_log_sensitive_value(tmp_path, caplog):
    cipher = load_cipher(config(tmp_path))
    sensitive = "PRIVATE_TEST_CIPHERTEXT"
    with caplog.at_level(logging.ERROR), pytest.raises(ValueError) as error:
        decrypt_text(cipher, sensitive)
    assert sensitive not in str(error.value)
    assert sensitive not in caplog.text


def test_empty_database_allows_initial_key_creation(tmp_path):
    (tmp_path / "enterprise_requests.db").touch()
    load_cipher(config(tmp_path))
    assert (tmp_path / "secret.key").exists()
    assert (tmp_path / "enterprise_requests.db").stat().st_size == 0
