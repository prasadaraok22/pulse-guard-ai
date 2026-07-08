"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, DateTime, Text, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LogEvent(Base):
    """A single parsed log line/event."""

    __tablename__ = "log_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(128), index=True, default="unknown")
    level: Mapped[str] = mapped_column(String(16), index=True, default="INFO")
    message: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=_utcnow)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (Index("ix_service_level_ts", "service", "level", "timestamp"),)


class Anomaly(Base):
    """A detected anomaly (error spike) for a service/time-bucket."""

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline: Mapped[float] = mapped_column(Float, default=0.0)
    zscore: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    reason: Mapped[str] = mapped_column(Text, default="")
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # --- Optional LLM enrichment (populated only when PULSE_LLM_ENABLED) ---
    llm_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_impact: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_enriched: Mapped[bool] = mapped_column(Boolean, default=False)


class AlertLog(Base):
    """Record of every (simulated) webhook alert fired."""

    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(Integer, index=True)
    service: Mapped[str] = mapped_column(String(128))
    payload: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(String(256), default="local-sink")
    status: Mapped[str] = mapped_column(String(32), default="simulated")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

