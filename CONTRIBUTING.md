# Contribuir

Gracias por el interés. El proyecto se mantiene en `dev` y se publica en `main`.

## Entorno

```bash
git clone https://github.com/bi0punk/catfinder.git
cd catfinder
uv venv -p 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

No necesitas descargar Ultralytics para correr los tests: el detector se prueba
con un doble inyectado.

## Flujo de ramas

```
main  ←  PR (merge --no-ff)  ←  dev  ←  feat/* | fix/* | docs/*
```

1. Crea tu rama desde `dev`.
2. Commits atómicos con mensaje convencional.
3. Abre PR contra `dev`. El CI debe quedar en verde.
4. El mantenedor hace merge `--no-ff` a `main` y publica la imagen.

## Commits

Formato: `tipo(alcance): descripción en imperativo`.

Tipos usados: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`.

Ejemplos:

```
feat(web): exponer /ready con estado del detector
fix(camera): no bloquear el hilo al reconectar
docs(deploy): documentar systemd con ProtectSystem
```

## Calidad

Antes de abrir el PR:

```bash
ruff check .
mypy app
vulture app scripts
bandit -q -r app scripts
pytest -q --cov=app --cov-fail-under=60
```

Todos estos comandos corren en CI. Si agregas lógica de detección, usa la
inyección (`YoloDetector(cfg, model_factory=...)`) en vez de cargar pesos reales.

## Tests

- `tests/test_config.py` — carga y límites de configuración.
- `tests/test_detector.py` — parseo, clases objetivo y filtros.
- `tests/test_main.py` — modo `--check`.
- `tests/test_web.py` — endpoints y autenticación.
- `tests/test_storage.py`, `test_notifier.py` — evidencias y Telegram.

Los tests usan `tmp_path` y `monkeypatch` para no depender de `.env`, cámaras ni red.

## Documentación

- README: visión general e inicio rápido.
- `docs/CONFIGURATION.md`: variables y rangos.
- `docs/DEPLOYMENT.md`: compose, GHCR, systemd.
- `docs/TROUBLESHOOTING.md`: diagnóstico por síntoma.

## Reportar bugs y proponer mejoras

Usa las plantillas de issue. Para vulnerabilidades, sigue `SECURITY.md` y no
publiques detalles explotables.

## Estilo

- Python 3.11+, tipado; `ruff` con líneas de 120.
- Sin `print` fuera de `--check`; usa `logging`.
- Errores esperables se registran y degradan sin tumbar el servicio.
- No agregues dependencias pesadas sin justificarlo (la imagen corre en CPU).
