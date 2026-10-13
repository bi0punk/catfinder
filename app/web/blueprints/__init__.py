from __future__ import annotations

from flask import Flask

from app.web.blueprints.api import build_api_blueprint
from app.web.blueprints.public import build_public_blueprint
from app.web.blueprints.ui import build_ui_blueprint
from app.web.context import WebContext


def register_blueprints(app: Flask, ctx: WebContext) -> None:
    app.register_blueprint(build_public_blueprint(ctx))
    app.register_blueprint(build_ui_blueprint(ctx))
    app.register_blueprint(build_api_blueprint(ctx))
