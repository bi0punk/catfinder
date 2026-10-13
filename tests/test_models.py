"""Tests de la capa domain: modelos, estado runtime y AppState."""

from __future__ import annotations

from app.domain.models import (
    AppState,
    CameraConfig,
    CameraRuntimeState,
    Detection,
    EventRecord,
)


def test_camera_config_public_and_private_dict():
    cam = CameraConfig(name="patio", rtsp_url="rtsp://admin:secret@10.0.0.1/live")
    assert cam.public_dict()["rtsp_url"].endswith("@10.0.0.1/live")
    assert "secret" not in cam.public_dict()["rtsp_url"]
    assert "***" in cam.public_dict()["rtsp_url"]
    assert cam.private_dict()["rtsp_url"] == "rtsp://admin:secret@10.0.0.1/live"


def test_detection_and_event_to_dict():
    det = Detection(x1=1, y1=2, x2=3, y2=4, label="cat", confidence=0.9)
    assert det.to_dict() == {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "label": "cat", "confidence": 0.9}

    event = EventRecord(
        ts_utc="2026-01-01T00:00:00Z",
        ts_local="2025-12-31 21:00:00",
        camera_name="patio",
        label="cat",
        confidence=0.8,
        image_path="patio/x.jpg",
        detections=[det.to_dict()],
    )
    assert event.to_dict()["camera_name"] == "patio"


def test_runtime_state_frames_and_marks():
    state = CameraRuntimeState(name="patio")
    assert state.get_frame() == (None, 0)
    assert state.wait_for_new_frame(-1) is True

    state.put_frame(b"jpeg-1")
    jpeg, jpeg_id = state.get_frame()
    assert jpeg == b"jpeg-1" and jpeg_id == 1
    assert state.wait_for_new_frame(0) is True
    assert state.wait_for_new_frame(1, timeout=0.01) is False
    assert state.to_dict()["status"] == "online"

    state.mark_error("degraded", "boom")
    assert state.to_dict()["status"] == "degraded"
    state.mark_reconnect("bye")
    assert state.to_dict()["reconnect_count"] == 1
    state.mark_detection(Detection(0, 0, 1, 1, "cat", 0.77))
    data = state.to_dict()
    assert data["detection_count"] == 1 and data["last_detection_label"] == "cat"


def test_app_state_snapshot_and_events():
    app_state = AppState(max_events=2)
    online = app_state.add_camera_state("patio")
    online.put_frame(b"x")
    app_state.add_camera_state("garage").mark_error("disabled", "")

    event = EventRecord("t", "t", "patio", "cat", 0.5, "p.jpg", [])
    app_state.add_event(event)

    snap = app_state.snapshot()
    assert snap["total_cameras"] == 2
    assert snap["online_cameras"] == 1
    assert snap["total_events_memory"] == 1
    assert app_state.get_camera_state("patio") is online
    assert app_state.get_camera_state("nope") is None

    app_state.remove_camera_state("patio")
    assert app_state.get_camera_state("patio") is None


def test_app_state_event_deque_bounded():
    app_state = AppState(max_events=1)
    for i in range(3):
        app_state.add_event(EventRecord("t", "t", f"c{i}", "cat", 0.1, "p.jpg", []))
    assert app_state.snapshot()["total_events_memory"] == 1
