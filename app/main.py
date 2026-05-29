from __future__ import annotations

import logging
import signal
import threading

from dotenv import load_dotenv

# Cargar .env y fijar límites antes de iniciar OpenCV/Torch pesado.
load_dotenv()
from app.core.utils import configure_numeric_runtime  # noqa: E402
configure_numeric_runtime()

from app.camera.manager import CameraManager  # noqa: E402
from app.core.config import load_app_config  # noqa: E402
from app.core.logging_config import setup_logging  # noqa: E402
from app.detection.yolo_detector import YoloDetector  # noqa: E402
from app.domain.models import AppState  # noqa: E402
from app.notifier.telegram import TelegramNotifier  # noqa: E402
from app.storage.evidence import EvidenceStore, RetentionThread  # noqa: E402
from app.web.server import create_web_app  # noqa: E402


def main() -> None:
    cfg = load_app_config()
    ui_logs = setup_logging(cfg.log_level)
    logging.info("CatFinder MVP iniciando")
    logging.info("Cámaras configuradas: %d", len(cfg.cameras))
    logging.info("Evidencias: %s", cfg.save_dir)

    stop_event = threading.Event()

    def _signal_handler(signum, _frame):
        logging.info("Señal recibida: %s. Deteniendo...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    app_state = AppState(max_events=cfg.max_events_memory)
    detector = YoloDetector(cfg)
    evidence_store = EvidenceStore(cfg)
    notifier = TelegramNotifier(cfg, stop_event)
    notifier.start()

    camera_manager = CameraManager(
        cfg=cfg,
        app_state=app_state,
        detector=detector,
        evidence_store=evidence_store,
        notifier=notifier,
        stop_event=stop_event,
    )
    camera_manager.start_all()

    retention = RetentionThread(evidence_store, stop_event)
    retention.start()

    flask_app = create_web_app(
        cfg=cfg,
        app_state=app_state,
        detector=detector,
        notifier=notifier,
        camera_manager=camera_manager,
        ui_logs=ui_logs,
        stop_event=stop_event,
    )

    try:
        flask_app.run(host=cfg.web_host, port=cfg.web_port, threaded=True, use_reloader=False)
    finally:
        stop_event.set()
        camera_manager.stop_all()
        logging.info("CatFinder detenido")


if __name__ == "__main__":
    main()
