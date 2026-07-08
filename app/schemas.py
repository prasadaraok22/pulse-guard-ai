"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class LogEventIn(BaseModel):
    """Structured log event ingestion payload."""

    service: str = Field(default="unknown", max_length=128)
    level: str = Field(default="INFO", max_length=16)
    message: str = ""
    timestamp: Optional[datetime] = None


class RawLogIn(BaseModel):
    """Raw multi-line log blob ingestion payload."""

    service: Optional[str] = None
    content: str = Field(..., description="Raw log text, one event per line")


class LogEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service: str
    level: str
    message: str
    timestamp: datetime


class IngestResult(BaseModel):
    ingested: int
    parsed_errors: int
    anomalies_detected: int
    alerts_fired: int


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service: str
    bucket_start: datetime
    error_count: int
    baseline: float
    zscore: float
    severity: str
    reason: str
    alert_sent: bool
    created_at: datetime
    # Optional LLM enrichment (null unless PULSE_LLM_ENABLED)
    llm_label: Optional[str] = None
    llm_summary: Optional[str] = None
    llm_root_cause: Optional[str] = None
    llm_remediation: Optional[str] = None
    llm_impact: Optional[str] = None
    llm_signature: Optional[str] = None
    llm_enriched: bool = False


class LLMStatus(BaseModel):
    enabled: bool
    configured: bool
    model: str
    base_url: str
    features: dict[str, bool]
    min_severity: str
    cache: dict[str, int]


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    anomaly_id: int
    service: str
    target: str
    status: str
    payload: str
    created_at: datetime


class TrendPoint(BaseModel):
    bucket: datetime
    total: int
    errors: int


class HealthTrend(BaseModel):
    service: str
    points: list[TrendPoint]
    health_score: float

