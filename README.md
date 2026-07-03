# CatFinder PRO

[![CI](https://github.com/bi0punk/catfinder/actions/workflows/ci.yml/badge.svg)](https://github.com/bi0punk/catfinder/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Sistema web en Python para visualizar cámaras RTSP, detectar gatos con YOLO/Ultralytics, dibujar bounding boxes visibles, guardar evidencias y enviar alertas por Telegram.

## Tabla de contenidos

- [Características](#características)
- [Stack](#stack)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Tests](#tests)
- [Configuración](#configuración)
- [CI](#ci)
- [Datos](#datos)
- [Seguridad](#seguridad)
- [Limitaciones y roadmap](#limitaciones-y-roadmap)
- [Licencia](#licencia)

## Características

- Visualización de cámaras RTSP con stream web en vivo.
- Detección de gatos con YOLO (Ultralytics), bounding boxes visibles overlay.
- Perfil ajustado para gatos pequeños/parciales/nocturnos (`CONFIDENCE_THRESHOLD=0.25`).
- Guardado de evidencias JPG + `events.jsonl` con retención configurable.
- Alertas por Telegram opcionales.
- Panel de diagnóstico con imagen (sube un frame y prueba detección).
- Configuración de cámaras vía `cameras.yaml` o panel web.
- Docker Compose listo para CPU-only.

## Stack

- **Lenguaje**: Python 3.11+
- **Web**: Flask + Jinja2 templates.
- **Visión**: Ultralytics YOLO (`yolo11n.pt`), OpenCV (headless).
- **Config**: PyYAML + python-dotenv.
- **Notificaciones**: requests (Telegram Bot API).
- **Calidad**: ruff (lint), pytest.
- **Despliegue**: Docker (python:3.11-slim + ffmpeg) + systemd (`catfinder.service`).

## Arquitectura

```
RTSP cameras
   │
   ▼
CameraWorker (app/camera) ──► YOLO detector (app/detection, cat-focused)
   │                              │
   │                              ▼
   │                         Bounding boxes + overlay (app/detection/draw.py)
   │
   ├──► Stream web (Flask, app/web) ──► Navegador :8080
   ├──► Evidencias JPG + events.jsonl (app/storage)
   └──► Telegram (app/notifier, opcional)
```

- **CameraWorker**: lee frames RTSP, aplica ROI/splits, encola para inferencia.
- **YOLO detector**: corre `yolo11n.pt` con `TARGET_CLASSES=cat`, persistencia de boxes configurable.
- **Web**: panel Flask con stream MJPEG, API REST, diagnóstico por imagen.
- **Storage**: capturas con retención por días, log de eventos JSONL.

## Requisitos

- Linux nativo (o Docker)
- Python 3.11+
- `llama.cpp` no requerido; sí `ffmpeg` para RTSP (ya en la imagen Docker)
- Cámara RTSP accesible (se recomienda substream para CPU-only)
- Modelo `yolo11n.pt` (ver [Instalación](#instalación))

## Flujo

```text
RTSP
  ↓
CameraWorker
  ↓
YOLO detector cat-focused
  ↓
Bounding boxes + overlay
  ↓
Stream web + evidencia JPG + events.jsonl
  ↓
Telegram opcional
```

## Instalación local Linux

### Opción A: clonar el repositorio

```bash
git clone https://github.com/bi0punk/catfinder.git
cd catfinder
cp .env.example .env
# Entorno (con uv, recomendado):
uv venv -p 3.11 .venv && uv pip install -r requirements-dev.txt
# o con pip:
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
# Obtener el modelo YOLO (no se commitea, ~5MB):
python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"  # descarga automática
# o manualmente desde https://github.com/ultralytics/assets/releases
python -m app.main
```

### Opción B: desde un release zip

```bash
unzip catfinder_pro_YYYYMMDD_HHMM.zip
cd catfinder_pro_YYYYMMDD_HHMM
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m app.main
```

Panel: `http://localhost:8080`

## Configurar cámara

Edita `config/cameras.yaml` (este archivo está en `.gitignore` — no se sube al repo):

```yaml
cameras:
  - name: patio
    rtsp_url: rtsp://usuario:password@192.168.1.100:554/Streaming/Channels/102
    enabled: true
    detect_fps: null
    cooldown_seconds: null
    max_frame_width: null
```

También puedes agregar cámaras desde el panel web.

## Diagnóstico recomendado

Primero usa el panel `Diagnóstico con imagen`:

1. Sube una imagen/frame donde aparezca el gato.
2. Prueba con `conf=0.20` e `imgsz=640`.
3. Si detecta en imagen pero no en vivo, el problema está en RTSP, resolución, iluminación o ángulo.
4. Si no detecta en imagen, marca `Probar todas las clases`.
5. Si sigue sin detectar, prueba `yolo11s.pt` o sube `INFER_IMGSZ=960`.

## Ajustes de producción CPU-only

Perfil equilibrado:

```env
CONFIDENCE_THRESHOLD=0.25
INFER_IMGSZ=640
DETECT_FPS=1.0
MAX_FRAME_WIDTH=1280
TORCH_NUM_THREADS=2
OPENCV_THREADS=1
```

## API principal

```text
GET  /health
GET  /ready
GET  /api/status
GET  /api/events
GET  /api/logs
GET  /api/detection
PUT  /api/detection
GET  /api/detection/classes
POST /api/detection/test-image
GET  /api/cameras
POST /api/cameras
PUT  /api/cameras/<name>
DELETE /api/cameras/<name>
POST /api/cameras/<name>/restart
GET  /stream/<name>
GET  /captures/<path>
POST /api/telegram/test
```

## Telegram

En `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABCDEF
TELEGRAM_CHAT_ID=123456789
```

## Docker Compose

```bash
cp .env.example .env
mkdir -p models captures
docker compose build
docker compose up -d
```

## Tests

```bash
# Tests ligeros (sin ultralytics/opencv/torch — imports perezosos):
PYTHONPATH=. pytest -q
```

Cobertura:

- `tests/test_config.py` — round-trip de `cameras.yaml`.
- `tests/test_utils.py` — `coerce_bool`, `valid_camera_name`.
- `tests/test_smoke.py` — higiene del repo (sin `.pt` commiteados, `.env.example` con perfil recomendado, `.gitignore` correcto).

Los tests de integración con detección real requieren `ultralytics` + cámara; no corren en CI por peso.

## CI

GitHub Actions (`.github/workflows/ci.yml`) sobre Python 3.11 / ubuntu-latest:

- **lint** — `ruff check .`
- **test** — instala deps livianas (pyyaml, dotenv, requests, flask, pytest) y corre `pytest -q` con `PYTHONPATH=.`. Las deps pesadas (ultralytics, opencv, torch) se omiten en CI gracias a imports perezosos.

## Datos

Directorios runtime (todos gitignored):

- `captures/` — evidencias JPG + `events.jsonl` (retención por `RETENTION_DAYS`).
- `models/` — modelo `yolo11n.pt` (descargable, no commiteado; se mantiene `models/.gitkeep`).
- `config/cameras.yaml` — credenciales RTSP (no commiteado).

## Seguridad

- El archivo `.env` contiene credenciales RTSP y Telegram — **nunca lo commitees**
- `config/cameras.yaml` también está en `.gitignore`
- Activa `WEB_PASSWORD` si expones el panel por VPN
- No publiques RTSP directo a internet. Usa Tailscale, WireGuard o reverse proxy con HTTPS
- Si clonaste el repo antes de la corrección, el token de Telegram pudo quedar expuesto — **revócalo en @BotFather**

## Limitaciones y roadmap

- **Limitación**: la detección depende de la calidad del substream RTSP y la iluminación; perfiles nocturnos pueden requerir `yolo11s.pt`.
- **Limitación**: sin GPU, la inferencia es CPU-only (`yolo11n.pt` recomendado por latencia).
- **Roadmap**: autodetección de substream, soporte multi-modelo, dashboard de eventos históricos.

## Licencia

MIT — ver [LICENSE](LICENSE).
