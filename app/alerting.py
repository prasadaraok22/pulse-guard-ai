"""Webhook alerting with real Slack / Discord support.

When an anomaly is detected we fire an alert. The destination format is
auto-detected from the webhook URL (or forced via PULSE_WEBHOOK_TYPE):

  * Slack   -> `hooks.slack.com`      => Block Kit message
  * Discord -> `discord.com/api/...`  => rich embed
  * generic -> anything else          => raw incident JSON

If no PULSE_WEBHOOK_URL is configured we record to a local sink so the flow is
fully demonstrable without external services.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Anomaly, AlertLog

_SEVERITY_COLOR = {          # Discord embed colors
    "critical": 0xE01E5A,
    "warning": 0xECB22E,
    "info": 0x36C5F0,
}
_SEVERITY_EMOJI = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


def detect_webhook_type(url: str) -> str:
    """Infer the webhook flavour from its URL (or the configured override)."""
    if settings.webhook_type and settings.webhook_type != "auto":
        return settings.webhook_type
    if not url:
        return "generic"
    lowered = url.lower()
    if "hooks.slack.com" in lowered:
        return "slack"
    if "discord.com/api/webhooks" in lowered or "discordapp.com/api/webhooks" in lowered:
        return "discord"
    return "generic"


def build_payload(anomaly: Anomaly) -> dict:
    """Construct the canonical incident payload (stored + used for generic)."""
    return {
        "event": "error_spike_detected",
        "service": anomaly.service,
        "severity": anomaly.severity,
        "error_count": anomaly.error_count,
        "baseline": anomaly.baseline,
        "zscore": anomaly.zscore,
        "reason": anomaly.reason,
        "bucket_start": anomaly.bucket_start.isoformat(),
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "source": settings.app_name,
    }


def build_slack_message(payload: dict) -> dict:
    """Slack Block Kit incident message."""
    emoji = _SEVERITY_EMOJI.get(payload["severity"], "🔔")
    title = f"{emoji} {payload['severity'].upper()} error spike — {payload['service']}"
    return {
        "text": title,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Service:*\n{payload['service']}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{payload['severity']}"},
                {"type": "mrkdwn", "text": f"*Errors:*\n{payload['error_count']}"},
                {"type": "mrkdwn", "text": f"*Baseline:*\n{payload['baseline']}"},
                {"type": "mrkdwn", "text": f"*Z-score:*\n{payload['zscore']}"},
                {"type": "mrkdwn", "text": f"*Bucket:*\n{payload['bucket_start']}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Reason:* {payload['reason']}"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"{payload['source']} · {payload['fired_at']}"}
            ]},
        ],
    }


def build_discord_message(payload: dict) -> dict:
    """Discord rich-embed incident message."""
    emoji = _SEVERITY_EMOJI.get(payload["severity"], "🔔")
    return {
        "content": f"{emoji} **{payload['severity'].upper()}** error spike detected",
        "embeds": [{
            "title": f"{payload['service']} — error spike",
            "description": payload["reason"],
            "color": _SEVERITY_COLOR.get(payload["severity"], 0x95A5A6),
            "fields": [
                {"name": "Errors", "value": str(payload["error_count"]), "inline": True},
                {"name": "Baseline", "value": str(payload["baseline"]), "inline": True},
                {"name": "Z-score", "value": str(payload["zscore"]), "inline": True},
                {"name": "Bucket", "value": payload["bucket_start"], "inline": False},
            ],
            "footer": {"text": f"{payload['source']}"},
            "timestamp": payload["fired_at"],
        }],
    }


def format_for_target(payload: dict, webhook_type: str) -> dict:
    """Return the concrete request body for the given webhook flavour."""
    if webhook_type == "slack":
        return build_slack_message(payload)
    if webhook_type == "discord":
        return build_discord_message(payload)
    return payload


def fire_alert(db: Session, anomaly: Anomaly) -> AlertLog:
    """Send (or simulate) a webhook alert for an anomaly and record it."""
    payload = build_payload(anomaly)
    target = settings.webhook_url or "local-sink"
    webhook_type = detect_webhook_type(settings.webhook_url)
    status = "simulated"

    if settings.webhook_url:
        body = format_for_target(payload, webhook_type)
        try:
            resp = httpx.post(settings.webhook_url, json=body, timeout=settings.webhook_timeout)
            status = f"sent:{webhook_type}:{resp.status_code}"
        except httpx.HTTPError as exc:  # network failure => degrade gracefully
            status = f"failed:{webhook_type}:{type(exc).__name__}"

    alert = AlertLog(
        anomaly_id=anomaly.id,
        service=anomaly.service,
        payload=json.dumps(payload),
        target=target,
        status=status,
    )
    db.add(alert)
    anomaly.alert_sent = True
    db.commit()
    db.refresh(alert)

    # Console visibility for SRE demo
    print(f"[ALERT] {anomaly.severity.upper()} {anomaly.service} -> {target} ({status})")
    return alert


def fire_pending_alerts(db: Session, anomalies: list[Anomaly]) -> list[AlertLog]:
    """Fire alerts for any anomalies that have not yet been alerted."""
    fired: list[AlertLog] = []
    for anomaly in anomalies:
        if not anomaly.alert_sent:
            fired.append(fire_alert(db, anomaly))
    return fired

