"""Tests del detector (sin cargar el modelo YOLO) y del logging UI."""

from __future__ import annotations

import logging

from app.core.logging_config import UILogHandler, setup_logging
from app.detection.base import Detector
from app.detection.yolo_detector import YoloDetector


def test_yolo_detector_is_detector():
    assert issubclass(YoloDetector, Detector)


def test_status_and_available_classes(cfg):
    detector = YoloDetector(cfg)
    status = detector.status()
    assert status["loaded"] is False
    assert status["available_classes_sample"] == []
    assert detector.available_classes() == []


def test_update_runtime_params_clamps(cfg):
    detector = YoloDetector(cfg)
    detector.update_runtime_params(
        {
            "confidence_threshold": 5,
            "infer_imgsz": 1,
            "detect_fps": 99,
            "cooldown_seconds": -1,
            "box_persist_seconds": 99,
            "draw_boxes": "no",
        }
    )
    assert detector.cfg.confidence_threshold == 0.99
    assert detector.cfg.infer_imgsz == 256
    assert detector.cfg.detect_fps == 10.0
    assert detector.cfg.cooldown_seconds == 0
    assert detector.cfg.box_persist_seconds == 10.0
    assert detector.cfg.draw_boxes is False


def test_update_runtime_params_target_classes(cfg):
    detector = YoloDetector(cfg)
    detector.update_runtime_params({"target_classes": "Cat, dog"})
    assert detector.cfg.target_classes == ["cat", "dog"]
    assert detector.loaded is False


def test_ui_log_handler_records():
    handler = UILogHandler(maxlen=5)
    logger = logging.getLogger("catfinder-test")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info("hola-mundo")
        records = handler.records(10)
        assert any(record["message"] == "hola-mundo" for record in records)
        assert handler.records(1)[0]["level"] == "INFO"
    finally:
        logger.removeHandler(handler)


def test_setup_logging_returns_ui_handler():
    handler = setup_logging("DEBUG")
    assert isinstance(handler, UILogHandler)
