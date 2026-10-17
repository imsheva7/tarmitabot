"""Configuration values without bot creation, database access, or file writes.

Loading is explicit. Merely importing this module does not read environment
variables. Existing deployment paths and environment names are preserved.
"""
from dataclasses import dataclass, field
import os
from typing import Mapping


class ConfigurationError(ValueError):
    """Invalid configuration, reported without including secret values."""


def _integer(environ, name, default=None):
    value = environ.get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"{name} must be an integer") from None


@dataclass(frozen=True)
class Settings:
    bot_token: str | None = field(repr=False)
    group_id: int
    database_directory: str
    database_path: str
    encryption_key_path: str
    fernet_key: str | None = field(repr=False)
    enable_initial_staff_seed: bool
    bootstrap_admin_telegram_id: int | None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *, data_directory=None):
        environ = os.environ if environ is None else environ
        # Preserve the legacy defaults. Tests/tools can supply their own directory
        # without changing process-wide environment or working directory.
        if data_directory is None:
            database_directory = "/data" if os.path.exists("/data") else "."
            key_directory = "/data" if os.path.isdir("/data") else "."
        else:
            database_directory = key_directory = os.fspath(data_directory)
        bootstrap_admin = environ.get("BOOTSTRAP_ADMIN_TELEGRAM_ID")
        return cls(
            bot_token=environ.get("BOT_TOKEN"),
            group_id=_integer(environ, "GROUP_ID", "-1003619551361"),
            database_directory=database_directory,
            database_path=os.path.join(database_directory, "enterprise_requests.db"),
            encryption_key_path=environ.get(
                "ENCRYPTION_KEY_PATH", os.path.join(key_directory, "secret.key")
            ),
            fernet_key=environ.get("FERNET_KEY"),
            enable_initial_staff_seed=environ.get("ENABLE_INITIAL_STAFF_SEED", "0") == "1",
            bootstrap_admin_telegram_id=(
                _integer(environ, "BOOTSTRAP_ADMIN_TELEGRAM_ID") if bootstrap_admin else None
            ),
        )

    def require_bot_token(self):
        """Validate the required credential only when starting the bot."""
        if not self.bot_token:
            raise ConfigurationError(
                "❌ خطای امنیتی بحرانی: متغیر محیطی BOT_TOKEN بر روی سرور تنظیم نشده است!"
            )
        return self.bot_token
