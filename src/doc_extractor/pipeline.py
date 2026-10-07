"""Turn a PDF into a stored row. The model fills fields. Code decides the status."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from doc_extractor.alerts import AlertHook
from doc_extractor.config import Settings
from doc_extractor.llm import build_provider, extract_with_retries, schema_from_hint
from doc_extractor.logging_config import log_event
from doc_extractor.models import SchemaSpec
from doc_extractor.pdf_text import extract_pdf_text
from doc_extractor.reminders import deliver, plan_reminders, refresh_statuses
from doc_extractor.review import apply_review
from doc_extractor.sheets import SheetsSink
from doc_extractor.status import compute_status
from doc_extractor.storage import DocumentRecord, Repository

logger = logging.getLogger("doc_extractor.pipeline")


@dataclass
class BatchResult:
    records: list[DocumentRecord]
    failures: list[tuple[str, str]]


class Pipeline:
    def __init__(self, settings: Settings, provider=None, alerts: AlertHook | None = None, sleep=None):
        self.settings = settings
        self.alerts = alerts or AlertHook(settings)
        self.repo = Repository(settings.database_path, settings.csv_path)
        self.repo.init()
        self.provider = provider if provider is not None else build_provider(settings)
        self.sheets = SheetsSink(settings, self.alerts)
        self.sleep = sleep if sleep is not None else time.sleep

    def process_path(self, path: Path, *, schema_hint: str | None, source: str) -> DocumentRecord:
        return self.process_bytes(
            path.read_bytes(),
            filename=path.name,
            schema_hint=schema_hint,
            source=source,
            parent_name=path.parent.name,
        )

    def process_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        schema_hint: str | None,
        source: str,
        parent_name: str | None = None,
    ) -> DocumentRecord:
        filename = Path(filename).name
        extracted = extract_pdf_text(data, self.settings)
        schema = schema_from_hint(
            schema_hint,
            filename,
            extracted.text,
            parent_name,
            self.settings.default_schema,
        )
        digest = hashlib.sha256(data).hexdigest()
        if extracted.status == "empty":
            record = self._store_unread(
                data_hash=digest,
                filename=filename,
                source=source,
                schema=schema,
                note=extracted.note,
            )
            log_event(
                logger,
                logging.WARNING,
                "pdf_has_no_text_layer",
                filename=filename,
                schema=schema.name,
            )
            self.alerts.send(f"No text layer in {filename}. {extracted.note}")
            return record

        model = extract_with_retries(
            self.provider,
            extracted.text,
            schema,
            filename=filename,
            attempts=max(1, self.settings.llm_max_retries),
            sleep=(lambda _seconds: None) if getattr(self.provider, "name", "") == "mock" else self.sleep,
        )

        reviewed = apply_review(model, schema)
        payload = reviewed.model_dump(mode="json")
        relevant = _as_date(payload.get(schema.date_field))
        status = compute_status(relevant, date.today(), self.settings.reminder_days)
        record = DocumentRecord(
            id=_document_id(source, schema.name, filename, digest),
            content_hash=digest,
            schema_name=schema.name,
            source=source,
            filename=filename,
            title=_text(payload.get(schema.title_field)),
            reference=_text(payload.get(schema.reference_field)),
            secondary=_text(payload.get(schema.secondary_field)) if schema.secondary_field else None,
            relevant_date=relevant,
            expiry_status=status,
            confidence=float(payload.get("confidence") or 0),
            needs_review=bool(payload.get("needs_review")),
            review_reasons=list(payload.get("review_reasons") or []),
            payload=payload,
            raw_text=extracted.text[:50000],
            processed_at=_now(),
            reminded_at=None,
            text_status=extracted.status,
        )
        saved = self.repo.save(record)
        self.sheets.upsert(saved)
        log_event(
            logger,
            logging.INFO,
            "document_processed",
            filename=filename,
            schema=schema.name,
            status=saved.expiry_status,
            needs_review=saved.needs_review,
            confidence=saved.confidence,
            provider=getattr(self.provider, "name", "unknown"),
        )
        return saved

    def process_folder(self, folder: Path, *, source: str, schema_hint: str | None = None) -> BatchResult:
        folder = Path(folder)
        records: list[DocumentRecord] = []
        failures: list[tuple[str, str]] = []
        paths = sorted(folder.glob("*.pdf")) if folder.exists() else []
        for path in paths:
            try:
                records.append(self.process_path(path, schema_hint=schema_hint, source=source))
            except Exception as exc:
                failures.append((path.name, str(exc)))
                log_event(logger, logging.ERROR, "document_failed", filename=path.name, error=str(exc))
                self.alerts.send(f"Failed to process {path.name}: {exc}")
        if source == "sample":
            self.repo.delete_samples_not_in({path.name for path in paths})
            self.repo.export_csv()
        return BatchResult(records=records, failures=failures)

    def run_reminders(self, *, dry_run: bool, today: date | None = None, sender=None):
        today = today or date.today()
        records = self.repo.list_all()
        changed = refresh_statuses(
            records,
            today=today,
            window_days=self.settings.reminder_days,
            repo=self.repo,
        )
        for record in changed:
            self.sheets.upsert(record)
        messages = plan_reminders(
            records,
            today=today,
            window_days=self.settings.reminder_days,
            to_addr=self.settings.reminder_to,
        )
        return deliver(
            messages,
            settings=self.settings,
            repo=self.repo,
            dry_run=dry_run,
            sender=sender,
        )

    def _store_unread(self, *, data_hash: str, filename: str, source: str, schema: SchemaSpec, note: str) -> DocumentRecord:
        payload = schema.model(
            confidence=0,
            needs_review=True,
            review_reasons=[note],
        ).model_dump(mode="json")
        record = DocumentRecord(
            id=_document_id(source, schema.name, filename, data_hash),
            content_hash=data_hash,
            schema_name=schema.name,
            source=source,
            filename=filename,
            title=None,
            reference=None,
            secondary=None,
            relevant_date=None,
            expiry_status=compute_status(None, date.today(), self.settings.reminder_days),
            confidence=0,
            needs_review=True,
            review_reasons=[note],
            payload=payload,
            raw_text="",
            processed_at=_now(),
            reminded_at=None,
            text_status="empty",
        )
        saved = self.repo.save(record)
        self.sheets.upsert(saved)
        return saved


def _document_id(source: str, schema_name: str, filename: str, digest: str) -> str:
    if source == "sample":
        return f"{schema_name}:sample:{Path(filename).stem}"
    return f"{schema_name}:{digest[:16]}"


def _as_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
