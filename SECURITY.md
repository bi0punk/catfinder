# Política de seguridad

## Versiones soportadas

| Versión | Soporte |
|---|---|
| 1.x | Sí (rama `main`) |
| < 1.0 | No |

## Cómo reportar una vulnerabilidad

Usa **GitHub Security Advisories** (pestaña *Security* → *Report a vulnerability*)
o abre un issue privado si el repositorio lo permite. No publiques detalles
explotables en un issue público.

Incluye:

- versión o commit afectado;
- pasos de reproducción;
- impacto (lectura de credenciales, bypass de auth, RCE, DoS…);
- configuración relevante (sin incluir tokens ni contraseñas reales).

Objetivo de respuesta: acuse en 72 h y parche o mitigación en 14 días para
vulnerabilidades confirmadas.

## Alcance

Se consideran vulnerabilidades:

- bypass de `WEB_PASSWORD` o exposición de la API sin autenticación;
- inyección de comandos en scripts (`scripts/`) o en rutas de modelo;
- lectura de `.env`, `config/cameras.yaml` o evidencias por usuarios no autorizados;
- SSRF hacia la red interna a través de URLs RTSP configurables;
- dependencias con CVE conocidos en el entorno de ejecución.

Fuera de alcance:

- acceso físico a las cámaras o a la red donde corre el servicio;
- vulnerabilidades en Ultralytics/OpenCV sin un vector propio de CatFinder;
- despliegues que exponen el panel a internet sin contraseña ni proxy.

## Recomendaciones de despliegue

- `WEB_HOST=127.0.0.1` por defecto; si publicas en LAN, define `WEB_PASSWORD`.
- No expongas RTSP directamente a internet; usa VPN o reverse proxy con TLS.
- Rota el token de Telegram si estuvo en un commit o log.
- Ejecuta el contenedor como usuario sin privilegios (ya es uid 10001).
- Mantén las dependencias al día: Dependabot + `pip-audit` en CI.

## Manejo de secretos

`.env` y `config/cameras.yaml` están en `.gitignore`. Si un secreto se filtró:

1. Rótalo en el origen (BotFather, cámara, etc.).
2. Elimínalo del historial (`git filter-repo`) y fuerza el push coordinado.
3. Verifica que no quede en logs, issues ni artefactos de CI.
