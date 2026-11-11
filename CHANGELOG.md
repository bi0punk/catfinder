# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y
versionado [SemVer](https://semver.org/lang/es/).

## [1.0.0] - 2026-11-11

Primera versión pensada para uso y despliegue reales.

### Añadido

- Modo `python -m app --check` para validar configuración, cámaras, modelo y
  rutas sin abrir RTSP ni el panel.
- Entrada `python -m app` además de `python -m app.main`.
- Inyección de fábrica de modelo en `YoloDetector` para testear el parseo sin
  instalar Ultralytics.
- Endpoint de salud consumido por el `HEALTHCHECK` del contenedor.
- Imagen Docker multi-stage, usuario sin privilegios (uid 10001) y publicación
  automática en GHCR.
- Job de auditoría de dependencias (`pip-audit`) y matriz de tests 3.11/3.12.
- Dependabot para pip, GitHub Actions y Docker.
- Plantillas de issue/PR y guía de contribución.
- Documentación: configuración, despliegue, troubleshooting y política de
  seguridad.

### Cambiado

- El CI crea un entorno virtual por job y cachea `uv`. Antes instalaba contra el
  Python del runner (externally-managed, PEP 668) y todos los jobs fallaban.
- `docker-compose.yml` usa healthcheck, `init`, `no-new-privileges` y referencia
  la imagen publicada.
- El README se reescribe con arquitectura, API, perfiles CPU/GPU y operación.
- El paquete se distribuye con `py.typed`.

### Corregido

- El build de Docker fallaba: `.dockerignore` excluía `README.md` y el
  `COPY config` apuntaba a un directorio inexistente.
- `main()` devolvía `None`; ahora devuelve código de salida y es testeable.
- Se documentaba `PROCESS_EVERY_N_FRAMES`, que no existía en el código.

### Seguridad

- Contenedor sin root y con `no-new-privileges`.
- Auditoría de dependencias en CI.
- `SECURITY.md` con alcance y rotación de secretos.

## [0.1.0] - 2026-10-12

- Detección cat-focused con YOLO, overlay y persistencia de cajas.
- Panel web con stream MJPEG, API REST y diagnóstico por imagen.
- Evidencias JPG + `events.jsonl` con retención.
- Alertas por Telegram con cola y cooldown.
- Perfil CPU-only y configuración por dominios.
