"""Fixtures compartidas: configuracion aislada y sin dependencias del entorno real."""

from __future__ import annotations

import pytest

from app.core.config import load_settings

_ENV_VARS = [
    "RTSP_URLS",
    "CAMERAS_FILE",
    "MODEL_PATH",
    "TARGET_CLASSES",
    "CONFIDENCE_THRESHOLD",
    "INFER_IMGSZ",
    "DETECT_FPS",
    "COOLDOWN_SECONDS",
    "DRAW_BOXES",
    "BOX_PERSIST_SECONDS",
    "MIN_BOX_AREA_RATIO",
    "DETECTOR_DEVICE",
    "MAX_FRAME_WIDTH",
    "JPEG_QUALITY",
    "SAVE_DIR",
    "EVENTS_JSONL",
    "RETENTION_DAYS",
    "MAX_EVENTS_MEMORY",
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "REQUEST_TIMEOUT_SECONDS",
    "TELEGRAM_QUEUE_SIZE",
    "WEB_HOST",
    "WEB_PORT",
    "WEB_TITLE",
    "WEB_PASSWORD",
    "RTSP_OPEN_TIMEOUT_MS",
    "RTSP_READ_TIMEOUT_MS",
    "RTSP_BUFFER_SIZE",
    "RECONNECT_DELAY_SECONDS",
    "RECONNECT_DELAY_MAX_SECONDS",
    "LOG_LEVEL",
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Aisla `.env`, cwd y variables de entorno; devuelve el root temporal."""
    monkeypatch.setattr("app.core.config.app_config.load_dotenv", lambda: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def cfg(clean_env):
    return load_settings()
