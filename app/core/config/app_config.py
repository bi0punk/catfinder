from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.core.config.camera import CameraSettings, load_camera_settings
from app.core.config.detection import DetectionSettings, load_detection_settings
from app.core.config.notifier import NotifierSettings, load_notifier_settings
from app.core.config.runtime import RuntimeSettings, load_runtime_settings
from app.core.config.storage import StorageSettings, load_storage_settings
from app.core.config.web import WebSettings, load_web_settings

# Orden de búsqueda para el acceso "plano" compatible con la API histórica.
_DOMAINS = ("camera", "detection", "storage", "notifier", "web", "runtime")


@dataclass
class AppConfig:
    """Configuración efectiva de la aplicación, agrupada por dominio.

    Mantiene la API plana histórica (``cfg.confidence_threshold``,
    ``cfg.save_dir``, ``cfg.web_host``...) delegando en los sub-objetos por
    dominio, de modo que el resto del código no necesita cambiar.
    """

    project_root: Path
    camera: CameraSettings
    detection: DetectionSettings
    storage: StorageSettings
    notifier: NotifierSettings
    web: WebSettings
    runtime: RuntimeSettings

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        for domain in _DOMAINS:
            sub = self.__dict__.get(domain)
            if sub is not None and hasattr(sub, name):
                return getattr(sub, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        if name in type(self).__dataclass_fields__:
            object.__setattr__(self, name, value)
            return
        for domain in _DOMAINS:
            sub = self.__dict__.get(domain)
            if sub is not None and hasattr(sub, name):
                setattr(sub, name, value)
                return
        object.__setattr__(self, name, value)

    def public_dict(self) -> dict:
        return {
            "model_path": self.detection.model_path,
            "target_classes": self.detection.target_classes,
            "confidence_threshold": self.detection.confidence_threshold,
            "infer_imgsz": self.detection.infer_imgsz,
            "detect_fps": self.detection.detect_fps,
            "cooldown_seconds": self.detection.cooldown_seconds,
            "draw_boxes": self.detection.draw_boxes,
            "box_persist_seconds": self.detection.box_persist_seconds,
            "min_box_area_ratio": self.detection.min_box_area_ratio,
            "detector_device": self.detection.detector_device,
            "max_frame_width": self.detection.max_frame_width,
            "jpeg_quality": self.detection.jpeg_quality,
            "save_dir": str(self.storage.save_dir),
            "events_jsonl": str(self.storage.events_jsonl),
            "retention_days": self.storage.retention_days,
            "telegram_enabled": self.notifier.telegram_enabled,
            "telegram_configured": bool(self.notifier.telegram_bot_token and self.notifier.telegram_chat_id),
            "web_host": self.web.web_host,
            "web_port": self.web.web_port,
            "cameras_file": str(self.camera.cameras_file),
        }


def _project_root() -> Path:
    return Path(os.getenv("PROJECT_ROOT", Path.cwd())).resolve()


def load_app_config() -> AppConfig:
    load_dotenv()
    root = _project_root()

    return AppConfig(
        project_root=root,
        camera=load_camera_settings(root, os.getenv("CAMERAS_FILE", "config/cameras.yaml")),
        detection=load_detection_settings(),
        storage=load_storage_settings(root),
        notifier=load_notifier_settings(),
        web=load_web_settings(),
        runtime=load_runtime_settings(),
    )


# Alias explícito de la API única de carga.
load_settings = load_app_config
