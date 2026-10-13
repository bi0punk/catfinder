from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.utils import ensure_dir, safe_int


@dataclass(slots=True)
class StorageSettings:
    """Ubicación y retención de evidencias y del log de eventos."""

    save_dir: Path
    events_jsonl: Path
    retention_days: int
    max_events_memory: int


def load_storage_settings(project_root: Path) -> StorageSettings:
    save_dir = Path(os.getenv("SAVE_DIR", "captures"))
    if not save_dir.is_absolute():
        save_dir = project_root / save_dir
    ensure_dir(save_dir)

    events_jsonl = Path(os.getenv("EVENTS_JSONL", str(save_dir / "events.jsonl")))
    if not events_jsonl.is_absolute():
        events_jsonl = project_root / events_jsonl
    ensure_dir(events_jsonl.parent)

    return StorageSettings(
        save_dir=save_dir,
        events_jsonl=events_jsonl,
        retention_days=max(0, safe_int(os.getenv("RETENTION_DAYS", "14"), 14)),
        max_events_memory=max(10, safe_int(os.getenv("MAX_EVENTS_MEMORY", "200"), 200)),
    )
