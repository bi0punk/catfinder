from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.core.utils import env_bool, safe_int


@dataclass(slots=True)
class NotifierSettings:
    """Configuración del notificador Telegram."""

    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    request_timeout_seconds: int
    telegram_queue_size: int


def load_notifier_settings() -> NotifierSettings:
    telegram_enabled = env_bool("TELEGRAM_ENABLED", False)
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if telegram_enabled and not (telegram_bot_token and telegram_chat_id):
        logging.warning("TELEGRAM_ENABLED=true pero faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. Telegram queda desactivado.")
        telegram_enabled = False

    return NotifierSettings(
        telegram_enabled=telegram_enabled,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        request_timeout_seconds=max(2, safe_int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"), 20)),
        telegram_queue_size=max(1, safe_int(os.getenv("TELEGRAM_QUEUE_SIZE", "50"), 50)),
    )
