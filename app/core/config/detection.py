from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.utils import env_bool, safe_float, safe_int


@dataclass(slots=True)
class DetectionSettings:
    """Parámetros del detector YOLO y del pre/post-procesado de frames."""

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


def load_detection_settings() -> DetectionSettings:
    target_classes = [x.strip().lower() for x in os.getenv("TARGET_CLASSES", "cat").split(",") if x.strip()]
    if not target_classes:
        target_classes = ["cat"]

    return DetectionSettings(
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
    )
