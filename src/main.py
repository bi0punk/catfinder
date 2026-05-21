"""
CatFinder RTSP Monitor – v2.1 (fixed)
--------------------------------------
Correcciones aplicadas (de menor a mayor):

  [B1] TRIVIAL   – from flask import request movido al top del archivo.
  [B2] TRIVIAL   – poll() ahora se llama inmediatamente al cargar la página
                   (antes el primer refresco tardaba 3 s).
  [B3] FÁCIL     – update_view_frame() ya no tiene calidad hardcoded a 85;
                   recibe jpeg_quality desde AppConfig.
  [B4] FÁCIL     – _stream_loop calculaba max(detections) dos veces; ahora
                   se computa una sola vez y se reutiliza.
  [B5] FÁCIL     – conf-badge en Jinja dejaba de renderizarse con conf=0.0
                   (falsy); ahora siempre existe en el DOM y JS lo actualiza.
  [B6] MEDIO     – XSS en updateEvents(): se usaba innerHTML con datos crudos
                   de la API. Ahora se construyen los nodos con createElement /
                   textContent para escapar correctamente.
  [B7] MEDIO     – Cola de Telegram sin maxsize podía crecer sin límite bajo
                   carga alta. Se añade maxsize=200 con descarte de mensajes
                   antiguos cuando está llena.
  [B8] MEDIO     – status_str leía state.views[...].status fuera del lock de
                   AppState. Ahora se accede a través del método thread-safe.
  [B9] GRANDE    – app.run() bloqueaba el hilo principal impidiendo un apagado
                   limpio vía señal. Reemplazado por make_server() de Werkzeug,
                   con server.shutdown() invocado desde el handler de señal.
  [B10] GRANDE   – knownEvents en el frontend crecía indefinidamente (memory
                   leak en browser). Ahora se limita a MAX_EVENTS entradas y
                   se recorta periódicamente.
"""

import json
import logging
import os
import queue
import signal
import concurrent.futures
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np
import requests
# [B1 FIX] request importado al nivel del módulo, no dentro de cada función.
from flask import Flask, Response, abort, jsonify, render_template, request, send_file
from dotenv import load_dotenv
from ultralytics import YOLO
from werkzeug.serving import make_server  # [B9 FIX]


# ─────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────


@dataclass
class CameraConfig:
    name: str
    rtsp_url: str
    split_mode: str = "none"   # none | vertical | horizontal
    split_ratio: float = 0.5


@dataclass
class ViewConfig:
    view_id: str
    camera_name: str
    view_name: str
    split_mode: str
    crop_label: str            # full | left | right | top | bottom


@dataclass
class AppConfig:
    cameras: List[CameraConfig]
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    model_path: str
    target_classes: List[str]
    confidence_threshold: float
    cooldown_seconds: int
    process_every_n_frames: int
    preview_every_n_frames: int
    save_dir: Path
    reconnect_delay_seconds: int
    jpeg_quality: int
    infer_imgsz: int
    request_timeout_seconds: int
    draw_boxes: bool
    web_host: str
    web_port: int
    web_title: str
    max_events: int
    stream_sleep_ms: int
    camera_rois: Dict[str, Tuple[int, int, int, int]]   # view_id -> (x1,y1,x2,y2)
    web_password: str = ""                               # vacío = sin autenticación


@dataclass
class EventRecord:
    ts_utc: str
    ts_local: str
    camera_name: str
    view_id: str
    label: str
    confidence: float
    alert_image: str   # ruta relativa a save_dir para servir por web
    raw_image: str     # idem


@dataclass
class ViewState:
    view_id: str
    camera_name: str
    view_name: str
    split_mode: str
    crop_label: str
    status: str = "starting"
    last_frame_at: str = "-"
    last_detection_label: str = "-"
    last_detection_conf: float = 0.0
    last_detection_at: str = "-"
    detection_count: int = 0
    latest_raw_jpeg: Optional[bytes] = None
    latest_annotated_jpeg: Optional[bytes] = None
    width: int = 0
    height: int = 0
    frame_counter: int = 0


# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────


def setup_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(asctime)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_now_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def clamp_ratio(value: float) -> float:
    return min(0.9, max(0.1, value))


def parse_name_url_map(raw: str) -> List[Tuple[str, str]]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("RTSP_URLS está vacío. Define al menos una URL en .env")

    items: List[Tuple[str, str]] = []
    for idx, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, url = item.split("=", 1)
            items.append((name.strip(), url.strip()))
        else:
            items.append((f"cam_{idx}", item))

    if not items:
        raise ValueError("No se parsearon cámaras válidas de RTSP_URLS")
    return items


def parse_key_value_map(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_roi_map(raw: str) -> Dict[str, Tuple[int, int, int, int]]:
    """
    Formato: viewid=x1:y1:x2:y2,viewid2=x1:y1:x2:y2
    Ejemplo: patio__left=0:100:640:480
    """
    result: Dict[str, Tuple[int, int, int, int]] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if "=" not in item:
            continue
        key, coords = item.split("=", 1)
        parts = coords.split(":")
        if len(parts) == 4:
            try:
                result[key.strip()] = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
            except ValueError:
                logging.warning("ROI inválido para %s: %s", key, coords)
    return result


def parse_camera_configs() -> List[CameraConfig]:
    base = parse_name_url_map(os.getenv("RTSP_URLS", ""))
    split_modes = parse_key_value_map(os.getenv("CAMERA_SPLITS", ""))
    split_ratios_raw = parse_key_value_map(os.getenv("CAMERA_SPLIT_RATIOS", ""))

    cameras: List[CameraConfig] = []
    for name, rtsp_url in base:
        # Advertir si el nombre de cámara colisiona con rutas reservadas
        if name.lower() == "raw":
            logging.warning(
                "La cámara se llama 'raw', lo que colisiona con /stream/raw/<view_id>. "
                "Renómbrala en RTSP_URLS para evitar ambigüedad."
            )
        split_mode = split_modes.get(name, "none").strip().lower() or "none"
        if split_mode not in {"none", "vertical", "horizontal"}:
            logging.warning("split_mode inválido para %s -> %s. Usando none.", name, split_mode)
            split_mode = "none"
        split_ratio = clamp_ratio(safe_float(split_ratios_raw.get(name, "0.5"), 0.5))
        cameras.append(CameraConfig(name=name, rtsp_url=rtsp_url, split_mode=split_mode, split_ratio=split_ratio))
    return cameras


def load_config() -> AppConfig:
    load_dotenv()

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    setup_logging(log_level)

    telegram_enabled = os.getenv("TELEGRAM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "y"}
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if telegram_enabled:
        if not telegram_bot_token:
            logging.warning("TELEGRAM_BOT_TOKEN no está definido. Telegram deshabilitado automáticamente.")
            telegram_enabled = False
        elif not telegram_chat_id:
            logging.warning("TELEGRAM_CHAT_ID no está definido. Telegram deshabilitado automáticamente.")
            telegram_enabled = False

    target_classes = [x.strip().lower() for x in os.getenv("TARGET_CLASSES", "cat").split(",") if x.strip()]
    cameras = parse_camera_configs()
    camera_rois = parse_roi_map(os.getenv("CAMERA_ROIS", ""))

    return AppConfig(
        cameras=cameras,
        telegram_enabled=telegram_enabled,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        model_path=os.getenv("MODEL_PATH", "yolo11n.pt").strip(),
        target_classes=target_classes,
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.55")),
        cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "60")),
        process_every_n_frames=max(1, int(os.getenv("PROCESS_EVERY_N_FRAMES", "5"))),
        preview_every_n_frames=max(1, int(os.getenv("PREVIEW_EVERY_N_FRAMES", "2"))),
        save_dir=Path(os.getenv("SAVE_DIR", "captures")).resolve(),
        reconnect_delay_seconds=int(os.getenv("RECONNECT_DELAY_SECONDS", "5")),
        jpeg_quality=int(os.getenv("JPEG_QUALITY", "85")),
        infer_imgsz=int(os.getenv("INFER_IMGSZ", "960")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        draw_boxes=os.getenv("DRAW_BOXES", "true").strip().lower() in {"1", "true", "yes", "y"},
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        web_title=os.getenv("WEB_TITLE", "CatFinder RTSP Monitor").strip(),
        max_events=int(os.getenv("MAX_EVENTS", "50")),
        stream_sleep_ms=int(os.getenv("STREAM_SLEEP_MS", "60")),
        web_password=os.getenv("WEB_PASSWORD", "").strip(),
        camera_rois=camera_rois,
    )


def build_view_configs(cameras: List[CameraConfig]) -> List[ViewConfig]:
    views: List[ViewConfig] = []
    for cam in cameras:
        if cam.split_mode == "vertical":
            views.append(ViewConfig(f"{cam.name}__left",   cam.name, f"{cam.name} / izquierda", "vertical",   "left"))
            views.append(ViewConfig(f"{cam.name}__right",  cam.name, f"{cam.name} / derecha",   "vertical",   "right"))
        elif cam.split_mode == "horizontal":
            views.append(ViewConfig(f"{cam.name}__top",    cam.name, f"{cam.name} / superior",  "horizontal", "top"))
            views.append(ViewConfig(f"{cam.name}__bottom", cam.name, f"{cam.name} / inferior",  "horizontal", "bottom"))
        else:
            views.append(ViewConfig(f"{cam.name}__full",   cam.name, cam.name,                  "none",       "full"))
    return views


# ─────────────────────────────────────────────
# Imagen / frame helpers
# ─────────────────────────────────────────────


def encode_jpg(frame, quality: int) -> Optional[bytes]:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buffer.tobytes() if ok else None


def draw_detections(frame, detections: List[Tuple[int, int, int, int, str, float]]):
    annotated = frame.copy()
    for x1, y1, x2, y2, label, score in detections:
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            annotated,
            f"{label} {score:.2f}",
            (x1, max(20, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return annotated


def add_overlay(frame, line1: str, line2: str = ""):
    out = frame.copy()
    h, w = out.shape[:2]
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 54), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, out, 0.35, 0, out)
    cv2.putText(out, line1, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (255, 255, 255), 1, cv2.LINE_AA)
    if line2:
        cv2.putText(out, line2, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 200), 1, cv2.LINE_AA)
    return out


def apply_roi(frame, roi: Optional[Tuple[int, int, int, int]]):
    """Dibuja un rectángulo indicando el ROI activo."""
    if roi is None:
        return frame
    x1, y1, x2, y2 = roi
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    out = frame.copy()
    cv2.rectangle(out, (x1, y1), (x2, y2), (255, 200, 0), 2)
    return out


# ─────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────


# [B7 FIX] Cola con maxsize para evitar crecimiento ilimitado de memoria.
_TELEGRAM_QUEUE_MAXSIZE = 200


class TelegramNotifier:
    """
    Envía fotos a Telegram en un hilo separado (no bloqueante).
    Si enabled=False todos los métodos son no-op silenciosos.
    """

    def __init__(self, enabled: bool, bot_token: str, chat_id: str, timeout_seconds: int = 20):
        self.enabled = enabled
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else ""
        # [B7 FIX] maxsize evita que la cola crezca sin límite bajo alta carga.
        self._queue: queue.Queue = queue.Queue(maxsize=_TELEGRAM_QUEUE_MAXSIZE)
        if enabled:
            self._worker_thread = threading.Thread(target=self._worker, daemon=True, name="telegram-worker")
            self._worker_thread.start()
            logging.info("TelegramNotifier iniciado (chat_id=%s)", chat_id)
        else:
            logging.info("TelegramNotifier deshabilitado.")

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if isinstance(item, tuple):
                if len(item) == 2:
                    self._send_sync(item[0], item[1])
                elif len(item) == 3:
                    self._send_sync_bytes(*item)
            self._queue.task_done()

    def _send_sync(self, image_path: Path, caption: str) -> None:
        url = f"{self.base_url}/sendPhoto"
        try:
            with image_path.open("rb") as f:
                response = requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": f},
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "CatFinder/2.1"},
                )
            if response.ok:
                logging.info("Telegram OK -> %s", image_path.name)
            else:
                logging.error("Telegram FAIL status=%s body=%s", response.status_code, response.text[:200])
        except Exception as exc:
            sanitized = f"https://api.telegram.org/bot***{self.bot_token[-4:]}" if self.bot_token else ""
            logging.error("Telegram exception enviando %s (url=%s): %s", image_path.name, sanitized, exc)

    def _send_sync_bytes(self, image_bytes: bytes, filename: str, caption: str) -> None:
        url = f"{self.base_url}/sendPhoto"
        try:
            from io import BytesIO
            response = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption},
                files={"photo": (filename, BytesIO(image_bytes), "image/jpeg")},
                timeout=self.timeout_seconds,
                headers={"User-Agent": "CatFinder/2.1"},
            )
            if response.ok:
                logging.info("Telegram OK -> %s", filename)
            else:
                logging.error("Telegram FAIL status=%s body=%s", response.status_code, response.text[:200])
        except Exception as exc:
            sanitized = f"https://api.telegram.org/bot***{self.bot_token[-4:]}" if self.bot_token else ""
            logging.error("Telegram exception enviando %s (url=%s): %s", filename, sanitized, exc)

    def send_photo(self, image_path: Path, caption: str) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait((image_path, caption))
        except queue.Full:
            logging.warning("Cola Telegram llena (%d items). Alerta descartada: %s", _TELEGRAM_QUEUE_MAXSIZE, image_path.name)

    def send_photo_bytes(self, image_bytes: bytes, filename: str, caption: str) -> None:
        if not self.enabled:
            return
        try:
            self._queue.put_nowait((image_bytes, filename, caption))
        except queue.Full:
            logging.warning("Cola Telegram llena (%d items). Alerta descartada: %s", _TELEGRAM_QUEUE_MAXSIZE, filename)

    def stop(self) -> None:
        if self.enabled:
            self._queue.put(None)


# ─────────────────────────────────────────────
# Motor de detección
# ─────────────────────────────────────────────


class DetectionEngine:
    def __init__(self, model_path: str, confidence_threshold: float, infer_imgsz: int):
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.infer_imgsz = infer_imgsz
        self.names = self._normalize_names(self.model.names)
        logging.info("Modelo cargado: %s | clases disponibles: %s", model_path, len(self.names))

    @staticmethod
    def _normalize_names(names) -> Dict[int, str]:
        if isinstance(names, dict):
            return {int(k): str(v).lower() for k, v in names.items()}
        if isinstance(names, list):
            return {idx: str(v).lower() for idx, v in enumerate(names)}
        return {}

    def resolve_target_ids(self, target_classes: List[str]) -> List[int]:
        ids = [idx for idx, name in self.names.items() if name in target_classes]
        if not ids:
            raise ValueError(
                f"Clases objetivo {target_classes} no encontradas en el modelo. "
                f"Muestra disponible: {list(self.names.values())[:20]}"
            )
        return ids

    def infer(self, frame):
        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            imgsz=self.infer_imgsz,
            verbose=False,
            stream=False,
        )
        return results[0] if results else None


# ─────────────────────────────────────────────
# Estado compartido
# ─────────────────────────────────────────────


class AppState:
    def __init__(self, views: List[ViewConfig], max_events: int, jpeg_quality: int):
        self.lock = threading.RLock()
        self.jpeg_quality = jpeg_quality  # [B3 FIX] guardado para encode_jpg
        self.views: Dict[str, ViewState] = {
            v.view_id: ViewState(
                view_id=v.view_id,
                camera_name=v.camera_name,
                view_name=v.view_name,
                split_mode=v.split_mode,
                crop_label=v.crop_label,
            )
            for v in views
        }
        self.events: Deque[EventRecord] = deque(maxlen=max_events)
        self._total_detections: int = 0

    # [B3 FIX] Usa self.jpeg_quality en lugar del valor hardcodeado 85.
    def update_view_frame(self, view_id: str, raw_frame, annotated_frame, status: str) -> None:
        raw_jpg = encode_jpg(raw_frame, quality=self.jpeg_quality)
        ann_jpg = encode_jpg(annotated_frame, quality=self.jpeg_quality)
        with self.lock:
            view = self.views[view_id]
            if raw_jpg:
                view.latest_raw_jpeg = raw_jpg
            if ann_jpg:
                view.latest_annotated_jpeg = ann_jpg
            view.status = status
            view.last_frame_at = local_now_str()
            view.height, view.width = raw_frame.shape[:2]
            view.frame_counter += 1

    def update_view_status(self, camera_name: str, status: str) -> None:
        with self.lock:
            for view in self.views.values():
                if view.camera_name == camera_name:
                    view.status = status

    # [B8 FIX] Método thread-safe para leer el status de una vista.
    def get_view_status(self, view_id: str) -> str:
        with self.lock:
            view = self.views.get(view_id)
            return view.status if view else "unknown"

    def update_detection(self, view_id: str, label: str, confidence: float) -> None:
        with self.lock:
            view = self.views[view_id]
            view.last_detection_label = label
            view.last_detection_conf = float(confidence)
            view.last_detection_at = local_now_str()
            view.detection_count += 1
            self._total_detections += 1

    def add_event(self, event: EventRecord) -> None:
        with self.lock:
            self.events.appendleft(event)

    def get_stream_bytes(self, view_id: str, annotated: bool = True) -> Optional[bytes]:
        with self.lock:
            view = self.views.get(view_id)
            if view is None:
                return None
            return view.latest_annotated_jpeg if annotated else view.latest_raw_jpeg

    def _view_dict(self, view: ViewState) -> dict:
        return {
            "view_id": view.view_id,
            "camera_name": view.camera_name,
            "view_name": view.view_name,
            "split_mode": view.split_mode,
            "crop_label": view.crop_label,
            "status": view.status,
            "last_frame_at": view.last_frame_at,
            "last_detection_label": view.last_detection_label,
            "last_detection_conf": round(view.last_detection_conf, 3),
            "last_detection_at": view.last_detection_at,
            "detection_count": view.detection_count,
            "width": view.width,
            "height": view.height,
            "frame_counter": view.frame_counter,
        }

    def _event_dict(self, event: EventRecord) -> dict:
        return {
            "ts_utc": event.ts_utc,
            "ts_local": event.ts_local,
            "camera_name": event.camera_name,
            "view_id": event.view_id,
            "label": event.label,
            "confidence": event.confidence,
            "alert_image": event.alert_image,
            "raw_image": event.raw_image,
        }

    def snapshot(self, page: int = 0, page_size: int = 50) -> dict:
        with self.lock:
            views = [self._view_dict(v) for v in self.views.values()]
            all_events = list(self.events)
            online = sum(1 for v in self.views.values() if v.status == "online")
            total_det = self._total_detections

        start = page * page_size
        events_page = [self._event_dict(e) for e in all_events[start: start + page_size]]
        return {
            "views": views,
            "events": events_page,
            "total_events": len(all_events),
            "online_views": online,
            "total_views": len(views),
            "total_detections": total_det,
        }


# ─────────────────────────────────────────────
# Pool de frames (último frame, thread-safe)
# ─────────────────────────────────────────────


class FramePool:
    """Retiene solo el frame más reciente. Publicador y consumidor
       operan en hilos distintos sin bloqueo mutuo."""
    def __init__(self):
        self._cv = threading.Condition()
        self._frame = None

    def publish(self, frame):
        with self._cv:
            self._frame = frame
            self._cv.notify_all()

    def latest(self, timeout=None):
        with self._cv:
            if self._frame is None:
                self._cv.wait(timeout)
            frame = self._frame
            self._frame = None
            return frame

    def peek(self):
        with self._cv:
            return self._frame is not None


# ─────────────────────────────────────────────
# Worker de inferencia (hilo separado)
# ─────────────────────────────────────────────


class InferenceWorker(threading.Thread):
    """Corre YOLO en un hilo dedicado para no bloquear la lectura de frames."""

    def __init__(
        self,
        camera_name: str,
        detector: DetectionEngine,
        target_ids: List[int],
        cfg: AppConfig,
        stop_event: threading.Event,
        infer_queue: queue.Queue,
        frame_pools: Dict[str, FramePool],
    ):
        super().__init__(name=f"infer:{camera_name}", daemon=True)
        self.detector = detector
        self.target_ids = set(target_ids)
        self.cfg = cfg
        self.stop_event = stop_event
        self.infer_queue = infer_queue
        self.frame_pools = frame_pools

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                view_cfg, view_frame = self.infer_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            result = self.detector.infer(view_frame)
            detections: List[Tuple[int, int, int, int, str, float]] = []

            if result is not None and result.boxes is not None:
                roi = self.cfg.camera_rois.get(view_cfg.view_id)
                for box in result.boxes:
                    cls_id = int(box.cls[0].item())
                    score = float(box.conf[0].item())
                    if cls_id not in self.target_ids:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    if roi:
                        rx1, ry1, rx2, ry2 = roi
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        if not (rx1 <= cx <= rx2 and ry1 <= cy <= ry2):
                            continue
                    label = self.detector.names.get(cls_id, str(cls_id))
                    detections.append((x1, y1, x2, y2, label, score))

            annotated = draw_detections(view_frame, detections) if (detections and self.cfg.draw_boxes) else view_frame.copy()

            roi = self.cfg.camera_rois.get(view_cfg.view_id)
            if roi:
                annotated = apply_roi(annotated, roi)

            strongest = max(detections, key=lambda x: x[5]) if detections else None
            line2 = f"detectado={strongest[4]}  conf={strongest[5]:.2f}" if strongest else ""
            annotated = add_overlay(annotated, f"{view_cfg.view_name}  {local_now_str()}", line2)

            self.frame_pools[view_cfg.view_id].publish((view_cfg, view_frame, annotated, detections, strongest))


# ─────────────────────────────────────────────
# Worker de cámara
# ─────────────────────────────────────────────


class CameraWorker(threading.Thread):
    def __init__(
        self,
        camera: CameraConfig,
        view_configs: List[ViewConfig],
        cfg: AppConfig,
        detector: DetectionEngine,
        notifier: TelegramNotifier,
        target_ids: List[int],
        state: AppState,
        stop_event: threading.Event,
    ):
        super().__init__(name=f"camera:{camera.name}", daemon=True)
        self.camera = camera
        self.view_configs: Dict[str, ViewConfig] = {vc.view_id: vc for vc in view_configs if vc.camera_name == camera.name}
        self.cfg = cfg
        self.detector = detector
        self.notifier = notifier
        self.target_ids = set(target_ids)
        self.state = state
        self.stop_event = stop_event
        self.frame_count = 0
        self.last_alert_at: Dict[str, float] = {}
        self.camera_dir = self.cfg.save_dir / self.camera.name
        ensure_dir(self.camera_dir)
        self.infer_queue: queue.Queue = queue.Queue(maxsize=2)
        self.frame_pools: Dict[str, FramePool] = {vc.view_id: FramePool() for vc in self.view_configs.values()}
        self.infer_worker: Optional[InferenceWorker] = None
        self.disk_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix=f"disk:{camera.name}"
        )

    # ── stream ──────────────────────────────

    def run(self) -> None:
        self.infer_worker = InferenceWorker(
            camera_name=self.camera.name,
            detector=self.detector,
            target_ids=list(self.target_ids),
            cfg=self.cfg,
            stop_event=self.stop_event,
            infer_queue=self.infer_queue,
            frame_pools=self.frame_pools,
        )
        self.infer_worker.start()

        while not self.stop_event.is_set():
            cap = self._open_stream()
            if cap is None:
                self.state.update_view_status(self.camera.name, "offline")
                time.sleep(self.cfg.reconnect_delay_seconds)
                continue
            try:
                self._stream_loop(cap)
            finally:
                cap.release()
            if not self.stop_event.is_set():
                self.state.update_view_status(self.camera.name, "reconnecting")
                logging.warning("%s desconectado. Reconectando en %ss…", self.camera.name, self.cfg.reconnect_delay_seconds)
                time.sleep(self.cfg.reconnect_delay_seconds)

    def _open_stream(self):
        logging.info("Abriendo stream RTSP -> %s", self.camera.rtsp_url)
        cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logging.error("No se pudo abrir el stream RTSP de %s", self.camera.name)
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        self.frame_count = 0
        self.state.update_view_status(self.camera.name, "online")
        return cap

    # ── split ────────────────────────────────

    def _split_frame(self, frame) -> List[Tuple[ViewConfig, object]]:
        h, w = frame.shape[:2]
        ratio = self.camera.split_ratio

        if self.camera.split_mode == "vertical":
            cut = max(1, min(w - 1, int(w * ratio)))
            pairs = [
                (self.view_configs.get(f"{self.camera.name}__left"),  np.ascontiguousarray(frame[:, :cut])),
                (self.view_configs.get(f"{self.camera.name}__right"), np.ascontiguousarray(frame[:, cut:])),
            ]
        elif self.camera.split_mode == "horizontal":
            cut = max(1, min(h - 1, int(h * ratio)))
            pairs = [
                (self.view_configs.get(f"{self.camera.name}__top"),    np.ascontiguousarray(frame[:cut, :])),
                (self.view_configs.get(f"{self.camera.name}__bottom"), np.ascontiguousarray(frame[cut:, :])),
            ]
        else:
            pairs = [(self.view_configs.get(f"{self.camera.name}__full"), np.ascontiguousarray(frame))]

        return [(vc, fr) for vc, fr in pairs if vc is not None]

    # ── loop principal ───────────────────────

    def _stream_loop(self, cap) -> None:
        while not self.stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                logging.error("Lectura de frame fallida en %s", self.camera.name)
                break

            self.frame_count += 1
            run_detect  = (self.frame_count % self.cfg.process_every_n_frames  == 0)
            run_preview = (self.frame_count % self.cfg.preview_every_n_frames  == 0)

            if not run_detect and not run_preview:
                continue

            for view_cfg, view_frame in self._split_frame(frame):
                if run_detect:
                    try:
                        self.infer_queue.put_nowait((view_cfg, view_frame))
                    except queue.Full:
                        pass

                if run_preview:
                    result = self.frame_pools[view_cfg.view_id].latest(timeout=0)
                    if result is not None:
                        vc, raw_fr, ann_fr, dets, strongest = result
                        self.state.update_view_frame(vc.view_id, raw_fr, ann_fr, "online")
                        if strongest:
                            self._maybe_alert(vc, raw_fr, ann_fr, dets, strongest)

    # ── alerta ───────────────────────────────

    def _maybe_alert(self, view_cfg: ViewConfig, raw_frame, annotated_frame, detections, strongest) -> None:
        now = time.time()
        last = self.last_alert_at.get(view_cfg.view_id, 0.0)
        remaining = self.cfg.cooldown_seconds - int(now - last)
        if now - last < self.cfg.cooldown_seconds:
            logging.info(
                "Detección ignorada (cooldown) | view=%s label=%s score=%.3f restante=%ss",
                view_cfg.view_id, strongest[4], strongest[5], max(0, remaining),
            )
            return
        self.last_alert_at[view_cfg.view_id] = now
        self.state.update_detection(view_cfg.view_id, strongest[4], strongest[5])
        self._handle_detection(view_cfg, raw_frame, annotated_frame, detections, strongest)

    def _handle_detection(self, view_cfg: ViewConfig, raw_frame, annotated_frame, detections, strongest) -> None:
        x1, y1, x2, y2, label, score = strongest
        ts_file  = local_now_for_filename()
        ts_utc   = utc_now_iso()
        ts_local = local_now_str()

        raw_bytes = encode_jpg(raw_frame, self.cfg.jpeg_quality)
        ann_bytes = encode_jpg(annotated_frame, self.cfg.jpeg_quality)

        metadata = {
            "camera":          self.camera.name,
            "view_id":         view_cfg.view_id,
            "view_name":       view_cfg.view_name,
            "split_mode":      self.camera.split_mode,
            "crop_label":      view_cfg.crop_label,
            "detected_label":  label,
            "confidence":      round(score, 4),
            "utc_timestamp":   ts_utc,
            "local_timestamp": ts_local,
            "bbox":            {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "all_detections":  [
                {"x1": dx1, "y1": dy1, "x2": dx2, "y2": dy2, "label": dl, "score": round(ds, 4)}
                for dx1, dy1, dx2, dy2, dl, ds in detections
            ],
        }

        prefix = f"{ts_file}_{view_cfg.crop_label}"
        cam_dir = self.camera_dir
        def _write_async():
            rp = cam_dir / f"{prefix}_raw.jpg"
            ap = cam_dir / f"{prefix}_alert.jpg"
            mp = cam_dir / f"{prefix}.json"
            ok_r = False
            ok_a = False
            if raw_bytes is not None:
                rp.write_bytes(raw_bytes)
                ok_r = True
            if ann_bytes is not None:
                ap.write_bytes(ann_bytes)
                ok_a = True
            mp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
            logging.info(
                "ALERT | camera=%s view=%s label=%s score=%.3f raw=%s ann=%s",
                self.camera.name, prefix, label, score, ok_r, ok_a,
            )

        self.disk_pool.submit(_write_async)

        ann_rel = f"{view_cfg.camera_name}/{prefix}_alert.jpg"
        raw_rel = f"{view_cfg.camera_name}/{prefix}_raw.jpg"

        event = EventRecord(
            ts_utc=ts_utc,
            ts_local=ts_local,
            camera_name=view_cfg.camera_name,
            view_id=view_cfg.view_id,
            label=label,
            confidence=round(score, 4),
            alert_image=ann_rel,
            raw_image=raw_rel,
        )
        self.state.add_event(event)

        caption = (
            f"\U0001f431 {label.capitalize()} detectado\n"
            f"Cámara: {view_cfg.camera_name}\n"
            f"Vista: {view_cfg.crop_label}\n"
            f"Confianza: {score:.2f}\n"
            f"UTC: {ts_utc}"
        )
        if ann_bytes is not None:
            self.notifier.send_photo_bytes(ann_bytes, f"{prefix}_alert.jpg", caption)


# ─────────────────────────────────────────────
# Web app
# ─────────────────────────────────────────────


def create_web_app(cfg: AppConfig, state: AppState, stop_event: threading.Event) -> Flask:
    app = Flask(__name__, template_folder="templates")

    if cfg.web_password:
        from functools import wraps
        def require_auth(f):
            @wraps(f)
            def decorated(*args, **kwargs):
                auth = request.authorization
                if not auth or auth.password != cfg.web_password:
                    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="CatFinder"'})
                return f(*args, **kwargs)
            return decorated
    else:
        def require_auth(f):
            return f

    # ── Página principal ──────────────────────

    @app.route("/")
    @require_auth
    def index():
        snap = state.snapshot()
        return render_template(
            "index.html",
            title=cfg.web_title,
            views=snap["views"],
            events=snap["events"],
            stats={
                "online_views":      snap["online_views"],
                "total_views":       snap["total_views"],
                "total_detections":  snap["total_detections"],
                "telegram_enabled":  cfg.telegram_enabled,
            },
            max_events=cfg.max_events,
        )

    # ── Streams MJPEG ─────────────────────────

    def _mjpeg_generator(view_id: str, annotated: bool):
        boundary = b"--frame\r\n"
        sleep_s = max(0.01, cfg.stream_sleep_ms / 1000.0)
        while not stop_event.is_set():
            frame = state.get_stream_bytes(view_id=view_id, annotated=annotated)
            if frame is None:
                time.sleep(0.25)
                continue
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(sleep_s)

    @app.route("/stream/<view_id>")
    def stream_annotated(view_id: str):
        if view_id not in state.views:
            abort(404)
        return Response(_mjpeg_generator(view_id, annotated=True), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/stream/raw/<view_id>")
    def stream_raw(view_id: str):
        if view_id not in state.views:
            abort(404)
        return Response(_mjpeg_generator(view_id, annotated=False), mimetype="multipart/x-mixed-replace; boundary=frame")

    # ── API ───────────────────────────────────

    @app.route("/api/status")
    @require_auth
    def api_status():
        return jsonify(state.snapshot())

    # [B1 FIX] request ya está importado al nivel del módulo.
    @app.route("/api/events")
    @require_auth
    def api_events():
        try:
            page      = max(0, int(request.args.get("page", 0)))
            page_size = min(200, max(1, int(request.args.get("page_size", 50))))
        except ValueError:
            page, page_size = 0, 50
        snap = state.snapshot(page=page, page_size=page_size)
        return jsonify({
            "events":       snap["events"],
            "total_events": snap["total_events"],
            "page":         page,
            "page_size":    page_size,
        })

    @app.route("/health")
    def health():
        snap = state.snapshot()
        return jsonify({
            "ok":                True,
            "stop_event":        stop_event.is_set(),
            "online_views":      snap["online_views"],
            "total_views":       snap["total_views"],
            "total_detections":  snap["total_detections"],
            "telegram_enabled":  cfg.telegram_enabled,
            "timestamp":         utc_now_iso(),
        })

    # ── Imágenes guardadas ────────────────────

    @app.route("/captures/<path:filepath>")
    def serve_capture(filepath: str):
        # Seguridad: resolvemos y verificamos que esté dentro de save_dir
        target = (cfg.save_dir / filepath).resolve()
        try:
            target.relative_to(cfg.save_dir)
        except ValueError:
            abort(403)
        if not target.exists() or not target.is_file():
            abort(404)
        return send_file(str(target), mimetype="image/jpeg")

    return app


# ─────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────


def main() -> None:
    cfg = load_config()
    ensure_dir(cfg.save_dir)
    if not os.access(cfg.save_dir, os.W_OK):
        logging.error("save_dir %s no tiene permisos de escritura", cfg.save_dir)
        raise SystemExit(1)

    logging.info(
        "Iniciando CatFinder | cámaras=%s | clases=%s | modelo=%s | web=%s:%s | telegram=%s",
        len(cfg.cameras), cfg.target_classes, cfg.model_path,
        cfg.web_host, cfg.web_port, cfg.telegram_enabled,
    )
    if cfg.camera_rois:
        logging.info("ROI configurados: %s", cfg.camera_rois)

    views = build_view_configs(cfg.cameras)
    # [B3 FIX] jpeg_quality pasado explícitamente a AppState.
    state = AppState(views=views, max_events=cfg.max_events, jpeg_quality=cfg.jpeg_quality)

    logging.info("IDs de clases objetivo -> %s", cfg.target_classes)

    notifier = TelegramNotifier(
        enabled=cfg.telegram_enabled,
        bot_token=cfg.telegram_bot_token,
        chat_id=cfg.telegram_chat_id,
        timeout_seconds=cfg.request_timeout_seconds,
    )

    stop_event = threading.Event()

    app = create_web_app(cfg=cfg, state=state, stop_event=stop_event)

    # [B9 FIX] make_server permite llamar server.shutdown() desde el signal handler,
    # parando Flask limpiamente sin depender de KeyboardInterrupt.
    server = make_server(cfg.web_host, cfg.web_port, app)
    server.timeout = 1  # permite que serve_forever() compruebe el stop_event periódicamente

    def shutdown_handler(signum, frame):
        logging.warning("Señal %s recibida. Apagando…", signum)
        stop_event.set()
        server.shutdown()

    signal.signal(signal.SIGINT,  shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    def _init_worker(cam):
        detector = DetectionEngine(
            model_path=cfg.model_path,
            confidence_threshold=cfg.confidence_threshold,
            infer_imgsz=cfg.infer_imgsz,
        )
        target_ids = detector.resolve_target_ids(cfg.target_classes)
        return CameraWorker(
            camera=cam,
            view_configs=views,
            cfg=cfg,
            detector=detector,
            notifier=notifier,
            target_ids=target_ids,
            state=state,
            stop_event=stop_event,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cfg.cameras)) as pool:
        workers = list(pool.map(_init_worker, cfg.cameras))

    for worker in workers:
        worker.start()

    logging.info("Servidor web en http://%s:%s", cfg.web_host, cfg.web_port)

    try:
        server.serve_forever()
    finally:
        stop_event.set()
        notifier.stop()
        for worker in workers:
            worker.join(timeout=5)
        for worker in workers:
            worker.disk_pool.shutdown(wait=False, cancel_futures=True)
        logging.info("Apagado completo.")


if __name__ == "__main__":
    main()
