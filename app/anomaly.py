"""Anomaly detection engine.

AI/statistical logic: for each service we bucket error counts into fixed
time windows, build a rolling baseline using an EWMA (exponentially weighted
moving average) plus a rolling-window Z-score. A bucket whose error count is
far above the baseline (high z-score) is flagged as a spike/anomaly.

This is explainable, dependency-light SRE anomaly detection.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LogEvent, Anomaly
from app.parser import ERROR_LEVELS


def _bucket_key(ts: datetime, bucket_seconds: int) -> datetime:
    epoch = int(ts.replace(tzinfo=timezone.utc).timestamp()) if ts.tzinfo is None else int(ts.timestamp())
    floored = epoch - (epoch % bucket_seconds)
    return datetime.fromtimestamp(floored, timezone.utc).replace(tzinfo=None)


def _severity(zscore: float) -> str:
    if zscore >= settings.zscore_threshold * 2:
        return "critical"
    if zscore >= settings.zscore_threshold:
        return "warning"
    return "info"


def build_error_buckets(db: Session, service: str) -> list[tuple[datetime, int]]:
    """Return ordered (bucket_start, error_count) for a service."""
    rows = db.execute(
        select(LogEvent.timestamp, LogEvent.level)
        .where(LogEvent.service == service)
        .where(LogEvent.level.in_(ERROR_LEVELS))
    ).all()

    counts: dict[datetime, int] = defaultdict(int)
    for ts, _level in rows:
        counts[_bucket_key(ts, settings.bucket_seconds)] += 1

    return sorted(counts.items())


def _rolling_stats(history: list[int]) -> tuple[float, float]:
    """Return (mean, std) of the rolling window, guarding tiny samples."""
    if not history:
        return 0.0, 0.0
    n = len(history)
    mean = sum(history) / n
    var = sum((x - mean) ** 2 for x in history) / n
    return mean, math.sqrt(var)


def detect_for_service(db: Session, service: str) -> list[Anomaly]:
    """Run detection for one service; persist & return NEW anomalies."""
    buckets = build_error_buckets(db, service)
    if len(buckets) < 2:
        return []

    window = settings.window_size
    z_thresh = settings.zscore_threshold
    alpha = settings.ewma_alpha
    min_events = settings.min_events_for_alert

    ewma = float(buckets[0][1])
    new_anomalies: list[Anomaly] = []

    for i, (bucket_start, count) in enumerate(buckets):
        history = [c for _, c in buckets[max(0, i - window):i]]
        mean, std = _rolling_stats(history)
        baseline = ewma if i > 0 else mean

        # Z-score vs rolling window; fall back to EWMA-relative deviation.
        if std > 1e-9:
            zscore = (count - mean) / std
        elif baseline > 1e-9:
            zscore = (count - baseline) / max(baseline, 1.0)
        else:
            zscore = float(count)

        is_spike = (
            count >= min_events
            and zscore >= z_thresh
            and count > baseline
        )

        if is_spike:
            existing = db.execute(
                select(Anomaly)
                .where(Anomaly.service == service)
                .where(Anomaly.bucket_start == bucket_start)
            ).scalar_one_or_none()

            if existing is None:
                reason = (
                    f"Error spike: {count} errors in {settings.bucket_seconds}s bucket "
                    f"(baseline≈{baseline:.1f}, z={zscore:.2f} ≥ {z_thresh})."
                )
                anomaly = Anomaly(
                    service=service,
                    bucket_start=bucket_start,
                    error_count=count,
                    baseline=round(baseline, 3),
                    zscore=round(zscore, 3),
                    severity=_severity(zscore),
                    reason=reason,
                    alert_sent=False,
                )
                db.add(anomaly)
                new_anomalies.append(anomaly)

        # Update EWMA baseline
        ewma = alpha * count + (1 - alpha) * ewma

    if new_anomalies:
        db.commit()
        for a in new_anomalies:
            db.refresh(a)
    return new_anomalies


def detect_all(db: Session) -> list[Anomaly]:
    """Run detection across every known service."""
    services = [s for (s,) in db.execute(select(LogEvent.service).distinct()).all()]
    found: list[Anomaly] = []
    for service in services:
        found.extend(detect_for_service(db, service))
    return found

