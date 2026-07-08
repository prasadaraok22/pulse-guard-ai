"""Scenario coverage tests: verify the engine detects each enterprise anomaly
pattern and correctly stays SILENT for healthy / sub-threshold services.

DB isolation handled by conftest.py — each test seeds fresh into a clean DB.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app import sample_data

client = TestClient(app)

# Services expected to raise at least one anomaly.
POSITIVE = {
    "payment-svc",
    "search-svc",
    "db-proxy",
    "api-gateway",
    "auth-svc",
    "batch-worker",
    "recommendation-svc",
    "inventory-svc",
}
# Services that must NEVER alert.
NEGATIVE = {"notifications-svc", "cdn-edge"}


def _ingest_enterprise() -> dict:
    blob = sample_data.build_dataset(minutes=45)
    r = client.post("/api/ingest/raw", json={"content": blob})
    assert r.status_code == 200, r.text
    return r.json()


def test_enterprise_ingest_runs():
    result = _ingest_enterprise()
    assert result["ingested"] > 1000
    assert result["anomalies_detected"] >= len(POSITIVE)
    assert result["alerts_fired"] >= len(POSITIVE)


def test_positive_scenarios_detected():
    _ingest_enterprise()
    anomalies = client.get("/api/anomalies?limit=500").json()
    flagged = {a["service"] for a in anomalies}
    missing = POSITIVE - flagged
    assert not missing, f"Expected anomalies not detected for: {missing}"


def test_negative_scenarios_silent():
    _ingest_enterprise()
    anomalies = client.get("/api/anomalies?limit=500").json()
    flagged = {a["service"] for a in anomalies}
    noisy = NEGATIVE & flagged
    assert not noisy, f"Healthy services incorrectly flagged: {noisy}"


def test_sudden_spike_is_critical():
    _ingest_enterprise()
    anomalies = client.get("/api/anomalies?service=payment-svc&limit=50").json()
    assert any(a["severity"] == "critical" for a in anomalies)
    assert max(a["error_count"] for a in anomalies) >= 30


def test_json_formatted_logs_detected():
    """inventory-svc emits JSON logs; ensure the parser + engine handle them."""
    _ingest_enterprise()
    anomalies = client.get("/api/anomalies?service=inventory-svc&limit=50").json()
    assert len(anomalies) >= 1


def test_demo_endpoint_seeds_enterprise():
    r = client.post("/api/demo/enterprise")
    assert r.status_code == 200
    body = r.json()
    assert body["ingested"] > 1000
    assert body["anomalies_detected"] >= 1


def test_alerts_carry_incident_payload():
    _ingest_enterprise()
    alerts = client.get("/api/alerts?limit=500").json()
    assert alerts
    sample = alerts[0]
    assert sample["target"] in ("local-sink",) or sample["target"].startswith("http")
    assert "error_spike_detected" in sample["payload"]

