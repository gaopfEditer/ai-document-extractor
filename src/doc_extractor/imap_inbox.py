"""Optional IMAP poll. PDF attachments are extracted and passed through the same pipeline."""

from __future__ import annotations

import email
import imaplib
import logging
from email.message import Message

from doc_extractor.logging_config import log_event
from doc_extractor.pipeline import Pipeline

logger = logging.getLogger("doc_extractor.imap")


class ImapNotConfigured(RuntimeError):
    pass


def pdf_attachments(message: Message) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename or not filename.lower().endswith(".pdf"):
            continue
        payload = part.get_payload(decode=True)
        if payload:
            found.append((_safe_filename(filename), payload))
    return found


def _safe_filename(filename: str) -> str:
    return filename.replace("\\", "/").split("/")[-1]


def poll_inbox(pipeline: Pipeline) -> int:
    settings = pipeline.settings
    if not settings.imap_host or not settings.imap_user:
        raise ImapNotConfigured(
            "IMAP is not configured. Set IMAP_HOST, IMAP_USER, and IMAP_PASSWORD, then run poll-inbox."
        )
    client = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    processed = 0
    try:
        client.login(settings.imap_user, settings.imap_password)
        status, _data = client.select(settings.imap_folder)
        if status != "OK":
            raise RuntimeError(f"Could not open IMAP folder {settings.imap_folder}.")
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("IMAP search failed.")
        message_ids = data[0].split() if data and data[0] else []
        for number in message_ids:
            status, fetched = client.fetch(number, "(RFC822)")
            if status != "OK" or not fetched:
                continue
            for item in fetched:
                if not isinstance(item, tuple):
                    continue
                message = email.message_from_bytes(item[1])
                for filename, payload in pdf_attachments(message):
                    pipeline.process_bytes(
                        payload,
                        filename=filename,
                        schema_hint=None,
                        source="imap",
                    )
                    processed += 1
            client.store(number, "+FLAGS", "\\Seen")
    finally:
        try:
            client.logout()
        except Exception:
            log_event(logger, logging.WARNING, "imap_logout_failed")
    log_event(logger, logging.INFO, "imap_poll_finished", attachments=processed)
    return processed
