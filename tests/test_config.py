from pathlib import Path

from app.core.config import load_cameras_file, save_cameras_file
from app.domain.models import CameraConfig


def test_save_load_cameras(tmp_path: Path):
    path = tmp_path / "cameras.yaml"
    cameras = [CameraConfig(name="patio", rtsp_url="rtsp://user:pass@1.2.3.4/live", enabled=True)]
    save_cameras_file(path, cameras)
    loaded = load_cameras_file(path)
    assert len(loaded) == 1
    assert loaded[0].name == "patio"
    assert loaded[0].rtsp_url.startswith("rtsp://")


def test_public_dict_redacts_password():
    cam = CameraConfig(name="x", rtsp_url="rtsp://admin:secret@10.0.0.1/live")
    assert "secret" not in cam.public_dict()["rtsp_url"]
    assert "***" in cam.public_dict()["rtsp_url"]
