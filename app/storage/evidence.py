from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from app.core.config import AppConfig
from app.core.utils import ensure_dir, filename_timestamp, local_now_str, utc_now_iso
from app.domain.models import Detection, EventRecord


class EvidenceStore:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._lock = threading.RLock()
        ensure_dir(cfg.save_dir)
        ensure_dir(cfg.events_jsonl.parent)

    def save_detection(self, camera_name: str, frame: np.ndarray, detections: list[Detection]) -> EventRecord:
        best = max(detections, key=lambda d: d.confidence)
        camera_dir = ensure_dir(self.cfg.save_dir / camera_name)
        filename = f"{filename_timestamp()}_{best.label}_{best.confidence:.2f}.jpg"
        image_path_abs = camera_dir / filename
        ok = cv2.imwrite(str(image_path_abs), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.cfg.jpeg_quality)])
        if not ok:
            raise RuntimeError(f"No se pudo guardar evidencia: {image_path_abs}")

        rel_path = str(image_path_abs.relative_to(self.cfg.save_dir))
        event = EventRecord(
            ts_utc=utc_now_iso(),
            ts_local=local_now_str(),
            camera_name=camera_name,
            label=best.label,
            confidence=round(float(best.confidence), 4),
            image_path=rel_path,
            detections=[d.to_dict() for d in detections],
        )
        self.append_event(event)
        return event

    def append_event(self, event: EventRecord) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            with self.cfg.events_jsonl.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def cleanup_old_files(self) -> int:
        if self.cfg.retention_days <= 0:
            return 0
        cutoff = time.time() - self.cfg.retention_days * 86400
        removed = 0
        for path in self.cfg.save_dir.rglob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except Exception as exc:
                logging.debug("No se pudo limpiar archivo antiguo %s: %s", path, exc)
        return removed


class RetentionThread(threading.Thread):
    def __init__(self, store: EvidenceStore, stop_event: threading.Event):
        super().__init__(name="retention", daemon=True)
        self.store = store
        self.stop_event = stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                removed = self.store.cleanup_old_files()
                if removed:
                    logging.info("Retención: %d evidencias antiguas eliminadas", removed)
            except Exception as exc:
                logging.warning("Retención falló: %s", exc)
            self.stop_event.wait(3600)
