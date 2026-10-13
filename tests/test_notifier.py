"""Tests del notificador Telegram con `requests` mockeado."""

from __future__ import annotations

import threading
import time

import pytest

from app.domain.models import EventRecord
from app.notifier.telegram import TelegramNotifier


class _FakeResponse:
    def __init__(self, ok: bool, text: str = ""):
        self.ok = ok
        self.text = text


def _event() -> EventRecord:
    return EventRecord("t", "t", "patio", "cat", 0.9, "patio/x.jpg", [])


def _notifier(cfg) -> TelegramNotifier:
    return TelegramNotifier(cfg, threading.Event())


def _enable_telegram(cfg):
    cfg.telegram_enabled = True
    cfg.telegram_bot_token = "token"
    cfg.telegram_chat_id = "chat"


def test_enqueue_skipped_when_disabled(cfg, tmp_path):
    notifier = _notifier(cfg)
    image = tmp_path / "p.jpg"
    image.write_bytes(b"x")
    notifier.enqueue_photo(_event(), image, "cap")
    assert notifier.status()["queue_size"] == 0


def test_enqueue_skipped_when_incomplete(cfg, tmp_path):
    cfg.telegram_enabled = True
    notifier = _notifier(cfg)
    image = tmp_path / "p.jpg"
    image.write_bytes(b"x")
    notifier.enqueue_photo(_event(), image, "cap")
    assert notifier.status()["queue_size"] == 0


def test_send_test_message_not_configured(cfg):
    ok, message = _notifier(cfg).send_test_message()
    assert ok is False
    assert "configurado" in message


def test_send_test_message_ok(cfg, monkeypatch):
    _enable_telegram(cfg)
    monkeypatch.setattr("app.notifier.telegram.requests.post", lambda *a, **k: _FakeResponse(True))
    ok, message = _notifier(cfg).send_test_message()
    assert ok is True
    assert message == "Mensaje enviado"


def test_send_test_message_failure(cfg, monkeypatch):
    _enable_telegram(cfg)
    monkeypatch.setattr("app.notifier.telegram.requests.post", lambda *a, **k: _FakeResponse(False, "boom"))
    ok, message = _notifier(cfg).send_test_message()
    assert ok is False
    assert message == "boom"


def test_send_test_message_exception(cfg, monkeypatch):
    _enable_telegram(cfg)

    def _raise(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.notifier.telegram.requests.post", _raise)
    ok, message = _notifier(cfg).send_test_message()
    assert ok is False
    assert "network down" in message


def test_send_photo_ok_and_failure(cfg, monkeypatch, tmp_path):
    _enable_telegram(cfg)
    image = tmp_path / "p.jpg"
    image.write_bytes(b"x")
    notifier = _notifier(cfg)

    monkeypatch.setattr("app.notifier.telegram.requests.post", lambda *a, **k: _FakeResponse(True))
    notifier._send_photo(image, "cap")

    monkeypatch.setattr("app.notifier.telegram.requests.post", lambda *a, **k: _FakeResponse(False, "nope"))
    with pytest.raises(RuntimeError):
        notifier._send_photo(image, "cap")


def test_worker_loop_sends_and_counts(cfg, monkeypatch, tmp_path):
    _enable_telegram(cfg)
    sent: list[str] = []
    monkeypatch.setattr(TelegramNotifier, "_send_photo", lambda self, path, caption: sent.append(caption))

    notifier = _notifier(cfg)
    image = tmp_path / "p.jpg"
    image.write_bytes(b"x")
    notifier.start()
    notifier.enqueue_photo(_event(), image, "cap")

    for _ in range(100):
        if notifier.sent_count:
            break
        time.sleep(0.02)

    notifier.stop_event.set()
    notifier._thread.join(timeout=2)
    assert notifier.sent_count == 1
    assert sent == ["cap"]
