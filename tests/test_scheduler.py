"""Tests for the continuous log-polling scheduler (file tailing + detection).

DB isolation + offset reset handled by conftest.py.
"""
from __future__ import annotations

import os
import tempfile

from app.config import settings
from app import scheduler


def _write(path: str, text: str, mode: str = "a") -> None:
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)


def test_poll_missing_directory():
    settings.poll_directory = os.path.join(tempfile.gettempdir(), "does_not_exist_xyz")
    scheduler._offsets.clear()
    result = scheduler.poll_once()
    assert result["ingested"] == 0
    assert result.get("note") == "watch directory missing"


def test_poll_tails_only_new_lines():
    watch = tempfile.mkdtemp(prefix="pulse_watch_")
    settings.poll_directory = watch
    settings.poll_glob = "*.log"
    scheduler._offsets.clear()

    log_path = os.path.join(watch, "payment-svc.log")

    # First batch: quiet baseline error buckets, then a clear spike bucket.
    lines = []
    for m in range(6):                       # 6 buckets with 1 error each (baseline)
        lines.append(f"2026-07-08T10:0{m}:00Z ERROR [payment-svc] minor blip")
    for i in range(20):                      # spike bucket 10:07 with 20 errors
        sec = f"{i % 60:02d}"
        lines.append(f"2026-07-08T10:07:{sec}Z ERROR [payment-svc] boom")
    _write(log_path, "\n".join(lines) + "\n")

    first = scheduler.poll_once()
    assert first["files"] == 1
    assert first["ingested"] == len(lines)
    assert first["anomalies"] >= 1
    assert first["alerts"] >= 1

    # Second poll with no new bytes -> nothing ingested.
    again = scheduler.poll_once()
    assert again["ingested"] == 0

    # Append more lines -> only the NEW ones are ingested.
    _write(log_path, "2026-07-08T10:08:00Z INFO [payment-svc] ok\n")
    third = scheduler.poll_once()
    assert third["ingested"] == 1


def test_poll_handles_rotation():
    watch = tempfile.mkdtemp(prefix="pulse_rotate_")
    settings.poll_directory = watch
    scheduler._offsets.clear()
    log_path = os.path.join(watch, "auth-svc.log")

    _write(log_path, "2026-07-08T11:00:00Z INFO [auth-svc] first entry padded longer\n")
    scheduler.poll_once()

    # Rotate: overwrite with a SHORTER file (size < previous offset) => re-read.
    _write(log_path, "2026-07-08T11:05:00Z INFO [auth-svc] b\n", mode="w")
    result = scheduler.poll_once()
    assert result["ingested"] == 1  # detected rotation, re-read from 0


def test_scheduler_start_stop():
    settings.poll_interval_seconds = 60
    settings.poll_directory = tempfile.mkdtemp(prefix="pulse_sched_")
    scheduler.start_scheduler()
    assert scheduler.is_running() is True
    st = scheduler.status()
    assert st["running"] is True
    scheduler.stop_scheduler()
    assert scheduler.is_running() is False

