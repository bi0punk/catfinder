# CatFinder PRO

Sistema web en Python para visualizar cámaras RTSP, detectar gatos con YOLO/Ultralytics, dibujar bounding boxes visibles, guardar evidencias y enviar alertas por Telegram.

Esta versión corrige el punto crítico del MVP anterior: la detección venía demasiado estricta para cámaras reales. Ahora el perfil inicial está ajustado para gatos pequeños/parciales/nocturnos:

```env
CONFIDENCE_THRESHOLD=0.25
INFER_IMGSZ=640
MAX_FRAME_WIDTH=1280
BOX_PERSIST_SECONDS=2.5
DRAW_BOXES=true
```

## Por qué podía no detectar gatos

1. `CONFIDENCE_THRESHOLD=0.45` era alto para gatos en cámaras RTSP. En la práctica un gato puede salir pequeño, oscuro, borroso, de perfil, parcial o con IR nocturno.
2. `INFER_IMGSZ=416` reducía demasiado la imagen antes de inferir. Si el gato ocupa pocos píxeles, YOLO puede descartarlo.
3. El stream RTSP puede estar usando substream de baja calidad, compresión fuerte o poca luz.
4. El modelo incluido `yolo11n.pt` es liviano y rápido, pero menos preciso que `yolo11s.pt` o `yolo11m.pt`.
5. La interfaz no mostraba ajustes ni diagnóstico visual simple; ahora puedes probar una imagen y ver el resultado anotado.
6. El handler de logs de UI tenía un bug: intentaba usar `self.formatTime`, por lo que podía dejar el panel de logs vacío.

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

Panel:

```text
http://localhost:8080
```

## Configurar cámara

Edita `config/cameras.yaml`:

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
4. Si no detecta en imagen, marca `Probar todas las clases`. Si aparece como `dog` u otra clase, el modelo liviano está confundiendo el objeto.
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

Más precisión, más CPU:

```env
CONFIDENCE_THRESHOLD=0.20
INFER_IMGSZ=960
DETECT_FPS=0.5
MAX_FRAME_WIDTH=1600
```

Menos CPU, menor precisión:

```env
CONFIDENCE_THRESHOLD=0.30
INFER_IMGSZ=512
DETECT_FPS=0.5
MAX_FRAME_WIDTH=960
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

## Probar una imagen por API

```bash
curl -s -X POST http://localhost:8080/api/detection/test-image \
  -F image=@/ruta/frame_gato.jpg \
  -F conf=0.20 \
  -F imgsz=640 \
  -F all_classes=false | jq
```

## Telegram

En `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABCDEF
TELEGRAM_CHAT_ID=123456789
```

Luego prueba desde el panel o con:

```bash
python scripts/test_telegram.py
```

## Docker Compose

```bash
cp .env.example .env
mkdir -p models captures
docker compose build
docker compose up -d
docker logs -f catfinder_pro
```

## Seguridad mínima

Activa contraseña si lo expones por VPN o red compartida:

```env
WEB_PASSWORD=clave_larga
```

No publiques el panel ni RTSP directo a internet. Usa Tailscale, WireGuard o reverse proxy con HTTPS.
