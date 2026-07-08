"""Tests for Slack / Discord / generic webhook payload building & detection."""
from __future__ import annotations

from datetime import datetime

from app.config import settings
from app import alerting
from app.models import Anomaly


def _anomaly() -> Anomaly:
    return Anomaly(
        id=1,
        service="payment-svc",
        bucket_start=datetime(2026, 7, 8, 10, 7, 0),
        error_count=20,
        baseline=1.5,
        zscore=8.2,
        severity="critical",
        reason="Error spike: 20 errors in 60s bucket (baseline≈1.5, z=8.20 ≥ 3.0).",
        alert_sent=False,
    )


def test_detect_webhook_type_auto():
    settings.webhook_type = "auto"
    assert alerting.detect_webhook_type("https://hooks.slack.com/services/T/B/X") == "slack"
    assert alerting.detect_webhook_type("https://discord.com/api/webhooks/123/abc") == "discord"
    assert alerting.detect_webhook_type("https://example.com/hook") == "generic"
    assert alerting.detect_webhook_type("") == "generic"


def test_detect_webhook_type_override():
    settings.webhook_type = "discord"
    assert alerting.detect_webhook_type("https://hooks.slack.com/x") == "discord"
    settings.webhook_type = "auto"  # reset


def test_build_slack_message():
    payload = alerting.build_payload(_anomaly())
    msg = alerting.build_slack_message(payload)
    assert "blocks" in msg
    assert msg["blocks"][0]["type"] == "header"
    assert "payment-svc" in msg["text"]


def test_build_discord_message():
    payload = alerting.build_payload(_anomaly())
    msg = alerting.build_discord_message(payload)
    assert "embeds" in msg
    embed = msg["embeds"][0]
    assert embed["color"] == 0xE01E5A  # critical color
    assert any(f["name"] == "Errors" for f in embed["fields"])


def test_format_for_target_generic():
    payload = alerting.build_payload(_anomaly())
    assert alerting.format_for_target(payload, "generic") is payload

