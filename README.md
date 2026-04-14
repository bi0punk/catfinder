# CatFinder RTSP Monitor – v2

Sistema de vigilancia con detección de objetos YOLO sobre streams RTSP,
alertas Telegram y panel web en tiempo real.

## Qué hay de nuevo en v2

| Área | Mejora |
|------|--------|
| **Telegram** | Asíncrono (cola no bloqueante) y completamente **opcional** |
| **Frontend** | Auto-refresh cada 3 s sin recargar página |
| **Frontend** | Tabla de eventos con thumbnails + modal de imagen |
| **Frontend** | Toast de notificación en nuevas detecciones |
| **Frontend** | Botón fullscreen por stream |
| **Frontend** | Toggle anotado/crudo por vista |
| **Frontend** | Barra de estadísticas global en tiempo real |
| **Backend** | Nuevo endpoint `/stream/raw/<view_id>` |
| **Backend** | Nuevo endpoint `/api/events?page=N&page_size=M` |
| **Backend** | Nuevo endpoint `/captures/<path>` para servir imágenes |
| **Backend** | Soporte de **ROI por vista** (`CAMERA_ROIS`) |
| **Backend** | `LOG_LEVEL` configurable en `.env` |
| **Backend** | `TELEGRAM_ENABLED` toggle explícito |
| **Backend** | Puerto por defecto corregido a `8080` en código y `.env` |
| **Backend** | `ViewConfig` reutilizado en lugar de recrearse por frame |
| **Backend** | Recuento de detecciones acumulado por vista |
| **Infra** | `Dockerfile` incluido |
| **Infra** | `catfinder.service` (systemd) incluido |

## Arquitectura

```text
RTSP camera
  └─> OpenCV VideoCapture
        └─> split opcional (none / vertical / horizontal)
              ├─> vista 1  ─> YOLO inference ─> ROI filter
              └─> vista 2  ─> YOLO inference ─> ROI filter
                                   │
                    ┌──────────────┼──────────────────┐
                    ▼              ▼                   ▼
              guardar JPG   Telegram (async)     Flask MJPEG
              + JSON        notifier             + API + UI
```

## Instalación rápida

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp example.env .env
# edita .env
python src/main.py
```

Abre `http://127.0.0.1:8080` en el navegador.

## Variables de entorno clave

### Cámaras

```env
RTSP_URLS=patio=rtsp://usuario:clave@192.168.1.50:554/stream1
CAMERA_SPLITS=patio=vertical       # none | vertical | horizontal
CAMERA_SPLIT_RATIOS=patio=0.5
```

### ROI por vista (nuevo en v2)

Filtra detecciones fuera del área definida. Las coordenadas son
píxeles relativos a la vista (después del split).

```env
# Formato: viewid=x1:y1:x2:y2
CAMERA_ROIS=patio__left=0:100:640:480,patio__right=50:0:620:480
```

### Telegram (ahora opcional)

```env
TELEGRAM_ENABLED=true   # false para deshabilitar sin errores
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### Log

```env
LOG_LEVEL=INFO   # DEBUG | INFO | WARNING | ERROR
```

## Endpoints API

| Endpoint | Descripción |
|----------|-------------|
| `GET /` | Panel web |
| `GET /stream/<view_id>` | Stream MJPEG anotado |
| `GET /stream/raw/<view_id>` | Stream MJPEG sin anotaciones *(nuevo)* |
| `GET /api/status` | JSON completo de estado |
| `GET /api/events?page=0&page_size=50` | Lista de eventos paginada *(nuevo)* |
| `GET /captures/<path>` | Imagen de captura guardada *(nuevo)* |
| `GET /health` | Health check |

## Docker

```bash
docker build -t catfinder .
docker run --env-file .env -p 8080:8080 -v $(pwd)/captures:/app/captures catfinder
```

## systemd

```bash
sudo cp catfinder.service /etc/systemd/system/
# Edita User= y WorkingDirectory= en el archivo
sudo systemctl daemon-reload
sudo systemctl enable --now catfinder
sudo journalctl -u catfinder -f
```

## Archivos generados

```text
captures/
  patio/
    20260413_120010_left_raw.jpg
    20260413_120010_left_alert.jpg
    20260413_120010_left.json
```

## Seguridad

- Los tokens Telegram no aparecen en logs.
- El endpoint `/captures/` valida que la ruta esté dentro de `SAVE_DIR` (no path traversal).
- Para exponer al exterior usa un reverse proxy (Nginx/Caddy) con autenticación básica.
