from __future__ import annotations

from flask import Blueprint, jsonify

from app.core.utils import utc_now_iso
from app.web.context import WebContext


def build_public_blueprint(ctx: WebContext) -> Blueprint:
    """Endpoints de salud, sin autenticación (para probes/CI)."""

    bp = Blueprint("public", __name__)

    @bp.route("/health")
    def health():
        return jsonify({"ok": True, "timestamp": utc_now_iso()})

    @bp.route("/ready")
    def ready():
        snapshot = ctx.app_state.snapshot()
        return jsonify(
            {
                "ok": True,
                "timestamp": utc_now_iso(),
                "cameras": snapshot["total_cameras"],
                "online_cameras": snapshot["online_cameras"],
                "detector_loaded": ctx.detector.loaded,
                "telegram": ctx.notifier.status(),
            }
        )

    return bp
