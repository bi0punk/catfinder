"""Tests de dibujo/preprocesado de frames (app/detection/draw.py)."""

from __future__ import annotations

import numpy as np

from app.detection.draw import apply_split, draw_detections, draw_overlay, encode_jpeg, resize_max_width
from app.domain.models import Detection


def test_apply_split_modes():
    frame = np.zeros((10, 20, 3), dtype=np.uint8)
    assert apply_split(frame, "left").shape == (10, 10, 3)
    assert apply_split(frame, "right").shape == (10, 10, 3)
    assert apply_split(frame, "top").shape == (5, 20, 3)
    assert apply_split(frame, "bottom").shape == (5, 20, 3)
    assert apply_split(frame, "none").shape == (10, 20, 3)
    assert apply_split(frame, "bogus").shape == (10, 20, 3)


def test_resize_max_width():
    frame = np.zeros((10, 100, 3), dtype=np.uint8)
    assert resize_max_width(frame, 50).shape[1] == 50
    assert resize_max_width(frame, 0) is frame
    assert resize_max_width(frame, 200) is frame


def test_encode_jpeg_returns_bytes():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    encoded = encode_jpeg(frame, 75)
    assert encoded is not None
    assert encoded[:2] == b"\xff\xd8"


def test_draw_detections_and_overlay():
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    detections = [Detection(x1=10, y1=10, x2=60, y2=60, label="cat", confidence=0.9)]
    annotated = draw_detections(frame, detections, True)
    assert annotated.shape == frame.shape
    assert annotated.any()

    assert draw_detections(frame, [], True).shape == frame.shape
    assert draw_detections(frame, detections, False).shape == frame.shape

    overlaid = draw_overlay(annotated, "patio", "ALERTA")
    assert overlaid.shape == frame.shape
