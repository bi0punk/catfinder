# Configuración

CatFinder se configura con variables de entorno. El orden de carga es:

1. Variables ya exportadas en el proceso.
2. Archivo `.env` en la raíz del proyecto (vía `python-dotenv`).
3. Valores por defecto del código.

Las cámaras pueden venir de `RTSP_URLS` o de `CAMERAS_FILE` (YAML). Si existen
ambas, se combinan; el panel web permite editar el YAML en caliente.

## Cámaras

| Variable | Default | Descripción |
|---|---|---|
| `RTSP_URLS` | vacío | Lista `nombre=rtsp://…,nombre2=rtsp://…` |
| `CAMERAS_FILE` | `config/cameras.yaml` | Ruta del YAML de cámaras |
| `CAMERA_SPLITS` | `none` | `none`, `vertical` u `horizontal` por vista |
| `CAMERA_ROIS` | vacío | Regiones de interés `vista=x1:y1:x2:y2` |

Formato del YAML:

```yaml
cameras:
  - name: patio
    rtsp_url: rtsp://user:pass@192.168.1.100:554/Streaming/Channels/102
    enabled: true
    detect_fps: 1.0        # opcional, sobreescribe el global
    cooldown_seconds: 60   # opcional
    max_frame_width: 1280  # opcional
    split_mode: none
```

El nombre solo admite letras, números, `-` y `_`. La URL debe empezar por
`rtsp://`; si no, la cámara se ignora con un warning.

## Detección

| Variable | Default | Rango | Descripción |
|---|---|---|---|
| `MODEL_PATH` | `models/yolo11n.pt` | — | Pesos YOLO (se descargan si faltan) |
| `TARGET_CLASSES` | `cat` | — | Clases separadas por coma (`cat,dog`) |
| `CONFIDENCE_THRESHOLD` | `0.25` | 0.01–0.99 | Umbral de confianza |
| `INFER_IMGSZ` | `640` | 256–1536 | Tamaño de inferencia |
| `DETECT_FPS` | `1.0` | 0.1–10 | Inferencias por segundo y cámara |
| `COOLDOWN_SECONDS` | `60` | ≥0 | Espera entre alertas del mismo evento |
| `DRAW_BOXES` | `true` | — | Dibujar cajas en el stream |
| `BOX_PERSIST_SECONDS` | `2.5` | 0–10 | Persistencia visual de la última caja |
| `MIN_BOX_AREA_RATIO` | `0.0` | 0–0.5 | Área mínima de caja respecto al frame |
| `DETECTOR_DEVICE` | `cpu` | — | `cpu`, `cuda`, `mps`… |
| `MAX_FRAME_WIDTH` | `1280` | ≥0 | Redimensiona antes de inferir (0 = sin límite) |
| `JPEG_QUALITY` | `75` | 40–95 | Calidad del stream/evidencias |

Los valores fuera de rango se recortan al límite, no fallan.

## RTSP y reconexión

| Variable | Default | Descripción |
|---|---|---|
| `RTSP_OPEN_TIMEOUT_MS` | `5000` | Timeout de apertura (mín. 1000) |
| `RTSP_READ_TIMEOUT_MS` | `5000` | Timeout de lectura (mín. 1000) |
| `RTSP_BUFFER_SIZE` | `1` | Buffer de OpenCV; 1 reduce latencia |
| `RECONNECT_DELAY_SECONDS` | `5` | Espera inicial entre reconexiones |
| `RECONNECT_DELAY_MAX_SECONDS` | `60` | Tope del backoff |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | `rtsp_transport;tcp\|…` | Opciones de FFmpeg |

## Recursos

Útiles en CPU: limitan BLAS/OpenCV/Torch y evitan que un worker se coma la máquina.

```env
OPENCV_THREADS=1
OMP_NUM_THREADS=2
MKL_NUM_THREADS=2
NUMEXPR_NUM_THREADS=2
TORCH_NUM_THREADS=2
TORCH_INTEROP_THREADS=1
```

## Evidencias

| Variable | Default | Descripción |
|---|---|---|
| `SAVE_DIR` | `captures` | Carpeta de JPG y `events.jsonl` |
| `EVENTS_JSONL` | `<SAVE_DIR>/events.jsonl` | Log de eventos |
| `RETENTION_DAYS` | `14` | Días de retención (0 = no borrar) |
| `MAX_EVENTS_MEMORY` | `200` | Eventos en memoria para la UI (mín. 10) |

## Telegram

| Variable | Default | Descripción |
|---|---|---|
| `TELEGRAM_ENABLED` | `false` | Activa notificaciones |
| `TELEGRAM_BOT_TOKEN` | vacío | Token de @BotFather |
| `TELEGRAM_CHAT_ID` | vacío | Chat o grupo destino |
| `REQUEST_TIMEOUT_SECONDS` | `20` | Timeout HTTP (mín. 2) |
| `TELEGRAM_QUEUE_SIZE` | `50` | Cola de mensajes (mín. 1) |

Si `TELEGRAM_ENABLED=true` y falta token o chat, el notificador se desactiva
con un warning (no rompe el arranque).

## Web

| Variable | Default | Descripción |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | Bind del panel |
| `WEB_PORT` | `8080` | Puerto |
| `WEB_TITLE` | `CatFinder MVP` | Título mostrado |
| `WEB_PASSWORD` | vacío | Basic auth del panel/API |

> Si usas `WEB_HOST=0.0.0.0`, **define `WEB_PASSWORD`** o restringe el acceso por red.

## Logs

| Variable | Default | Descripción |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Perfiles listos para copiar

### CPU modesta (Raspberry Pi 4/5, mini PC)

```env
CONFIDENCE_THRESHOLD=0.25
INFER_IMGSZ=640
DETECT_FPS=1.0
MAX_FRAME_WIDTH=1280
OPENCV_THREADS=1
TORCH_NUM_THREADS=2
```

### Varias cámaras

```env
RTSP_URLS=patio=rtsp://…/102,garage=rtsp://…/102,porton=rtsp://…/102
DETECT_FPS=0.5
MAX_FRAME_WIDTH=960
```

### GPU

```env
DETECTOR_DEVICE=cuda
INFER_IMGSZ=960
DETECT_FPS=5
```
