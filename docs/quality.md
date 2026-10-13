# CatFinder — Control de calidad del repo

Bitácora del saneamiento/refactor sobre la rama `dev`.

## Baseline (commit 1)

Entorno: `.venv` (Python 3.13), deps runtime + extra `dev` declaradas en `pyproject.toml`.

### Estado inicial

| Chequeo | Resultado | Detalles |
| --- | --- | --- |
| `pytest -q` | 8 tests, **2 fallos** | `test_no_tracked_yolo_weights` y `test_gitignore_excludes_models` fallaban |
| `ruff check .` | Verde | tras configurar `[tool.ruff]` (E,F,I,UP,B,SIM,ARG,C4) |
| `mypy app` | Verde | config `[tool.mypy]` en `pyproject.toml`; se eliminaron 2 `type: ignore` huérfanos |
| Cobertura inicial | **16%** (999/1189 líneas sin cubrir) | `pytest --cov=app` |

### Hallazgos de higiene corregidos en baseline

- `models/yolo11n.pt` y `car.zip` estaban **trackeados** pese a `.gitignore`
  (`*.pt`, `*.zip`): `git rm --cached`. Se añadió `models/*.pt` explícito.
- `.coverage`/`.mypy_cache/`/`htmlcov/` se ignoran.
- `config/cameras.yaml` pasa a estar **sin seguimiento** (archivo runtime que el propio
  manager reescribe y puede contener credenciales en las URLs RTSP).

-> Siguiente: hallazgos de vulture/bandit/radon en `docs/quality.md` (commit de búsqueda).

## Búsqueda con vulture / bandit / radon (commit 2)

Herramientas: `vulture 2.16`, `bandit 1.9.x`, `radon 6.x`.

### vulture (`vulture app scripts`, min_confidence=60)

Falsos positivos neutralizados en `[tool.vulture]` de `pyproject.toml` con
`ignore_decorators = ["@app.route", "@bp.route", "@require_auth"]` (rutas Flask) y
`ignore_names = ["ts_utc", "runtime"]` (campos reales consumidos por el framework/delegación).

Código muerto real detectado (eliminado en el commit de código muerto):

- `app/core/utils.py:89` — `clamp()` (sin usos).
- `app/detection/draw.py:115` — `draw_no_detection()` (sin usos).
- `app/notifier/telegram.py:28` — `TelegramNotifier.configure()` (sin llamadas).

### bandit (`bandit -r app scripts`)

1 hallazgo **Low**:

- `B110 try/except/pass` en `app/core/utils.py:72` (`redact_url`). Es un `except: pass`
  de fallback; se refactoriza en hardening para no silenciar excepciones.

No hay issues Medium/High. No se detectan secretos hardcodeados en código; el acceso a
bot token / password se hace vía env (`os.getenv`) y `public_dict()` no los expone.

### radon (`radon cc app -s`, `radon mi app -s`)

- Complejidad media general: **A** (2.98).
- `load_app_config` es la más compleja: **C (15)** -> justifica la división de config.
- Mantenibilidad más baja: `app/web/server.py` (**A 29.36**) -> justifica extraer blueprints.
- `load_cameras_file` C (12) y `_parse_rtsp_urls` B (7) -> se conservan en el módulo de
  cámaras de config tras dividir.

## Modularización y desacoplamiento (commits 4–7)

- `app/core/config.py` (249 L) -> paquete `app/core/config/` por dominios
  (`camera`, `detection`, `storage`, `notifier`, `web`, `runtime`) con
  `AppConfig` agrupando sub-configs y API plana retrocompatible; carga única
  `load_app_config()` / `load_settings()`.
- `app/web/server.py` (259 L) -> `create_web_app` como wiring (~35 L) +
  `app/web/context.py` (WebContext) + blueprints `public`, `ui`, `api`.
- `app/detection/yolo_detector.py` -> interfaz `Detector.detect(frame)`
  (`app/detection/base.py`) implementada por `YoloDetector`. El dibujo sigue
  centralizado en `app/detection/draw.py` (sin duplicar).
- Capas: `camera`/`detection`/`storage`/`notifier` no importan `app.web`.
  Se agrega `tests/test_architecture.py` para bloquear regresiones.

## Cobertura de tests (commit 8)

Nuevos módulos de test (pytest, sin cargar YOLO ni abrir RTSP):

- `tests/conftest.py` — fixtures `clean_env`/`cfg` (env aislado + `PROJECT_ROOT` temporal).
- `tests/test_models.py` — `CameraConfig`, `Detection`, `EventRecord`, `CameraRuntimeState`, `AppState`.
- `tests/test_storage.py` — `EvidenceStore` (guardado, append jsonl, retención) y `RetentionThread`.
- `tests/test_notifier.py` — `TelegramNotifier` con `requests.post` mockeado (cola, envío, errores).
- `tests/test_config_settings.py` — defaults, clamps, Telegram, RTSP_URLS, rutas y `public_dict` sin secretos.
- `tests/test_draw.py` — split, resize, encode JPEG, dibujo/overlay.
- `tests/test_detector.py` — `Detector`/`YoloDetector.status`, `update_runtime_params`; `UILogHandler`.
- `tests/test_web.py` — Flask `TestClient`: health/ready, index, API, cámaras, auth básica, captures.

| Métrica | Baseline | Final |
| --- | --- | --- |
| Tests | 8 (2 fallos) | **63 (0 fallos)** |
| Cobertura `app` | **16%** | **67%** |
| Líneas sin cubrir | 999 | 399 |