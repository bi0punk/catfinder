# CatFinder MVP

Proyecto limpio para detectar gatos en cámaras RTSP, dibujar la detección, guardar evidencia y enviar foto por Telegram.

Está diseñado en capas para poder crecer sin convertir el proyecto en un script monolítico:

```text
RTSP Camera
  ↓
CameraWorker / CameraManager
  ↓
YoloDetector
  ↓
Draw + EvidenceStore
  ↓
TelegramNotifier
  ↓
Flask Web/API
```

## Qué hace

1. Lee cámaras RTSP.
2. Detecta gatos con YOLO/Ultralytics.
3. Dibuja caja, etiqueta y fecha sobre el frame.
4. Guarda evidencia en `captures/<camara>/`.
5. Registra eventos en `captures/events.jsonl`.
6. Envía la foto por Telegram si está habilitado.
7. Permite gestionar cámaras desde API y panel web.
8. Evita spam con `COOLDOWN_SECONDS`.

## Estructura

```text
catfinder_mvp/
├── app/
│   ├── camera/          # workers RTSP y manager de cámaras
│   ├── core/            # configuración, logging, utilidades
│   ├── detection/       # YOLO + dibujo
│   ├── domain/          # modelos de datos y estado
│   ├── notifier/        # Telegram
│   ├── storage/         # evidencias, events.jsonl, retención
│   └── web/             # Flask, API y UI
├── config/cameras.yaml
├── captures/
├── models/
├── scripts/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Instalación local en Linux

```bash
unzip catfinder_mvp_YYYYMMDD_HHMMSS.zip
cd catfinder_mvp_YYYYMMDD_HHMMSS
cp .env.example .env
mkdir -p models captures
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Descarga o copia el modelo:

```bash
# opción simple: Ultralytics puede descargarlo automáticamente si hay internet
# o copia un yolo11n.pt ya descargado:
cp /ruta/yolo11n.pt models/yolo11n.pt
```

Configura la cámara en `config/cameras.yaml`:

```yaml
cameras:
  - name: patio
    rtsp_url: rtsp://usuario:password@192.168.1.100:554/Streaming/Channels/102
    enabled: true
    detect_fps: null
    cooldown_seconds: null
    max_frame_width: null
```

Ejecuta:

```bash
python -m app.main
```

Panel:

```text
http://localhost:8080
```

## Configuración Telegram

Edita `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABCDEF
TELEGRAM_CHAT_ID=123456789
```

Prueba:

```bash
source .venv/bin/activate
python scripts/test_telegram.py
```

También puedes probar desde el panel web con el botón `Probar Telegram`.

## Configuración recomendada CPU-only

Para una máquina sin GPU:

```env
MODEL_PATH=models/yolo11n.pt
TARGET_CLASSES=cat
CONFIDENCE_THRESHOLD=0.45
INFER_IMGSZ=416
DETECT_FPS=1.0
COOLDOWN_SECONDS=60
MAX_FRAME_WIDTH=960
JPEG_QUALITY=75
OPENCV_THREADS=1
OMP_NUM_THREADS=2
MKL_NUM_THREADS=2
TORCH_NUM_THREADS=2
TORCH_INTEROP_THREADS=1
```

Si la CPU sube mucho:

1. Baja `INFER_IMGSZ` a `320`.
2. Baja `DETECT_FPS` a `0.5`.
3. Usa substream RTSP, por ejemplo Hikvision/Ezviz `Streaming/Channels/102`.
4. Mantén `MAX_FRAME_WIDTH=960` o menor.

## API principal

```text
GET  /health
GET  /ready
GET  /api/status
GET  /api/events
GET  /api/logs
GET  /api/cameras
POST /api/cameras
PUT  /api/cameras/<name>
DELETE /api/cameras/<name>
POST /api/cameras/<name>/restart
GET  /stream/<name>
GET  /captures/<path>
POST /api/telegram/test
```

Agregar cámara por API:

```bash
curl -s -X POST http://localhost:8080/api/cameras \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"patio",
    "rtsp_url":"rtsp://usuario:password@192.168.1.100:554/Streaming/Channels/102",
    "enabled":true
  }' | jq
```

## Docker Compose

```bash
cp .env.example .env
mkdir -p models captures
# cp /ruta/yolo11n.pt models/yolo11n.pt

docker compose build
docker compose up -d
docker logs -f catfinder_mvp
```

## Seguridad mínima

Activa contraseña para el panel:

```env
WEB_PASSWORD=clave_larga
```

No expongas RTSP ni el panel directo a internet. Usa VPN/Tailscale o reverse proxy con HTTPS.

## Próximas mejoras naturales

1. ROI por cámara para alertar solo en zonas.
2. Horarios de vigilancia.
3. Detección de otros objetos: perros, personas, autos.
4. Base SQLite para eventos.
5. Grabación de clips cortos antes/después de la detección.
6. Prometheus/Grafana para monitoreo.
