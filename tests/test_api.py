"""End-to-end tests for Pulse Guard AI. DB isolation handled by conftest.py."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app import parser

client = TestClient(app)


def _spike_blob() -> str:
    lines = []
    # 5 quiet buckets, then a big spike bucket
    for minute in range(5):
        for i in range(1):
            lines.append(f"2024-05-01T12:0{minute}:0{i} ERROR [svc-a] blip")
    # spike minute 06
    for i in range(30):
        sec = f"{i % 60:02d}"
        lines.append(f"2024-05-01T12:06:{sec} ERROR [svc-a] mass failure")
    return "\n".join(lines)


def _seed_spike():
    r = client.post("/api/ingest/raw", json={"content": _spike_blob()})
    assert r.status_code == 200
    return r.json()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_parser_plaintext_and_json():
    ev = parser.parse_line("2024-05-01T12:00:00Z ERROR [pay] boom")
    assert ev["service"] == "pay"
    assert ev["level"] == "ERROR"
    j = parser.parse_line('{"level":"error","service":"auth","message":"x"}')
    assert j["service"] == "auth"
    assert j["level"] == "ERROR"


def test_ingest_and_detect_spike():
    data = _seed_spike()
    assert data["ingested"] > 0
    assert data["anomalies_detected"] >= 1
    assert data["alerts_fired"] >= 1


def test_anomalies_endpoint():
    _seed_spike()
    r = client.get("/api/anomalies")
    assert r.status_code == 200
    assert any(a["service"] == "svc-a" for a in r.json())


def test_alerts_endpoint():
    _seed_spike()
    r = client.get("/api/alerts")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_trends_endpoint():
    _seed_spike()
    r = client.get("/api/trends", params={"service": "svc-a", "minutes": 1440})
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "svc-a"
    assert 0 <= body["health_score"] <= 100

