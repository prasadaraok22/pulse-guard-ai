"""Background scheduler for continuous log polling (SRE watchdog mode).

Tails `*.log` files in a watched directory, ingesting only NEW bytes on each
tick (offset tracking + rotation handling), then runs the anomaly engine and
fires alerts. Powered by APScheduler.
"""
from __future__ import annotations

import glob
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.models import LogEvent
from app import parser, anomaly as anomaly_engine, alerting

# file path -> last read byte offset
_offsets: dict[str, int] = {}
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_last_result: dict = {"ingested": 0, "files": 0, "anomalies": 0, "alerts": 0}


def _read_new_lines(path: str) -> str:
    """Return only the bytes appended since we last read this file."""
    size = os.path.getsize(path)
    last = _offsets.get(path, 0)
    if size < last:          # file truncated / rotated -> start over
        last = 0
    if size == last:
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(last)
        chunk = fh.read()
        _offsets[path] = fh.tell()
    return chunk


def poll_once() -> dict:
    """Scan the watch directory once, ingest new log lines, detect + alert."""
    global _last_result
    with _lock:
        directory = settings.poll_directory
        if not os.path.isdir(directory):
            _last_result = {"ingested": 0, "files": 0, "anomalies": 0,
                            "alerts": 0, "note": "watch directory missing"}
            return _last_result

        pattern = os.path.join(directory, settings.poll_glob)
        events: list[dict] = []
        files_scanned = 0
        for path in sorted(glob.glob(pattern)):
            files_scanned += 1
            chunk = _read_new_lines(path)
            if not chunk:
                continue
            default_service = os.path.splitext(os.path.basename(path))[0]
            events.extend(parser.parse_blob(chunk, default_service))

        if not events:
            _last_result = {"ingested": 0, "files": files_scanned,
                            "anomalies": 0, "alerts": 0}
            return _last_result

        db = SessionLocal()
        try:
            for ev in events:
                db.add(LogEvent(**ev))
            db.commit()
            anomalies = anomaly_engine.detect_all(db)
            alerts = alerting.fire_pending_alerts(db, anomalies)
            _last_result = {
                "ingested": len(events),
                "files": files_scanned,
                "anomalies": len(anomalies),
                "alerts": len(alerts),
            }
            return _last_result
        finally:
            db.close()


def _safe_poll() -> None:
    try:
        result = poll_once()
        if result.get("ingested"):
            print(f"[POLL] ingested={result['ingested']} "
                  f"anomalies={result['anomalies']} alerts={result['alerts']}")
    except Exception as exc:  # never let a bad tick kill the scheduler
        print(f"[POLL][ERROR] {type(exc).__name__}: {exc}")


def start_scheduler() -> None:
    """Start the background poller (idempotent)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    os.makedirs(settings.poll_directory, exist_ok=True)
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _safe_poll,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="log_poll",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    print(f"[SCHEDULER] polling '{settings.poll_directory}/{settings.poll_glob}' "
          f"every {settings.poll_interval_seconds}s")


def stop_scheduler() -> None:
    """Stop the background poller (idempotent)."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def is_running() -> bool:
    return bool(_scheduler and _scheduler.running)


def status() -> dict:
    return {
        "running": is_running(),
        "directory": settings.poll_directory,
        "glob": settings.poll_glob,
        "interval_seconds": settings.poll_interval_seconds,
        "tracked_files": sorted(_offsets.keys()),
        "last_result": _last_result,
    }

