from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from app.domain.models import Detection


class Detector(ABC):
    """Interfaz mínima de un detector de objetos.

    Las implementaciones solo deben resolver ``detect(frame)``; el dibujo y el
    pre/post-procesado visual viven en :mod:`app.detection.draw` para no
    duplicar lógica entre detectores.
    """

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Devuelve las detecciones relevantes para un frame BGR."""
        raise NotImplementedError
