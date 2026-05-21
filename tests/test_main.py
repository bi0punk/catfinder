"""Tests para CatFinder RTSP Monitor."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Parcheamos módulos pesados ANTES de importar main
with patch.dict("sys.modules", {
    "cv2": MagicMock(),
    "ultralytics": MagicMock(),
    "ultralytics.YOLO": MagicMock(),
}):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

    import main as _main_module
    from main import (
        AppConfig,
        AppState,
        CameraConfig,
        CameraWorker,
        DetectionEngine,
        EventRecord,
        ViewConfig,
        ViewState,
        _TELEGRAM_QUEUE_MAXSIZE,
        build_view_configs,
        clamp_ratio,
        ensure_dir,
        load_config,
        parse_camera_configs,
        parse_key_value_map,
        parse_name_url_map,
        parse_roi_map,
        safe_float,
    )


# ─── Fixtures ────────────────────────────────────────

@pytest.fixture
def sample_camera() -> CameraConfig:
    return CameraConfig(name="patio", rtsp_url="rtsp://user:pass@192.168.1.1:554/stream1")


@pytest.fixture
def sample_view() -> ViewConfig:
    return ViewConfig("patio__full", "patio", "Patio", "none", "full")


@pytest.fixture
def sample_event() -> EventRecord:
    return EventRecord(
        ts_utc="2025-01-01T00:00:00Z",
        ts_local="2025-01-01 00:00:00",
        camera_name="patio",
        view_id="patio__full",
        label="cat",
        confidence=0.95,
        alert_image="patio/alert.jpg",
        raw_image="patio/raw.jpg",
    )


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        cameras=[CameraConfig("patio", "rtsp://localhost/stream1")],
        telegram_enabled=False,
        telegram_bot_token="",
        telegram_chat_id="",
        model_path="yolo11n.pt",
        target_classes=["cat"],
        confidence_threshold=0.55,
        cooldown_seconds=60,
        process_every_n_frames=5,
        preview_every_n_frames=2,
        save_dir=Path("/tmp/catfinder_test"),
        reconnect_delay_seconds=5,
        jpeg_quality=85,
        infer_imgsz=960,
        request_timeout_seconds=20,
        draw_boxes=True,
        web_host="0.0.0.0",
        web_port=8080,
        web_title="Test",
        max_events=50,
        stream_sleep_ms=60,
        camera_rois={},
    )


# ─── Test: parse_name_url_map ───────────────────────

class TestParseNameUrlMap:
    def test_single_camera_with_name(self):
        result = parse_name_url_map("patio=rtsp://192.168.1.1/stream1")
        assert result == [("patio", "rtsp://192.168.1.1/stream1")]

    def test_multiple_cameras(self):
        result = parse_name_url_map("cam1=url1,cam2=url2")
        assert result == [("cam1", "url1"), ("cam2", "url2")]

    def test_without_name_auto_numbers(self):
        result = parse_name_url_map("rtsp://192.168.1.1/stream1,rtsp://192.168.1.2/stream1")
        assert result == [("cam_1", "rtsp://192.168.1.1/stream1"), ("cam_2", "rtsp://192.168.1.2/stream1")]

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="vacío"):
            parse_name_url_map("")

    def test_whitespace_handling(self):
        result = parse_name_url_map("  patio = url1 , jardin = url2  ")
        assert result == [("patio", "url1"), ("jardin", "url2")]

    def test_mixed_with_and_without_name(self):
        result = parse_name_url_map("patio=url1,rtsp://cam2/stream")
        assert result == [("patio", "url1"), ("cam_2", "rtsp://cam2/stream")]


# ─── Test: parse_key_value_map ──────────────────────

class TestParseKeyValueMap:
    def test_simple(self):
        assert parse_key_value_map("a=1,b=2") == {"a": "1", "b": "2"}

    def test_skips_malformed(self):
        assert parse_key_value_map("a=1,noequal, b=2") == {"a": "1", "b": "2"}

    def test_empty(self):
        assert parse_key_value_map("") == {}
        assert parse_key_value_map(None) == {}


# ─── Test: parse_roi_map ────────────────────────────

class TestParseRoiMap:
    def test_valid_roi(self):
        assert parse_roi_map("patio__left=0:100:640:480") == {"patio__left": (0, 100, 640, 480)}

    def test_invalid_coords_skipped(self):
        assert parse_roi_map("patio__left=0:abc:640:480") == {}

    def test_multiple_rois(self):
        result = parse_roi_map("a=0:0:100:200,b=10:10:300:400")
        assert result == {"a": (0, 0, 100, 200), "b": (10, 10, 300, 400)}

    def test_empty(self):
        assert parse_roi_map("") == {}
        assert parse_roi_map(None) == {}


# ─── Test: safe_float / clamp_ratio ─────────────────

class TestSafeFloat:
    def test_valid(self):
        assert safe_float("3.14", 0.0) == 3.14

    def test_invalid_returns_default(self):
        assert safe_float("not_a_number", 0.5) == 0.5


class TestClampRatio:
    def test_mid_range(self):
        assert clamp_ratio(0.5) == 0.5

    def test_below_min(self):
        assert clamp_ratio(0.0) == 0.1

    def test_above_max(self):
        assert clamp_ratio(1.0) == 0.9

    def test_edge_values(self):
        assert clamp_ratio(0.1) == 0.1
        assert clamp_ratio(0.9) == 0.9


# ─── Test: build_view_configs ───────────────────────

class TestBuildViewConfigs:
    def test_no_split(self):
        cameras = [CameraConfig("patio", "rtsp://url", "none")]
        views = build_view_configs(cameras)
        assert len(views) == 1
        assert views[0].view_id == "patio__full"
        assert views[0].crop_label == "full"

    def test_vertical_split(self):
        cameras = [CameraConfig("patio", "rtsp://url", "vertical")]
        views = build_view_configs(cameras)
        assert len(views) == 2
        assert views[0].view_id == "patio__left"
        assert views[0].crop_label == "left"
        assert views[1].view_id == "patio__right"
        assert views[1].crop_label == "right"

    def test_horizontal_split(self):
        cameras = [CameraConfig("patio", "rtsp://url", "horizontal")]
        views = build_view_configs(cameras)
        assert len(views) == 2
        assert views[0].view_id == "patio__top"
        assert views[1].view_id == "patio__bottom"

    def test_multiple_cameras(self):
        cameras = [
            CameraConfig("cam1", "rtsp://url1", "none"),
            CameraConfig("cam2", "rtsp://url2", "vertical"),
        ]
        views = build_view_configs(cameras)
        assert len(views) == 3  # 1 + 2


# ─── Test: AppState thread-safety ───────────────────

class TestAppState:
    @pytest.fixture
    def state(self):
        views = [ViewConfig("v1", "cam1", "View 1", "none", "full")]
        return AppState(views=views, max_events=10, jpeg_quality=85)

    def test_initial_state(self, state):
        snap = state.snapshot()
        assert snap["total_views"] == 1
        assert snap["total_events"] == 0
        assert snap["total_detections"] == 0

    def test_update_view_frame(self, state):
        dummy_frame = MagicMock()
        dummy_frame.shape = (480, 640, 3)

        with patch.object(_main_module, "encode_jpg", return_value=b"jpeg_bytes"):
            state.update_view_frame("v1", dummy_frame, dummy_frame, "online")

        snap = state.snapshot()
        assert snap["views"][0]["status"] == "online"
        assert snap["views"][0]["width"] == 640
        assert snap["views"][0]["height"] == 480

    def test_add_event(self, state, sample_event):
        state.add_event(sample_event)
        snap = state.snapshot()
        assert snap["total_events"] == 1
        assert snap["events"][0]["label"] == "cat"

    def test_max_events_bounded(self, state, sample_event):
        for i in range(15):
            e = EventRecord(
                ts_utc=f"2025-01-01T00:0{i}:00Z",
                ts_local="",
                camera_name="patio",
                view_id="v1",
                label="cat",
                confidence=0.9,
                alert_image=f"{i}.jpg",
                raw_image=f"{i}_raw.jpg",
            )
            state.add_event(e)

        snap = state.snapshot()
        assert snap["total_events"] == 10  # maxlen=10

    def test_get_view_status(self, state):
        assert state.get_view_status("v1") == "starting"
        assert state.get_view_status("nonexistent") == "unknown"

    def test_update_detection(self, state):
        state.update_detection("v1", "cat", 0.95)
        snap = state.snapshot()
        assert snap["views"][0]["detection_count"] == 1
        assert snap["views"][0]["last_detection_label"] == "cat"

    def test_get_stream_bytes(self, state):
        assert state.get_stream_bytes("v1", annotated=True) is None
        assert state.get_stream_bytes("nonexistent") is None

    def test_concurrent_access(self, state):
        """Verifica que el RLock soporta acceso concurrente sin corrupción."""
        original_encode = _main_module.encode_jpg
        _main_module.encode_jpg = lambda f, quality=85: b"jpeg"

        def writer():
            dummy = MagicMock()
            dummy.shape = (480, 640, 3)
            for _ in range(100):
                state.update_view_frame("v1", dummy, dummy, "online")
                state.update_detection("v1", "cat", 0.9)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        _main_module.encode_jpg = original_encode

        snap = state.snapshot()
        assert snap["views"][0]["detection_count"] == 400
        assert snap["total_detections"] == 400

    def test_snapshot_pagination(self, state, sample_event):
        for i in range(10):
            e = EventRecord(
                ts_utc=f"2025-01-01T00:0{i}:00Z",
                ts_local="",
                camera_name="patio",
                view_id="v1",
                label="cat",
                confidence=0.9,
                alert_image=f"{i}.jpg",
                raw_image=f"{i}_raw.jpg",
            )
            state.add_event(e)

        page0 = state.snapshot(page=0, page_size=3)
        assert len(page0["events"]) == 3

        page1 = state.snapshot(page=1, page_size=3)
        assert len(page1["events"]) == 3

        assert page0["events"][0]["ts_utc"] != page1["events"][0]["ts_utc"]


# ─── Test: TelegramNotifier ─────────────────────────

class TestTelegramNotifier:
    def test_disabled_is_noop(self):
        tn = _main_module.TelegramNotifier.__new__(_main_module.TelegramNotifier)
        tn.enabled = False
        tn.send_photo(Path("test.jpg"), "caption")
        tn.stop()

    def test_queue_bounded(self):
        tn = _main_module.TelegramNotifier.__new__(_main_module.TelegramNotifier)
        tn.enabled = True
        tn._queue = queue.Queue(maxsize=_TELEGRAM_QUEUE_MAXSIZE)
        tn.bot_token = "test"
        tn.chat_id = "123"
        tn.base_url = "https://api.telegram.org/bottest"
        tn.timeout_seconds = 20

        for i in range(_TELEGRAM_QUEUE_MAXSIZE):
            tn.send_photo(Path(f"{i}.jpg"), "cap")

        assert tn._queue.qsize() == _TELEGRAM_QUEUE_MAXSIZE

        tn.send_photo(Path("overflow.jpg"), "cap")
        assert tn._queue.qsize() == _TELEGRAM_QUEUE_MAXSIZE


# ─── Test: CameraConfig / EventRecord dataclasses ───

class TestDataClasses:
    def test_camera_config_defaults(self):
        c = CameraConfig("cam", "rtsp://url")
        assert c.split_mode == "none"
        assert c.split_ratio == 0.5

    def test_event_record_fields(self, sample_event):
        assert sample_event.ts_utc == "2025-01-01T00:00:00Z"
        assert sample_event.confidence == 0.95

    def test_view_config_creation(self, sample_view):
        assert sample_view.view_id == "patio__full"
        assert sample_view.camera_name == "patio"

    def test_view_state_defaults(self):
        vs = ViewState("v1", "cam1", "V1", "none", "full")
        assert vs.status == "starting"
        assert vs.detection_count == 0
        assert vs.latest_raw_jpeg is None
        assert vs.frame_counter == 0


# ─── Test: ensure_dir ───────────────────────────────

class TestEnsureDir:
    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "subdir" / "nested"
            ensure_dir(d)
            assert d.exists()
            assert d.is_dir()

    def test_existing_directory_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "exists"
            d.mkdir()
            ensure_dir(d)  # no debe lanzar excepción


# ─── Test: DetectionEngine (mockeado) ───────────────

class TestDetectionEngine:
    def test_resolve_target_ids(self):
        mock_model = MagicMock()
        mock_model.names = {0: "person", 15: "cat", 16: "dog"}

        engine = DetectionEngine.__new__(DetectionEngine)
        engine.model = mock_model
        engine.names = {0: "person", 15: "cat", 16: "dog"}
        engine.confidence_threshold = 0.55
        engine.infer_imgsz = 960

        ids = engine.resolve_target_ids(["cat"])
        assert ids == [15]

        ids = engine.resolve_target_ids(["cat", "dog"])
        assert ids == [15, 16]

        with pytest.raises(ValueError):
            engine.resolve_target_ids(["unicorn"])

    def test_normalize_names_dict(self):
        names = DetectionEngine._normalize_names({0: "Cat", 1: "Dog"})
        assert names == {0: "cat", 1: "dog"}

    def test_normalize_names_list(self):
        names = DetectionEngine._normalize_names(["Cat", "Dog"])
        assert names == {0: "cat", 1: "dog"}

    def test_normalize_names_empty(self):
        assert DetectionEngine._normalize_names({}) == {}
        assert DetectionEngine._normalize_names([]) == {}

    def test_infer_no_lock(self):
        """Verifica que infer() ya no usa threading.Lock (cada instancia es exclusiva)."""
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_model.predict.return_value = [mock_result]

        engine = DetectionEngine.__new__(DetectionEngine)
        engine.model = mock_model
        engine.names = {0: "person"}
        engine.confidence_threshold = 0.55
        engine.infer_imgsz = 960

        result = engine.infer(MagicMock())
        assert result is mock_result
        mock_model.predict.assert_called_once()


# ─── Test: parse_camera_configs (con env mockeado) ──

class TestParseCameraConfigs:
    @patch.dict(os.environ, {
        "RTSP_URLS": "patio=rtsp://192.168.1.1/stream1",
        "CAMERA_SPLITS": "patio=vertical",
        "CAMERA_SPLIT_RATIOS": "patio=0.3",
    })
    def test_with_all_options(self):
        cameras = parse_camera_configs()
        assert len(cameras) == 1
        assert cameras[0].name == "patio"
        assert cameras[0].rtsp_url == "rtsp://192.168.1.1/stream1"
        assert cameras[0].split_mode == "vertical"
        assert cameras[0].split_ratio == 0.3

    @patch.dict(os.environ, {
        "RTSP_URLS": "cam1=url1,cam2=url2",
        "CAMERA_SPLITS": "",
        "CAMERA_SPLIT_RATIOS": "",
    })
    def test_multiple_cameras_defaults(self):
        cameras = parse_camera_configs()
        assert len(cameras) == 2
        for cam in cameras:
            assert cam.split_mode == "none"
            assert cam.split_ratio == 0.5

    @patch.dict(os.environ, {
        "RTSP_URLS": "patio=url",
        "CAMERA_SPLITS": "patio=invalid",
        "CAMERA_SPLIT_RATIOS": "patio=5.0",
    })
    def test_invalid_split_mode_falls_back(self):
        cameras = parse_camera_configs()
        assert cameras[0].split_mode == "none"
        assert cameras[0].split_ratio == 0.9  # clamped


# ─── Test: AppConfig dataclass ──────────────────────

class TestAppConfig:
    def test_web_password_default_empty(self, app_config):
        assert app_config.web_password == ""

    def test_web_password_custom(self):
        cfg = AppConfig(
            cameras=[],
            telegram_enabled=False,
            telegram_bot_token="",
            telegram_chat_id="",
            model_path="yolo11n.pt",
            target_classes=["cat"],
            confidence_threshold=0.55,
            cooldown_seconds=60,
            process_every_n_frames=5,
            preview_every_n_frames=2,
            save_dir=Path("/tmp"),
            reconnect_delay_seconds=5,
            jpeg_quality=85,
            infer_imgsz=960,
            request_timeout_seconds=20,
            draw_boxes=True,
            web_host="0.0.0.0",
            web_port=8080,
            web_title="Test",
            max_events=50,
            stream_sleep_ms=60,
            camera_rois={},
            web_password="secret123",
        )
        assert cfg.web_password == "secret123"
