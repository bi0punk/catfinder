from __future__ import annotations

import cv2
import numpy as np

from app.core.utils import local_now_str
from app.domain.models import Detection


_VALID_SPLITS = {"none", "left", "right", "top", "bottom"}


def apply_split(frame: np.ndarray, split_mode: str) -> np.ndarray:
    """Crop a dual-lens frame to one half.

    Dual-lens RTSP cameras pack two views side-by-side (left/right) or
    stacked (top/bottom) into a single stream.  This crops to the
    requested half so detection and streaming only see one lens.
    """
    mode = (split_mode or "none").lower()
    if mode not in _VALID_SPLITS or mode == "none":
        return frame
    h, w = frame.shape[:2]
    if mode == "left":
        return frame[:, : w // 2]
    if mode == "right":
        return frame[:, w // 2 :]
    if mode == "top":
        return frame[: h // 2, :]
    # bottom
    return frame[h // 2 :, :]



_LABEL_ES = {
    "cat": "GATO",
    "dog": "PERRO",
    "person": "PERSONA",
}


def _clip_point(x: int, y: int, frame: np.ndarray) -> tuple[int, int]:
    h, w = frame.shape[:2]
    return max(0, min(w - 1, int(x))), max(0, min(h - 1, int(y)))


def draw_detections(frame: np.ndarray, detections: list[Detection], draw_boxes: bool = True) -> np.ndarray:
    """Draw classic computer-vision bounding boxes over detections.

    The project stores and streams this annotated frame, so the user can visually
    confirm whether the model is actually firing. The drawing is intentionally
    high-contrast for dark/night RTSP feeds.
    """
    output = frame.copy()
    if not draw_boxes or not detections:
        return output

    h, w = output.shape[:2]
    thickness = max(2, int(round(min(w, h) / 360)))
    font_scale = max(0.55, min(1.0, w / 1280.0))

    for det in detections:
        x1, y1 = _clip_point(det.x1, det.y1, output)
        x2, y2 = _clip_point(det.x2, det.y2, output)
        if x2 <= x1 or y2 <= y1:
            continue

        color = (0, 255, 80)  # BGR: bright green
        cv2.rectangle(output, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)

        # Small corner accents make the box visible even over noisy night feeds.
        corner = max(14, min(42, int(0.18 * min(x2 - x1, y2 - y1))))
        cv2.line(output, (x1, y1), (x1 + corner, y1), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x1, y1), (x1, y1 + corner), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x2, y1), (x2 - corner, y1), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x2, y1), (x2, y1 + corner), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x1, y2), (x1 + corner, y2), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x1, y2), (x1, y2 - corner), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x2, y2), (x2 - corner, y2), color, thickness + 1, cv2.LINE_AA)
        cv2.line(output, (x2, y2), (x2, y2 - corner), color, thickness + 1, cv2.LINE_AA)

        label_name = _LABEL_ES.get(det.label.lower(), det.label.upper())
        label = f"{label_name} {det.confidence:.2f}"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        text_x = x1
        text_y = max(th + 10, y1 - 8)
        bg_y1 = max(0, text_y - th - baseline - 8)
        bg_x2 = min(w - 1, text_x + tw + 14)
        cv2.rectangle(output, (text_x, bg_y1), (bg_x2, text_y + baseline), color, -1)
        cv2.putText(
            output,
            label,
            (text_x + 7, text_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )
    return output


def draw_overlay(frame: np.ndarray, camera_name: str, status_text: str = "") -> np.ndarray:
    output = frame.copy()
    h, w = output.shape[:2]
    text = f"{camera_name} | {local_now_str()}"
    if status_text:
        text += f" | {status_text}"
    overlay = output.copy()
    cv2.rectangle(overlay, (0, 0), (w, 42), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.72, output, 0.28, 0, output)
    cv2.putText(output, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2, cv2.LINE_AA)
    return output


def draw_no_detection(frame: np.ndarray, text: str = "sin deteccion") -> np.ndarray:
    output = frame.copy()
    cv2.putText(output, text, (12, output.shape[0] - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (180, 180, 180), 2, cv2.LINE_AA)
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
