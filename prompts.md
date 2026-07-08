# Prompts Audit Log — Pulse Guard AI

This file is the required **Human-in-the-Loop audit trail**. Every architect
(user) prompt is recorded verbatim, along with the resulting action taken by the
AI engineer (GitHub Copilot).

---

## Turn 1 — Project Kickoff & Scaffolding

**Elapsed Time at start:** T+0:00

**Architect Prompt:**
> Lead Architect mode: ON. We are building a Python-based, API-first " Intelligent Observability & Event Watchdog" using a free database and a dashboard.
> Rules:
> 1. No Manual Edits: You provide all logic and fixes. I will not edit any code.
> 2. Audit Log: You must maintain a file named prompts.md. After every turn, update that file (or provide the text block) with the prompt I just used.
> 3. Time-Check: Start a timer. Goal is an MVP in 4-6 hours (Max window: 16h). Report 'Elapsed Time' at the end of every response. Acknowledge and let's start.
>
> Project : Intelligent Observability & Event Watchdog
> Focus: Site Reliability (SRE). Develop a service that parses application or platform logs to detect anomalies or "spikes" in errors using AI logic. When thresholds are breached, the system must trigger a simulated webhook alert and visualize health trends.

**AI Engineer Action:**
- Acknowledged Lead Architect mode and all 3 rules; started the timer.
- Chose stack: **FastAPI + Uvicorn** (API-first), **SQLite + SQLAlchemy 2.0** (free DB), **Chart.js** dashboard.
- Scaffolded the full MVP:
  - `requirements.txt` — pinned dependencies.
  - `app/config.py` — env-driven settings (detection thresholds, webhook URL).
  - `app/database.py` — SQLAlchemy engine/session/Base + `init_db`.
  - `app/models.py` — `LogEvent`, `Anomaly`, `AlertLog` tables.
  - `app/schemas.py` — Pydantic v2 request/response models.
  - `app/parser.py` — plaintext + JSON log parser with level normalization.
  - `app/anomaly.py` — **AI logic**: rolling-window Z-score + EWMA baseline spike detection.
  - `app/alerting.py` — simulated webhook alert firing + local sink.
  - `app/main.py` — FastAPI app: ingest, query, trends, health endpoints + dashboard.
  - `app/static/index.html` + `app/static/app.js` — Chart.js health-trend dashboard with live auto-refresh & one-click demo data.
  - `scripts/seed_demo.py` — synthetic log seeder with an intentional error spike.
  - `samples/sample_logs.txt` — mixed plaintext/JSON sample logs.
  - `tests/test_api.py` — 6 end-to-end tests (parser, ingest, detection, alerts, trends).

**Verification (live run):**
- Installed deps in `.venv`; `pytest` → **6 passed**.
- Ran server (port `8000` was occupied by another local app, so used **8100**).
- Seeded demo → `ingested: 740, parsed_errors: 98, anomalies_detected: 2, alerts_fired: 2`.
- Confirmed `/api/services`, `/api/anomalies`, `/api/alerts`, `/api/trends` (health_score 72.48) all return correctly.
- Detected a **critical** spike in `payment-svc` (25 errors, z=6.71) and fired simulated webhook alerts. ✅

**Note to Architect:** Port `8000` is already in use on this machine by another
service. Run with `uvicorn app.main:app --port 8100` (or any free port).

**Elapsed Time at end of Turn 1:** ~T+0:50

---

## Turn 2 — Enterprise Test Data & Anomaly Coverage

**Architect Prompt:**
> Add enterprise test data to ensure covers various anamoly detections

**AI Engineer Action:**
- Created `app/sample_data.py` — a single-source generator producing a realistic
  **10-service, ~13k-line** dataset (plaintext + JSON) tuned to the engine's
  thresholds (60s buckets, z≥3, min 5 errors/bucket).
- Covered **8 anomaly patterns** + **2 negative (must-not-alert) cases**:
  `SUDDEN_SPIKE`, `GRADUAL_CREEP`, `SUSTAINED_OUTAGE`, `CASCADE_GATEWAY`,
  `CASCADE_AUTH`, `PERIODIC_BURST`, `RECOVERY`, `JSON_SPIKE`, plus
  `HEALTHY_NOISE` (sub-threshold) and `STEADY_HEALTHY` (no errors).
- Added `POST /api/demo/enterprise` one-click endpoint + a **"Load Enterprise
  Data"** dashboard button, both reusing the shared generator.
- Refactored `scripts/seed_enterprise.py` to import from `app.sample_data`
  (no duplicate logic) with `--write` / `--no-post` flags; writes
  `samples/enterprise_logs.txt`.
- Added `tests/test_scenarios.py` — 7 scenario tests asserting each positive
  pattern is detected, JSON logs parse, spikes are `critical`, alerts carry the
  incident payload, and healthy services stay silent.
- Updated `README.md` with the scenario table + new endpoint.

**Verification (live run):**
- Full suite → **13 passed** (`6` core + `7` scenario).
- One-click endpoint & CLI both → `ingested: 13440, anomalies_detected: 14, alerts_fired: 14`.
- Result: **8/8 positive services flagged 🚨, 2/2 healthy services silent ✅** — exactly as designed.

**Elapsed Time at end of Turn 2:** ~T+1:35

---

## Turn 3 — Continuous Poller, Real Slack/Discord Webhooks & Presentation Deck

**Architect Prompt:**
> Add support background scheduler for continuous log polling, a real Slack/Discord webhook, or the submission presentation deck next

**AI Engineer Action — delivered all three:**

1. **Continuous log polling (background scheduler)**
   - `app/scheduler.py` — APScheduler poller that tails `*.log` files in a watch
     directory, ingesting only **new** bytes per tick (offset tracking +
     **rotation** handling), then runs detection & fires alerts.
   - Wired into app `lifespan` (auto-start via `PULSE_POLL_ENABLED`) with
     `/api/scheduler/{status,start,stop,poll}` endpoints + a dashboard control card.
   - `ingest_watch/` watch directory (README + git-ignored `*.log`).

2. **Real Slack / Discord webhooks**
   - Rebuilt `app/alerting.py`: auto-detects flavour from the URL
     (`hooks.slack.com` → Slack Block Kit, `discord.com/api/webhooks` → rich
     embed), `PULSE_WEBHOOK_TYPE` override, generic JSON + local-sink fallback.
   - Severity-colored embeds; graceful degradation on network errors.

3. **Submission presentation deck**
   - `docs/presentation.md` — 16-slide Marp deck (problem, vision, architecture,
     AI logic, coverage, watchdog, alerting, dashboard, testing, roadmap).

4. **Test-isolation hardening**
   - Added `tests/conftest.py` (single fresh session DB + per-test table wipe +
     poller offset reset), fixing cross-module contamination / stale-anomaly
     flakiness. Refactored tests to be self-seeding.
   - New suites: `tests/test_scheduler.py` (tailing, rotation, start/stop),
     `tests/test_alerting.py` (Slack/Discord/generic payloads + detection).

**Verification (live run):**
- Full suite → **22 passed**.
- Poller live test: dropped a spike into `ingest_watch/checkout-svc.log`; poller
  auto-ingested 26 lines and flagged a **critical** anomaly (z=19) + alert:
  `[POLL] ingested=26 anomalies=1 alerts=1`. ✅

**Elapsed Time at end of Turn 3:** ~T+2:45

---

## Turn 4 — PPTX Deck, Docker + Postgres, GitHub Actions CI

**Architect Prompt:**
> Render the deck to PPTX, add a Dockerfile + Postgres option for deployment and wire a GitHub Actions CI to run the tests on push

**AI Engineer Action — delivered all three:**

1. **PPTX deck**
   - Rendered `docs/presentation.md` → `docs/PulseGuardAI.pptx` (2.6 MB) via
     `@marp-team/marp-cli`. Regenerate command documented in the README.

2. **Docker + Postgres deployment**
   - `Dockerfile` — slim Python 3.11 image, layer-cached deps, non-root user,
     `curl` healthcheck on `/api/health`.
   - `docker-compose.yml` — app + `postgres:16` with healthcheck, volume, and
     env wiring (`PULSE_DATABASE_URL=postgresql+psycopg2://…`, poller enabled).
   - `.dockerignore`; added `psycopg2-binary` to `requirements.txt`.
   - `app/database.py` — `pool_pre_ping` for non-SQLite engines; DB swappable
     via a single env var.

3. **GitHub Actions CI** (`.github/workflows/ci.yml`, on push/PR)
   - **Tests (SQLite)** — full pytest suite.
   - **Tests (Postgres)** — full suite against a Postgres service container
     (via new `PULSE_TEST_DATABASE_URL` honored by `conftest.py`).
   - **Docker build** — validates the image builds.
   - Added a CI status badge to the README.

**Verification (live run):**
- PPTX generated & validated (valid OOXML zip, 2.6 MB).
- Installed `psycopg2-binary`; full suite → **22 passed**.
- Docker daemon offline locally → build validated by the CI `docker-build` job.

**Elapsed Time at end of Turn 4:** ~T+3:25

---

## Turn 5 — PDF Deck, .env.example & Architecture Diagram

**Architect Prompt:**
> Also add a PDF export of the deck, a .env.example file, or a short architecture diagram image for the repo

**AI Engineer Action — delivered all three:**

1. **PDF deck** — rendered `docs/presentation.md` → `docs/PulseGuardAI.pdf`
   (503 KB, PDF 1.7) via `@marp-team/marp-cli`. Regenerate command in README.

2. **`.env.example`** — documented every `PULSE_*` variable (database,
   detection tuning, Slack/Discord webhook, poller, testing override) with
   sensible defaults and copy-to-`.env` guidance.

3. **Architecture diagram** — hand-authored `docs/architecture.svg` (dark theme
   matching the dashboard) showing Sources → Parser → DB → AI Engine →
   Alerting/Dashboard flow. Embedded at the top of the README (with the text
   diagram kept as a `<details>` fallback).

**Verification:**
- PDF validated (PDF 1.7); SVG validated as well-formed XML.
- All three artifacts confirmed **git-tracked** (not ignored).

**Elapsed Time at end of Turn 5:** ~T+3:50


