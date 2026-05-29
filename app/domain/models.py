from __future__ import annotations

import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from app.core.utils import local_now_str, redact_url, utc_now_iso


@dataclass(slots=True)
class CameraConfig:
    name: str
    rtsp_url: str
    enabled: bool = True
    detect_fps: Optional[float] = None
    cooldown_seconds: Optional[int] = None
    max_frame_width: Optional[int] = None

    def public_dict(self) -> dict:
        data = asdict(self)
        data["rtsp_url"] = redact_url(self.rtsp_url)
        return data

    def private_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class EventRecord:
    ts_utc: str
    ts_local: str
    camera_name: str
    label: str
    confidence: float
    image_path: str
    detections: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CameraRuntimeState:
    name: str
    status: str = "starting"
    last_frame_at: str = "-"
    last_error: str = ""
    last_detection_label: str = "-"
    last_detection_confidence: float = 0.0
    last_detection_at: str = "-"
    detection_count: int = 0
    frame_count: int = 0
    reconnect_count: int = 0
    _jpeg: Optional[bytes] = field(default=None, repr=False)
    _jpeg_id: int = field(default=0, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _frame_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def put_frame(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._jpeg_id += 1
            self.frame_count += 1
            self.last_frame_at = local_now_str()
            self.status = "online"
        self._frame_event.set()
        self._frame_event.clear()

    def get_frame(self) -> tuple[Optional[bytes], int]:
        with self._lock:
            return self._jpeg, self._jpeg_id

    def wait_for_new_frame(self, previous_id: int, timeout: float = 1.0) -> bool:
        with self._lock:
            if self._jpeg_id > previous_id:
                return True
        return self._frame_event.wait(timeout)

    def mark_error(self, status: str, message: str) -> None:
        with self._lock:
            self.status = status
            self.last_error = message[:300]

    def mark_reconnect(self, message: str = "") -> None:
        with self._lock:
            self.status = "reconnecting"
            self.reconnect_count += 1
            self.last_error = message[:300]

    def mark_detection(self, detection: Detection) -> None:
        with self._lock:
            self.last_detection_label = detection.label
            self.last_detection_confidence = float(detection.confidence)
            self.last_detection_at = local_now_str()
            self.detection_count += 1

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "status": self.status,
                "last_frame_at": self.last_frame_at,
                "last_error": self.last_error,
                "last_detection_label": self.last_detection_label,
                "last_detection_confidence": round(self.last_detection_confidence, 4),
                "last_detection_at": self.last_detection_at,
                "detection_count": self.detection_count,
                "frame_count": self.frame_count,
                "reconnect_count": self.reconnect_count,
            }


class AppState:
    def __init__(self, max_events: int = 200):
        self._lock = threading.RLock()
        self.camera_states: dict[str, CameraRuntimeState] = {}
        self.events: deque[EventRecord] = deque(maxlen=max_events)
        self.started_at = utc_now_iso()

    def add_camera_state(self, name: str) -> CameraRuntimeState:
        with self._lock:
            state = CameraRuntimeState(name=name)
            self.camera_states[name] = state
            return state

    def remove_camera_state(self, name: str) -> None:
        with self._lock:
            self.camera_states.pop(name, None)

    def get_camera_state(self, name: str) -> CameraRuntimeState | None:
        with self._lock:
            return self.camera_states.get(name)

    def add_event(self, event: EventRecord) -> None:
        with self._lock:
            self.events.appendleft(event)

    def snapshot(self) -> dict:
        with self._lock:
            cameras = [state.to_dict() for state in self.camera_states.values()]
            events = [event.to_dict() for event in self.events]
        return {
            "started_at": self.started_at,
            "total_cameras": len(cameras),
            "online_cameras": sum(1 for cam in cameras if cam["status"] == "online"),
            "total_events_memory": len(events),
            "cameras": cameras,
            "events": events,
        }
