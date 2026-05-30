from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.core.utils import coerce_bool, env_bool, ensure_dir, safe_float, safe_int, valid_camera_name
from app.domain.models import CameraConfig


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    cameras_file: Path
    cameras: list[CameraConfig]

    model_path: str
    target_classes: list[str]
    confidence_threshold: float
    infer_imgsz: int
    detect_fps: float
    cooldown_seconds: int
    draw_boxes: bool
    box_persist_seconds: float
    min_box_area_ratio: float
    detector_device: str
    max_frame_width: int
    jpeg_quality: int

    save_dir: Path
    events_jsonl: Path
    retention_days: int
    max_events_memory: int

    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    request_timeout_seconds: int
    telegram_queue_size: int

    web_host: str
    web_port: int
    web_title: str
    web_password: str

    rtsp_open_timeout_ms: int
    rtsp_read_timeout_ms: int
    rtsp_buffer_size: int
    reconnect_delay_seconds: int
    reconnect_delay_max_seconds: int
    log_level: str

    def public_dict(self) -> dict:
        return {
            "model_path": self.model_path,
            "target_classes": self.target_classes,
            "confidence_threshold": self.confidence_threshold,
            "infer_imgsz": self.infer_imgsz,
            "detect_fps": self.detect_fps,
            "cooldown_seconds": self.cooldown_seconds,
            "draw_boxes": self.draw_boxes,
            "box_persist_seconds": self.box_persist_seconds,
            "min_box_area_ratio": self.min_box_area_ratio,
            "detector_device": self.detector_device,
            "max_frame_width": self.max_frame_width,
            "jpeg_quality": self.jpeg_quality,
            "save_dir": str(self.save_dir),
            "events_jsonl": str(self.events_jsonl),
            "retention_days": self.retention_days,
            "telegram_enabled": self.telegram_enabled,
            "telegram_configured": bool(self.telegram_bot_token and self.telegram_chat_id),
            "web_host": self.web_host,
            "web_port": self.web_port,
            "cameras_file": str(self.cameras_file),
        }


def _project_root() -> Path:
    return Path(os.getenv("PROJECT_ROOT", Path.cwd())).resolve()


def _parse_rtsp_urls(raw: str) -> list[CameraConfig]:
    cameras: list[CameraConfig] = []
    if not raw.strip():
        return cameras
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            logging.warning("RTSP_URLS inválido, falta nombre=url: %s", item)
            continue
        name, url = item.split("=", 1)
        name = name.strip()
        url = url.strip()
        if not valid_camera_name(name):
            logging.warning("Nombre de cámara inválido en RTSP_URLS: %s", name)
            continue
        if not url.startswith("rtsp://"):
            logging.warning("URL RTSP inválida para cámara %s", name)
            continue
        cameras.append(CameraConfig(name=name, rtsp_url=url, enabled=True))
    return cameras


def load_cameras_file(cameras_file: Path) -> list[CameraConfig]:
    if not cameras_file.exists():
        return []
    try:
        data = yaml.safe_load(cameras_file.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logging.warning("No se pudo leer %s: %s", cameras_file, exc)
        return []

    raw_cameras = data.get("cameras", []) if isinstance(data, dict) else []
    cameras: list[CameraConfig] = []
    for item in raw_cameras:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("rtsp_url", "")).strip()
        if not valid_camera_name(name):
            logging.warning("Cámara ignorada por nombre inválido: %s", name)
            continue
        if not url.startswith("rtsp://"):
            logging.warning("Cámara %s ignorada porque rtsp_url no empieza con rtsp://", name)
            continue
        cameras.append(
            CameraConfig(
                name=name,
                rtsp_url=url,
                enabled=coerce_bool(item.get("enabled", True), True),
                detect_fps=safe_float(item.get("detect_fps"), 0.0) or None,
                cooldown_seconds=safe_int(item.get("cooldown_seconds"), 0) or None,
                max_frame_width=safe_int(item.get("max_frame_width"), 0) or None,
                split_mode=str(item.get("split_mode", "none")).lower(),
            )
        )
    return cameras


def save_cameras_file(cameras_file: Path, cameras: list[CameraConfig]) -> None:
    ensure_dir(cameras_file.parent)
    data = {"cameras": [camera.private_dict() for camera in sorted(cameras, key=lambda c: c.name)]}
    cameras_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _ensure_sample_cameras_file(cameras_file: Path) -> None:
    if cameras_file.exists():
        return
    ensure_dir(cameras_file.parent)
    sample = {
        "cameras": [
            {
                "name": "patio",
                "rtsp_url": "rtsp://usuario:password@192.168.1.100:554/Streaming/Channels/102",
                "enabled": False,
                "detect_fps": None,
                "cooldown_seconds": None,
                "max_frame_width": None,
            }
        ]
    }
    cameras_file.write_text(yaml.safe_dump(sample, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_app_config() -> AppConfig:
    load_dotenv()
    root = _project_root()

    cameras_file = Path(os.getenv("CAMERAS_FILE", "config/cameras.yaml"))
    if not cameras_file.is_absolute():
        cameras_file = root / cameras_file
    _ensure_sample_cameras_file(cameras_file)

    file_cameras = load_cameras_file(cameras_file)
    env_cameras = _parse_rtsp_urls(os.getenv("RTSP_URLS", ""))

    # Si el archivo existe con cámaras reales, manda el archivo. Si solo está el sample deshabilitado
    # y el usuario configuró RTSP_URLS, usa RTSP_URLS para facilitar MVP rápido.
    enabled_file_cameras = [c for c in file_cameras if c.enabled]
    cameras = file_cameras
    if env_cameras and not enabled_file_cameras:
        cameras = env_cameras
        save_cameras_file(cameras_file, cameras)

    save_dir = Path(os.getenv("SAVE_DIR", "captures"))
    if not save_dir.is_absolute():
        save_dir = root / save_dir
    ensure_dir(save_dir)

    events_jsonl = Path(os.getenv("EVENTS_JSONL", str(save_dir / "events.jsonl")))
    if not events_jsonl.is_absolute():
        events_jsonl = root / events_jsonl
    ensure_dir(events_jsonl.parent)

    telegram_enabled = env_bool("TELEGRAM_ENABLED", False)
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if telegram_enabled and not (telegram_bot_token and telegram_chat_id):
        logging.warning("TELEGRAM_ENABLED=true pero faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. Telegram queda desactivado.")
        telegram_enabled = False

    target_classes = [x.strip().lower() for x in os.getenv("TARGET_CLASSES", "cat").split(",") if x.strip()]
    if not target_classes:
        target_classes = ["cat"]

    return AppConfig(
        project_root=root,
        cameras_file=cameras_file,
        cameras=cameras,
        model_path=os.getenv("MODEL_PATH", "models/yolo11n.pt"),
        target_classes=target_classes,
        # Default tuned for cats: lower confidence and larger image size. Cats are often small,
        # partially visible, dark, or captured in IR/night mode.
        confidence_threshold=max(0.01, min(0.99, safe_float(os.getenv("CONFIDENCE_THRESHOLD", "0.25"), 0.25))),
        infer_imgsz=max(256, min(1536, safe_int(os.getenv("INFER_IMGSZ", "640"), 640))),
        detect_fps=max(0.1, min(10.0, safe_float(os.getenv("DETECT_FPS", "1.0"), 1.0))),
        cooldown_seconds=max(0, safe_int(os.getenv("COOLDOWN_SECONDS", "60"), 60)),
        draw_boxes=env_bool("DRAW_BOXES", True),
        box_persist_seconds=max(0.0, min(10.0, safe_float(os.getenv("BOX_PERSIST_SECONDS", "2.5"), 2.5))),
        min_box_area_ratio=max(0.0, min(0.50, safe_float(os.getenv("MIN_BOX_AREA_RATIO", "0.0"), 0.0))),
        detector_device=os.getenv("DETECTOR_DEVICE", "cpu").strip() or "cpu",
        max_frame_width=max(0, safe_int(os.getenv("MAX_FRAME_WIDTH", "1280"), 1280)),
        jpeg_quality=max(40, min(95, safe_int(os.getenv("JPEG_QUALITY", "75"), 75))),
        save_dir=save_dir,
        events_jsonl=events_jsonl,
        retention_days=max(0, safe_int(os.getenv("RETENTION_DAYS", "14"), 14)),
        max_events_memory=max(10, safe_int(os.getenv("MAX_EVENTS_MEMORY", "200"), 200)),
        telegram_enabled=telegram_enabled,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        request_timeout_seconds=max(2, safe_int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"), 20)),
        telegram_queue_size=max(1, safe_int(os.getenv("TELEGRAM_QUEUE_SIZE", "50"), 50)),
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=safe_int(os.getenv("WEB_PORT", "8080"), 8080),
        web_title=os.getenv("WEB_TITLE", "CatFinder MVP").strip(),
        web_password=os.getenv("WEB_PASSWORD", "").strip(),
        rtsp_open_timeout_ms=max(1000, safe_int(os.getenv("RTSP_OPEN_TIMEOUT_MS", "5000"), 5000)),
        rtsp_read_timeout_ms=max(1000, safe_int(os.getenv("RTSP_READ_TIMEOUT_MS", "5000"), 5000)),
        rtsp_buffer_size=max(1, safe_int(os.getenv("RTSP_BUFFER_SIZE", "1"), 1)),
        reconnect_delay_seconds=max(1, safe_int(os.getenv("RECONNECT_DELAY_SECONDS", "5"), 5)),
        reconnect_delay_max_seconds=max(5, safe_int(os.getenv("RECONNECT_DELAY_MAX_SECONDS", "60"), 60)),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )
