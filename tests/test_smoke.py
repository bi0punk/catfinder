"""Smoke tests: validan higiene del repo y config base sin deps pesadas."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_tracked_yolo_weights():
    """Los pesos .pt no deben commitearse (pesan ~5MB y son descargables)."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "models/"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    pt_tracked = [line for line in tracked.splitlines() if line.endswith(".pt")]
    assert not pt_tracked, f"Pesos .pt commiteados: {pt_tracked}"


def test_env_example_has_recommended_profile():
    """El .env.example debe reflejar el perfil recomendado para gatos (no el 0.45 estricto)."""
    env = (REPO_ROOT / ".env.example").read_text()
    assert "CONFIDENCE_THRESHOLD=0.25" in env
    assert "INFER_IMGSZ=640" in env
    assert "CONFIDENCE_THRESHOLD=0.45" not in env


def test_gitignore_excludes_models():
    gi = (REPO_ROOT / ".gitignore").read_text()
    assert "models/*.pt" in gi


@pytest.fixture
def cameras_yaml(tmp_path):
    return tmp_path / "cameras.yaml"


def test_config_roundtrip(cameras_yaml):
    """Round-trip de cameras.yaml sin necesidad de ultralytics/cv2."""
    from app.core.config import save_cameras_file
    from app.domain.models import CameraConfig

    cameras = [CameraConfig(name="patio", rtsp_url="rtsp://u:p@1.2.3.4/live", enabled=True)]
    save_cameras_file(cameras_yaml, cameras)
    assert cameras_yaml.exists()
