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