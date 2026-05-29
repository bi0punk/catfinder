from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import AppConfig
from app.domain.models import Detection


class YoloDetector:
    """Lazy-loaded YOLO detector.

    The lock intentionally serializes inference. On CPU-only systems this is usually
    more stable than allowing multiple camera threads to run YOLO at the same time.
    """

    ALIASES = {
        "gato": "cat",
        "gatos": "cat",
        "cat": "cat",
        "perro": "dog",
        "perros": "dog",
        "persona": "person",
        "personas": "person",
        "humano": "person",
    }

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._model: Any = None
        self._names: dict[int, str] = {}
        self._target_ids: list[int] = []
        self._lock = threading.RLock()
        self.loaded = False
        self.error = ""
        self._last_load_attempt = 0.0

    def _resolve_model_path(self) -> str:
        raw = Path(self.cfg.model_path)
        candidates = [raw]
        if not raw.is_absolute():
            candidates.append(self.cfg.project_root / raw)
        candidates.append(Path("/models/yolo11n.pt"))
        candidates.append(self.cfg.project_root / "models" / "yolo11n.pt")
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        return str(raw)

    def _load_locked(self) -> None:
        from ultralytics import YOLO  # lazy import

        model_path = self._resolve_model_path()
        self._model = YOLO(model_path)
        names_raw = getattr(self._model, "names", {})
        if isinstance(names_raw, dict):
            self._names = {int(k): str(v).lower() for k, v in names_raw.items()}
        else:
            self._names = {i: str(v).lower() for i, v in enumerate(names_raw)}

        desired = [self.ALIASES.get(cls.lower(), cls.lower()) for cls in self.cfg.target_classes]
        ids: list[int] = []
        for cls in desired:
            ids.extend([idx for idx, label in self._names.items() if label == cls])
        self._target_ids = sorted(set(ids))
        if not self._target_ids:
            available = list(self._names.values())[:40]
            raise RuntimeError(f"Clases objetivo no encontradas: {desired}. Disponibles ejemplo: {available}")

        self.loaded = True
        self.error = ""
        logging.info("YOLO cargado: %s | clases=%s | ids=%s", model_path, desired, self._target_ids)

    def ensure_loaded(self) -> None:
        with self._lock:
            if self.loaded:
                return
            now = time.time()
            if self.error and now - self._last_load_attempt < 20:
                raise RuntimeError(self.error)
            self._last_load_attempt = now
            try:
                self._load_locked()
            except Exception as exc:
                self.error = str(exc)
                logging.exception("No se pudo cargar YOLO: %s", exc)
                raise

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._lock:
            self.ensure_loaded()
            assert self._model is not None
            results = self._model.predict(
                source=frame,
                imgsz=self.cfg.infer_imgsz,
                conf=self.cfg.confidence_threshold,
                classes=self._target_ids,
                verbose=False,
                device="cpu",
            )

        detections: list[Detection] = []
        if not results:
            return detections
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return detections

        for box in boxes:
            try:
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                label = self._names.get(cls_id, str(cls_id))
                detections.append(Detection(x1=x1, y1=y1, x2=x2, y2=y2, label=label, confidence=confidence))
            except Exception as exc:
                logging.debug("Detección YOLO ignorada por formato inesperado: %s", exc)
        return detections

    def update_runtime_params(self, payload: dict) -> None:
        with self._lock:
            if "confidence_threshold" in payload:
                self.cfg.confidence_threshold = max(0.01, min(0.99, float(payload["confidence_threshold"])))
            if "infer_imgsz" in payload:
                self.cfg.infer_imgsz = max(256, int(payload["infer_imgsz"]))
            if "detect_fps" in payload:
                self.cfg.detect_fps = max(0.1, float(payload["detect_fps"]))
            if "cooldown_seconds" in payload:
                self.cfg.cooldown_seconds = max(0, int(payload["cooldown_seconds"]))
            if "target_classes" in payload:
                raw = payload["target_classes"]
                classes = raw.split(",") if isinstance(raw, str) else list(raw)
                self.cfg.target_classes = [str(x).strip().lower() for x in classes if str(x).strip()]
                self.loaded = False
                self._model = None
                self._target_ids = []

    def status(self) -> dict:
        return {
            "loaded": self.loaded,
            "error": self.error,
            "target_classes": self.cfg.target_classes,
            "target_ids": self._target_ids,
            "confidence_threshold": self.cfg.confidence_threshold,
            "infer_imgsz": self.cfg.infer_imgsz,
        }
