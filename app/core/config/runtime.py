from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.utils import safe_int


@dataclass(slots=True)
class RuntimeSettings:
    """Parámetros de conexión RTSP, reconexión y logging."""

    rtsp_open_timeout_ms: int
    rtsp_read_timeout_ms: int
    rtsp_buffer_size: int
    reconnect_delay_seconds: int
    reconnect_delay_max_seconds: int
    log_level: str


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        rtsp_open_timeout_ms=max(1000, safe_int(os.getenv("RTSP_OPEN_TIMEOUT_MS", "5000"), 5000)),
        rtsp_read_timeout_ms=max(1000, safe_int(os.getenv("RTSP_READ_TIMEOUT_MS", "5000"), 5000)),
        rtsp_buffer_size=max(1, safe_int(os.getenv("RTSP_BUFFER_SIZE", "1"), 1)),
        reconnect_delay_seconds=max(1, safe_int(os.getenv("RECONNECT_DELAY_SECONDS", "5"), 5)),
        reconnect_delay_max_seconds=max(5, safe_int(os.getenv("RECONNECT_DELAY_MAX_SECONDS", "60"), 60)),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )
