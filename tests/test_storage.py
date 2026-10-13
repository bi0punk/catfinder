"""Tests de storage/evidence: guardado, append al jsonl y retención."""

from __future__ import annotations

import json
import os
import threading
import time

import numpy as np

from app.domain.models import Detection, EventRecord
from app.storage.evidence import EvidenceStore, RetentionThread


def _detections():
    return [Detection(x1=0, y1=0, x2=4, y2=4, label="cat", confidence=0.8)]


def _event(camera_name: str) -> EventRecord:
    return EventRecord("t", "t", camera_name, "cat", 0.8, f"{camera_name}/x.jpg", [])


def test_save_detection_writes_image_and_event(cfg):
    store = EvidenceStore(cfg)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    event = store.save_detection("cam1", frame, _detections())

    assert (cfg.save_dir / event.image_path).is_file()
    assert event.camera_name == "cam1"
    assert event.label == "cat"
    assert event.confidence == 0.8

    lines = cfg.events_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["camera_name"] == "cam1"


def test_append_event_adds_lines(cfg):
    store = EvidenceStore(cfg)
    store.append_event(_event("cam1"))
    store.append_event(_event("cam2"))
    assert len(cfg.events_jsonl.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_cleanup_old_files(cfg):
    store = EvidenceStore(cfg)
    cfg.retention_days = 1

    old = cfg.save_dir / "cam" / "old.jpg"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"old")
    stale = time.time() - 10 * 86400
    os.utime(old, (stale, stale))

    new = cfg.save_dir / "cam" / "new.jpg"
    new.write_bytes(b"new")

    removed = store.cleanup_old_files()
    assert removed == 1
    assert not old.exists()
    assert new.exists()


def test_cleanup_disabled_when_retention_zero(cfg):
    store = EvidenceStore(cfg)
    cfg.retention_days = 0
    assert store.cleanup_old_files() == 0


def test_retention_thread_exits_when_stopped(cfg):
    store = EvidenceStore(cfg)
    stop_event = threading.Event()
    stop_event.set()
    thread = RetentionThread(store, stop_event)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
