# CatFinder — Control de calidad del repo

Bitácora del saneamiento/refactor sobre la rama `dev`.

## Baseline (commit 1)

Entorno: `.venv` (Python 3.13), deps de `requirements.txt` + `requirements-dev.txt`
(pytest, ruff) + herramientas de análisis (mypy, ruff, vulture, bandit, radon, pytest-cov).

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
`ignore_decorators = ["@app.route", "@require_auth"]` (rutas Flask) y
`ignore_names = ["ts_utc"]` (campo real de `EventRecord`).

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