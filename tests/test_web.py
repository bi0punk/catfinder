"""Tests de la capa web (Flask TestClient) sin cargar YOLO ni abrir RTSP."""

from __future__ import annotations

import base64
import threading

import pytest

from app.camera.manager import CameraManager
from app.core.logging_config import UILogHandler
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState
from app.notifier.telegram import TelegramNotifier
from app.storage.evidence import EvidenceStore
from app.web.server import create_web_app


def build_app(cfg):
    stop_event = threading.Event()
    app_state = AppState()
    detector = YoloDetector(cfg)
    notifier = TelegramNotifier(cfg, stop_event)
    evidence_store = EvidenceStore(cfg)
    manager = CameraManager(cfg, app_state, detector, evidence_store, notifier, stop_event)
    app = create_web_app(cfg, app_state, detector, notifier, manager, UILogHandler(), stop_event)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def web(cfg):
    return build_app(cfg), cfg


def test_health_and_ready_are_public(web):
    app, _ = web
    client = app.test_client()
    assert client.get("/health").json["ok"] is True
    ready = client.get("/ready").json
    assert ready["ok"] is True
    assert ready["detector_loaded"] is False


def test_index_renders_title(web):
    app, cfg = web
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert cfg.web_title.encode() in response.data


def test_api_status_events_logs(web):
    app, _ = web
    client = app.test_client()
    status = client.get("/api/status").json
    assert status["config"]["web_port"] == 8080
    assert "detector" in status and "telegram" in status
    assert "events" in client.get("/api/events").json
    assert "logs" in client.get("/api/logs?limit=5").json


def test_api_detection_get_and_put(web):
    app, _ = web
    client = app.test_client()
    assert client.get("/api/detection").json["loaded"] is False
    updated = client.put("/api/detection", json={"confidence_threshold": 0.5})
    assert updated.status_code == 200
    assert updated.json["detector"]["confidence_threshold"] == 0.5


def test_api_cameras_crud(web):
    app, _ = web
    client = app.test_client()
    created = client.post(
        "/api/cameras",
        json={"name": "garage", "rtsp_url": "rtsp://1.2.3.4/live", "enabled": False},
    )
    assert created.status_code == 201
    assert client.get("/api/cameras").json["cameras"][0]["name"] == "garage"

    invalid = client.post("/api/cameras", json={"name": "bad/name", "rtsp_url": "rtsp://x"})
    assert invalid.status_code == 400
    assert client.put("/api/cameras/nope", json={}).status_code == 404

    assert client.delete("/api/cameras/garage").status_code == 200


def test_stream_unknown_camera_404(web):
    app, _ = web
    assert app.test_client().get("/stream/nope").status_code == 404


def test_captures_serves_file_and_blocks_traversal(web):
    app, cfg = web
    client = app.test_client()
    image = cfg.save_dir / "cam" / "x.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"\xff\xd8\xff\xe0")
    assert client.get("/captures/cam/x.jpg").status_code == 200
    assert client.get("/captures/missing.jpg").status_code == 404
    assert client.get("/captures/..%2f..%2fetc%2fpasswd").status_code == 403


def test_basic_auth_when_password_set(cfg):
    cfg.web_password = "secret"
    app = build_app(cfg)
    client = app.test_client()
    assert client.get("/").status_code == 401
    assert client.get("/health").status_code == 200

    token = base64.b64encode(b":secret").decode()
    response = client.get("/", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 200
