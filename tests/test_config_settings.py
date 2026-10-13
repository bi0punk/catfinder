"""Tests de la carga de configuración por dominios y API plana."""

from __future__ import annotations

from app.core.config import load_cameras_file, load_settings


def test_defaults(clean_env):
    cfg = load_settings()
    assert cfg.confidence_threshold == 0.25
    assert cfg.infer_imgsz == 640
    assert cfg.target_classes == ["cat"]
    assert cfg.web_host == "127.0.0.1"
    assert cfg.log_level == "INFO"
    assert cfg.detector_device == "cpu"
    assert cfg.retention_days == 14
    assert cfg.telegram_enabled is False
    assert cfg.project_root == clean_env


def test_flat_delegation_and_mutation(clean_env):
    cfg = load_settings()
    cfg.confidence_threshold = 0.5
    assert cfg.detection.confidence_threshold == 0.5
    cfg.save_dir = clean_env / "other"
    assert cfg.storage.save_dir == clean_env / "other"
    cfg.cameras = []
    assert cfg.camera.cameras == []


def test_clamps(clean_env, monkeypatch):
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "5")
    monkeypatch.setenv("INFER_IMGSZ", "10")
    monkeypatch.setenv("JPEG_QUALITY", "1")
    monkeypatch.setenv("DETECT_FPS", "99")
    monkeypatch.setenv("COOLDOWN_SECONDS", "-3")
    cfg = load_settings()
    assert cfg.confidence_threshold == 0.99
    assert cfg.infer_imgsz == 256
    assert cfg.jpeg_quality == 40
    assert cfg.detect_fps == 10.0
    assert cfg.cooldown_seconds == 0


def test_telegram_requires_credentials(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    assert load_settings().telegram_enabled is False


def test_telegram_enabled_with_credentials(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    cfg = load_settings()
    assert cfg.telegram_enabled is True
    assert cfg.public_dict()["telegram_configured"] is True


def test_rtsp_urls_override_disabled_sample(clean_env, monkeypatch):
    monkeypatch.setenv("RTSP_URLS", "patio=rtsp://1.2.3.4/live,bad=ftp://x,=rtsp://y")
    cfg = load_settings()
    assert [c.name for c in cfg.cameras] == ["patio"]
    assert load_cameras_file(cfg.cameras_file)[0].name == "patio"


def test_storage_paths_resolved(clean_env):
    cfg = load_settings()
    assert cfg.save_dir == clean_env / "captures"
    assert cfg.events_jsonl == cfg.save_dir / "events.jsonl"


def test_runtime_and_web_settings(clean_env, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("RECONNECT_DELAY_MAX_SECONDS", "1")
    monkeypatch.setenv("WEB_PORT", "9000")
    monkeypatch.setenv("WEB_PASSWORD", "secret")
    cfg = load_settings()
    assert cfg.log_level == "DEBUG"
    assert cfg.reconnect_delay_max_seconds == 5
    assert cfg.web_port == 9000
    assert cfg.web_password == "secret"


def test_public_dict_excludes_credentials(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN-XYZ")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT-XYZ")
    monkeypatch.setenv("WEB_PASSWORD", "PWD-XYZ")
    cfg = load_settings()
    public = cfg.public_dict()
    rendered = str(public)
    assert "TOKEN-XYZ" not in rendered
    assert "PWD-XYZ" not in rendered
    assert "web_password" not in public
    assert public["telegram_configured"] is True
