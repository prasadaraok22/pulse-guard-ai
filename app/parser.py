"""Log parsing: turn raw log text into structured LogEvent rows.

Supports two shapes automatically:
  1. JSON-per-line (structured logs)
  2. Plaintext with a common pattern:  "<timestamp> <LEVEL> [service] message"
Anything unrecognised is stored as INFO so nothing is silently dropped.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

LEVELS = {"TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}

# 2024-05-01T12:00:00Z ERROR [payment-svc] connection refused
_PLAINTEXT = re.compile(
    r"^\s*(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)?\s*"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)?\s*"
    r"(?:\[(?P<service>[^\]]+)\])?\s*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)

_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def _parse_ts(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    value = value.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_level(level: Optional[str]) -> str:
    if not level:
        return "INFO"
    level = level.upper()
    if level == "WARNING":
        level = "WARN"
    return level if level in LEVELS or level == "WARN" else "INFO"


def parse_line(line: str, default_service: Optional[str] = None) -> Optional[dict]:
    """Parse one raw log line into a dict. Returns None for blank lines."""
    line = line.strip()
    if not line:
        return None

    # Try JSON first
    if line.startswith("{"):
        try:
            obj = json.loads(line)
            return {
                "service": str(obj.get("service") or obj.get("logger") or default_service or "unknown"),
                "level": _normalize_level(str(obj.get("level") or obj.get("severity") or "INFO")),
                "message": str(obj.get("message") or obj.get("msg") or ""),
                "timestamp": _parse_ts(str(obj.get("timestamp") or obj.get("time") or "")),
            }
        except (json.JSONDecodeError, ValueError):
            pass

    m = _PLAINTEXT.match(line)
    if not m:
        return {
            "service": default_service or "unknown",
            "level": "INFO",
            "message": line,
            "timestamp": _parse_ts(None),
        }

    return {
        "service": (m.group("service") or default_service or "unknown").strip(),
        "level": _normalize_level(m.group("level")),
        "message": (m.group("message") or "").strip(),
        "timestamp": _parse_ts(m.group("ts")),
    }


def parse_blob(content: str, default_service: Optional[str] = None) -> list[dict]:
    """Parse a multi-line log blob into a list of structured events."""
    events: list[dict] = []
    for line in content.splitlines():
        parsed = parse_line(line, default_service)
        if parsed:
            events.append(parsed)
    return events


def is_error(level: str) -> bool:
    return level.upper() in ERROR_LEVELS

