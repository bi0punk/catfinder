# Troubleshooting

Diagnóstico rápido en este orden: **salud → configuración → cámara → modelo →
notificación**.

## 1. El contenedor no queda healthy

```bash
docker compose ps
docker inspect --format '{{json .State.Health}}' catfinder_pro | python -m json.tool
docker compose logs --tail=100 catfinder
```

| Causa | Verificación | Solución |
|---|---|---|
| Puerto ocupado | `ss -ltnp \| grep 8080` | Cambia `WEB_PORT` o el mapeo |
| Falla el arranque por config | `python -m app --check` | Corrige `.env` |
| Modelo no encontrado | logs `YOLO cargado` | Copia el `.pt` a `models/` |
| Permisos de volúmenes | logs `Permission denied` | `chown -R 10001:10001 config captures` |

## 2. `No se pudo abrir RTSP`

```bash
ffplay -rtsp_transport tcp -i "rtsp://user:pass@IP:554/..."
```

| Causa | Solución |
|---|---|
| URL/códec incorrecto | Usa el **substream** (Hikvision `.../102`, Dahua `subtype=1`) |
| Credenciales | Codifica caracteres especiales de la password |
| Red/VPN | Verifica que el contenedor tenga ruta a la cámara |
| Cámara saturó conexiones | Reinicia la cámara o baja `DETECT_FPS` |

## 3. Se conecta y se corta cada X segundos

Sube los timeouts y fuerza TCP:

```env
RTSP_OPEN_TIMEOUT_MS=10000
RTSP_READ_TIMEOUT_MS=10000
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;10000000
```

El worker reconecta con backoff exponencial (`RECONNECT_DELAY_SECONDS` →
`RECONNECT_DELAY_MAX_SECONDS`); revisa que no esté en bucle.

## 4. Detecta en imagen pero no en vivo

1. Panel → **Diagnóstico con imagen**, sube un frame del mismo stream.
2. Prueba `conf=0.20`, `imgsz=640` y **todas las clases**.
3. Si en imagen funciona, el problema es el frame: resolución, IR nocturno,
   ángulo o compresión. Baja `MAX_FRAME_WIDTH` a 960 y prueba.
4. Si sigue igual, cambia a `yolo11s.pt` y `INFER_IMGSZ=960`.

## 5. No detecta nada

| Revisión | Comando/acción |
|---|---|
| ¿La clase existe en el modelo? | `GET /api/detection/classes` |
| ¿`TARGET_CLASSES` bien escrito? | `cat`, no `gato` (hay alias, pero revisa) |
| ¿Confianza muy alta? | `CONFIDENCE_THRESHOLD=0.20` |
| ¿Caja muy chica filtrada? | `MIN_BOX_AREA_RATIO=0.0` |
| ¿Modelo cargado? | `GET /api/status` → `detector.loaded` |

## 6. CPU al 100 % / se cuelga

```env
DETECT_FPS=0.5
MAX_FRAME_WIDTH=960
INFER_IMGSZ=640
OPENCV_THREADS=1
TORCH_NUM_THREADS=2
```

- Usa substream, no el stream principal.
- Con varias cámaras, reparte `DETECT_FPS` (p. ej. 0.5 por cámara).
- En Raspberry Pi, `yolo11n` + 640 es el límite práctico.

## 7. Telegram no envía

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
```

- `TELEGRAM_ENABLED=true`, token y chat presentes.
- El bot debe haber recibido `/start` en ese chat.
- Prueba `POST /api/telegram/test` y revisa `docker compose logs`.
- Si el token estuvo en git, revócalo en @BotFather.

## 8. Panel accesible sin contraseña

Define `WEB_PASSWORD` y reinicia. Si lo publicas fuera de localhost, además:

- bind a `127.0.0.1` y accede por túnel SSH/Tailscale, o
- reverse proxy con HTTPS y auth.

## 9. `Permission denied` en captures/models

El contenedor corre como uid 10001:

```bash
sudo chown -R 10001:10001 captures config models
```

## 10. Tests o CI en rojo

```bash
uv venv --python 3.12
uv pip install --no-deps -e .
uv pip install flask python-dotenv PyYAML requests "numpy>=1.24,<3" \
  opencv-python-headless pytest pytest-cov ruff mypy vulture bandit
ruff check . && mypy app && pytest -q
```

Los errores más comunes son de entorno (PEP 668 en runners) y se resuelven
creando el `venv`; el workflow ya lo hace.

## Recoger un diagnóstico

```bash
python -m app --check
curl -fsS localhost:8080/ready | python -m json.tool
docker compose logs --tail=200 catfinder > catfinder.log
```

Adjunta `catfinder.log`, la salida de `/ready` y la versión instalada
(`python -m pip show catfinder | head -3`) al abrir un issue.
