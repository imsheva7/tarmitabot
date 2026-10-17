"""Create application resources explicitly, then bind the legacy runtime facade."""
from dataclasses import dataclass, field
import logging

from aiogram import Bot, Dispatcher
from aiogram.utils.token import validate_token
from cryptography.fernet import Fernet

from .core.encryption import load_cipher
from .core.settings import Settings


@dataclass
class Application:
    settings: Settings
    bot: Bot = field(repr=False)
    dispatcher: Dispatcher = field(repr=False)
    cipher: Fernet = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self):
        if self._closed:
            return
        try:
            try:
                await self.dispatcher.storage.close()
            finally:
                await self.bot.session.close()
        finally:
            self._closed = True


def create_application(settings: Settings, *, configure_logging=True):
    """Create resources without opening the database or starting polling/jobs."""
    token = settings.require_bot_token()
    validate_token(token)
    cipher = load_cipher(settings)
    if configure_logging:
        logging.basicConfig(
            filename="bot_errors.log", level=logging.ERROR,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
    return Application(settings, Bot(token=token), Dispatcher(), cipher)


def initialize_runtime(settings: Settings | None = None, *, configure_logging=True):
    """Initialize once per process, before importing legacy handler modules.

    Repeated calls reuse the same application. Rebinding an initialized facade
    would leave stale wildcard imports in legacy handlers, so it is rejected.
    """
    from .core import runtime
    existing = runtime._application
    if existing is not None:
        if existing._closed:
            raise RuntimeError("Application is closed; restart the process to initialize again")
        if settings is not None and settings != existing.settings:
            raise RuntimeError("Runtime is already initialized with different settings; restart the process")
        return existing
    settings = Settings.from_env() if settings is None else settings
    application = create_application(settings, configure_logging=configure_logging)
    application.dispatcher.callback_query.middleware(runtime.AdminGuard())
    runtime._bind_application(application)
    return application
