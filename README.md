# MVP RTSP + YOLO + Telegram para detectar gatos

Base mínima pero lista para ejecutar en Linux. Hace esto:

1. Se conecta a una o varias cámaras RTSP.
2. Ejecuta detección con YOLO.
3. Si detecta un `cat`, guarda captura cruda y captura anotada.
4. Envía la imagen anotada por Telegram.
5. Aplica cooldown por cámara para evitar spam.
6. Reintenta si la cámara RTSP se cae.

## Arquitectura rápida

```text
RTSP camera(s)
   -> OpenCV VideoCapture
      -> YOLO inference
         -> filtro por clase "cat"
            -> guardar JPG + JSON
               -> sendPhoto a Telegram
```

## Requisitos

- Linux
- Python 3.10+
- FFmpeg disponible en el sistema es recomendable para RTSP estable

## Instalación

```bash
cd cat_rtsp_telegram_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Ahora edita `.env` con tus datos reales.

## Cómo obtener el token y chat_id de Telegram

### 1) Crear bot
- Habla con `@BotFather` en Telegram.
- Crea el bot y copia el token.

### 2) Obtener chat_id
Una forma simple es escribirle un mensaje a tu bot y luego ejecutar:

```bash
curl "https://api.telegram.org/bot<TU_TOKEN>/getUpdates"
```

Busca el campo `chat.id` del chat donde quieres recibir alertas.

## Ejecución

```bash
source .venv/bin/activate
python src/main.py
```

## Variables importantes

```env
RTSP_URLS=patio=rtsp://usuario:clave@192.168.1.50:554/stream1,entrada=rtsp://usuario:clave@192.168.1.51:554/stream1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
MODEL_PATH=yolo11n.pt
TARGET_CLASSES=cat
CONFIDENCE_THRESHOLD=0.55
COOLDOWN_SECONDS=60
PROCESS_EVERY_N_FRAMES=5
```

## Salida del proyecto

Las capturas quedan en:

```text
captures/
  cam_1/
    20260412_120010_raw.jpg
    20260412_120010_alert.jpg
    20260412_120010.json
```

El JSON contiene:
- cámara
- etiqueta detectada
- confianza
- timestamp UTC
- bbox
- lista de detecciones de ese evento

## Ajustes recomendados

### Opción simple
- `MODEL_PATH=yolo11n.pt`
- `PROCESS_EVERY_N_FRAMES=5`
- `CONFIDENCE_THRESHOLD=0.55`
- CPU o GPU ligera

### Opción más robusta
- `MODEL_PATH=yolo11s.pt` o un modelo custom entrenado con tus cámaras
- recorte por ROI antes de inferencia
- tracking para evitar alertas duplicadas
- cola asíncrona para Telegram
- servicio `systemd`
- dashboard web con timeline de eventos

## Cuellos de botella reales

1. **RTSP inestable**: muchas cámaras baratas cortan frames o introducen latencia.
2. **Falsos positivos**: con gato funciona, pero depende mucho del ángulo, luz y distancia.
3. **CPU**: varias cámaras + modelo grande saturan rápido.
4. **Spam de alertas**: por eso ya dejé cooldown por cámara.

## Siguiente mejora natural

- Agregar ROI por cámara para no analizar toda la escena.
- Crear modo `snapshot_on_track` para avisar una sola vez por evento.
- Entrenar modelo custom si tus cámaras son nocturnas o muy gran angular.
- Añadir interfaz web Flask para ver eventos, logs y estado RTSP.

## Notas

- El modelo preentrenado debe reconocer la clase `cat`.
- En la primera ejecución, Ultralytics puede descargar el modelo si no existe localmente.
- Si tu OpenCV no abre RTSP con `CAP_FFMPEG`, revisa que el build tenga soporte FFmpeg/GStreamer.
