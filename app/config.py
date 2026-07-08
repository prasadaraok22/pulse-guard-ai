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

    # LLM enrichment (OPT-IN — off by default, zero external deps when disabled)
    llm_enabled: bool = False            # master switch for all LLM features
    llm_api_key: str = ""                # provider API key (required when enabled)
    llm_base_url: str = "https://api.openai.com/v1"  # OpenAI-compatible endpoint
    llm_model: str = "gpt-4o-mini"       # chat-completions model name
    llm_timeout: float = 20.0            # per-call timeout (seconds)
    llm_max_messages: int = 12           # top error messages sampled per anomaly
    llm_summarize: bool = True           # root-cause + remediation summary
    llm_classify: bool = True            # error label (e.g. "DB timeout")
    llm_triage: bool = True              # business-impact rating
    # Cost controls
    llm_min_severity: str = "critical"   # auto-enrich only >= this (info|warning|critical)
    llm_cache_enabled: bool = True       # reuse results by error-signature
    llm_cache_max: int = 512             # max cached signatures (LRU eviction)

    # App
    app_name: str = "Pulse Guard AI"


settings = Settings()

