"""Seed the running API with synthetic logs containing a deliberate error spike.

Usage:
    python scripts/seed_demo.py            # posts to http://localhost:8000
    PULSE_API=http://host:port python scripts/seed_demo.py
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import httpx

API = os.environ.get("PULSE_API", "http://localhost:8000")


def generate() -> str:
    services = ["payment-svc", "auth-svc", "checkout-svc"]
    now = datetime.now(timezone.utc)
    lines: list[str] = []
    for m in range(20, -1, -1):
        base = now - timedelta(minutes=m)
        for svc in services:
            normal = random.randint(8, 12)
            for i in range(normal):
                ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                lines.append(f"{ts} INFO [{svc}] request handled ok")
            # inject spike into payment-svc 4-6 minutes ago
            spike = 25 if (svc == "payment-svc" and 4 <= m <= 6) else 0
            errors = (1 if random.random() < 0.3 else 0) + spike
            for i in range(errors):
                ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                lines.append(f"{ts} ERROR [{svc}] downstream timeout / 500")
    return "\n".join(lines)


def main() -> None:
    blob = generate()
    resp = httpx.post(f"{API}/api/ingest/raw", json={"content": blob}, timeout=30)
    resp.raise_for_status()
    print("Ingest result:", resp.json())
    print("Anomalies:", httpx.get(f"{API}/api/anomalies").json())


if __name__ == "__main__":
    main()

