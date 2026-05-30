from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2

from app.core.config import AppConfig
from app.detection.draw import draw_detections, draw_overlay, encode_jpeg, resize_max_width
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState, CameraConfig, CameraRuntimeState, Detection
from app.notifier.telegram import TelegramNotifier
from app.storage.evidence import EvidenceStore


class CameraWorker(threading.Thread):
    def __init__(
        self,
        cfg: AppConfig,
        camera: CameraConfig,
        runtime_state: CameraRuntimeState,
        detector: YoloDetector,
        evidence_store: EvidenceStore,
        notifier: TelegramNotifier,
        app_state: AppState,
        stop_event: threading.Event,
    ):
        super().__init__(name=f"camera-{camera.name}", daemon=True)
        self.cfg = cfg
        self.camera = camera
        self.runtime_state = runtime_state
        self.detector = detector
        self.evidence_store = evidence_store
        self.notifier = notifier
        self.app_state = app_state
        self.stop_event = stop_event
        self._stop_camera = threading.Event()
        self._last_detection_ts = 0.0
        self._last_alert_ts = 0.0
        self._last_detections: list[Detection] = []
        self._last_detections_until = 0.0

    def stop(self) -> None:
        self._stop_camera.set()

    def _should_stop(self) -> bool:
        return self.stop_event.is_set() or self._stop_camera.is_set()

    def _open_capture(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self.cfg.rtsp_buffer_size)
        except Exception:
            pass
        for prop_name, value in (
            ("CAP_PROP_OPEN_TIMEOUT_MSEC", self.cfg.rtsp_open_timeout_ms),
            ("CAP_PROP_READ_TIMEOUT_MSEC", self.cfg.rtsp_read_timeout_ms),
        ):
            prop = getattr(cv2, prop_name, None)
            if prop is not None:
                try:
                    cap.set(prop, value)
                except Exception:
                    pass
        return cap

    def run(self) -> None:
        delay = self.cfg.reconnect_delay_seconds
        while not self._should_stop():
            cap = None
            try:
                cap = self._open_capture()
                if not cap.isOpened():
                    raise RuntimeError("VideoCapture no pudo abrir RTSP")
                logging.info("Cámara online: %s", self.camera.name)
                self.runtime_state.mark_error("online", "")
                delay = self.cfg.reconnect_delay_seconds
                self._read_loop(cap)
            except Exception as exc:
                message = str(exc)
                logging.warning("Cámara %s desconectada/error: %s", self.camera.name, message)
                self.runtime_state.mark_reconnect(message)
                if cap is not None:
                    cap.release()
                self.stop_event.wait(delay)
                delay = min(self.cfg.reconnect_delay_max_seconds, max(delay + 2, delay * 2))
            finally:
                if cap is not None:
                    cap.release()
        self.runtime_state.mark_error("stopped", "")
        logging.info("Worker detenido: %s", self.camera.name)

    def _read_loop(self, cap: cv2.VideoCapture) -> None:
        while not self._should_stop():
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError("No se pudo leer frame RTSP")

            max_width = self.camera.max_frame_width or self.cfg.max_frame_width
            frame = resize_max_width(frame, max_width)
            now = time.time()
            detect_fps = self.camera.detect_fps or self.cfg.detect_fps
            detect_interval = 1.0 / max(0.1, detect_fps)

            detections: list[Detection] = []
            if now - self._last_detection_ts >= detect_interval:
                self._last_detection_ts = now
                detections = self._detect_frame(frame)
                if detections:
                    self._last_detections = detections
                    self._last_detections_until = now + self.cfg.box_persist_seconds
                    best = max(detections, key=lambda d: d.confidence)
                    self.runtime_state.mark_detection(best)
                    self._maybe_alert(frame, detections, now)

            if not detections and now <= self._last_detections_until:
                detections = self._last_detections
            elif now > self._last_detections_until:
                self._last_detections = []

            annotated = draw_detections(frame, detections, self.cfg.draw_boxes)
            status_text = ""
            if detections:
                best = max(detections, key=lambda d: d.confidence)
                status_text = f"{best.label} {best.confidence:.2f}"
            annotated = draw_overlay(annotated, self.camera.name, status_text)
            jpeg = encode_jpeg(annotated, self.cfg.jpeg_quality)
            if jpeg:
                self.runtime_state.put_frame(jpeg)

    def _detect_frame(self, frame) -> list[Detection]:
        try:
            return self.detector.detect(frame)
        except Exception as exc:
            self.runtime_state.mark_error("degraded", f"YOLO: {exc}")
            logging.warning("Detección falló en cámara %s: %s", self.camera.name, exc)
            return []

    def _maybe_alert(self, frame, detections: list[Detection], now: float) -> None:
        cooldown = self.camera.cooldown_seconds if self.camera.cooldown_seconds is not None else self.cfg.cooldown_seconds
        if now - self._last_alert_ts < cooldown:
            return
        self._last_alert_ts = now
        annotated = draw_overlay(draw_detections(frame, detections, self.cfg.draw_boxes), self.camera.name, "ALERTA")
        try:
            event = self.evidence_store.save_detection(self.camera.name, annotated, detections)
            self.app_state.add_event(event)
            image_abs = self.cfg.save_dir / event.image_path
            caption = (
                f"🐱 Gato detectado\n"
                f"Cámara: {event.camera_name}\n"
                f"Clase: {event.label}\n"
                f"Confianza: {event.confidence:.2f}\n"
                f"Fecha: {event.ts_local}"
            )
            self.notifier.enqueue_photo(event, image_abs, caption)
            logging.info("Gato detectado | cam=%s | conf=%.2f | image=%s", event.camera_name, event.confidence, event.image_path)
        except Exception as exc:
            logging.warning("No se pudo guardar/enviar evidencia de %s: %s", self.camera.name, exc)
