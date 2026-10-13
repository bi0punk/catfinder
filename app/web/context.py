from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from functools import wraps

from flask import Response, request

from app.camera.manager import CameraManager
from app.core.config import AppConfig
from app.core.logging_config import UILogHandler
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState
from app.notifier.telegram import TelegramNotifier


@dataclass
class WebContext:
    """Dependencias compartidas por las rutas de la capa web."""

    cfg: AppConfig
    app_state: AppState
    detector: YoloDetector
    notifier: TelegramNotifier
    camera_manager: CameraManager
    ui_logs: UILogHandler
    stop_event: threading.Event

    def require_auth(self, fn):
        """Basic auth opcional: solo actúa si ``cfg.web_password`` está definido."""
        if not self.cfg.web_password:
            return fn

        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth = request.authorization
            if not auth or not secrets.compare_digest(str(auth.password), self.cfg.web_password):
                return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="CatFinder"'})
            return fn(*args, **kwargs)

        return wrapper
