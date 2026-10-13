from __future__ import annotations

from app.core.utils import coerce_bool, safe_float, safe_int, valid_camera_name
from app.domain.models import CameraConfig


def camera_from_payload(payload: dict) -> CameraConfig:
    name = str(payload.get("name", "")).strip()
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    if not valid_camera_name(name):
        raise ValueError("Nombre inválido. Usa letras, números, guion o guion bajo")
    if not rtsp_url.startswith("rtsp://"):
        raise ValueError("rtsp_url debe empezar con rtsp://")
    split_mode = str(payload.get("split_mode", "none")).lower()
    if split_mode not in {"none", "left", "right", "top", "bottom"}:
        split_mode = "none"
    return CameraConfig(
        name=name,
        rtsp_url=rtsp_url,
        enabled=coerce_bool(payload.get("enabled", True), True),
        detect_fps=safe_float(payload.get("detect_fps"), 0.0) or None,
        cooldown_seconds=safe_int(payload.get("cooldown_seconds"), 0) or None,
        max_frame_width=safe_int(payload.get("max_frame_width"), 0) or None,
        split_mode=split_mode,
    )
