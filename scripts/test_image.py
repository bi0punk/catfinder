#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import load_app_config  # noqa: E402
from app.core.logging_config import setup_logging  # noqa: E402
from app.detection.draw import draw_detections, draw_overlay  # noqa: E402
from app.detection.yolo_detector import YoloDetector  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba detección de gato sobre una imagen local.")
    parser.add_argument("image", help="Ruta a imagen JPG/PNG")
    parser.add_argument("--conf", type=float, default=None, help="Confianza de prueba, ejemplo 0.20")
    parser.add_argument("--imgsz", type=int, default=None, help="Tamaño inferencia, ejemplo 640")
    parser.add_argument("--all-classes", action="store_true", help="No filtrar por cat; útil para diagnóstico")
    parser.add_argument("--out", default="captures/_diagnostics/manual_test.jpg", help="Salida anotada")
    args = parser.parse_args()

    setup_logging("INFO")
    cfg = load_app_config()
    frame = cv2.imread(args.image)
    if frame is None:
        print(f"[ERROR] No se pudo leer imagen: {args.image}", file=sys.stderr)
        return 2

    detector = YoloDetector(cfg)
    detections = detector.diagnose(frame, conf=args.conf, imgsz=args.imgsz, all_classes=args.all_classes)
    annotated = draw_overlay(draw_detections(frame, detections, True), "test-image", f"detecciones={len(detections)}")

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), annotated):
        print(f"[ERROR] No se pudo escribir salida: {out}", file=sys.stderr)
        return 3

    print(f"[OK] detecciones={len(detections)} salida={out}")
    for det in detections:
        print(f"- {det.label} conf={det.confidence:.3f} box=({det.x1},{det.y1},{det.x2},{det.y2})")
    print("status=", detector.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
