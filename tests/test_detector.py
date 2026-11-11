"""Tests del detector (sin cargar el modelo YOLO) y del logging UI."""

from __future__ import annotations

import logging

import numpy as np
import pytest

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
        assert handler.records(0) == []
    finally:
        logger.removeHandler(handler)


def test_setup_logging_returns_ui_handler():
    handler = setup_logging("DEBUG")
    assert isinstance(handler, UILogHandler)


# ---------------------------------------------------------------------------
# Dobles de YOLO: permiten probar el parseo sin instalar Ultralytics (~2 GB).
# ---------------------------------------------------------------------------


class _Scalar:
    def __init__(self, values):
        self._values = values

    def __getitem__(self, index):
        return self._values[index]

    def tolist(self):
        return list(self._values)


class _Box:
    def __init__(self, xyxy, cls, conf):
        self.xyxy = [_Scalar(xyxy)]
        self.cls = _Scalar([cls])
        self.conf = _Scalar([conf])


class _Result:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeModel:
    def __init__(self, boxes, names):
        self._boxes = boxes
        self.names = names
        self.calls = []

    def predict(self, *, source, imgsz, conf, verbose, device, classes=None):
        self.calls.append({"imgsz": imgsz, "conf": conf, "classes": classes})
        boxes = self._boxes
        if classes is not None:
            boxes = [box for box in boxes if int(box.cls[0]) in classes]
        return [_Result(boxes)]


def _detector(cfg, tmp_path, boxes, names=None):
    model_path = tmp_path / "pesos.pt"
    model_path.write_bytes(b"fake")
    cfg.model_path = str(model_path)
    cfg.target_classes = ["gato"]
    cfg.min_box_area_ratio = 0.0
    fake = _FakeModel(boxes, names or {0: "cat", 1: "dog"})
    return YoloDetector(cfg, model_factory=lambda _path: fake), fake, model_path


def test_detect_usa_clases_objetivo_y_mapea_etiquetas(cfg, tmp_path):
    boxes = [
        _Box((10, 10, 50, 50), 0, 0.90),
        _Box((60, 60, 90, 90), 1, 0.80),
    ]
    detector, fake, model_path = _detector(cfg, tmp_path, boxes)

    detections = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert [d.label for d in detections] == ["cat"]
    assert detections[0].confidence == pytest.approx(0.90)
    assert detector.loaded is True
    assert detector.status()["resolved_model_path"] == str(model_path.resolve())
    assert fake.calls[0]["classes"] == [0]


def test_diagnose_all_classes_no_filtra(cfg, tmp_path):
    boxes = [_Box((10, 10, 50, 50), 0, 0.9), _Box((60, 60, 90, 90), 1, 0.8)]
    detector, fake, _ = _detector(cfg, tmp_path, boxes)

    detections = detector.diagnose(np.zeros((100, 100, 3), dtype=np.uint8), all_classes=True)

    assert {d.label for d in detections} == {"cat", "dog"}
    assert fake.calls[0]["classes"] is None


def test_detect_descarta_cajas_bajo_el_area_minima(cfg, tmp_path):
    boxes = [_Box((10, 10, 20, 20), 0, 0.9)]
    detector, _, _ = _detector(cfg, tmp_path, boxes)
    detector.cfg.min_box_area_ratio = 0.5

    assert detector.detect(np.zeros((100, 100, 3), dtype=np.uint8)) == []


def test_detect_recorta_cajas_fuera_del_frame(cfg, tmp_path):
    boxes = [_Box((-20, -20, 200, 200), 0, 0.9)]
    detector, _, _ = _detector(cfg, tmp_path, boxes)

    (detection,) = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

    assert (detection.x1, detection.y1, detection.x2, detection.y2) == (0, 0, 99, 99)


def test_clase_objetivo_inexistente_falla_con_mensaje_util(cfg, tmp_path):
    detector, _, _ = _detector(cfg, tmp_path, [], names={0: "cat"})
    cfg.target_classes = ["perro"]

    with pytest.raises(RuntimeError, match="no existen en el modelo"):
        detector.ensure_loaded()
    assert detector.loaded is False
    assert "no existen en el modelo" in detector.error
