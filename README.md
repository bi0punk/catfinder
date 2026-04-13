# CatFinder RTSP Web MVP

MVP listo para Linux que hace esto:

1. Se conecta a una o varias cámaras RTSP.
2. Detecta gatos con YOLO.
3. Envía alertas con imagen por Telegram.
4. Guarda captura cruda, captura anotada y metadatos JSON.
5. Expone una interfaz web simple con Bootstrap.
6. Soporta cámaras de doble lente o streams compuestos con corte **vertical** u **horizontal**.

## Qué mejora esta versión

Además del detector base, esta versión agrega:

- Vista web en tiempo real por navegador.
- Split de una transmisión en dos vistas separadas.
- Split vertical: izquierda / derecha.
- Split horizontal: superior / inferior.
- Ratio configurable por cámara para mover la línea de corte.
- Panel con eventos recientes y estado por vista.

## Arquitectura

```text
RTSP camera física
   -> OpenCV VideoCapture
      -> split opcional (none / vertical / horizontal)
         -> vista 1
         -> vista 2
            -> YOLO inference por vista
               -> guardar JPG + JSON
               -> sendPhoto a Telegram
               -> publicar MJPEG en Flask
```

## Requisitos

- Linux
- Python 3.10+
- FFmpeg/GStreamer en el sistema ayuda bastante para RTSP

## Instalación

```bash
cd catfinder_web_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp example.env .env
```

Después edita `.env`.

## Variables clave

### 1) Cámara RTSP

```env
RTSP_URLS=patio=rtsp://usuario:clave@192.168.1.50:554/stream1
```

También puedes poner varias:

```env
RTSP_URLS=patio=rtsp://ip1/stream1,entrada=rtsp://ip2/stream1
```

### 2) Telegram

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### 3) Split de cámara doble lente

Ejemplo vertical:

```env
CAMERA_SPLITS=patio=vertical
CAMERA_SPLIT_RATIOS=patio=0.5
```

Eso crea dos vistas web y dos canales lógicos de detección:

- `patio / izquierda`
- `patio / derecha`

Ejemplo horizontal:

```env
CAMERA_SPLITS=patio=horizontal
CAMERA_SPLIT_RATIOS=patio=0.5
```

Eso crea:

- `patio / superior`
- `patio / inferior`

### 4) Web

```env
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

## Ejecución

```bash
source .venv/bin/activate
python src/main.py
```

Luego abre en el navegador:

```text
http://IP_DE_TU_EQUIPO:8080
```

Si lo ejecutas en la misma máquina:

```text
http://127.0.0.1:8080
```

## Archivos generados

```text
captures/
  patio/
    20260413_120010_left_raw.jpg
    20260413_120010_left_alert.jpg
    20260413_120010_left.json
```

El JSON guarda:

- cámara física
- vista lógica
- tipo de split
- bbox
- confianza
- timestamp UTC/local
- ruta de archivos

## Cómo usar el split correctamente

### Caso 1: cámara normal
Usa:

```env
CAMERA_SPLITS=patio=none
```

### Caso 2: stream con dos lentes lado a lado
Usa:

```env
CAMERA_SPLITS=patio=vertical
CAMERA_SPLIT_RATIOS=patio=0.5
```

### Caso 3: stream con una imagen arriba y otra abajo
Usa:

```env
CAMERA_SPLITS=patio=horizontal
CAMERA_SPLIT_RATIOS=patio=0.5
```

### Caso 4: la línea de corte no está al centro
Ajusta el ratio. Ejemplo:

```env
CAMERA_SPLIT_RATIOS=patio=0.47
```

Con eso cortas al 47% del ancho o alto, según el modo.

## Rendimiento real

### Opción simple
- `MODEL_PATH=yolo11n.pt`
- `PROCESS_EVERY_N_FRAMES=5`
- 1 a 3 cámaras en CPU razonable

### Opción más robusta
- GPU NVIDIA con CUDA
- `yolo11s.pt` o modelo custom
- tracking para evitar duplicados
- ROI por vista
- servicio `systemd`
- reverse proxy con Nginx

## Cuellos de botella

1. RTSP inestable o con buffering alto.
2. Streams dobles en alta resolución consumen más CPU.
3. MJPEG web también consume CPU porque codifica JPEG constantemente.
4. El split ayuda, pero duplica vistas lógicas si una cámara se parte en dos.

## Próxima mejora recomendada

La siguiente iteración natural sería:

- definir ROI por cada mitad
- grabar clips cortos además de fotos
- panel con logs en vivo
- filtros por cámara y exportación de eventos
- ejecutar como servicio Linux

## Seguridad

Si un token de Telegram quedó expuesto en consola o capturas, regénéralo en `@BotFather` antes de usar este proyecto en serio.
