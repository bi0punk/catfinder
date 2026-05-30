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
    """Lazy-loaded YOLO detector focused on reliable cat detection.

    The inference lock intentionally serializes model execution. On CPU-only
    systems this is usually more stable than allowing multiple RTSP workers to
    execute PyTorch at the same time.
    """

    ALIASES = {
        "gato": "cat",
        "gatos": "cat",
        "felino": "cat",
        "felinos": "cat",
        "cat": "cat",
        "cats": "cat",
        "perro": "dog",
        "perros": "dog",
        "dog": "dog",
        "dogs": "dog",
        "persona": "person",
        "personas": "person",
        "humano": "person",
        "humanos": "person",
        "person": "person",
        "people": "person",
    }

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._model: Any = None
        self._names: dict[int, str] = {}
        self._target_ids: list[int] = []
        self._target_labels: list[str] = []
        self._resolved_model_path = ""
        self._lock = threading.RLock()
        self.loaded = False
        self.error = ""
        self._last_load_attempt = 0.0
        self._last_infer_ms = 0.0
        self._last_detection_count = 0

    def _resolve_model_path(self) -> str:
        raw = Path(self.cfg.model_path)
        candidates = [raw]
        if not raw.is_absolute():
            candidates.append(self.cfg.project_root / raw)
        candidates.append(Path("/models/yolo11n.pt"))
        candidates.append(self.cfg.project_root / "models" / "yolo11n.pt")
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        return str(raw)

    def _desired_labels(self) -> list[str]:
        labels = []
        for raw in self.cfg.target_classes:
            label = self.ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
            if label and label not in labels:
                labels.append(label)
        return labels or ["cat"]

    def _load_locked(self) -> None:
        from ultralytics import YOLO  # lazy import: avoids heavy startup until needed

        model_path = self._resolve_model_path()
        self._resolved_model_path = model_path
        self._model = YOLO(model_path)
        names_raw = getattr(self._model, "names", {})
        if isinstance(names_raw, dict):
            self._names = {int(k): str(v).lower() for k, v in names_raw.items()}
        else:
            self._names = {i: str(v).lower() for i, v in enumerate(names_raw)}

        desired = self._desired_labels()
        ids: list[int] = []
        for cls in desired:
            ids.extend([idx for idx, label in self._names.items() if label == cls])

        self._target_labels = desired
        self._target_ids = sorted(set(ids))
        if not self._target_ids:
            available = ", ".join(f"{idx}:{name}" for idx, name in list(self._names.items())[:80])
            raise RuntimeError(
                "Las clases objetivo no existen en el modelo. "
                f"target_classes={desired}. Clases disponibles: {available}"
            )

        self.loaded = True
        self.error = ""
        logging.info(
            "YOLO cargado | model=%s | target_labels=%s | target_ids=%s | conf=%.2f | imgsz=%s",
            model_path,
            desired,
            self._target_ids,
            self.cfg.confidence_threshold,
            self.cfg.infer_imgsz,
        )

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

    def _predict(self, frame: np.ndarray, *, conf: float | None = None, imgsz: int | None = None, all_classes: bool = False):
        self.ensure_loaded()
        assert self._model is not None
        source = np.ascontiguousarray(frame)
        kwargs = {
            "source": source,
            "imgsz": int(imgsz or self.cfg.infer_imgsz),
            "conf": float(conf if conf is not None else self.cfg.confidence_threshold),
            "verbose": False,
            "device": self.cfg.detector_device,
        }
        if not all_classes:
            kwargs["classes"] = self._target_ids
        started = time.perf_counter()
        results = self._model.predict(**kwargs)
        self._last_infer_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return results

    def _parse_results(self, frame: np.ndarray, results) -> list[Detection]:
        detections: list[Detection] = []
        if not results:
            self._last_detection_count = 0
            return detections
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            self._last_detection_count = 0
            return detections

        h, w = frame.shape[:2]
        frame_area = max(1, h * w)
        min_area = float(getattr(self.cfg, "min_box_area_ratio", 0.0)) * frame_area

        for box in boxes:
            try:
                x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].tolist()]
                x1 = max(0, min(w - 1, x1))
                x2 = max(0, min(w - 1, x2))
                y1 = max(0, min(h - 1, y1))
                y2 = max(0, min(h - 1, y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                if min_area > 0 and ((x2 - x1) * (y2 - y1)) < min_area:
                    continue
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                label = self._names.get(cls_id, str(cls_id))
                detections.append(Detection(x1=x1, y1=y1, x2=x2, y2=y2, label=label, confidence=confidence))
            except Exception as exc:
                logging.debug("Detección YOLO ignorada por formato inesperado: %s", exc)
        self._last_detection_count = len(detections)
        return detections

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._lock:
            results = self._predict(frame)
            return self._parse_results(frame, results)

    def diagnose(self, frame: np.ndarray, *, conf: float | None = None, imgsz: int | None = None, all_classes: bool = False) -> list[Detection]:
        """Run a manual diagnostic inference.

        all_classes=True is slower but useful to confirm whether the model sees
        something else instead of cat, for example dog/person/bird.
        """
        with self._lock:
            results = self._predict(frame, conf=conf, imgsz=imgsz, all_classes=all_classes)
            return self._parse_results(frame, results)

    def update_runtime_params(self, payload: dict) -> None:
        with self._lock:
            if "confidence_threshold" in payload:
                self.cfg.confidence_threshold = max(0.01, min(0.99, float(payload["confidence_threshold"])))
            if "infer_imgsz" in payload:
                self.cfg.infer_imgsz = max(256, min(1536, int(payload["infer_imgsz"])))
            if "detect_fps" in payload:
                self.cfg.detect_fps = max(0.1, min(10.0, float(payload["detect_fps"])))
            if "cooldown_seconds" in payload:
                self.cfg.cooldown_seconds = max(0, int(payload["cooldown_seconds"]))
            if "draw_boxes" in payload:
                from app.core.utils import coerce_bool

                self.cfg.draw_boxes = coerce_bool(payload["draw_boxes"], True)
            if "box_persist_seconds" in payload:
                self.cfg.box_persist_seconds = max(0.0, min(10.0, float(payload["box_persist_seconds"])))
            if "target_classes" in payload:
                raw = payload["target_classes"]
                classes = raw.split(",") if isinstance(raw, str) else list(raw)
                self.cfg.target_classes = [str(x).strip().lower() for x in classes if str(x).strip()]
                self.loaded = False
                self._model = None
                self._target_ids = []
                self._target_labels = []

    def status(self) -> dict:
        return {
            "loaded": self.loaded,
            "error": self.error,
            "model_path": self.cfg.model_path,
            "resolved_model_path": self._resolved_model_path,
            "target_classes": self.cfg.target_classes,
            "target_labels": self._target_labels,
            "target_ids": self._target_ids,
            "confidence_threshold": self.cfg.confidence_threshold,
            "infer_imgsz": self.cfg.infer_imgsz,
            "detect_fps": self.cfg.detect_fps,
            "draw_boxes": self.cfg.draw_boxes,
            "box_persist_seconds": self.cfg.box_persist_seconds,
            "detector_device": self.cfg.detector_device,
            "last_infer_ms": self._last_infer_ms,
            "last_detection_count": self._last_detection_count,
            "available_classes_sample": self.available_classes(limit=80),
        }

    def available_classes(self, limit: int = 120) -> list[dict]:
        return [{"id": idx, "label": label} for idx, label in list(sorted(self._names.items()))[:limit]]
