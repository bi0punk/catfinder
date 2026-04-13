import json
import logging
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template
from ultralytics import YOLO


# -----------------------------
# Configuration
# -----------------------------


@dataclass
class CameraConfig:
    name: str
    rtsp_url: str
    split_mode: str = "none"  # none | vertical | horizontal
    split_ratio: float = 0.5


@dataclass
class ViewConfig:
    view_id: str
    camera_name: str
    view_name: str
    split_mode: str
    crop_label: str  # full | left | right | top | bottom


@dataclass
class AppConfig:
    cameras: List[CameraConfig]
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


@dataclass
class EventRecord:
    ts_utc: str
    ts_local: str
    camera_name: str
    view_id: str
    label: str
    confidence: float
    alert_image: str
    raw_image: str


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
    latest_raw_jpeg: Optional[bytes] = None
    latest_annotated_jpeg: Optional[bytes] = None
    width: int = 0
    height: int = 0
    frame_counter: int = 0


# -----------------------------
# Helpers
# -----------------------------


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(asctime)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def utc_now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


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
        raise ValueError("RTSP_URLS is empty. Define at least one camera URL in .env")

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
        raise ValueError("No valid cameras were parsed from RTSP_URLS")
    return items


def parse_key_value_map(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    raw = (raw or "").strip()
    if not raw:
        return result
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_camera_configs() -> List[CameraConfig]:
    base = parse_name_url_map(os.getenv("RTSP_URLS", ""))
    split_modes = parse_key_value_map(os.getenv("CAMERA_SPLITS", ""))
    split_ratios_raw = parse_key_value_map(os.getenv("CAMERA_SPLIT_RATIOS", ""))

    cameras: List[CameraConfig] = []
    for name, rtsp_url in base:
        split_mode = split_modes.get(name, "none").strip().lower() or "none"
        if split_mode not in {"none", "vertical", "horizontal"}:
            logging.warning("Invalid split mode for %s -> %s. Using none.", name, split_mode)
            split_mode = "none"
        split_ratio = clamp_ratio(safe_float(split_ratios_raw.get(name, "0.5"), 0.5))
        cameras.append(
            CameraConfig(
                name=name,
                rtsp_url=rtsp_url,
                split_mode=split_mode,
                split_ratio=split_ratio,
            )
        )
    return cameras


def load_config() -> AppConfig:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in .env")
    if not telegram_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID is missing in .env")

    target_classes = [x.strip().lower() for x in os.getenv("TARGET_CLASSES", "cat").split(",") if x.strip()]
    cameras = parse_camera_configs()

    return AppConfig(
        cameras=cameras,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        model_path=os.getenv("MODEL_PATH", "yolo11n.pt").strip(),
        target_classes=target_classes,
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.55")),
        cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "60")),
        process_every_n_frames=int(os.getenv("PROCESS_EVERY_N_FRAMES", "5")),
        preview_every_n_frames=max(1, int(os.getenv("PREVIEW_EVERY_N_FRAMES", "2"))),
        save_dir=Path(os.getenv("SAVE_DIR", "captures")).resolve(),
        reconnect_delay_seconds=int(os.getenv("RECONNECT_DELAY_SECONDS", "5")),
        jpeg_quality=int(os.getenv("JPEG_QUALITY", "85")),
        infer_imgsz=int(os.getenv("INFER_IMGSZ", "960")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        draw_boxes=os.getenv("DRAW_BOXES", "true").strip().lower() in {"1", "true", "yes", "y"},
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=int(os.getenv("WEB_PORT", "8081")),
        web_title=os.getenv("WEB_TITLE", "CatFinder RTSP Monitor").strip(),
        max_events=int(os.getenv("MAX_EVENTS", "50")),
        stream_sleep_ms=int(os.getenv("STREAM_SLEEP_MS", "60")),
    )


def build_view_configs(cameras: List[CameraConfig]) -> List[ViewConfig]:
    views: List[ViewConfig] = []
    for camera in cameras:
        if camera.split_mode == "vertical":
            views.append(ViewConfig(f"{camera.name}__left", camera.name, f"{camera.name} / izquierda", "vertical", "left"))
            views.append(ViewConfig(f"{camera.name}__right", camera.name, f"{camera.name} / derecha", "vertical", "right"))
        elif camera.split_mode == "horizontal":
            views.append(ViewConfig(f"{camera.name}__top", camera.name, f"{camera.name} / superior", "horizontal", "top"))
            views.append(ViewConfig(f"{camera.name}__bottom", camera.name, f"{camera.name} / inferior", "horizontal", "bottom"))
        else:
            views.append(ViewConfig(f"{camera.name}__full", camera.name, camera.name, "none", "full"))
    return views


def encode_jpg(frame, quality: int) -> Optional[bytes]:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return None
    return buffer.tobytes()


def save_jpg(frame, output_path: Path, quality: int) -> bool:
    encoded = encode_jpg(frame, quality)
    if encoded is None:
        return False
    output_path.write_bytes(encoded)
    return True


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
    cv2.rectangle(out, (0, 0), (w, 50), (0, 0, 0), -1)
    cv2.addWeighted(out, 0.65, frame, 0.35, 0, out)
    cv2.putText(out, line1, (12, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
    if line2:
        cv2.putText(out, line2, (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return out


# -----------------------------
# Telegram
# -----------------------------


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: int = 20):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def send_photo(self, image_path: Path, caption: str) -> bool:
        url = f"{self.base_url}/sendPhoto"
        try:
            with image_path.open("rb") as f:
                files = {"photo": f}
                data = {"chat_id": self.chat_id, "caption": caption}
                response = requests.post(url, data=data, files=files, timeout=self.timeout_seconds)
            if response.ok:
                logging.info("Telegram OK -> %s", image_path.name)
                return True
            logging.error("Telegram FAIL status=%s body=%s", response.status_code, response.text)
            return False
        except Exception as exc:
            logging.exception("Telegram exception sending %s: %s", image_path, exc)
            return False


# -----------------------------
# Detection engine
# -----------------------------


class DetectionEngine:
    def __init__(self, model_path: str, confidence_threshold: float, infer_imgsz: int):
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.infer_imgsz = infer_imgsz
        self.lock = threading.Lock()
        self.names = self._normalize_names(self.model.names)
        logging.info("Loaded model=%s names_count=%s", model_path, len(self.names))

    @staticmethod
    def _normalize_names(names) -> Dict[int, str]:
        if isinstance(names, dict):
            return {int(k): str(v).lower() for k, v in names.items()}
        if isinstance(names, list):
            return {idx: str(v).lower() for idx, v in enumerate(names)}
        return {}

    def resolve_target_ids(self, target_classes: List[str]) -> List[int]:
        target_ids = [idx for idx, name in self.names.items() if name in target_classes]
        if not target_ids:
            raise ValueError(
                f"No target classes {target_classes} found in model labels. Available sample={list(self.names.values())[:20]}"
            )
        return target_ids

    def infer(self, frame):
        with self.lock:
            results = self.model.predict(
                source=frame,
                conf=self.confidence_threshold,
                imgsz=self.infer_imgsz,
                verbose=False,
                stream=False,
            )
        if not results:
            return None
        return results[0]


# -----------------------------
# Shared state
# -----------------------------


class AppState:
    def __init__(self, views: List[ViewConfig], max_events: int):
        self.lock = threading.RLock()
        self.views: Dict[str, ViewState] = {
            view.view_id: ViewState(
                view_id=view.view_id,
                camera_name=view.camera_name,
                view_name=view.view_name,
                split_mode=view.split_mode,
                crop_label=view.crop_label,
            )
            for view in views
        }
        self.events: Deque[EventRecord] = deque(maxlen=max_events)

    def update_view_frame(self, view_id: str, raw_frame, annotated_frame, status: str) -> None:
        with self.lock:
            view = self.views[view_id]
            raw_jpg = encode_jpg(raw_frame, quality=85)
            ann_jpg = encode_jpg(annotated_frame, quality=85)
            if raw_jpg is not None:
                view.latest_raw_jpeg = raw_jpg
            if ann_jpg is not None:
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

    def update_detection(self, view_id: str, label: str, confidence: float) -> None:
        with self.lock:
            view = self.views[view_id]
            view.last_detection_label = label
            view.last_detection_conf = float(confidence)
            view.last_detection_at = local_now_str()

    def add_event(self, event: EventRecord) -> None:
        with self.lock:
            self.events.appendleft(event)

    def get_stream_bytes(self, view_id: str, annotated: bool = True) -> Optional[bytes]:
        with self.lock:
            view = self.views.get(view_id)
            if view is None:
                return None
            return view.latest_annotated_jpeg if annotated else view.latest_raw_jpeg

    def snapshot(self) -> Dict[str, object]:
        with self.lock:
            views = [
                {
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
                    "width": view.width,
                    "height": view.height,
                    "frame_counter": view.frame_counter,
                }
                for view in self.views.values()
            ]
            events = [event.__dict__ for event in list(self.events)]
        return {"views": views, "events": events}


# -----------------------------
# Camera worker
# -----------------------------


class CameraWorker(threading.Thread):
    def __init__(
        self,
        camera: CameraConfig,
        cfg: AppConfig,
        detector: DetectionEngine,
        notifier: TelegramNotifier,
        target_ids: List[int],
        state: AppState,
        stop_event: threading.Event,
    ):
        super().__init__(name=f"camera:{camera.name}", daemon=True)
        self.camera = camera
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

    def run(self) -> None:
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
                logging.warning("%s disconnected. Reconnecting in %ss", self.camera.name, self.cfg.reconnect_delay_seconds)
                time.sleep(self.cfg.reconnect_delay_seconds)

    def _open_stream(self):
        logging.info("Opening RTSP stream -> %s", self.camera.rtsp_url)
        cap = cv2.VideoCapture(self.camera.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logging.error("Cannot open RTSP stream for %s", self.camera.name)
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        self.state.update_view_status(self.camera.name, "online")
        return cap

    def _split_views(self, frame) -> List[Tuple[ViewConfig, object]]:
        height, width = frame.shape[:2]
        ratio = self.camera.split_ratio

        if self.camera.split_mode == "vertical":
            cut = max(1, min(width - 1, int(width * ratio)))
            left = frame[:, :cut].copy()
            right = frame[:, cut:].copy()
            return [
                (ViewConfig(f"{self.camera.name}__left", self.camera.name, f"{self.camera.name} / izquierda", "vertical", "left"), left),
                (ViewConfig(f"{self.camera.name}__right", self.camera.name, f"{self.camera.name} / derecha", "vertical", "right"), right),
            ]

        if self.camera.split_mode == "horizontal":
            cut = max(1, min(height - 1, int(height * ratio)))
            top = frame[:cut, :].copy()
            bottom = frame[cut:, :].copy()
            return [
                (ViewConfig(f"{self.camera.name}__top", self.camera.name, f"{self.camera.name} / superior", "horizontal", "top"), top),
                (ViewConfig(f"{self.camera.name}__bottom", self.camera.name, f"{self.camera.name} / inferior", "horizontal", "bottom"), bottom),
            ]

        return [(ViewConfig(f"{self.camera.name}__full", self.camera.name, self.camera.name, "none", "full"), frame.copy())]

    def _stream_loop(self, cap) -> None:
        while not self.stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                logging.error("Frame read failed from %s", self.camera.name)
                break

            self.frame_count += 1
            split_views = self._split_views(frame)
            should_run_detection = self.frame_count % self.cfg.process_every_n_frames == 0
            should_refresh_preview = self.frame_count % self.cfg.preview_every_n_frames == 0

            for view_cfg, view_frame in split_views:
                detections: List[Tuple[int, int, int, int, str, float]] = []

                if should_run_detection:
                    detections = self._detect_targets(view_frame)

                annotated = draw_detections(view_frame, detections) if detections and self.cfg.draw_boxes else view_frame.copy()
                line1 = f"{view_cfg.view_name} | {self.camera.split_mode} | {local_now_str()}"
                if detections:
                    strongest = max(detections, key=lambda x: x[5])
                    line2 = f"detectado={strongest[4]} conf={strongest[5]:.2f}"
                else:
                    line2 = f"estado={self.state.views[view_cfg.view_id].status}"
                annotated = add_overlay(annotated, line1, line2)

                if should_refresh_preview or detections:
                    self.state.update_view_frame(view_cfg.view_id, view_frame, annotated, status="online")

                if detections:
                    strongest = max(detections, key=lambda x: x[5])
                    self._maybe_alert(view_cfg, view_frame, annotated, detections, strongest)

    def _detect_targets(self, frame) -> List[Tuple[int, int, int, int, str, float]]:
        result = self.detector.infer(frame)
        if result is None or result.boxes is None:
            return []

        detections: List[Tuple[int, int, int, int, str, float]] = []
        for box in result.boxes:
            cls_id = int(box.cls[0].item())
            score = float(box.conf[0].item())
            if cls_id not in self.target_ids:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            label = self.detector.names.get(cls_id, str(cls_id))
            detections.append((x1, y1, x2, y2, label, score))
        return detections

    def _maybe_alert(self, view_cfg: ViewConfig, raw_frame, annotated_frame, detections, strongest) -> None:
        x1, y1, x2, y2, label, score = strongest
        now = time.time()
        last_view_alert = self.last_alert_at.get(view_cfg.view_id, 0.0)
        remaining = self.cfg.cooldown_seconds - int(now - last_view_alert)
        if now - last_view_alert < self.cfg.cooldown_seconds:
            logging.info(
                "Detection ignored by cooldown | camera=%s view=%s label=%s score=%.3f remaining=%ss",
                self.camera.name,
                view_cfg.view_id,
                label,
                score,
                max(0, remaining),
            )
            return

        self.last_alert_at[view_cfg.view_id] = now
        self.state.update_detection(view_cfg.view_id, label, score)
        self._handle_detection(view_cfg, raw_frame, annotated_frame, detections, strongest)

    def _handle_detection(self, view_cfg: ViewConfig, raw_frame, annotated_frame, detections, strongest) -> None:
        x1, y1, x2, y2, label, score = strongest
        ts_file = local_now_for_filename()
        ts_utc = utc_now_iso()
        ts_local = local_now_str()

        prefix = f"{ts_file}_{view_cfg.crop_label}"
        raw_path = self.camera_dir / f"{prefix}_raw.jpg"
        ann_path = self.camera_dir / f"{prefix}_alert.jpg"
        meta_path = self.camera_dir / f"{prefix}.json"

        raw_saved = save_jpg(raw_frame, raw_path, self.cfg.jpeg_quality)
        ann_saved = save_jpg(annotated_frame, ann_path, self.cfg.jpeg_quality)

        metadata = {
            "camera": self.camera.name,
            "view_id": view_cfg.view_id,
            "view_name": view_cfg.view_name,
            "split_mode": self.camera.split_mode,
            "crop_label": view_cfg.crop_label,
            "rtsp_url": self.camera.rtsp_url,
            "detected_label": label,
            "confidence": round(score, 4),
            "utc_timestamp": ts_utc,
            "local_timestamp": ts_local,
            "raw_path": str(raw_path),
            "alert_path": str(ann_path),
            "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "all_detections": [
                {"x1": dx1, "y1": dy1, "x2": dx2, "y2": dy2, "label": dlabel, "score": round(dscore, 4)}
                for dx1, dy1, dx2, dy2, dlabel, dscore in detections
            ],
        }
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

        logging.info(
            "ALERT | camera=%s view=%s label=%s score=%.3f raw_saved=%s ann_saved=%s",
            self.camera.name,
            view_cfg.view_id,
            label,
            score,
            raw_saved,
            ann_saved,
        )

        event = EventRecord(
            ts_utc=ts_utc,
            ts_local=ts_local,
            camera_name=self.camera.name,
            view_id=view_cfg.view_id,
            label=label,
            confidence=round(score, 4),
            alert_image=str(ann_path),
            raw_image=str(raw_path),
        )
        self.state.add_event(event)

        caption = (
            f"🐱 Gato detectado\n"
            f"Cámara: {self.camera.name}\n"
            f"Vista: {view_cfg.crop_label}\n"
            f"Confianza: {score:.2f}\n"
            f"UTC: {ts_utc}"
        )
        if ann_saved:
            self.notifier.send_photo(ann_path, caption)


# -----------------------------
# Web app
# -----------------------------


def create_web_app(cfg: AppConfig, state: AppState, stop_event: threading.Event) -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.route("/")
    def index():
        snapshot = state.snapshot()
        return render_template("index.html", title=cfg.web_title, views=snapshot["views"], events=snapshot["events"])

    @app.route("/api/status")
    def api_status():
        return jsonify(state.snapshot())

    @app.route("/health")
    def health():
        snapshot = state.snapshot()
        online_views = sum(1 for v in snapshot["views"] if v["status"] == "online")
        return jsonify(
            {
                "ok": True,
                "stop_event": stop_event.is_set(),
                "online_views": online_views,
                "total_views": len(snapshot["views"]),
                "timestamp": utc_now_iso(),
            }
        )

    @app.route("/stream/<view_id>")
    def stream_view(view_id: str):
        def generate():
            boundary = b"--frame\r\n"
            while not stop_event.is_set():
                frame = state.get_stream_bytes(view_id=view_id, annotated=True)
                if frame is None:
                    time.sleep(0.25)
                    continue
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(max(0.01, cfg.stream_sleep_ms / 1000.0))

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


# -----------------------------
# Main
# -----------------------------


def main() -> None:
    setup_logging()
    cfg = load_config()
    ensure_dir(cfg.save_dir)

    logging.info("Starting CatFinder web RTSP monitor")
    logging.info("Cameras=%s | target_classes=%s | model=%s | web=%s:%s", len(cfg.cameras), cfg.target_classes, cfg.model_path, cfg.web_host, cfg.web_port)

    views = build_view_configs(cfg.cameras)
    state = AppState(views=views, max_events=cfg.max_events)

    detector = DetectionEngine(
        model_path=cfg.model_path,
        confidence_threshold=cfg.confidence_threshold,
        infer_imgsz=cfg.infer_imgsz,
    )
    target_ids = detector.resolve_target_ids(cfg.target_classes)
    logging.info("Resolved target class IDs -> %s", target_ids)

    notifier = TelegramNotifier(
        bot_token=cfg.telegram_bot_token,
        chat_id=cfg.telegram_chat_id,
        timeout_seconds=cfg.request_timeout_seconds,
    )

    stop_event = threading.Event()

    def shutdown_handler(signum, frame):
        logging.warning("Signal %s received. Shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    workers = [
        CameraWorker(
            camera=camera,
            cfg=cfg,
            detector=detector,
            notifier=notifier,
            target_ids=target_ids,
            state=state,
            stop_event=stop_event,
        )
        for camera in cfg.cameras
    ]

    for worker in workers:
        worker.start()

    app = create_web_app(cfg=cfg, state=state, stop_event=stop_event)

    try:
        app.run(host=cfg.web_host, port=cfg.web_port, debug=False, threaded=True, use_reloader=False)
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=5)
        logging.info("Shutdown complete")


if __name__ == "__main__":
    main()
