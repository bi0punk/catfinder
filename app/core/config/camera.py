from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.utils import coerce_bool, ensure_dir, safe_float, safe_int, valid_camera_name
from app.domain.models import CameraConfig


@dataclass(slots=True)
class CameraSettings:
    """Configuración de cámaras RTSP (archivo + lista efectiva)."""

    cameras_file: Path
    cameras: list[CameraConfig]


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


def ensure_sample_cameras_file(cameras_file: Path) -> None:
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


def load_camera_settings(project_root: Path, cameras_file_env: str) -> CameraSettings:
    cameras_file = Path(cameras_file_env)
    if not cameras_file.is_absolute():
        cameras_file = project_root / cameras_file
    ensure_sample_cameras_file(cameras_file)

    file_cameras = load_cameras_file(cameras_file)
    env_cameras = _parse_rtsp_urls(os.getenv("RTSP_URLS", ""))

    # Si el archivo existe con cámaras reales, manda el archivo. Si solo está el sample deshabilitado
    # y el usuario configuró RTSP_URLS, usa RTSP_URLS para facilitar MVP rápido.
    enabled_file_cameras = [c for c in file_cameras if c.enabled]
    cameras = file_cameras
    if env_cameras and not enabled_file_cameras:
        cameras = env_cameras
        save_cameras_file(cameras_file, cameras)

    return CameraSettings(cameras_file=cameras_file, cameras=cameras)
