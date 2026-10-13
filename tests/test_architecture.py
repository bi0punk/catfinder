"""Pruebas de arquitectura: evitan regresiones de acoplamiento entre capas.

Regla de dependencias (de abajo hacia arriba):

    core/domain  <-  detection, storage, notifier  <-  camera  <-  web  <-  main

- ``camera`` (workers) no debe importar la capa ``web``.
- ``detection`` no debe importar ``camera`` ni ``web``.
- ``domain`` solo puede depender de ``core``.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _layer_files(layer: str):
    return sorted((APP / layer).rglob("*.py"))


def test_camera_layer_does_not_import_web():
    offenders = {
        str(path.relative_to(APP)): sorted(m for m in _imports(path) if m.startswith("app.web"))
        for path in _layer_files("camera")
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"camera importa web: {offenders}"


def test_detection_layer_is_independent():
    forbidden = ("app.camera", "app.web", "app.notifier", "app.storage")
    offenders = {}
    for path in _layer_files("detection"):
        bad = sorted(m for m in _imports(path) if m.startswith(forbidden))
        if bad:
            offenders[str(path.relative_to(APP))] = bad
    assert not offenders, f"detection acoplado: {offenders}"


def test_domain_layer_only_depends_on_core():
    allowed = {"app.core", "app.domain"}
    offenders = {}
    for path in _layer_files("domain"):
        bad = sorted(
            m
            for m in _imports(path)
            if m.startswith("app.") and not any(m.startswith(a) for a in allowed)
        )
        if bad:
            offenders[str(path.relative_to(APP))] = bad
    assert not offenders, f"domain depende de capas superiores: {offenders}"


def test_workers_do_not_import_web_blueprints():
    worker = APP / "camera" / "worker.py"
    assert not any(m.startswith("app.web") for m in _imports(worker))
