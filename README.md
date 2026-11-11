# CatFinder PRO

Monitor de cámaras RTSP con detección de gatos en tiempo real (YOLO), panel web,
evidencias y alertas por Telegram. Pensado para correr en CPU, en una Raspberry Pi
o en cualquier servidor Linux sin GPU.

[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fbi0punk%2Fcatfinder-2496ED?logo=docker)](https://github.com/bi0punk/catfinder/pkgs/container/catfinder)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-76%25-brightgreen.svg)](#calidad)

## Qué resuelve

Tienes una o varias cámaras IP y quieres saber cuándo aparece tu gato, no recibir
una notificación por cada movimiento. CatFinder:

- Lee los streams RTSP y detecta **solo las clases que le indiques** (`cat` por defecto).
- Dibuja las cajas sobre el video en vivo y guarda la evidencia en disco.
- Envía una alerta a Telegram con la imagen, respetando un *cooldown* por evento.
- Expone un panel web y una API REST para operarlo sin tocar archivos.
- Funciona sin GPU: `yolo11n` en CPU con límites de hilos y FPS configurables.

## Arquitectura

```mermaid
flowchart LR
    CAM[Cámaras RTSP] --> W[CameraWorker<br/>captura + reconexión]
    W --> Q[Cola acotada]
    Q --> D[YoloDetector<br/>ultralytics]
    D --> O[Overlay<br/>bounding boxes]
    O --> S[Stream MJPEG]
    O --> E[EvidenceStore<br/>JPG + events.jsonl]
    O --> N[TelegramNotifier<br/>cola + cooldown]
    C[AppConfig<br/>.env + cameras.yaml] --> W
    C --> D
    C --> S
```

| Capa | Módulo | Responsabilidad |
|---|---|---|
| Captura | `app/camera` | Abrir RTSP, reconectar, limitar FPS, repartir frames |
| Dominio | `app/domain` | `Detection`, `AppState`, eventos |
| Detección | `app/detection` | Cargar YOLO, inferir, dibujar cajas |
| Almacenamiento | `app/storage` | Evidencias, JSONL, retención |
| Notificación | `app/notifier` | Telegram con cola y reintentos |
| Web | `app/web` | Flask, API REST, MJPEG, diagnóstico |
| Config | `app/core/config` | `.env` + YAML validado por dominio |

Cada capa depende de interfaces (`Detector`) y de `AppConfig`; no hay imports
circulares ni estado global. El detector acepta una **fábrica de modelo**
inyectable, lo que permite testear el parseo sin instalar Ultralytics.

## Stack

- **Python 3.11+**, tipado y verificado con `mypy`.
- **Flask** para el panel y la API.
- **Ultralytics YOLO** (import perezoso) + **OpenCV headless**.
- **pytest** (70+ tests), **ruff**, **vulture**, **bandit**, **pip-audit**.
- **Docker multi-stage** con usuario sin privilegios y healthcheck.
- **GitHub Actions**: lint, tipos, dead-code, seguridad, matriz 3.11/3.12,
  auditoría de dependencias y publicación de imagen en GHCR.

## Inicio rápido

### Docker (recomendado)

```bash
cp .env.example .env          # edita RTSP_URLS y, si quieres, Telegram
docker compose up -d
```

Panel: <http://localhost:8080> · Salud: <http://localhost:8080/health>

También puedes usar la imagen publicada:

```bash
docker run --rm -p 8080:8080 --env-file .env \
  -v "$PWD/config:/app/config" -v "$PWD/models:/app/models:ro" \
  ghcr.io/bi0punk/catfinder:latest
```

### Local

```bash
git clone https://github.com/bi0punk/catfinder.git
cd catfinder
cp .env.example .env

uv venv -p 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

python -m app --check        # valida config, rutas y cámaras
python -m app                # arranca panel + workers
```

El modelo `yolo11n.pt` no se versiona: se descarga solo la primera vez, o lo
copias a `models/` y apuntas `MODEL_PATH`.

## Configuración

Todo se configura con variables de entorno (`.env`) y, opcionalmente, con
`config/cameras.yaml` para las cámaras. Tabla completa en
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Mínimo para arrancar:

```env
RTSP_URLS=patio=rtsp://user:pass@192.168.1.100:554/Streaming/Channels/102
TARGET_CLASSES=cat
CONFIDENCE_THRESHOLD=0.25
INFER_IMGSZ=640
DETECT_FPS=1.0
MAX_FRAME_WIDTH=1280
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

Perfil CPU-only (el que usa el proyecto en producción):

```env
TORCH_NUM_THREADS=2
OPENCV_THREADS=1
```

## Uso

1. Abre el panel y comprueba el estado de cada cámara.
2. Si no detecta, usa **Diagnóstico con imagen**: sube un frame y prueba
   `conf=0.20`, `imgsz=640` y "todas las clases".
3. Ajusta `DETECT_FPS` (1–2 en CPU) y `MAX_FRAME_WIDTH` (1280) hasta que el
   consumo sea estable.
4. Activa Telegram cuando la detección sea fiable.

### API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Liveness (sin auth) |
| GET | `/ready` | Cámaras online, detector y Telegram |
| GET | `/api/status` | Estado agregado |
| GET | `/api/events` | Últimos eventos |
| GET | `/api/logs` | Logs en memoria para la UI |
| GET/PUT | `/api/detection` | Parámetros en caliente |
| GET | `/api/detection/classes` | Clases disponibles en el modelo |
| POST | `/api/detection/test-image` | Inferencia sobre una imagen |
| GET/POST | `/api/cameras` | Listar / agregar cámaras |
| PUT/DELETE | `/api/cameras/<name>` | Editar / eliminar |
| POST | `/api/cameras/<name>/restart` | Reiniciar worker |
| GET | `/stream/<name>` | Stream MJPEG |
| POST | `/api/telegram/test` | Probar notificación |

Si defines `WEB_PASSWORD`, el panel y la API piden autenticación básica.

## Calidad

```bash
ruff check . && mypy app && vulture app scripts
bandit -q -r app scripts
pytest --cov=app --cov-report=term-missing --cov-fail-under=60
```

Cobertura actual: **76 %** (gate 60 %). Los tests no descargan Ultralytics:
el detector se prueba con un doble inyectado, y el resto usa `tmp_path` y
`monkeypatch` para aislar `.env`, cámara y red.

## CI/CD

GitHub solo aloja el código. La integración continua y el despliegue se
ejecutan en GitLab/entorno local; los workflows de `.github/` están
deshabilitados en GitHub. La validación es la de la sección anterior.

## Despliegue

- **Compose / Docker**: ver [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- **systemd**: `catfinder.service` incluido (ajusta `WorkingDirectory` y usuario).
- **Imagen**: `ghcr.io/bi0punk/catfinder:latest`.
- El contenedor corre como uid 10001, con `no-new-privileges` y healthcheck
  contra `/health`.

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `No se pudo abrir RTSP` | URL, credenciales o códec | Prueba con `ffplay`; usa el substream |
| Se corta cada X segundos | Timeout de lectura | Sube `RTSP_READ_TIMEOUT_MS` |
| CPU al 100 % | FPS/imgsz altos | `DETECT_FPS=1`, `INFER_IMGSZ=640`, `MAX_FRAME_WIDTH=1280` |
| No detecta de noche | Confianza alta | `CONFIDENCE_THRESHOLD=0.20` y `yolo11s.pt` |
| Telegram no envía | Token/chat inválido | `POST /api/telegram/test` y revisa logs |
| Panel sin auth | `WEB_PASSWORD` vacío | Define password o restringe por red |

Más en [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Estructura

```
catfinder/
├── app/
│   ├── __main__.py          # python -m app
│   ├── main.py              # arranque, señales, --check
│   ├── camera/              # manager + worker RTSP
│   ├── core/                # config por dominio, logging, utils
│   ├── detection/           # Detector, YoloDetector, overlay
│   ├── domain/              # modelos de dominio
│   ├── notifier/            # Telegram
│   ├── storage/             # evidencias + retención
│   └── web/                 # Flask, blueprints, templates
├── config/                  # cameras.yaml (gitignored)
├── docs/                    # configuración, despliegue, troubleshooting
├── models/                  # pesos (gitignored)
├── scripts/                 # utilidades de operación
├── tests/                   # 70+ tests
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Seguridad

- `.env` y `config/cameras.yaml` contienen credenciales: están en `.gitignore`.
- Define `WEB_PASSWORD` si el panel sale de `localhost`.
- No expongas RTSP a internet: usa Tailscale/WireGuard o un reverse proxy HTTPS.
- Dependencias auditadas con `pip-audit` en CI.
- Si un token de Telegram estuvo en un commit antiguo, revócalo en @BotFather.

## Roadmap

- [x] Detección cat-focused con overlay
- [x] Panel, evidencias y Telegram
- [x] Docker multi-stage, healthcheck y CI completo
- [ ] Autodetección de substream
- [ ] Soporte multi-modelo por cámara
- [ ] Dashboard histórico de eventos

## Licencia

MIT — ver [LICENSE](LICENSE).
