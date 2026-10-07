"""Small web app: dashboard, upload, and reminder run."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from doc_extractor import __version__
from doc_extractor.config import Settings, get_settings
from doc_extractor.dashboard import reminder_run_from_meta, render_dashboard
from doc_extractor.imap_inbox import ImapNotConfigured, poll_inbox
from doc_extractor.logging_config import configure_logging, log_event
from doc_extractor.pipeline import Pipeline
from doc_extractor.watcher import FolderWatcher

logger = logging.getLogger("doc_extractor.app")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.log_level)
        pipeline: Pipeline = application.state.pipeline
        if settings.process_samples_on_start:
            result = pipeline.process_folder(settings.samples_dir, source="sample")
            log_event(
                logger,
                logging.INFO,
                "startup_samples_processed",
                documents=len(result.records),
                failures=len(result.failures),
            )
            pipeline.run_reminders(dry_run=settings.reminder_dry_run)
        watcher = None
        if settings.watch_enabled:
            watcher = FolderWatcher(pipeline, settings)
            watcher.start()
            application.state.watcher = watcher
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = _start_scheduler(pipeline, settings)
            application.state.scheduler = scheduler
        yield
        if watcher is not None:
            watcher.stop()
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    application = FastAPI(
        title="AI Document Extractor",
        version=__version__,
        description="Extract certificate and invoice fields from PDFs, track dates, and draft reminders.",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.pipeline = Pipeline(settings)

    @application.get("/", response_class=HTMLResponse)
    def dashboard(view: str = "all", error: str | None = None):
        if view not in {"all", "coi", "invoice", "review"}:
            view = "all"
        pipeline: Pipeline = application.state.pipeline
        raw = pipeline.repo.get_meta("last_reminder_run")
        html = render_dashboard(
            records=pipeline.repo.list_all(),
            reminder_run=reminder_run_from_meta(raw),
            settings=settings,
            view=view,
            error=error,
            today=date.today(),
        )
        return HTMLResponse(html)

    @application.get("/api/health")
    def health():
        pipeline: Pipeline = application.state.pipeline
        return {
            "status": "ok",
            "version": __version__,
            "provider": settings.llm_provider,
            "demo_mode": settings.demo_mode or settings.llm_provider == "mock",
            "reminder_dry_run": settings.reminder_dry_run,
            "reminder_days": settings.reminder_days,
            "sheets_configured": pipeline.sheets.enabled,
            "imap_configured": bool(settings.imap_host and settings.imap_user),
            "smtp_configured": bool(settings.smtp_host),
            "ocr_enabled": settings.ocr_enabled,
            "documents": len(pipeline.repo.list_all()),
        }

    @application.get("/api/documents")
    def documents(schema: str | None = None):
        pipeline: Pipeline = application.state.pipeline
        rows = []
        for record in pipeline.repo.list_all():
            if schema and record.schema_name != schema:
                continue
            rows.append(
                {
                    "id": record.id,
                    "schema": record.schema_name,
                    "filename": record.filename,
                    "title": record.title,
                    "reference": record.reference,
                    "secondary": record.secondary,
                    "relevant_date": record.relevant_date.isoformat() if record.relevant_date else None,
                    "status": record.expiry_status,
                    "confidence": record.confidence,
                    "needs_review": record.needs_review,
                    "review_reasons": record.review_reasons,
                    "source": record.source,
                    "text_status": record.text_status,
                    "processed_at": record.processed_at,
                    "reminded_at": record.reminded_at,
                    "payload": record.payload,
                }
            )
        return rows

    @application.get("/api/reminders")
    def reminders():
        pipeline: Pipeline = application.state.pipeline
        return reminder_run_from_meta(pipeline.repo.get_meta("last_reminder_run")) or {
            "messages": [],
            "dry_run": settings.reminder_dry_run,
        }

    @application.post("/api/reminders/run")
    def run_reminders(dry_run: bool = True):
        pipeline: Pipeline = application.state.pipeline
        messages = pipeline.run_reminders(dry_run=dry_run)
        return {"dry_run": dry_run, "count": len(messages), "subjects": [message.subject for message in messages]}

    @application.post("/api/documents")
    async def upload_api(
        file: UploadFile = File(...),
        schema_name: str = Form("auto"),
    ):
        pipeline: Pipeline = application.state.pipeline
        filename, data, problem = await _read_upload(file)
        if problem:
            return JSONResponse({"error": problem}, status_code=400)
        try:
            record = pipeline.process_bytes(data, filename=filename, schema_hint=schema_name, source="upload")
        except Exception as exc:
            pipeline.alerts.send(f"Failed to process {filename}: {exc}")
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(
            {
                "id": record.id,
                "schema": record.schema_name,
                "title": record.title,
                "status": record.expiry_status,
                "needs_review": record.needs_review,
                "confidence": record.confidence,
                "payload": record.payload,
            }
        )

    @application.post("/upload")
    async def upload_form(
        file: UploadFile = File(...),
        schema_name: str = Form("auto"),
    ):
        pipeline: Pipeline = application.state.pipeline
        filename, data, problem = await _read_upload(file)
        if problem:
            return RedirectResponse(f"/?error={quote(problem)}", status_code=303)
        try:
            pipeline.process_bytes(data, filename=filename, schema_hint=schema_name, source="upload")
        except Exception as exc:
            pipeline.alerts.send(f"Failed to process {filename}: {exc}")
            return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
        return RedirectResponse("/", status_code=303)

    @application.post("/api/inbox/poll")
    def poll():
        pipeline: Pipeline = application.state.pipeline
        try:
            count = poll_inbox(pipeline)
        except ImapNotConfigured as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"attachments": count}

    @application.get("/extractions.csv")
    def download_csv():
        path = settings.csv_path
        if not path.exists():
            return PlainTextResponse("No rows yet.\n", status_code=404)
        return FileResponse(path, media_type="text/csv", filename="extractions.csv")

    return application


async def _read_upload(file: UploadFile) -> tuple[str, bytes, str | None]:
    filename = Path(file.filename or "upload.pdf").name
    if not filename.lower().endswith(".pdf"):
        return filename, b"", "Please upload a PDF."
    data = await file.read()
    if not data:
        return filename, data, "That file was empty."
    if not data.startswith(b"%PDF"):
        return filename, data, "That file does not look like a PDF."
    if len(data) > MAX_UPLOAD_BYTES:
        return filename, data, "That PDF is larger than 15 MB."
    return filename, data, None


def _start_scheduler(pipeline: Pipeline, settings: Settings):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone="UTC")

    def job() -> None:
        try:
            pipeline.run_reminders(dry_run=settings.reminder_dry_run)
            log_event(logger, logging.INFO, "scheduled_reminder_finished", dry_run=settings.reminder_dry_run)
        except Exception as exc:
            log_event(logger, logging.ERROR, "scheduled_reminder_failed", error=str(exc))
            pipeline.alerts.send(f"Daily reminder job failed: {exc}")

    scheduler.add_job(
        job,
        CronTrigger(hour=settings.scheduler_hour, minute=settings.scheduler_minute),
        id="daily-reminders",
        replace_existing=True,
    )
    scheduler.start()
    log_event(
        logger,
        logging.INFO,
        "scheduler_started",
        hour=settings.scheduler_hour,
        minute=settings.scheduler_minute,
        timezone="UTC",
    )
    return scheduler
