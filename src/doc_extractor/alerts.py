"""Optional Slack or Telegram notification when processing fails."""

from __future__ import annotations

import logging

import httpx

from doc_extractor.config import Settings
from doc_extractor.logging_config import log_event

logger = logging.getLogger("doc_extractor.alerts")


class AlertHook:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client

    def send(self, message: str) -> bool:
        url = self.settings.alert_webhook_url.strip()
        if not url:
            log_event(logger, logging.INFO, "alert_skipped", reason="no_webhook", alert=message)
            return False
        kind = self.settings.alert_webhook_type.lower().strip()
        if kind == "telegram":
            if not self.settings.telegram_chat_id:
                log_event(logger, logging.ERROR, "alert_skipped", reason="missing_telegram_chat_id")
                return False
            payload = {"chat_id": self.settings.telegram_chat_id, "text": message}
        else:
            payload = {"text": message}
        try:
            if self.client is not None:
                response = self.client.post(url, json=payload)
            else:
                response = httpx.post(url, json=payload, timeout=10)
        except Exception as exc:
            log_event(logger, logging.ERROR, "alert_failed", error=str(exc))
            return False
        if response.status_code >= 400:
            log_event(
                logger,
                logging.ERROR,
                "alert_rejected",
                status_code=response.status_code,
                body=response.text[:300],
            )
            return False
        log_event(logger, logging.INFO, "alert_sent", webhook_type=kind or "slack")
        return True
