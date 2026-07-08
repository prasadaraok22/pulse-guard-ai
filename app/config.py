"""Application configuration via environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Pulse Guard AI."""

    model_config = SettingsConfigDict(env_prefix="PULSE_", env_file=".env", extra="ignore")

    # Database
    database_url: str = "sqlite:///./pulse_guard.db"

    # Anomaly detection tuning
    window_size: int = 12          # number of buckets in the rolling window
    bucket_seconds: int = 60       # size of each time bucket (seconds)
    zscore_threshold: float = 3.0  # z-score above which a spike is flagged
    ewma_alpha: float = 0.3        # smoothing factor for EWMA baseline
    min_events_for_alert: int = 5  # minimum errors in a bucket before alerting

    # Webhook alerting
    webhook_url: str = ""          # external webhook (empty => local sink only)
    webhook_type: str = "auto"     # auto | slack | discord | generic
    webhook_timeout: float = 5.0

    # Continuous log polling (background scheduler)
    poll_enabled: bool = False           # auto-start the poller on app startup
    poll_directory: str = "./ingest_watch"  # directory to watch for *.log files
    poll_glob: str = "*.log"             # filename pattern to tail
    poll_interval_seconds: int = 30      # how often to poll

    # App
    app_name: str = "Pulse Guard AI"


settings = Settings()

