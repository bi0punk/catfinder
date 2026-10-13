from __future__ import annotations

from flask import Blueprint, Response, abort, render_template, send_file

from app.web.context import WebContext


def build_ui_blueprint(ctx: WebContext) -> Blueprint:
    """Vistas HTML, streaming MJPEG y descarga de capturas."""

    bp = Blueprint("ui", __name__)
    require_auth = ctx.require_auth
    cfg = ctx.cfg

    @bp.route("/")
    @require_auth
    def index():
        return render_template("index.html", title=cfg.web_title)

    @bp.route("/stream/<name>")
    @require_auth
    def stream(name: str):
        state = ctx.app_state.get_camera_state(name)
        if state is None:
            abort(404)

        def generate():
            last_id = -1
            while not ctx.stop_event.is_set():
                current_state = ctx.app_state.get_camera_state(name)
                if current_state is None:
                    break
                current_state.wait_for_new_frame(last_id, timeout=1.0)
                jpeg, jpeg_id = current_state.get_frame()
                if jpeg is None or jpeg_id == last_id:
                    continue
                last_id = jpeg_id
                yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + jpeg + b"\r\n"

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @bp.route("/captures/<path:relative_path>")
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

    return bp
