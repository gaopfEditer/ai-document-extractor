from __future__ import annotations

from pathlib import Path

import pytest

from doc_extractor.config import Settings, load_settings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("WATCH_ENABLED", "false")
    monkeypatch.setenv("PROCESS_SAMPLES_ON_START", "false")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REMINDER_DRY_RUN", "true")
    data = tmp_path / "data"
    return load_settings(
        demo_mode=True,
        llm_provider="mock",
        reminder_dry_run=True,
        scheduler_enabled=False,
        watch_enabled=False,
        process_samples_on_start=False,
        data_dir=data,
        database_path=data / "extractor.db",
        csv_path=data / "extractions.csv",
        reminder_preview_path=data / "reminder_preview.txt",
        samples_dir=tmp_path / "samples",
        watch_dir=tmp_path / "inbox",
        reminder_days=30,
        reminder_to="project-manager@example.com",
        alert_webhook_url="",
    )
