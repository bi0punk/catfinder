from __future__ import annotations

import threading

from flask import Flask

from app.camera.manager import CameraManager
from app.core.config import AppConfig
from app.core.logging_config import UILogHandler
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState
from app.notifier.telegram import TelegramNotifier
from app.web.blueprints import register_blueprints
from app.web.context import WebContext


def create_web_app(
    cfg: AppConfig,
    app_state: AppState,
    detector: YoloDetector,
    notifier: TelegramNotifier,
    camera_manager: CameraManager,
    ui_logs: UILogHandler,
    stop_event: threading.Event,
) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    ctx = WebContext(
        cfg=cfg,
        app_state=app_state,
        detector=detector,
        notifier=notifier,
        camera_manager=camera_manager,
        ui_logs=ui_logs,
        stop_event=stop_event,
    )
    register_blueprints(app, ctx)
    return app
