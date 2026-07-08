"""Enterprise synthetic log-data generator (single source of truth).

Used by both the CLI seeder (`scripts/seed_enterprise.py`) and the dashboard
one-click endpoint (`POST /api/demo/enterprise`). Produces a realistic
multi-service dataset that exercises every anomaly pattern the detection engine
supports, plus healthy / sub-threshold services that must NOT alert.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

HISTORY_MINUTES = 45

INFO_MESSAGES = [
    "request handled ok",
    "200 OK GET /api/v1/resource",
    "cache hit",
    "healthcheck passed",
    "processed message batch",
]
ERROR_MESSAGES = {
    "payment-svc": "downstream timeout / 500 gateway error",
    "search-svc": "query executor exception: shard unavailable",
    "db-proxy": "connection pool exhausted / read timeout",
    "api-gateway": "upstream 503 service unavailable",
    "auth-svc": "token validation failed / IdP unreachable",
    "batch-worker": "job failed: unhandled exception in worker",
    "recommendation-svc": "model serving 500 / feature store timeout",
    "inventory-svc": "stock lookup failed: deadlock detected",
    "notifications-svc": "transient SMTP 421 throttled",
    "cdn-edge": "origin fetch error",
}

JSON_SERVICES = {"inventory-svc"}

SCENARIO_LEGEND = {
    "payment-svc": "SUDDEN_SPIKE",
    "search-svc": "GRADUAL_CREEP",
    "db-proxy": "SUSTAINED_OUTAGE",
    "api-gateway": "CASCADE_GATEWAY",
    "auth-svc": "CASCADE_AUTH",
    "batch-worker": "PERIODIC_BURST",
    "recommendation-svc": "RECOVERY",
    "inventory-svc": "JSON_SPIKE",
    "notifications-svc": "HEALTHY_NOISE (no alert)",
    "cdn-edge": "STEADY_HEALTHY (no alert)",
}


def _ts(base: datetime, second: int) -> str:
    return (base + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(rng, lines, service, base, level, count, as_json) -> None:
    for i in range(count):
        second = (i * 3) % 60
        ts = _ts(base, second)
        msg = rng.choice(INFO_MESSAGES) if level == "INFO" else ERROR_MESSAGES.get(service, "error")
        if as_json:
            lines.append(json.dumps({"timestamp": ts, "level": level, "service": service, "message": msg}))
        else:
            lines.append(f"{ts} {level} [{service}] {msg}")


def _profile(rng, service: str, n: int) -> list[int]:
    """Return an error-count-per-minute list of length n for a service."""
    if service == "payment-svc":            # SUDDEN_SPIKE
        p = [rng.randint(0, 2) for _ in range(n)]
        p[n - 5] = 35
        return p
    if service == "search-svc":             # GRADUAL_CREEP
        ramp = [1, 1, 2, 2, 3, 4, 6, 9, 14, 20, 28]
        p = [rng.randint(0, 1) for _ in range(n)]
        for i, v in enumerate(ramp):
            idx = n - len(ramp) + i
            if idx >= 0:
                p[idx] = v
        return p
    if service == "db-proxy":               # SUSTAINED_OUTAGE
        p = [rng.randint(0, 1) for _ in range(n)]
        for m in range(n - 9, n - 3):
            if m >= 0:
                p[m] = 30
        p[n - 2] = 4
        p[n - 1] = 1
        return p
    if service == "api-gateway":            # CASCADE root
        p = [rng.randint(0, 2) for _ in range(n)]
        p[n - 7] = 22
        p[n - 6] = 18
        return p
    if service == "auth-svc":               # CASCADE downstream
        p = [rng.randint(0, 1) for _ in range(n)]
        p[n - 7] = 16
        p[n - 6] = 20
        return p
    if service == "batch-worker":           # PERIODIC_BURST
        p = [rng.randint(0, 1) for _ in range(n)]
        for m in range(n - 1, -1, -6):
            p[m] = 15
        return p
    if service == "recommendation-svc":     # RECOVERY
        p = [rng.randint(0, 1) for _ in range(n)]
        p[n - 10] = 18
        p[n - 9] = 12
        return p
    if service == "inventory-svc":          # JSON_SPIKE
        p = [rng.randint(0, 2) for _ in range(n)]
        p[n - 4] = 24
        return p
    if service == "notifications-svc":      # HEALTHY_NOISE (sub-threshold)
        return [rng.randint(0, 3) for _ in range(n)]
    if service == "cdn-edge":               # STEADY_HEALTHY
        return [0 for _ in range(n)]
    return [0 for _ in range(n)]


def _info_rate(service: str) -> tuple[int, int]:
    heavy = {"api-gateway", "cdn-edge", "search-svc"}
    return (40, 60) if service in heavy else (12, 25)


def build_dataset(minutes: int = HISTORY_MINUTES, seed: int = 42) -> str:
    """Build the full enterprise log blob (plaintext + JSON mixed)."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    lines: list[str] = []

    for service in SCENARIO_LEGEND:
        as_json = service in JSON_SERVICES
        errors = _profile(rng, service, minutes)
        lo, hi = _info_rate(service)
        for m in range(minutes):
            base = now - timedelta(minutes=(minutes - 1 - m))
            _emit(rng, lines, service, base, "INFO", rng.randint(lo, hi), as_json)
            if errors[m] > 0:
                _emit(rng, lines, service, base, "ERROR", errors[m], as_json)

    rng.shuffle(lines)
    return "\n".join(lines)

