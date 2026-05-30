from __future__ import annotations

import logging
from collections import deque
from threading import RLock


class UILogHandler(logging.Handler):
    def __init__(self, maxlen: int = 300):
        super().__init__()
        self._records: deque[dict] = deque(maxlen=maxlen)
        self._lock = RLock()
        self._time_formatter = logging.Formatter(datefmt="%Y-%m-%d %H:%M:%S")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._records.appendleft(
                    {
                        "ts": self._time_formatter.formatTime(record, "%Y-%m-%d %H:%M:%S"),
                        "level": record.levelname,
                        "thread": record.threadName,
                        "message": record.getMessage(),
                    }
                )
        except Exception:
            self.handleError(record)

    def records(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(self._records)[:limit]


def setup_logging(level_name: str = "INFO") -> UILogHandler:
    level = getattr(logging, level_name.upper(), logging.INFO)
    formatter = logging.Formatter(
        "[%(levelname)s] %(asctime)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)

    if not any(getattr(h, "_catfinder_console", False) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream._catfinder_console = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    ui_handler = UILogHandler(maxlen=300)
    ui_handler.setFormatter(formatter)
    root.addHandler(ui_handler)
    return ui_handler
