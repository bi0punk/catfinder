# CatFinder PRO

Sistema web en Python para visualizar cámaras RTSP, detectar gatos con YOLO/Ultralytics, dibujar bounding boxes visibles, guardar evidencias y enviar alertas por Telegram.

**Security:** Credenciales RTSP y Telegram se configuran en `.env` (excluido de git). No commitees credenciales reales.

Esta versión corrige el punto crítico del MVP anterior: la detección venía demasiado estricta para cámaras reales. Ahora el perfil inicial está ajustado para gatos pequeños/parciales/nocturnos:

```env
CONFIDENCE_THRESHOLD=0.25
INFER_IMGSZ=640
MAX_FRAME_WIDTH=1280
BOX_PERSIST_SECONDS=2.5
DRAW_BOXES=true
```

## Por qué podía no detectar gatos

1. `CONFIDENCE_THRESHOLD=0.45` era alto para gatos en cámaras RTSP.
2. `INFER_IMGSZ=416` reducía demasiado la imagen antes de inferir.
3. El stream RTSP puede estar usando substream de baja calidad.
4. El modelo `yolo11n.pt` es liviano pero menos preciso que `yolo11s.pt`.
5. Ahora puedes probar una imagen y ver el resultado anotado.
6. Bug de logs de UI corregido.

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
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
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

## Seguridad

- El archivo `.env` contiene credenciales RTSP y Telegram — **nunca lo commitees**
- `config/cameras.yaml` también está en `.gitignore`
- Activa `WEB_PASSWORD` si expones el panel por VPN
- No publiques RTSP directo a internet. Usa Tailscale, WireGuard o reverse proxy con HTTPS
- Si clonaste el repo antes de la corrección, el token de Telegram pudo quedar expuesto — **revócalo en @BotFather**
