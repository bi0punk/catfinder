"""Tests del punto de entrada sin abrir RTSP ni el servidor web."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.main import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_check_valida_config_y_sale(clean_env, capsys):
    assert main(["--check"]) == 0
    salida = capsys.readouterr().out
    assert "OK:" in salida
    assert "cámara" in salida


def test_check_falla_si_la_config_es_invalida(clean_env, monkeypatch):
    def _boom():
        raise ValueError("config rota")

    monkeypatch.setattr("app.main.load_app_config", _boom)
    with pytest.raises(ValueError, match="config rota"):
        main(["--check"])


def test_check_no_duplica_logs():
    """Un logging.debug antes de configurar el logger no debe instalar basicConfig."""
    proc = subprocess.run(
        [sys.executable, "-m", "app", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    banner = [line for line in proc.stderr.splitlines() if "CatFinder MVP iniciando" in line]
    assert len(banner) == 1, banner
