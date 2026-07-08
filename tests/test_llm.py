"""Tests for opt-in LLM enrichment. DB isolation handled by conftest.py.

Uses a mocked httpx.post so no real network/model is required. Settings are
toggled via monkeypatch so they auto-revert (keeping other suites' LLM off).
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app import llm as llm_module
from app import alerting
from app.models import Anomaly

client = TestClient(app)


class _FakeResp:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):  # pragma: no cover - trivial
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _seed_spike(service: str = "pay-svc", msg: str = "db connection timeout"):
    lines = [f"2024-05-01T12:0{m}:00 ERROR [{service}] {msg}" for m in range(6)]
    lines += [f"2024-05-01T12:07:{i % 60:02d} ERROR [{service}] {msg}" for i in range(20)]
    r = client.post("/api/ingest/raw", json={"content": "\n".join(lines)})
    assert r.status_code == 200
    return r.json()


def _first_anomaly_id(service: str = "pay-svc") -> int:
    anomalies = client.get(f"/api/anomalies?service={service}").json()
    assert anomalies, "expected a detected anomaly"
    return anomalies[0]["id"]


def _enable_llm(monkeypatch, content: str):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: _FakeResp(content))


# --------------------------------------------------------------------------- #
def test_disabled_by_default():
    assert llm_module.is_enabled() is False
    st = client.get("/api/llm/status").json()
    assert st["enabled"] is False
    assert st["configured"] is False


def test_enrich_endpoint_409_when_disabled():
    _seed_spike()
    aid = _first_anomaly_id()
    r = client.post(f"/api/anomalies/{aid}/enrich")
    assert r.status_code == 409


def test_enrichment_applies_all_fields(monkeypatch):
    _enable_llm(monkeypatch, json.dumps({
        "root_cause": "DB connection pool exhausted",
        "remediation": "Increase pool size / add read replica",
        "label": "DB timeout",
        "impact": "high",
    }))
    _seed_spike()
    aid = _first_anomaly_id()
    r = client.post(f"/api/anomalies/{aid}/enrich")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_enriched"] is True
    assert body["llm_label"] == "DB timeout"
    assert body["llm_impact"] == "high"
    assert "pool" in body["llm_root_cause"].lower()
    assert body["llm_remediation"]


def test_ingest_auto_enriches_when_enabled(monkeypatch):
    _enable_llm(monkeypatch, json.dumps({
        "root_cause": "Upstream 503s", "remediation": "Failover",
        "label": "Upstream outage", "impact": "critical",
    }))
    _seed_spike()  # enrichment happens inside fire_alert during ingest
    anomalies = client.get("/api/anomalies?service=pay-svc").json()
    assert anomalies[0]["llm_enriched"] is True
    assert anomalies[0]["llm_label"] == "Upstream outage"


def test_payload_and_messages_include_ai_insight():
    a = Anomaly(
        id=1, service="pay-svc", bucket_start=datetime(2026, 7, 8, 10, 0),
        error_count=20, baseline=1.0, zscore=9.0, severity="critical", reason="r",
        alert_sent=False, llm_enriched=True, llm_label="DB timeout",
        llm_root_cause="pool exhausted", llm_remediation="scale pool", llm_impact="high",
    )
    payload = alerting.build_payload(a)
    assert payload["ai_insight"]["label"] == "DB timeout"

    discord = alerting.build_discord_message(payload)
    names = [f["name"] for f in discord["embeds"][0]["fields"]]
    assert any("AI label" in n for n in names)

    slack = alerting.build_slack_message(payload)
    assert "🤖" in json.dumps(slack, ensure_ascii=False)


def test_enrichment_failure_is_fail_safe(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm_module.httpx, "post", _boom)
    _seed_spike()  # must not crash despite LLM errors
    aid = _first_anomaly_id()
    r = client.post(f"/api/anomalies/{aid}/enrich")
    assert r.status_code == 200
    assert r.json()["llm_enriched"] is False


def test_malformed_json_is_tolerated():
    # code-fenced / prose-wrapped JSON should still parse
    parsed = llm_module._safe_parse_json('```json\n{"label": "X"}\n```')
    assert parsed == {"label": "X"}
    assert llm_module._safe_parse_json("not json at all") is None


# --- Cost control: severity gating ----------------------------------------- #
def test_passes_severity_gate(monkeypatch):
    crit = Anomaly(severity="critical")
    warn = Anomaly(severity="warning")
    monkeypatch.setattr(settings, "llm_min_severity", "critical")
    assert llm_module.passes_severity(crit) is True
    assert llm_module.passes_severity(warn) is False
    monkeypatch.setattr(settings, "llm_min_severity", "warning")
    assert llm_module.passes_severity(warn) is True


def test_auto_enrich_skips_below_threshold(monkeypatch):
    from datetime import datetime
    from app.database import SessionLocal

    _enable_llm(monkeypatch, json.dumps({"label": "X", "root_cause": "y", "impact": "high"}))
    monkeypatch.setattr(settings, "llm_min_severity", "critical")

    db = SessionLocal()
    try:
        warn = Anomaly(
            service="warn-svc", bucket_start=datetime(2026, 7, 8, 10, 0),
            error_count=6, baseline=1.0, zscore=4.0, severity="warning", reason="r",
        )
        db.add(warn)
        db.commit()
        db.refresh(warn)
        # Auto path skips a warning when min_severity=critical...
        assert llm_module.maybe_enrich(db, warn) is False
        assert warn.llm_enriched is False
        # ...but a manual/forced call still enriches it.
        assert llm_module.maybe_enrich(db, warn, force=True) is True
        assert warn.llm_enriched is True
    finally:
        db.close()


# --- Cost control: caching by error-signature ------------------------------ #
def test_signature_normalizes_variables():
    s1 = llm_module.signature([("timeout after 500ms on 10.0.0.1", 3)])
    s2 = llm_module.signature([("timeout after 1200ms on 10.0.0.9", 5)])
    assert s1 == s2  # digits + IPs normalized to the same template


def test_cache_reuses_by_signature(monkeypatch):
    calls = {"n": 0}

    def _counting_post(*a, **k):
        calls["n"] += 1
        return _FakeResp(json.dumps({
            "label": "DB timeout", "root_cause": "pool", "remediation": "scale", "impact": "high",
        }))

    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(llm_module.httpx, "post", _counting_post)

    # Two different services, IDENTICAL error text => identical signature.
    _seed_spike(service="svc-a")   # auto-enrich (critical) -> cache MISS (1 call)
    _seed_spike(service="svc-b")   # identical signature   -> cache HIT (0 calls)

    assert calls["n"] == 1
    st = client.get("/api/llm/status").json()
    assert st["cache"]["hits"] >= 1
    # Both anomalies still got enriched (one from the live call, one from cache).
    a = client.get("/api/anomalies?service=svc-a").json()[0]
    b = client.get("/api/anomalies?service=svc-b").json()[0]
    assert a["llm_enriched"] and b["llm_enriched"]
    assert a["llm_signature"] == b["llm_signature"]


