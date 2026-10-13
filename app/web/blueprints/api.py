from __future__ import annotations

import cv2
import numpy as np
from flask import Blueprint, abort, jsonify, request

from app.core.utils import (
    coerce_bool,
    ensure_dir,
    filename_timestamp,
    safe_float,
    safe_int,
)
from app.detection.draw import draw_detections, draw_overlay
from app.web.context import WebContext
from app.web.helpers import camera_from_payload


def build_api_blueprint(ctx: WebContext) -> Blueprint:
    """Endpoints JSON de estado, detección, cámaras y Telegram."""

    bp = Blueprint("api", __name__, url_prefix="/api")
    require_auth = ctx.require_auth
    cfg = ctx.cfg
    detector = ctx.detector
    notifier = ctx.notifier
    camera_manager = ctx.camera_manager

    @bp.route("/status")
    @require_auth
    def api_status():
        payload = ctx.app_state.snapshot()
        payload["config"] = cfg.public_dict()
        payload["detector"] = detector.status()
        payload["telegram"] = notifier.status()
        return jsonify(payload)

    @bp.route("/events")
    @require_auth
    def api_events():
        return jsonify({"events": ctx.app_state.snapshot()["events"]})

    @bp.route("/logs")
    @require_auth
    def api_logs():
        limit = min(300, max(1, safe_int(request.args.get("limit", "100"), 100)))
        return jsonify({"logs": ctx.ui_logs.records(limit)})

    @bp.route("/detection", methods=["GET", "PUT"])
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

    @bp.route("/detection/classes")
    @require_auth
    def api_detection_classes():
        try:
            detector.ensure_loaded()
            return jsonify({"ok": True, "classes": detector.available_classes(limit=200)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.route("/detection/test-image", methods=["POST"])
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

    @bp.route("/cameras", methods=["GET", "POST"])
    @require_auth
    def api_cameras():
        if request.method == "GET":
            return jsonify({"cameras": camera_manager.list_public()})
        payload = request.get_json(silent=True) or {}
        try:
            camera = camera_from_payload(payload)
            camera_manager.add_camera(camera)
            return jsonify({"ok": True, "camera": camera.public_dict()}), 201
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.route("/cameras/<name>", methods=["PUT", "DELETE"])
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
            camera = camera_from_payload(payload)
            camera_manager.update_camera(name, camera)
            return jsonify({"ok": True, "camera": camera.public_dict()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.route("/cameras/<name>/restart", methods=["POST"])
    @require_auth
    def api_camera_restart(name: str):
        if not camera_manager.has(name):
            abort(404)
        camera_manager.restart_camera(name)
        return jsonify({"ok": True})

    @bp.route("/telegram/test", methods=["POST"])
    @require_auth
    def api_telegram_test():
        ok, message = notifier.send_test_message()
        return jsonify({"ok": ok, "message": message}), 200 if ok else 400

    return bp
