"""Runtime settings. Environment variables and an optional .env file override defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    demo_mode: bool = False
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    llm_max_retries: int = 3
    default_schema: str = "coi"

    watch_dir: Path = Path("inbox")
    watch_enabled: bool = False
    watch_interval_seconds: float = 5
    samples_dir: Path = Path("samples")
    data_dir: Path = Path("data")
    database_path: Path = Path("data/extractor.db")
    csv_path: Path = Path("data/extractions.csv")
    reminder_preview_path: Path = Path("data/reminder_preview.txt")
    schema_dir: Path = Path("schemas")
    process_samples_on_start: bool = False

    reminder_days: int = 30
    reminder_dry_run: bool = True
    reminder_to: str = "project-manager@example.com"
    reminder_from: str = "reminders@example.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    scheduler_enabled: bool = False
    scheduler_hour: int = 8
    scheduler_minute: int = 0

    google_service_account_file: str = ""
    google_sheet_id: str = ""
    google_worksheet: str = "Extractions"

    imap_enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    alert_webhook_url: str = ""
    alert_webhook_type: str = "slack"
    telegram_chat_id: str = ""

    ocr_enabled: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8741

    text_char_limit: int = Field(default=20000)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_settings(**overrides: object) -> Settings:
    """Return settings, with explicit overrides winning over the environment."""
    base = Settings()
    if not overrides:
        return base
    return base.model_copy(update=overrides)
