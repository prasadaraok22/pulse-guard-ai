"""Opt-in LLM enrichment for anomalies (OFF by default).

When `PULSE_LLM_ENABLED=true` and an API key is set, each newly detected spike
is enriched with:

  * root-cause hypothesis + suggested remediation (summarizer)
  * a short error label / classification (e.g. "DB timeout")
  * a business-impact / triage rating (low | medium | high | critical)

Design goals:
  - **Zero disruption to the deterministic core**: the statistical engine
    remains the sole trigger; the LLM only *annotates* existing anomalies.
  - **Zero new dependencies**: uses the already-present `httpx` to call any
    OpenAI-compatible `/chat/completions` endpoint (OpenAI, Azure, OpenRouter,
    local llama.cpp/ollama proxies, ...).
  - **Fail-safe**: if disabled, unconfigured, or the call errors/times out, we
    silently no-op — ingestion, detection and alerting never break.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, OrderedDict

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LogEvent, Anomaly
from app.parser import ERROR_LEVELS
from app.anomaly import _bucket_key

_VALID_IMPACT = {"low", "medium", "high", "critical"}
_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

# In-memory LRU cache: error-signature -> enrichment result dict.
_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_stats = {"hits": 0, "misses": 0}


def is_enabled() -> bool:
    """True only when the feature is switched on AND an API key is present."""
    return bool(settings.llm_enabled and settings.llm_api_key)


def _severity_rank(name: str) -> int:
    return _SEVERITY_RANK.get((name or "").lower(), 0)


def passes_severity(anomaly: Anomaly) -> bool:
    """True if the anomaly is severe enough to auto-enrich (cost control)."""
    return _severity_rank(anomaly.severity) >= _severity_rank(settings.llm_min_severity)


def should_auto_enrich(anomaly: Anomaly) -> bool:
    return is_enabled() and not anomaly.llm_enriched and passes_severity(anomaly)


def status() -> dict:
    """Report LLM configuration (safe: never returns the API key)."""
    return {
        "enabled": bool(settings.llm_enabled),
        "configured": bool(settings.llm_api_key),
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "features": {
            "summarize": settings.llm_summarize,
            "classify": settings.llm_classify,
            "triage": settings.llm_triage,
        },
        "min_severity": settings.llm_min_severity,
        "cache": {
            "enabled": int(settings.llm_cache_enabled),
            "size": len(_cache),
            "hits": _cache_stats["hits"],
            "misses": _cache_stats["misses"],
        },
    }


def sample_error_messages(db: Session, anomaly: Anomaly) -> list[tuple[str, int]]:
    """Return the most common error messages in the anomaly's time bucket."""
    rows = db.execute(
        select(LogEvent.message, LogEvent.timestamp)
        .where(LogEvent.service == anomaly.service)
        .where(LogEvent.level.in_(ERROR_LEVELS))
    ).all()

    counter: Counter[str] = Counter()
    for message, ts in rows:
        if _bucket_key(ts, settings.bucket_seconds) == anomaly.bucket_start:
            counter[(message or "").strip()] += 1
    return counter.most_common(settings.llm_max_messages)


# --- Error-signature (for caching) ------------------------------------------ #
_NORMALIZERS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b"), "<uuid>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"\d+"), "<n>"),          # numbers, even when glued to units (500ms)
    (re.compile(r"\s+"), " "),
]


def _normalize(message: str) -> str:
    text = (message or "").lower().strip()
    for pattern, repl in _NORMALIZERS:
        text = pattern.sub(repl, text)
    return text.strip()


def signature(samples: list[tuple[str, int]]) -> str:
    """Stable hash of the normalized error-message templates in this spike."""
    templates = sorted({_normalize(msg) for msg, _ in samples if msg})
    basis = "|".join(templates) or "empty"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _cache_get(sig: str) -> dict | None:
    if not settings.llm_cache_enabled:
        return None
    if sig in _cache:
        _cache.move_to_end(sig)          # LRU touch
        _cache_stats["hits"] += 1
        return _cache[sig]
    _cache_stats["misses"] += 1
    return None


def _cache_put(sig: str, result: dict) -> None:
    if not settings.llm_cache_enabled:
        return
    _cache[sig] = result
    _cache.move_to_end(sig)
    while len(_cache) > settings.llm_cache_max:
        _cache.popitem(last=False)       # evict least-recently-used


def cache_clear() -> None:
    _cache.clear()
    _cache_stats["hits"] = 0
    _cache_stats["misses"] = 0


def _build_prompt(anomaly: Anomaly, samples: list[tuple[str, int]]) -> list[dict]:
    lines = [f"- ({count}x) {msg}" for msg, count in samples if msg]
    sample_block = "\n".join(lines) if lines else "(no message text available)"
    wanted = []
    if settings.llm_summarize:
        wanted.append('"root_cause" (1-2 sentence hypothesis), "remediation" (concrete next step)')
    if settings.llm_classify:
        wanted.append('"label" (<= 4 words, e.g. "DB timeout")')
    if settings.llm_triage:
        wanted.append('"impact" (one of: low, medium, high, critical)')
    fields = "; ".join(wanted)

    system = (
        "You are an SRE incident assistant. Given a burst of error logs from one "
        "service, respond with STRICT JSON only (no markdown), with keys: "
        f"{fields}. Be concise and specific; do not invent details not implied "
        "by the logs."
    )
    user = (
        f"Service: {anomaly.service}\n"
        f"Spike: {anomaly.error_count} errors in a {settings.bucket_seconds}s window "
        f"(baseline≈{anomaly.baseline}, z-score={anomaly.zscore}, severity={anomaly.severity}).\n"
        f"Top error messages:\n{sample_block}\n\n"
        "Return the JSON object now."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _call_llm(messages: list[dict]) -> dict | None:
    """Call an OpenAI-compatible chat-completions endpoint; parse JSON reply."""
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(url, headers=headers, json=body, timeout=settings.llm_timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _safe_parse_json(content)


def _safe_parse_json(content: str) -> dict | None:
    content = (content or "").strip()
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # tolerate models that wrap JSON in prose/code fences
        start, end = content.find("{"), content.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(content[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
        return None


def _apply(anomaly: Anomaly, result: dict, sig: str | None = None) -> None:
    if settings.llm_classify:
        label = str(result.get("label") or "").strip()[:64]
        anomaly.llm_label = label or None
    if settings.llm_summarize:
        rc = str(result.get("root_cause") or "").strip()
        rem = str(result.get("remediation") or "").strip()
        anomaly.llm_root_cause = rc or None
        anomaly.llm_remediation = rem or None
        parts = [p for p in (rc, (f"Fix: {rem}" if rem else "")) if p]
        anomaly.llm_summary = " ".join(parts) or None
    if settings.llm_triage:
        impact = str(result.get("impact") or "").strip().lower()
        anomaly.llm_impact = impact if impact in _VALID_IMPACT else None
    if sig:
        anomaly.llm_signature = sig
    anomaly.llm_enriched = True


def maybe_enrich(db: Session, anomaly: Anomaly, force: bool = False) -> bool:
    """Enrich a single anomaly in place if enabled. Returns True if applied.

    * Auto path (force=False): only enriches spikes at/above
      ``PULSE_LLM_MIN_SEVERITY`` (cost control).
    * ``force=True`` (manual endpoint): bypasses the severity gate.
    * Results are cached by **error-signature** so repeated/similar spikes reuse
      a prior answer with **no** API call.

    Fail-safe: any error (network, parse, config) is swallowed so the core
    pipeline never breaks.
    """
    if not is_enabled() or anomaly.llm_enriched:
        return False
    if not force and not passes_severity(anomaly):
        return False
    try:
        samples = sample_error_messages(db, anomaly)
        sig = signature(samples)

        cached = _cache_get(sig)
        if cached is not None:
            _apply(anomaly, cached, sig)
            db.add(anomaly)
            db.commit()
            db.refresh(anomaly)
            print(f"[LLM] cache HIT {anomaly.service} sig={sig} "
                  f"label={anomaly.llm_label!r}")
            return True

        result = _call_llm(_build_prompt(anomaly, samples))
        if not result:
            return False
        _cache_put(sig, result)
        _apply(anomaly, result, sig)
        db.add(anomaly)
        db.commit()
        db.refresh(anomaly)
        print(f"[LLM] cache MISS {anomaly.service} sig={sig} "
              f"label={anomaly.llm_label!r} impact={anomaly.llm_impact!r}")
        return True
    except Exception as exc:  # noqa: BLE001 — never let enrichment crash ingestion
        print(f"[LLM][WARN] enrichment skipped: {type(exc).__name__}: {exc}")
        db.rollback()
        return False


def enrich_anomalies(db: Session, anomalies: list[Anomaly]) -> int:
    """Enrich a batch of anomalies (auto path); returns how many were enriched."""
    if not is_enabled():
        return 0
    return sum(1 for a in anomalies if maybe_enrich(db, a))


def enrich_anomalies(db: Session, anomalies: list[Anomaly]) -> int:
    """Enrich a batch of anomalies; returns how many were enriched."""
    if not is_enabled():
        return 0
    return sum(1 for a in anomalies if maybe_enrich(db, a))

