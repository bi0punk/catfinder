import os
import cv2
import time
import json
import queue
import signal
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
from dotenv import load_dotenv
from ultralytics import YOLO


# -----------------------------
# Configuration
# -----------------------------

@dataclass
class CameraConfig:
    name: str
    rtsp_url: str


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
    save_dir: Path
    reconnect_delay_seconds: int
    jpeg_quality: int
    infer_imgsz: int
    request_timeout_seconds: int
    draw_boxes: bool


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(asctime)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_cameras(raw: str) -> List[CameraConfig]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("RTSP_URLS is empty. Define at least one camera URL in .env")

    cameras: List[CameraConfig] = []
    for idx, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            name, url = item.split("=", 1)
            cameras.append(CameraConfig(name=name.strip(), rtsp_url=url.strip()))
        else:
            cameras.append(CameraConfig(name=f"cam_{idx}", rtsp_url=item))

    if not cameras:
        raise ValueError("No valid RTSP cameras were parsed from RTSP_URLS")
    return cameras


def load_config() -> AppConfig:
    load_dotenv()

    cameras = parse_cameras(os.getenv("RTSP_URLS", "rtsp://peww:tn3tdw@192.168.1.11:554/live/ch00_1"))
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in .env")
    if not telegram_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID is missing in .env")

    target_classes = [x.strip().lower() for x in os.getenv("TARGET_CLASSES", "cat").split(",") if x.strip()]

    return AppConfig(
        cameras=cameras,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        model_path=os.getenv("MODEL_PATH", "yolo11n.pt").strip(),
        target_classes=target_classes,
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.55")),
        cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS", "60")),
        process_every_n_frames=int(os.getenv("PROCESS_EVERY_N_FRAMES", "5")),
        save_dir=Path(os.getenv("SAVE_DIR", "captures")).resolve(),
        reconnect_delay_seconds=int(os.getenv("RECONNECT_DELAY_SECONDS", "5")),
        jpeg_quality=int(os.getenv("JPEG_QUALITY", "92")),
        infer_imgsz=int(os.getenv("INFER_IMGSZ", "960")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        draw_boxes=os.getenv("DRAW_BOXES", "true").strip().lower() in {"1", "true", "yes", "y"},
    )


# -----------------------------
# Telegram client
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

    def infer(self, frame) -> Optional[object]:
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
# Utilities
# -----------------------------


def utc_now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def local_now_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def encode_and_save_jpg(frame, output_path: Path, quality: int) -> bool:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return False
    output_path.write_bytes(buffer.tobytes())
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
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return annotated


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
        stop_event: threading.Event,
    ):
        super().__init__(name=f"camera:{camera.name}", daemon=True)
        self.camera = camera
        self.cfg = cfg
        self.detector = detector
        self.notifier = notifier
        self.target_ids = set(target_ids)
        self.stop_event = stop_event
        self.frame_count = 0
        self.last_alert_at = 0.0

        self.camera_dir = self.cfg.save_dir / self.camera.name
        ensure_dir(self.camera_dir)

    def run(self) -> None:
        while not self.stop_event.is_set():
            cap = self._open_stream()
            if cap is None:
                time.sleep(self.cfg.reconnect_delay_seconds)
                continue

            try:
                self._stream_loop(cap)
            finally:
                cap.release()

            if not self.stop_event.is_set():
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
        return cap

    def _stream_loop(self, cap) -> None:
        while not self.stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                logging.error("Frame read failed from %s", self.camera.name)
                break

            self.frame_count += 1
            if self.frame_count % self.cfg.process_every_n_frames != 0:
                continue

            result = self.detector.infer(frame)
            if result is None or result.boxes is None:
                continue

            detections = []
            for box in result.boxes:
                cls_id = int(box.cls[0].item())
                score = float(box.conf[0].item())
                if cls_id not in self.target_ids:
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                label = self.detector.names.get(cls_id, str(cls_id))
                detections.append((x1, y1, x2, y2, label, score))

            if not detections:
                continue

            strongest = max(detections, key=lambda x: x[5])
            now = time.time()
            remaining = self.cfg.cooldown_seconds - int(now - self.last_alert_at)
            if now - self.last_alert_at < self.cfg.cooldown_seconds:
                logging.info(
                    "Detection ignored by cooldown | camera=%s label=%s score=%.3f remaining=%ss",
                    self.camera.name,
                    strongest[4],
                    strongest[5],
                    max(0, remaining),
                )
                continue

            self.last_alert_at = now
            self._handle_detection(frame, detections, strongest)

    def _handle_detection(self, frame, detections, strongest) -> None:
        x1, y1, x2, y2, label, score = strongest
        ts_file = local_now_for_filename()
        ts_utc = utc_now_iso()

        raw_path = self.camera_dir / f"{ts_file}_raw.jpg"
        ann_path = self.camera_dir / f"{ts_file}_alert.jpg"
        meta_path = self.camera_dir / f"{ts_file}.json"

        annotated = draw_detections(frame, detections) if self.cfg.draw_boxes else frame.copy()
        overlay_text = f"camera={self.camera.name} | label={label} | conf={score:.2f} | utc={ts_utc}"
        cv2.putText(
            annotated,
            overlay_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        raw_saved = encode_and_save_jpg(frame, raw_path, self.cfg.jpeg_quality)
        ann_saved = encode_and_save_jpg(annotated, ann_path, self.cfg.jpeg_quality)

        metadata = {
            "camera": self.camera.name,
            "rtsp_url": self.camera.rtsp_url,
            "detected_label": label,
            "confidence": round(score, 4),
            "utc_timestamp": ts_utc,
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
            "ALERT | camera=%s label=%s score=%.3f raw_saved=%s ann_saved=%s",
            self.camera.name,
            label,
            score,
            raw_saved,
            ann_saved,
        )

        caption = (
            f"🐱 Gato detectado\n"
            f"Cámara: {self.camera.name}\n"
            f"Confianza: {score:.2f}\n"
            f"UTC: {ts_utc}"
        )

        if ann_saved:
            self.notifier.send_photo(ann_path, caption)


# -----------------------------
# Main
# -----------------------------


def main() -> None:
    setup_logging()
    cfg = load_config()
    ensure_dir(cfg.save_dir)

    logging.info("Starting cat RTSP monitor")
    logging.info("Cameras=%s | target_classes=%s | model=%s", len(cfg.cameras), cfg.target_classes, cfg.model_path)

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
            stop_event=stop_event,
        )
        for camera in cfg.cameras
    ]

    for worker in workers:
        worker.start()

    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=5)
        logging.info("Shutdown complete")


if __name__ == "__main__":
    main()
