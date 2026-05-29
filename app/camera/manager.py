from __future__ import annotations

import logging
import threading

from app.core.config import AppConfig, save_cameras_file
from app.core.utils import valid_camera_name
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState, CameraConfig
from app.notifier.telegram import TelegramNotifier
from app.storage.evidence import EvidenceStore
from app.camera.worker import CameraWorker


class CameraManager:
    def __init__(
        self,
        cfg: AppConfig,
        app_state: AppState,
        detector: YoloDetector,
        evidence_store: EvidenceStore,
        notifier: TelegramNotifier,
        stop_event: threading.Event,
    ):
        self.cfg = cfg
        self.app_state = app_state
        self.detector = detector
        self.evidence_store = evidence_store
        self.notifier = notifier
        self.stop_event = stop_event
        self._workers: dict[str, CameraWorker] = {}
        self._configs: dict[str, CameraConfig] = {cam.name: cam for cam in cfg.cameras}
        self._lock = threading.RLock()

    def start_all(self) -> None:
        for camera in list(self._configs.values()):
            if camera.enabled:
                self.start_camera(camera.name)
            else:
                self.app_state.add_camera_state(camera.name).mark_error("disabled", "Cámara deshabilitada")

    def start_camera(self, name: str) -> None:
        with self._lock:
            if name in self._workers:
                return
            camera = self._configs.get(name)
            if camera is None:
                raise KeyError(f"Cámara no existe: {name}")
            state = self.app_state.get_camera_state(name) or self.app_state.add_camera_state(name)
            worker = CameraWorker(
                cfg=self.cfg,
                camera=camera,
                runtime_state=state,
                detector=self.detector,
                evidence_store=self.evidence_store,
                notifier=self.notifier,
                app_state=self.app_state,
                stop_event=self.stop_event,
            )
            self._workers[name] = worker
            worker.start()
            logging.info("Cámara iniciada: %s", name)

    def stop_camera(self, name: str) -> None:
        with self._lock:
            worker = self._workers.pop(name, None)
        if worker:
            worker.stop()
            worker.join(timeout=5)
        state = self.app_state.get_camera_state(name)
        if state:
            state.mark_error("stopped", "")

    def stop_all(self) -> None:
        with self._lock:
            names = list(self._workers.keys())
        for name in names:
            self.stop_camera(name)

    def add_camera(self, camera: CameraConfig, persist: bool = True) -> None:
        if not valid_camera_name(camera.name):
            raise ValueError("Nombre de cámara inválido")
        if not camera.rtsp_url.startswith("rtsp://"):
            raise ValueError("rtsp_url debe empezar con rtsp://")
        with self._lock:
            if camera.name in self._configs:
                raise ValueError(f"La cámara ya existe: {camera.name}")
            self._configs[camera.name] = camera
            self.cfg.cameras = list(self._configs.values())
        if camera.enabled:
            self.start_camera(camera.name)
        else:
            self.app_state.add_camera_state(camera.name).mark_error("disabled", "Cámara deshabilitada")
        if persist:
            self.persist()

    def update_camera(self, name: str, camera: CameraConfig, persist: bool = True) -> None:
        if name != camera.name:
            raise ValueError("No se permite renombrar cámara desde update; elimínala y créala de nuevo")
        with self._lock:
            if name not in self._configs:
                raise KeyError(f"Cámara no existe: {name}")
            was_running = name in self._workers
            self._configs[name] = camera
            self.cfg.cameras = list(self._configs.values())
        if was_running:
            self.stop_camera(name)
        if camera.enabled:
            self.start_camera(name)
        else:
            state = self.app_state.get_camera_state(name) or self.app_state.add_camera_state(name)
            state.mark_error("disabled", "Cámara deshabilitada")
        if persist:
            self.persist()

    def remove_camera(self, name: str, persist: bool = True) -> None:
        with self._lock:
            if name not in self._configs:
                raise KeyError(f"Cámara no existe: {name}")
        self.stop_camera(name)
        self.app_state.remove_camera_state(name)
        with self._lock:
            self._configs.pop(name, None)
            self.cfg.cameras = list(self._configs.values())
        if persist:
            self.persist()

    def restart_camera(self, name: str) -> None:
        with self._lock:
            camera = self._configs.get(name)
            if camera is None:
                raise KeyError(f"Cámara no existe: {name}")
        self.stop_camera(name)
        if camera.enabled:
            self.start_camera(name)

    def list_public(self) -> list[dict]:
        with self._lock:
            return [camera.public_dict() for camera in sorted(self._configs.values(), key=lambda c: c.name)]

    def list_private(self) -> list[CameraConfig]:
        with self._lock:
            return list(self._configs.values())

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._configs

    def persist(self) -> None:
        save_cameras_file(self.cfg.cameras_file, self.list_private())
