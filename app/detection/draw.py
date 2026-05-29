from __future__ import annotations

import cv2
import numpy as np

from app.core.utils import local_now_str
from app.domain.models import Detection


def draw_detections(frame: np.ndarray, detections: list[Detection], draw_boxes: bool = True) -> np.ndarray:
    output = frame.copy()
    if not draw_boxes:
        return output
    for det in detections:
        cv2.rectangle(output, (det.x1, det.y1), (det.x2, det.y2), (0, 220, 0), 2)
        label = f"{det.label} {det.confidence:.2f}"
        y = max(24, det.y1 - 8)
        cv2.rectangle(output, (det.x1, y - 22), (min(output.shape[1] - 1, det.x1 + 150), y + 4), (0, 220, 0), -1)
        cv2.putText(output, label, (det.x1 + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
    return output


def draw_overlay(frame: np.ndarray, camera_name: str, status_text: str = "") -> np.ndarray:
    output = frame.copy()
    text = f"{camera_name} | {local_now_str()}"
    if status_text:
        text += f" | {status_text}"
    cv2.rectangle(output, (0, 0), (min(output.shape[1], 760), 34), (0, 0, 0), -1)
    cv2.putText(output, text, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    return output


def resize_max_width(frame: np.ndarray, max_width: int) -> np.ndarray:
    if max_width <= 0 or frame.shape[1] <= max_width:
        return frame
    scale = max_width / float(frame.shape[1])
    new_height = int(frame.shape[0] * scale)
    return cv2.resize(frame, (max_width, new_height), interpolation=cv2.INTER_AREA)


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes | None:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return None
    return buffer.tobytes()
