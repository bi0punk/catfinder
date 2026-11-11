# Despliegue

Tres formas soportadas: Docker Compose (recomendada), imagen publicada en GHCR y
systemd en Linux nativo con entorno virtual.

> Las imágenes publicadas usan **Python 3.15**. Para el entorno local se recomienda 3.12 (el CI prueba 3.11 y 3.12).

## 1. Docker Compose

```bash
git clone https://github.com/bi0punk/catfinder.git
cd catfinder
cp .env.example .env
mkdir -p models captures config
# edita .env: RTSP_URLS, WEB_PASSWORD, TELEGRAM_*
docker compose up -d
docker compose logs -f catfinder
```

Comprobaciones:

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
docker inspect --format '{{.State.Health.Status}}' catfinder_pro
```

El contenedor:

- corre como **uid 10001** (`catfinder`), no root;
- usa `init: true` para cosechar procesos de FFmpeg;
- aplica `no-new-privileges`;
- tiene **healthcheck** contra `/health`;
- escucha en `0.0.0.0` dentro del contenedor (mapeado a `127.0.0.1:8080` por
  defecto en compose; cámbialo si lo publicas en la LAN).

Volúmenes:

| Host | Contenedor | Uso |
|---|---|---|
| `./config` | `/app/config` | `cameras.yaml` editable |
| `./captures` | `/app/captures` | Evidencias y `events.jsonl` |
| `./models` | `/app/models` (ro) | Pesos YOLO |

## 2. Imagen publicada (GHCR)

Cada push a `main` publica `ghcr.io/bi0punk/catfinder:latest` y `:main`; los tags
semánticos generan `:X.Y.Z`.

```bash
docker pull ghcr.io/bi0punk/catfinder:latest
docker run -d --name catfinder --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  --env-file .env \
  -v "$PWD/config:/app/config" \
  -v "$PWD/captures:/app/captures" \
  -v "$PWD/models:/app/models:ro" \
  --shm-size=512m \
  --security-opt no-new-privileges:true \
  ghcr.io/bi0punk/catfinder:latest
```

Si el paquete es privado, autentícate primero:

```bash
echo "$GH_TOKEN" | docker login ghcr.io -u bi0punk --password-stdin
```

## 3. systemd (Linux nativo)

```bash
sudo useradd -r -s /usr/sbin/nologin catfinder
sudo mkdir -p /opt/catfinder && sudo chown catfinder: /opt/catfinder
sudo -u catfinder git clone https://github.com/bi0punk/catfinder.git /opt/catfinder
cd /opt/catfinder
sudo -u catfinder python3.12 -m venv .venv
sudo -u catfinder .venv/bin/pip install -e .
sudo -u catfinder cp .env.example .env
```

Unidad de ejemplo (`/etc/systemd/system/catfinder.service`):

```ini
[Unit]
Description=CatFinder RTSP monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=catfinder
Group=catfinder
WorkingDirectory=/opt/catfinder
EnvironmentFile=/opt/catfinder/.env
ExecStart=/opt/catfinder/.venv/bin/python -m app
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/catfinder/captures /opt/catfinder/config

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now catfinder
systemctl status catfinder
```

El `catfinder.service` del repo es una plantilla para usuario; ajústalo a tu ruta.

## Validación antes de desplegar

```bash
python -m app --check
```

Valida `.env`, cámaras, modelo y rutas sin abrir RTSP ni el panel. Úsalo también
en el pipeline antes de reiniciar el servicio.

## Actualización

```bash
git pull --ff-only
docker compose build && docker compose up -d
# o, en systemd:
.venv/bin/pip install -e . && sudo systemctl restart catfinder
```

## Recursos recomendados

| Escenario | CPU | RAM | Notas |
|---|---|---|---|
| 1 cámara 720p, 1 FPS | 1 vCPU | 1 GB | `yolo11n`, `MAX_FRAME_WIDTH=1280` |
| 3 cámaras 1080p, 0.5 FPS | 2 vCPU | 2 GB | `DETECT_FPS=0.5`, substream |
| GPU opcional | — | 2 GB VRAM | `DETECTOR_DEVICE=cuda` |

## Checklist de producción

- [ ] `WEB_PASSWORD` definido (o bind solo a localhost/VPN).
- [ ] `TELEGRAM_ENABLED=true` probado con `/api/telegram/test`.
- [ ] `models/yolo11n.pt` presente y `--check` en verde.
- [ ] `captures/` con retención acorde (`RETENTION_DAYS`).
- [ ] Backup de `config/cameras.yaml` (credenciales).
- [ ] Healthcheck en verde y `restart: unless-stopped`.
- [ ] Logs revisados tras 24 h (`docker compose logs`).
