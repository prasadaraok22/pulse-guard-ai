"""Enterprise-grade synthetic log generator for Pulse Guard AI.

Generates a realistic multi-service dataset that exercises EVERY anomaly
pattern the detection engine supports, plus healthy/negative cases that must
NOT trigger alerts. Import `build_dataset()` from tests, or run this file to
seed a running API instance.

Scenarios covered
-----------------
  SUDDEN_SPIKE     payment-svc      quiet baseline then one huge bucket  -> critical
  GRADUAL_CREEP    search-svc       slowly ramping error rate            -> warning/critical
  SUSTAINED_OUTAGE db-proxy         multi-minute plateau then recovery   -> multiple
  CASCADE_GATEWAY  api-gateway      correlated spike (root of cascade)   -> critical
  CASCADE_AUTH     auth-svc         correlated downstream spike          -> critical
  PERIODIC_BURST   batch-worker     repeating bursts every few minutes   -> multiple
  RECOVERY         recommendation   spike then clean recovery            -> warning
  JSON_SPIKE       inventory-svc    spike emitted as JSON logs           -> critical
  HEALTHY_NOISE    notifications    sub-threshold blips                  -> NONE (negative)
  STEADY_HEALTHY   cdn-edge         pure success traffic                 -> NONE (negative)

Usage
-----
    python scripts/seed_enterprise.py                 # POST to http://localhost:8000
    PULSE_API=http://localhost:8100 python scripts/seed_enterprise.py
    python scripts/seed_enterprise.py --write         # also write sample files
    python scripts/seed_enterprise.py --minutes 45    # history length
"""
from __future__ import annotations

import argparse
import os
import sys

# Make the project root importable so `app.sample_data` resolves when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sample_data import build_dataset, SCENARIO_LEGEND, HISTORY_MINUTES  # noqa: E402


def _seed(api: str, blob: str) -> None:
    import httpx

    resp = httpx.post(f"{api}/api/ingest/raw", json={"content": blob}, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    print("Ingest result:", result)

    anomalies = httpx.get(f"{api}/api/anomalies?limit=100", timeout=30).json()
    print(f"\nDetected {len(anomalies)} anomalies:")
    by_service: dict[str, int] = {}
    for a in anomalies:
        by_service[a["service"]] = by_service.get(a["service"], 0) + 1
    for service, scenario in SCENARIO_LEGEND.items():
        count = by_service.get(service, 0)
        mark = "🚨" if count else ("✅" if "no alert" in scenario else "  ")
        print(f"  {mark} {service:<20} {scenario:<26} anomalies={count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed enterprise test data.")
    parser.add_argument("--minutes", type=int, default=HISTORY_MINUTES)
    parser.add_argument("--write", action="store_true", help="write sample files to samples/")
    parser.add_argument("--no-post", action="store_true", help="do not POST to the API")
    args = parser.parse_args()

    blob = build_dataset(args.minutes)
    print(f"Generated {len(blob.splitlines())} log lines across {len(SCENARIO_LEGEND)} services.")

    if args.write:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = os.path.join(here, "samples", "enterprise_logs.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        print(f"Wrote sample dataset -> {out}")

    if not args.no_post:
        api = os.environ.get("PULSE_API", "http://localhost:8000")
        _seed(api, blob)


if __name__ == "__main__":
    main()

