"""Explicit key loading and encryption, independent of Telegram startup."""
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

from .settings import Settings


def load_cipher(settings: Settings):
    """Load the existing key, or create one only for a new/empty database.

    The environment key takes precedence. Existing keys are never overwritten,
    and an existing nonempty database must never trigger silent key rotation.
    """
    path = Path(settings.encryption_key_path)
    if settings.fernet_key:
        try:
            key = settings.fernet_key.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("Invalid encryption key configuration") from None
    elif path.exists():
        key = path.read_bytes().strip()
    else:
        database = Path(settings.database_path)
        if database.exists() and database.stat().st_size > 0:
            raise RuntimeError(
                "Encryption key missing for an existing database. Restore secret.key or FERNET_KEY."
            )
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Another startup may have created the key after our existence check.
            # Reuse it; never replace it with our generated key.
            key = path.read_bytes().strip()
        else:
            with os.fdopen(fd, "wb") as key_file:
                key_file.write(key)
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise ValueError("Invalid encryption key configuration") from None


def encrypt_text(cipher, plain_text):
    if not plain_text:
        return ""
    return cipher.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_text(cipher, encrypted_text):
    if not encrypted_text:
        return ""
    try:
        return cipher.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logging.error("Unable to decrypt sensitive value: %s", type(exc).__name__)
        raise ValueError("Sensitive data could not be decrypted; check encryption key") from exc
