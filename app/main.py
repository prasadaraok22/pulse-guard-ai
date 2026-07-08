"""FastAPI application: API-first Intelligent Observability & Event Watchdog."""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, init_db
from app.models import LogEvent, Anomaly, AlertLog
from app import parser, anomaly as anomaly_engine, alerting, schemas, scheduler, llm


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.poll_enabled:
        scheduler.start_scheduler()
    try:
        yield
    finally:
        scheduler.stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    description="Intelligent Observability & Event Watchdog — parses logs, detects error spikes with AI logic, fires webhook alerts, and visualizes health trends.",
    version="0.1.0",
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"



# ----------------------------- Ingestion ---------------------------------- #
def _persist_and_detect(db: Session, events: list[dict]) -> schemas.IngestResult:
    parsed_errors = 0
    for ev in events:
        db.add(LogEvent(**ev))
        if parser.is_error(ev["level"]):
            parsed_errors += 1
    db.commit()

    anomalies = anomaly_engine.detect_all(db)
    alerts = alerting.fire_pending_alerts(db, anomalies)

    return schemas.IngestResult(
        ingested=len(events),
        parsed_errors=parsed_errors,
        anomalies_detected=len(anomalies),
        alerts_fired=len(alerts),
    )


@app.post("/api/ingest/raw", response_model=schemas.IngestResult, tags=["ingest"])
def ingest_raw(payload: schemas.RawLogIn, db: Session = Depends(get_db)):
    """Ingest a raw multi-line log blob (plaintext or JSON-per-line)."""
    events = parser.parse_blob(payload.content, payload.service)
    if not events:
        raise HTTPException(status_code=400, detail="No parseable log lines found.")
    return _persist_and_detect(db, events)


@app.post("/api/demo/enterprise", response_model=schemas.IngestResult, tags=["demo"])
def seed_enterprise_demo(minutes: int = Query(default=45, ge=10, le=180), db: Session = Depends(get_db)):
    """One-click: generate & ingest an enterprise dataset covering every anomaly
    pattern (sudden spike, gradual creep, sustained outage, cascade, periodic
    burst, recovery, JSON logs) plus healthy services that must not alert."""
    from app.sample_data import build_dataset

    events = parser.parse_blob(build_dataset(minutes))
    return _persist_and_detect(db, events)


@app.post("/api/ingest/events", response_model=schemas.IngestResult, tags=["ingest"])
def ingest_events(events: list[schemas.LogEventIn], db: Session = Depends(get_db)):
    """Ingest a batch of already-structured log events."""
    normalized = [
        {
            "service": e.service,
            "level": parser._normalize_level(e.level),
            "message": e.message,
            "timestamp": e.timestamp or datetime.now(timezone.utc).replace(tzinfo=None),
        }
        for e in events
    ]
    return _persist_and_detect(db, normalized)


@app.post("/api/ingest/file", response_model=schemas.IngestResult, tags=["ingest"])
async def ingest_file(
    file: UploadFile = File(...),
    service: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Upload a log file for ingestion."""
    content = (await file.read()).decode("utf-8", errors="replace")
    events = parser.parse_blob(content, service)
    if not events:
        raise HTTPException(status_code=400, detail="No parseable log lines found.")
    return _persist_and_detect(db, events)


# ------------------------------- Queries ---------------------------------- #
@app.get("/api/services", tags=["query"])
def list_services(db: Session = Depends(get_db)):
    """List known services with total & error event counts."""
    rows = db.execute(
        select(
            LogEvent.service,
            func.count(LogEvent.id),
            func.sum(case((LogEvent.level.in_(parser.ERROR_LEVELS), 1), else_=0)),
        ).group_by(LogEvent.service)
    ).all()
    return [
        {"service": s, "total": int(total or 0), "errors": int(errors or 0)}
        for s, total, errors in rows
    ]


@app.get("/api/anomalies", response_model=list[schemas.AnomalyOut], tags=["query"])
def list_anomalies(
    service: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    """List detected anomalies, newest first."""
    stmt = select(Anomaly).order_by(Anomaly.bucket_start.desc()).limit(limit)
    if service:
        stmt = stmt.where(Anomaly.service == service)
    return list(db.execute(stmt).scalars().all())


@app.get("/api/llm/status", response_model=schemas.LLMStatus, tags=["llm"])
def llm_status():
    """Report whether opt-in LLM enrichment is enabled and configured."""
    return llm.status()


@app.post("/api/anomalies/{anomaly_id}/enrich", response_model=schemas.AnomalyOut, tags=["llm"])
def enrich_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    """Manually (re)run LLM enrichment for one anomaly.

    Requires PULSE_LLM_ENABLED + a configured API key, else returns 409.
    """
    anomaly: Anomaly | None = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=404, detail="Anomaly not found.")
    if not llm.is_enabled():
        raise HTTPException(
            status_code=409,
            detail="LLM enrichment is disabled. Set PULSE_LLM_ENABLED=true and PULSE_LLM_API_KEY.",
        )
    anomaly.llm_enriched = False  # allow re-enrichment on demand
    llm.maybe_enrich(db, anomaly, force=True)  # manual bypasses severity gate
    db.refresh(anomaly)
    return anomaly


@app.get("/api/alerts", response_model=list[schemas.AlertOut], tags=["query"])
def list_alerts(limit: int = Query(default=100, le=1000), db: Session = Depends(get_db)):
    """List fired (simulated) webhook alerts, newest first."""
    stmt = select(AlertLog).order_by(AlertLog.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


@app.get("/api/trends", response_model=schemas.HealthTrend, tags=["query"])
def health_trend(
    service: str = Query(...),
    minutes: int = Query(default=60, le=1440),
    db: Session = Depends(get_db),
):
    """Return bucketed total/error counts + a 0-100 health score for a service."""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    rows = db.execute(
        select(LogEvent.timestamp, LogEvent.level)
        .where(LogEvent.service == service)
        .where(LogEvent.timestamp >= since)
    ).all()

    totals: dict[datetime, int] = defaultdict(int)
    errors: dict[datetime, int] = defaultdict(int)
    for ts, level in rows:
        bucket = anomaly_engine._bucket_key(ts, settings.bucket_seconds)
        totals[bucket] += 1
        if parser.is_error(level):
            errors[bucket] += 1

    points = [
        schemas.TrendPoint(bucket=b, total=totals[b], errors=errors[b])
        for b in sorted(totals)
    ]

    total_all = sum(totals.values())
    error_all = sum(errors.values())
    error_rate = (error_all / total_all) if total_all else 0.0
    health_score = round(max(0.0, 100.0 * (1.0 - error_rate)), 2)

    return schemas.HealthTrend(service=service, points=points, health_score=health_score)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.app_name, "version": "0.1.0"}


# --------------------------- Scheduler / Poller --------------------------- #
@app.get("/api/scheduler/status", tags=["scheduler"])
def scheduler_status():
    """Current state of the continuous log poller."""
    return scheduler.status()


@app.post("/api/scheduler/start", tags=["scheduler"])
def scheduler_start():
    """Start continuous log polling of the watch directory."""
    scheduler.start_scheduler()
    return scheduler.status()


@app.post("/api/scheduler/stop", tags=["scheduler"])
def scheduler_stop():
    """Stop continuous log polling."""
    scheduler.stop_scheduler()
    return scheduler.status()


@app.post("/api/scheduler/poll", tags=["scheduler"])
def scheduler_poll_now():
    """Trigger a single poll of the watch directory immediately."""
    return scheduler.poll_once()


# ------------------------------ Dashboard --------------------------------- #
@app.get("/", include_in_schema=False)
def dashboard():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": f"{settings.app_name} running. See /docs for the API."}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


