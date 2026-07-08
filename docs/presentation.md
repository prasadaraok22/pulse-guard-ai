---
marp: true
theme: uncover
class: invert
paginate: true
title: Pulse Guard AI — Intelligent Observability & Event Watchdog
---

<!-- Render: `npx @marp-team/marp-cli docs/presentation.md -o deck.pdf`  (or open in VS Code Marp preview) -->

# 🛡️ Pulse Guard AI
### Intelligent Observability & Event Watchdog

**Graduate Vibe Coding Challenge — Project 3 (SRE)**

*Architect-directed. AI-engineered. Human-in-the-loop.*

---

## The Problem

Modern cloud platforms emit **millions of log lines**. Buried inside are the
**error spikes** that precede outages.

- 🔍 Manual log-watching doesn't scale
- ⏰ Static thresholds are noisy & miss creeping degradation
- 🚨 Alerts arrive **after** customers already feel the pain

> SREs need an **automated watchdog** that learns normal and flags abnormal.

---

## The Vision

An **API-first**, **AI-driven** service that:

1. **Ingests** application/platform logs (any format)
2. **Learns** each service's normal error baseline
3. **Detects** anomalies / spikes with explainable statistics
4. **Explains** spikes with optional LLM root-cause + remediation
5. **Alerts** via real Slack / Discord webhooks
6. **Visualizes** health trends on a live dashboard

---

## Architecture

```
 Logs ─▶ /api/ingest ─▶ Parser ─▶ DB ─▶ Anomaly Engine (Z-score + EWMA)
   ▲         │              (SQLite/PG)          │
   │         │                        threshold breached?
 Watch dir ──┘                                   ▼
 (poller)                        🤖 LLM enrichment (opt-in, severity-gated, cached)
                                                 │
                        Slack / Discord webhook ─┴─▶ Dashboard (Chart.js)
```

**API-first · Free DB · Explainable AI · Optional GenAI · Real alerts**

---

## Tech Stack

| Layer      | Technology            | Why |
|------------|-----------------------|-----|
| API        | FastAPI + Uvicorn     | Async, auto OpenAPI docs |
| Database   | SQLite / Postgres     | Free-tier, one-env-var swap |
| AI Logic   | Rolling Z-score + EWMA| Explainable, dependency-light |
| GenAI      | Opt-in LLM enrichment | Root-cause, label, triage |
| Scheduler  | APScheduler           | Continuous log polling |
| Alerting   | httpx → Slack/Discord | Real incident delivery |
| Dashboard  | HTML + Chart.js       | Live health trends |

---

## AI Logic — How Detection Works

Two layers: a **deterministic** detector (always on) + **optional GenAI**.

For each service, per 60-second bucket of **error** events:

- **EWMA baseline** adapts to traffic: `ewma = α·count + (1-α)·ewma`
- **Rolling Z-score**: `z = (count − mean) / std`
- **Spike** flagged when `count ≥ 5` **and** `z ≥ 3` **and** `count > baseline`
- **Severity**: `z ≥ 6` → 🔴 critical, `z ≥ 3` → 🟠 warning

> The statistical engine is the **sole trigger** — explainable, no black box.
> The LLM only *annotates* (next slide), so detection stays deterministic.

---

## Anomaly Coverage (Enterprise Test Data)

10-service, ~13k-line synthetic dataset — **8 fault patterns + 2 healthy**:

| Pattern | Example | Result |
|---|---|---|
| Sudden spike | payment-svc | 🚨 |
| Gradual creep | search-svc | 🚨 |
| Sustained outage | db-proxy | 🚨 |
| Cascade | gateway → auth | 🚨 |
| Periodic burst | batch-worker | 🚨 |
| Recovery | recommendation | 🚨 |
| JSON-format spike | inventory-svc | 🚨 |
| Sub-threshold / healthy | notifications, cdn-edge | ✅ silent |

---

## Continuous Watchdog Mode

Background **APScheduler** tails `*.log` files in a watch directory:

- ⚡ Ingests only **new** bytes each tick (offset tracking)
- 🔄 Handles **log rotation** / truncation
- 🧠 Runs detection + fires alerts automatically
- 🎛️ Controllable via API & dashboard (start / stop / poll now)

```bash
PULSE_POLL_ENABLED=true uvicorn app.main:app
echo "... ERROR [svc] boom" >> ingest_watch/svc.log   # auto-detected
```

---

## Real Alerting — Slack & Discord

Auto-detects the webhook flavour from its URL:

- **Slack** → Block Kit incident message
- **Discord** → color-coded rich embed
- **Generic** → raw incident JSON
- **No URL** → local sink (fully demoable offline)

```bash
PULSE_WEBHOOK_URL=https://hooks.slack.com/services/T/B/X \
  uvicorn app.main:app
```

---

## 🤖 Optional LLM Enrichment (opt-in)

The statistical engine triggers; the LLM **annotates** — never disrupts the
deterministic core. Off by default, zero new deps (`httpx`), fail-safe.

- 🧠 **Summarizer** → root-cause hypothesis + remediation
- 🏷️ **Classifier** → short label (e.g. `DB timeout`)
- 🚦 **Triage** → business-impact rating (low → critical)

Shown in the dashboard **AI Insight** column + Slack/Discord embeds.

**Cost controls:**

- **Severity gate** — auto-enrich only ≥ `PULSE_LLM_MIN_SEVERITY` (default critical)
- **Signature cache** — normalize (mask numbers/IPs/UUIDs) + hash → reuse answers
  for repeated spikes with **zero** API calls
- Any OpenAI-compatible endpoint (OpenAI, Azure, OpenRouter, local ollama)

```bash
PULSE_LLM_ENABLED=true PULSE_LLM_API_KEY=sk-... uvicorn app.main:app
```

---

## Live Dashboard

- 📊 **Health score** + error-rate trend chart (Chart.js)
- 🚨 Detected anomalies table (severity, z-score, baseline, **AI Insight**)
- 📨 Fired webhook alerts log
- 🎛️ Poller controls + one-click demo / enterprise data
- 🤖 AI-enrichment status badge (model + cache hits)
- 🔄 Auto-refresh every 15s

---

## Quality & Testing

- ✅ **33 automated tests** (pytest) — parser, detection, scenarios, scheduler
  tailing/rotation, Slack/Discord payloads, LLM enrichment (mocked)
- ✅ True-positive **and** true-negative anomaly coverage
- ✅ LLM tests: severity gating, signature caching, fail-safe, default-off
- ✅ **CI** on push/PR — SQLite + Postgres suites, Docker build, secret-gated
  real-LLM smoke test
- ✅ Graceful degradation (webhook/LLM failures never crash ingestion)

---

## Vibe Coding Workflow

- 🧭 **Architect** sets vision & rules; **AI** writes 100% of code
- 📝 `prompts.md` — full human-in-the-loop audit log
- ⏱️ MVP delivered well within the 4–6h target window
- 🔁 Bugs fixed by describing them to the AI — **zero manual edits**

---

## Roadmap

- ✅ **Shipped:** opt-in LLM enrichment, Docker + Postgres, CI pipeline
- 🌊 Kafka streaming ingestion (opt-in adapter, partition-by-service scale)
- 🤖 ML detectors (seasonal Holt-Winters, isolation forest)
- 🔗 Native cloud log sources (CloudWatch, Azure Monitor)
- 📈 Per-metric detection (latency, throughput, saturation)
- 🧵 LLM incident correlation across cascading services

---

# 🛡️ Pulse Guard AI

### Detect the spike. Explain it. Trigger the alert.

**Thank you.**

*API-first · Explainable AI + Optional GenAI · Human-in-the-loop*

