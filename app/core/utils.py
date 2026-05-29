from __future__ import annotations

import datetime as dt
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def env_bool(name: str, default: bool = False) -> bool:
    return coerce_bool(os.getenv(name), default)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def local_now_str() -> str:
    return local_now().strftime("%Y-%m-%d %H:%M:%S")


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename_timestamp() -> str:
    return local_now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def redact_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            user = parsed.username or "user"
            return urlunparse(parsed._replace(netloc=f"{user}:***@{host}{port}"))
    except Exception:
        pass
    return url


_RESERVED_NAMES = {"api", "stream", "captures", "health", "ready", "metrics", "static", "logs"}
_CAMERA_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")


def valid_camera_name(name: str) -> bool:
    if not name:
        return False
    if name.lower() in _RESERVED_NAMES:
        return False
    return bool(_CAMERA_RE.match(name))


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def configure_numeric_runtime() -> None:
    """Limit CPU libraries before heavy work starts.

    This does not replace OS-level resource controls, but helps CPU-only boxes avoid
    runaway thread creation by OpenCV/PyTorch/BLAS.
    """
    os.environ.setdefault("OMP_NUM_THREADS", os.getenv("OMP_NUM_THREADS", "2"))
    os.environ.setdefault("MKL_NUM_THREADS", os.getenv("MKL_NUM_THREADS", "2"))
    os.environ.setdefault("NUMEXPR_NUM_THREADS", os.getenv("NUMEXPR_NUM_THREADS", "2"))
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        os.getenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000|max_delay;500000"),
    )

    try:
        import cv2  # type: ignore

        cv2.setNumThreads(safe_int(os.getenv("OPENCV_THREADS", "1"), 1))
    except Exception as exc:  # pragma: no cover - best effort
        logging.debug("No se pudo configurar OpenCV threads: %s", exc)

    try:
        import torch  # type: ignore

        torch.set_num_threads(safe_int(os.getenv("TORCH_NUM_THREADS", "2"), 2))
        torch.set_num_interop_threads(safe_int(os.getenv("TORCH_INTEROP_THREADS", "1"), 1))
    except Exception as exc:  # pragma: no cover - best effort
        logging.debug("No se pudo configurar Torch threads: %s", exc)
