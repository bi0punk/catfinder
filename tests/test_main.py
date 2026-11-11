"""Tests del punto de entrada sin abrir RTSP ni el servidor web."""

from __future__ import annotations

import pytest

from app.main import main


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
