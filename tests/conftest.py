"""Shared pytest fixtures + test isolation.

`settings` and the SQLAlchemy engine are process-level singletons, so we pin a
single fresh temp database for the whole test session (unique per run to avoid
stale data) and truncate all tables before every test for isolation.
"""
from __future__ import annotations

import os
import tempfile
import uuid

# MUST run before any `app.*` import so the engine binds to this DB.
# Honour PULSE_TEST_DATABASE_URL (e.g. Postgres in CI); else a fresh temp SQLite
# file, unique per run to avoid stale data.
_default = f"sqlite:///{os.path.join(tempfile.gettempdir(), f'pulse_test_{uuid.uuid4().hex}.db')}"
os.environ["PULSE_DATABASE_URL"] = os.environ.get("PULSE_TEST_DATABASE_URL", _default)

import pytest  # noqa: E402

from app.database import init_db, SessionLocal  # noqa: E402
from app.models import LogEvent, Anomaly, AlertLog  # noqa: E402
from app import scheduler  # noqa: E402
from app import llm  # noqa: E402

init_db()


@pytest.fixture(autouse=True)
def clean_state():
    """Wipe all tables + poller offsets + LLM cache before each test."""
    db = SessionLocal()
    try:
        db.query(AlertLog).delete()
        db.query(Anomaly).delete()
        db.query(LogEvent).delete()
        db.commit()
    finally:
        db.close()
    scheduler._offsets.clear()
    llm.cache_clear()
    yield

