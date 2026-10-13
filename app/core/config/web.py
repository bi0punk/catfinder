from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.utils import safe_int


@dataclass(slots=True)
class WebSettings:
    """Configuración del servidor web Flask."""

    web_host: str
    web_port: int
    web_title: str
    web_password: str


def load_web_settings() -> WebSettings:
    return WebSettings(
        web_host=os.getenv("WEB_HOST", "127.0.0.1").strip(),
        web_port=safe_int(os.getenv("WEB_PORT", "8080"), 8080),
        web_title=os.getenv("WEB_TITLE", "CatFinder MVP").strip(),
        # Sin password la web no exige auth; se recomienda definir WEB_PASSWORD si WEB_HOST=0.0.0.0.
        web_password=os.getenv("WEB_PASSWORD", "").strip(),
    )
