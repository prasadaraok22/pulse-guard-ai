"""Real-LLM integration smoke test (opt-in).

Skipped automatically unless BOTH a real API key is present AND the feature is
enabled. In CI this runs only in the secret-gated `llm-smoke` job:

    PULSE_LLM_ENABLED=true PULSE_LLM_API_KEY=$OPENAI_API_KEY \
        pytest -m integration tests/test_llm_integration.py

It makes a genuine call to the configured OpenAI-compatible endpoint, so it is
kept out of the normal unit suite (which uses mocked responses).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

if not (os.environ.get("PULSE_LLM_API_KEY") and
        os.environ.get("PULSE_LLM_ENABLED", "").lower() in ("1", "true", "yes")):
    pytest.skip(
        "Real LLM key not configured; skipping integration smoke test.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import llm as llm_module  # noqa: E402

client = TestClient(app)


def _seed_spike():
    msg = "database connection pool exhausted: could not obtain connection within 30s"
    lines = [f"2026-07-08T12:0{m}:00Z ERROR [payments-api] {msg}" for m in range(6)]
    lines += [f"2026-07-08T12:07:{i % 60:02d}Z ERROR [payments-api] {msg}" for i in range(20)]
    r = client.post("/api/ingest/raw", json={"content": "\n".join(lines)})
    assert r.status_code == 200


def test_real_llm_enrichment_smoke():
    assert llm_module.is_enabled(), "LLM must be enabled for the smoke test"
    _seed_spike()
    anomalies = client.get("/api/anomalies?service=payments-api").json()
    assert anomalies, "expected a detected anomaly"
    aid = anomalies[0]["id"]

    r = client.post(f"/api/anomalies/{aid}/enrich")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_enriched"] is True
    # At least one enrichment field should be populated by the real model.
    assert any(body.get(k) for k in ("llm_label", "llm_root_cause", "llm_impact"))
    assert body["llm_signature"]

