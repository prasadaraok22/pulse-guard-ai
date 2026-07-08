# Pulse Guard AI

> **AI-powered SRE watchdog that parses logs, detects error spikes, and fires real-time webhook alerts with live health dashboards.**

📦 **Repository:** https://github.com/prasadaraok22/pulse-guard-ai

[![CI](https://github.com/prasadaraok22/pulse-guard-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/prasadaraok22/pulse-guard-ai/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)

An AI-powered **Intelligent Observability & Event Watchdog** for modern cloud
applications. Pulse Guard ingests application/platform logs, detects error
**spikes/anomalies** using statistical AI logic, fires **simulated webhook
alerts** when thresholds are breached, and **visualizes health trends** on a
live dashboard.

> Graduate Vibe Coding Challenge — Project 3 (SRE / Observability).
> Built API-first in Python with a free database, fully via AI orchestration.

---

## ✨ Features

- **API-first** ingestion (raw log blobs, structured events, or file upload).
- **Smart log parser** — handles plaintext and JSON-per-line formats.
- **AI anomaly detection** — rolling-window **Z-score** + **EWMA** baseline to
  catch error spikes while adapting to normal traffic.
- **Optional LLM enrichment** (opt-in, off by default) — annotates each spike
  with a root-cause hypothesis, remediation, error label, and impact rating;
  attached to the alert & Slack/Discord message.
- **Continuous watchdog** — background **APScheduler** tails `*.log` files in a
  watch directory (offset tracking + rotation handling), auto-detecting & alerting.
- **Real webhook alerting** — auto-detects **Slack** (Block Kit) / **Discord**
  (rich embed) from the URL, or records to a local sink for demos.
- **Live dashboard** (Chart.js) — health score, error trends, anomalies, alerts,
  and poller controls with auto-refresh and one-click demo data.
- **Free database** — SQLite out of the box (swap to Postgres via one env var).

## 🏗️ Architecture

![Pulse Guard AI architecture](docs/architecture.svg)

<details>
<summary>Text diagram</summary>

```
 Logs ─▶ /api/ingest ─▶ Parser ─▶ SQLite ─▶ Anomaly Engine (Z-score + EWMA)
   ▲         │                                      │
 Watch dir ──┘                          threshold breached?
 (poller)                                          ▼
                         Slack / Discord webhook ─▶ Dashboard (Chart.js)
```
</details>

| Layer      | Technology            |
|------------|-----------------------|
| API        | FastAPI + Uvicorn     |
| Database   | SQLite + SQLAlchemy 2 |
| AI Logic   | Rolling Z-score + EWMA|
| Alerting   | httpx webhook POST    |
| Dashboard  | HTML + Chart.js       |

## 🚀 Quickstart

```bash
# 1. Create & activate a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 2b. (optional) copy the sample env and tweak settings
cp .env.example .env

# 3. Run the API + dashboard
uvicorn app.main:app --reload

# (If port 8000 is busy, pick another, e.g. --port 8100)

# 4. Open the dashboard
open http://localhost:8000          # dashboard
open http://localhost:8000/docs     # interactive API docs
```

### Load demo data

Click **"Load Demo Data"** on the dashboard, or run:

```bash
python scripts/seed_demo.py
```

This ingests ~20 minutes of synthetic traffic with a deliberate error spike in
`payment-svc`, which the engine flags as an anomaly and fires an alert for.

### Load enterprise test data (full anomaly coverage)

Click **"Load Enterprise Data"** on the dashboard, hit `POST /api/demo/enterprise`,
or run the CLI seeder:

```bash
python scripts/seed_enterprise.py            # generate + POST to the API
python scripts/seed_enterprise.py --write    # also write samples/enterprise_logs.txt
```

This generates a realistic **10-service** dataset (~13k log lines, plaintext +
JSON) that exercises **every** detection pattern, and includes healthy services
that must *not* alert:

| Service              | Scenario           | Expected            |
|----------------------|--------------------|---------------------|
| `payment-svc`        | `SUDDEN_SPIKE`     | 🚨 critical         |
| `search-svc`         | `GRADUAL_CREEP`    | 🚨 ramping          |
| `db-proxy`           | `SUSTAINED_OUTAGE` | 🚨 multi-bucket     |
| `api-gateway`        | `CASCADE_GATEWAY`  | 🚨 correlated       |
| `auth-svc`           | `CASCADE_AUTH`     | 🚨 correlated       |
| `batch-worker`       | `PERIODIC_BURST`   | 🚨 repeating        |
| `recommendation-svc` | `RECOVERY`         | 🚨 spike + recover  |
| `inventory-svc`      | `JSON_SPIKE`       | 🚨 (JSON logs)      |
| `notifications-svc`  | `HEALTHY_NOISE`    | ✅ no alert (<5/min)|
| `cdn-edge`           | `STEADY_HEALTHY`   | ✅ no alert         |

The generator lives in `app/sample_data.py` (single source of truth), shared by
the CLI, the API endpoint, and the scenario tests.

## 🔌 API Reference

| Method | Endpoint              | Description                                   |
|--------|-----------------------|-----------------------------------------------|
| POST   | `/api/ingest/raw`     | Ingest a raw multi-line log blob              |
| POST   | `/api/ingest/events`  | Ingest structured log events (JSON array)     |
| POST   | `/api/ingest/file`    | Upload a log file                             |
| POST   | `/api/demo/enterprise`| Seed the enterprise anomaly-coverage dataset  |
| GET    | `/api/services`       | List services with total/error counts         |
| GET    | `/api/anomalies`      | List detected anomalies                       |
| GET    | `/api/alerts`         | List fired (simulated) webhook alerts         |
| GET    | `/api/trends`         | Bucketed health trend + health score          |
| GET    | `/api/scheduler/status`| Continuous poller status                      |
| POST   | `/api/scheduler/start`| Start continuous log polling                  |
| POST   | `/api/scheduler/stop` | Stop continuous log polling                   |
| POST   | `/api/scheduler/poll` | Poll the watch directory once, now            |
| GET    | `/api/llm/status`     | LLM enrichment status (enabled/configured)    |
| POST   | `/api/anomalies/{id}/enrich` | Manually run LLM enrichment on an anomaly |
| GET    | `/api/health`         | Service liveness                              |

### Example

```bash
curl -X POST http://localhost:8000/api/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"content": "2024-05-01T12:01:00Z ERROR [payment-svc] timeout"}'
```

## 🔔 Real Slack / Discord alerting

Set a webhook URL — the flavour is auto-detected (or force with `PULSE_WEBHOOK_TYPE`):

```bash
# Slack (Block Kit message)
PULSE_WEBHOOK_URL=https://hooks.slack.com/services/T00/B00/XXXX uvicorn app.main:app

# Discord (rich embed)
PULSE_WEBHOOK_URL=https://discord.com/api/webhooks/123/abcxyz uvicorn app.main:app
```

With no URL configured, alerts are recorded to a **local sink** so the flow is
fully demonstrable offline.

## 🐕 Continuous log polling (watchdog mode)

The background scheduler tails `*.log` files in a watch directory, ingesting only
new lines each tick (with rotation handling), then detects & alerts:

```bash
PULSE_POLL_ENABLED=true PULSE_POLL_INTERVAL_SECONDS=10 uvicorn app.main:app --port 8100

# feed it — filename (sans extension) becomes the service name
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ERROR [payment-svc] timeout" >> ingest_watch/payment-svc.log
```

Control it at runtime via the dashboard **Continuous Log Poller** card or the
`/api/scheduler/*` endpoints.

## 🤖 Optional LLM enrichment (opt-in)

The statistical engine is the **sole trigger** for anomalies — it never calls an
LLM. When you opt in, detected spikes are additionally *annotated* by an LLM:

- **Summarizer** — root-cause hypothesis + suggested remediation
- **Classifier** — a short error label (e.g. `DB timeout`, `auth failure`)
- **Triage** — a business-impact rating (`low`/`medium`/`high`/`critical`)

The insight is stored on the anomaly, shown on the dashboard (**AI Insight**
column), and embedded in the Slack/Discord alert. It's **off by default**, uses
the already-present `httpx` (no new dependencies), and is **fail-safe** — any
error or timeout is swallowed so ingestion/detection/alerting never break.

**Cost controls:**

- **Severity gating** — auto-enrichment only fires for spikes at/above
  `PULSE_LLM_MIN_SEVERITY` (default `critical`). Lower-severity spikes are
  skipped automatically; you can still enrich any anomaly manually via the API.
- **Response caching** — results are cached by **error-signature** (the
  normalized error-message templates, with numbers/IPs/UUIDs masked). Repeated
  or similar spikes reuse a prior answer with **no** API call. Cache hits/misses
  are visible on `GET /api/llm/status`.

```bash
# Any OpenAI-compatible endpoint (OpenAI, Azure, OpenRouter, local ollama proxy)
PULSE_LLM_ENABLED=true \
PULSE_LLM_API_KEY=sk-... \
PULSE_LLM_MODEL=gpt-4o-mini \
PULSE_LLM_MIN_SEVERITY=critical \
  uvicorn app.main:app --port 8100

# Check status (incl. cache stats) / manually enrich a specific anomaly
curl localhost:8100/api/llm/status
curl -X POST localhost:8100/api/anomalies/1/enrich
```

## ⚙️ Configuration

All settings are env vars with the `PULSE_` prefix (see `app/config.py`):

| Variable                  | Default                    | Meaning                          |
|---------------------------|----------------------------|----------------------------------|
| `PULSE_DATABASE_URL`      | `sqlite:///./pulse_guard.db` | DB connection string           |
| `PULSE_BUCKET_SECONDS`    | `60`                       | Time-bucket size for detection   |
| `PULSE_WINDOW_SIZE`       | `12`                       | Rolling window length (buckets)  |
| `PULSE_ZSCORE_THRESHOLD`  | `3.0`                      | Z-score to flag a spike          |
| `PULSE_EWMA_ALPHA`        | `0.3`                      | EWMA smoothing factor            |
| `PULSE_MIN_EVENTS_FOR_ALERT` | `5`                     | Min errors before alerting       |
| `PULSE_WEBHOOK_URL`       | `""`                       | Webhook to POST alerts to        |
| `PULSE_WEBHOOK_TYPE`      | `auto`                     | `auto`/`slack`/`discord`/`generic`|
| `PULSE_POLL_ENABLED`      | `false`                    | Auto-start the log poller        |
| `PULSE_POLL_DIRECTORY`    | `./ingest_watch`           | Directory of `*.log` to tail     |
| `PULSE_POLL_GLOB`         | `*.log`                    | Filename pattern to poll         |
| `PULSE_POLL_INTERVAL_SECONDS` | `30`                   | Poll frequency                   |
| `PULSE_LLM_ENABLED`       | `false`                    | Opt-in LLM enrichment master switch |
| `PULSE_LLM_API_KEY`       | `""`                       | LLM provider API key             |
| `PULSE_LLM_BASE_URL`      | `https://api.openai.com/v1`| OpenAI-compatible endpoint       |
| `PULSE_LLM_MODEL`         | `gpt-4o-mini`              | Chat-completions model           |
| `PULSE_LLM_MIN_SEVERITY`  | `critical`                | Auto-enrich only >= this severity |
| `PULSE_LLM_CACHE_ENABLED` | `true`                     | Cache LLM results by error-signature |

## 🧪 Tests

```bash
pip install pytest
pytest
```

## 🐳 Deployment (Docker + Postgres)

Run the full stack (app + Postgres) with one command:

```bash
docker compose up --build
# app       -> http://localhost:8000  (dashboard + /docs)
# postgres  -> localhost:5432 (pulse/pulse, db "pulseguard")
```

The app container is configured via env in `docker-compose.yml`:
`PULSE_DATABASE_URL=postgresql+psycopg2://pulse:pulse@db:5432/pulseguard`, with
the continuous poller enabled against the mounted `./ingest_watch` volume.

Build/run the image standalone:

```bash
docker build -t pulse-guard-ai .
docker run -p 8000:8000 \
  -e PULSE_DATABASE_URL=sqlite:////app/pulse_guard.db \
  pulse-guard-ai
```

Switch databases with a single env var — SQLite (default) or Postgres:

```bash
PULSE_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname uvicorn app.main:app
```

## ⚙️ Continuous Integration

`.github/workflows/ci.yml` runs on every push / PR:

- **Tests (SQLite)** — full pytest suite.
- **Tests (Postgres)** — same suite against a Postgres service container
  (via `PULSE_TEST_DATABASE_URL`).
- **Docker build** — validates the image builds.
- **LLM integration smoke** (secret-gated) — on push, runs a **real** LLM call
  against the model if an `OPENAI_API_KEY` repo secret is set; otherwise it
  skips cleanly. Add the secret under *Settings → Secrets and variables →
  Actions* to enable it.

## 📄 Project Docs

- `prompts.md` — full Human-in-the-Loop audit log of every architect prompt.
- `docs/architecture.svg` — architecture diagram (embedded above).
- `docs/presentation.md` — submission deck (Marp Markdown).
- `docs/PulseGuardAI.pptx` — rendered PowerPoint deck. Regenerate with:
  `npx @marp-team/marp-cli docs/presentation.md --pptx -o docs/PulseGuardAI.pptx`
- `docs/PulseGuardAI.pdf` — rendered PDF deck. Regenerate with:
  `npx @marp-team/marp-cli docs/presentation.md --pdf -o docs/PulseGuardAI.pdf`
- `.env.example` — sample environment configuration (copy to `.env`).
- `docs/tagle-tag.md` — Tagle "Tag" profile summary (Phase 1 deliverable).
- `info.md` — challenge brief.

## ✅ Submission Checklist

- [x] Python, API-first, free-tier DB (SQLite/Postgres), dashboard
- [x] Public GitHub repo — https://github.com/prasadaraok22/pulse-guard-ai
- [x] `prompts.md` full human-in-the-loop audit log
- [x] AI-generated deck — `docs/presentation.md` + `PulseGuardAI.pptx` / `.pdf`
- [ ] Tagle "Tag" summary — fill in `docs/tagle-tag.md` + attach screenshot
- [x] Cloud resources: **none provisioned** (local SQLite / optional local
  Postgres via Docker) — nothing to decommission

## 📜 License

Released under the [MIT License](LICENSE) — free to use, modify, and distribute.

