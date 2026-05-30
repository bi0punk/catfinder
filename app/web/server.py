from __future__ import annotations

import secrets
import threading
from functools import wraps

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, render_template, request, send_file

from app.camera.manager import CameraManager
from app.core.config import AppConfig
from app.core.logging_config import UILogHandler
from app.core.utils import coerce_bool, ensure_dir, filename_timestamp, safe_float, safe_int, utc_now_iso, valid_camera_name
from app.detection.draw import draw_detections, draw_overlay
from app.detection.yolo_detector import YoloDetector
from app.domain.models import AppState, CameraConfig
from app.notifier.telegram import TelegramNotifier


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

    def require_auth(fn):
        if not cfg.web_password:
            return fn

        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth = request.authorization
            if not auth or not secrets.compare_digest(str(auth.password), cfg.web_password):
                return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="CatFinder"'})
            return fn(*args, **kwargs)

        return wrapper

    @app.route("/")
    @require_auth
    def index():
        return render_template("index.html", title=cfg.web_title)

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "timestamp": utc_now_iso()})

    @app.route("/ready")
    def ready():
        snapshot = app_state.snapshot()
        return jsonify(
            {
                "ok": True,
                "timestamp": utc_now_iso(),
                "cameras": snapshot["total_cameras"],
                "online_cameras": snapshot["online_cameras"],
                "detector_loaded": detector.loaded,
                "telegram": notifier.status(),
            }
        )

    @app.route("/api/status")
    @require_auth
    def api_status():
        payload = app_state.snapshot()
        payload["config"] = cfg.public_dict()
        payload["detector"] = detector.status()
        payload["telegram"] = notifier.status()
        return jsonify(payload)

    @app.route("/api/events")
    @require_auth
    def api_events():
        return jsonify({"events": app_state.snapshot()["events"]})

    @app.route("/api/logs")
    @require_auth
    def api_logs():
        limit = min(300, max(1, safe_int(request.args.get("limit", "100"), 100)))
        return jsonify({"logs": ui_logs.records(limit)})

    @app.route("/api/detection", methods=["GET", "PUT"])
    @require_auth
    def api_detection():
        if request.method == "GET":
            return jsonify(detector.status())
        payload = request.get_json(silent=True) or {}
        try:
            detector.update_runtime_params(payload)
            return jsonify({"ok": True, "detector": detector.status(), "config": cfg.public_dict()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/detection/classes")
    @require_auth
    def api_detection_classes():
        try:
            detector.ensure_loaded()
            return jsonify({"ok": True, "classes": detector.available_classes(limit=200)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/detection/test-image", methods=["POST"])
    @require_auth
    def api_detection_test_image():
        file = request.files.get("image")
        if file is None:
            return jsonify({"ok": False, "error": "Falta archivo image"}), 400
        raw = np.frombuffer(file.read(), dtype=np.uint8)
        frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"ok": False, "error": "No se pudo leer la imagen"}), 400

        conf = request.form.get("conf")
        imgsz = request.form.get("imgsz")
        all_classes = coerce_bool(request.form.get("all_classes"), False)
        try:
            detections = detector.diagnose(
                frame,
                conf=safe_float(conf, cfg.confidence_threshold) if conf not in {None, ""} else None,
                imgsz=safe_int(imgsz, cfg.infer_imgsz) if imgsz not in {None, ""} else None,
                all_classes=all_classes,
            )
            annotated = draw_overlay(draw_detections(frame, detections, True), "diagnostico", f"detecciones={len(detections)}")
            diag_dir = ensure_dir(cfg.save_dir / "_diagnostics")
            filename = f"{filename_timestamp()}_diagnostic.jpg"
            path = diag_dir / filename
            ok = cv2.imwrite(str(path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), int(cfg.jpeg_quality)])
            if not ok:
                raise RuntimeError("No se pudo guardar imagen diagnóstica")
            rel = str(path.relative_to(cfg.save_dir))
            return jsonify(
                {
                    "ok": True,
                    "detections": [d.to_dict() for d in detections],
                    "count": len(detections),
                    "image_path": rel,
                    "image_url": f"/captures/{rel}",
                    "detector": detector.status(),
                    "all_classes": all_classes,
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "detector": detector.status()}), 400

    @app.route("/api/cameras", methods=["GET", "POST"])
    @require_auth
    def api_cameras():
        if request.method == "GET":
            return jsonify({"cameras": camera_manager.list_public()})
        payload = request.get_json(silent=True) or {}
        try:
            camera = _camera_from_payload(payload)
            camera_manager.add_camera(camera)
            return jsonify({"ok": True, "camera": camera.public_dict()}), 201
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/cameras/<name>", methods=["PUT", "DELETE"])
    @require_auth
    def api_camera_detail(name: str):
        if not camera_manager.has(name):
            abort(404)
        if request.method == "DELETE":
            camera_manager.remove_camera(name)
            return jsonify({"ok": True})
        payload = request.get_json(silent=True) or {}
        payload["name"] = name
        try:
            camera = _camera_from_payload(payload)
            camera_manager.update_camera(name, camera)
            return jsonify({"ok": True, "camera": camera.public_dict()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/cameras/<name>/restart", methods=["POST"])
    @require_auth
    def api_camera_restart(name: str):
        if not camera_manager.has(name):
            abort(404)
        camera_manager.restart_camera(name)
        return jsonify({"ok": True})

    @app.route("/api/telegram/test", methods=["POST"])
    @require_auth
    def api_telegram_test():
        ok, message = notifier.send_test_message()
        return jsonify({"ok": ok, "message": message}), 200 if ok else 400

    @app.route("/stream/<name>")
    @require_auth
    def stream(name: str):
        state = app_state.get_camera_state(name)
        if state is None:
            abort(404)

        def generate():
            last_id = -1
            while not stop_event.is_set():
                current_state = app_state.get_camera_state(name)
                if current_state is None:
                    break
                current_state.wait_for_new_frame(last_id, timeout=1.0)
                jpeg, jpeg_id = current_state.get_frame()
                if jpeg is None or jpeg_id == last_id:
                    continue
                last_id = jpeg_id
                yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + jpeg + b"\r\n"

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/captures/<path:relative_path>")
    @require_auth
    def captures(relative_path: str):
        target = (cfg.save_dir / relative_path).resolve()
        try:
            target.relative_to(cfg.save_dir.resolve())
        except ValueError:
            abort(403)
        if not target.is_file():
            abort(404)
        return send_file(str(target), mimetype="image/jpeg")

    return app


def _camera_from_payload(payload: dict) -> CameraConfig:
    name = str(payload.get("name", "")).strip()
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    if not valid_camera_name(name):
        raise ValueError("Nombre inválido. Usa letras, números, guion o guion bajo")
    if not rtsp_url.startswith("rtsp://"):
        raise ValueError("rtsp_url debe empezar con rtsp://")
    split_mode = str(payload.get("split_mode", "none")).lower()
    if split_mode not in {"none", "left", "right", "top", "bottom"}:
        split_mode = "none"
    return CameraConfig(
        name=name,
        rtsp_url=rtsp_url,
        enabled=coerce_bool(payload.get("enabled", True), True),
        detect_fps=safe_float(payload.get("detect_fps"), 0.0) or None,
        cooldown_seconds=safe_int(payload.get("cooldown_seconds"), 0) or None,
        max_frame_width=safe_int(payload.get("max_frame_width"), 0) or None,
        split_mode=split_mode,
    )
