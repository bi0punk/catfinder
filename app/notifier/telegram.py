from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

import requests

from app.core.config import AppConfig
from app.core.utils import local_now_str
from app.domain.models import EventRecord


class TelegramNotifier:
    def __init__(self, cfg: AppConfig, stop_event: threading.Event):
        self.cfg = cfg
        self.stop_event = stop_event
        self._queue: queue.Queue[tuple[EventRecord, Path, str]] = queue.Queue(maxsize=cfg.telegram_queue_size)
        self._thread = threading.Thread(target=self._worker_loop, name="telegram", daemon=True)
        self.sent_count = 0
        self.failed_count = 0
        self.dropped_count = 0

    def start(self) -> None:
        self._thread.start()

    def configure(self, enabled: bool, token: str, chat_id: str) -> None:
        self.cfg.telegram_enabled = enabled
        self.cfg.telegram_bot_token = token.strip()
        self.cfg.telegram_chat_id = chat_id.strip()

    def enqueue_photo(self, event: EventRecord, image_path_abs: Path, caption: str) -> None:
        if not self.cfg.telegram_enabled:
            return
        if not (self.cfg.telegram_bot_token and self.cfg.telegram_chat_id):
            logging.warning("Telegram habilitado pero incompleto. No se envía evidencia.")
            return
        try:
            self._queue.put_nowait((event, image_path_abs, caption))
        except queue.Full:
            self.dropped_count += 1
            logging.warning("Cola Telegram llena. Evidencia descartada para envío: %s", image_path_abs)

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                event, image_path_abs, caption = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._send_photo(image_path_abs, caption)
                self.sent_count += 1
                logging.info("Telegram OK: %s", event.image_path)
            except Exception as exc:
                self.failed_count += 1
                logging.warning("Telegram falló para %s: %s", event.image_path, exc)
            finally:
                self._queue.task_done()

    def _send_photo(self, image_path_abs: Path, caption: str) -> None:
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendPhoto"
        with image_path_abs.open("rb") as fh:
            response = requests.post(
                url,
                data={"chat_id": self.cfg.telegram_chat_id, "caption": caption},
                files={"photo": fh},
                timeout=self.cfg.request_timeout_seconds,
            )
        if not response.ok:
            raise RuntimeError(response.text[:500])

    def send_test_message(self) -> tuple[bool, str]:
        if not self.cfg.telegram_enabled or not self.cfg.telegram_bot_token or not self.cfg.telegram_chat_id:
            return False, "Telegram no está configurado"
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage",
                data={"chat_id": self.cfg.telegram_chat_id, "text": f"CatFinder test OK | {local_now_str()}"},
                timeout=self.cfg.request_timeout_seconds,
            )
            if response.ok:
                return True, "Mensaje enviado"
            return False, response.text[:500]
        except Exception as exc:
            return False, str(exc)

    def status(self) -> dict:
        return {
            "enabled": self.cfg.telegram_enabled,
            "configured": bool(self.cfg.telegram_bot_token and self.cfg.telegram_chat_id),
            "queue_size": self._queue.qsize(),
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "dropped_count": self.dropped_count,
        }
