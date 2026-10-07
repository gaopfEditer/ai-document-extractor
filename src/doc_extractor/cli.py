"""Command line entry points for the demo, one-off files, and the web app."""

from __future__ import annotations

from pathlib import Path

import typer

from doc_extractor.config import Settings, load_settings
from doc_extractor.logging_config import configure_logging
from doc_extractor.pipeline import Pipeline
from doc_extractor.status import status_phrase

app = typer.Typer(
    help="Extract fields from PDFs, track expiry and due dates, and draft reminder emails.",
    no_args_is_help=True,
    add_completion=False,
)


def main() -> None:
    app()


@app.command()
def demo(
    samples_dir: Path = typer.Option(Path("samples"), "--samples-dir", help="Folder of sample PDFs."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Where CSV, SQLite, and the email preview are written."),
) -> None:
    """Process the sample PDFs offline and print the reminder emails."""
    settings = _data_settings(
        data_dir,
        samples_dir=samples_dir,
        demo_mode=True,
        llm_provider="mock",
        reminder_dry_run=True,
        watch_enabled=False,
        scheduler_enabled=False,
        process_samples_on_start=False,
    )
    configure_logging(settings.log_level)
    result_code = run_demo(settings, samples_dir)
    raise typer.Exit(code=result_code)


@app.command()
def process(
    path: Path = typer.Argument(..., help="A PDF file or a folder of PDFs."),
    schema: str = typer.Option("auto", "--schema", help="coi, invoice, or auto."),
    source: str = typer.Option("cli", "--source", help="Label stored with the row."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir"),
) -> None:
    """Extract one PDF, or every PDF in a folder."""
    settings = _data_settings(data_dir)
    configure_logging(settings.log_level)
    pipeline = Pipeline(settings)
    if path.is_dir():
        result = pipeline.process_folder(path, source=source, schema_hint=schema)
        for record in result.records:
            _print_record(record, settings.reminder_days)
        for name, error in result.failures:
            typer.echo(f"FAILED  {name}: {error}")
        raise typer.Exit(code=1 if result.failures else 0)
    if not path.exists():
        typer.echo(f"File not found: {path}")
        raise typer.Exit(code=1)
    record = pipeline.process_path(path, schema_hint=schema, source=source)
    _print_record(record, settings.reminder_days)


@app.command()
def remind(
    send: bool = typer.Option(False, "--send", help="Send through SMTP. Without this flag, the command follows REMINDER_DRY_RUN."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the emails and do not send them."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir"),
) -> None:
    """Find rows inside the reminder window and draft or send the emails."""
    settings = _data_settings(data_dir)
    configure_logging(settings.log_level)
    if send and dry_run:
        typer.echo("Choose either --send or --dry-run.")
        raise typer.Exit(code=2)
    if send:
        use_dry_run = False
    elif dry_run:
        use_dry_run = True
    else:
        use_dry_run = settings.reminder_dry_run
    pipeline = Pipeline(settings)
    messages = pipeline.run_reminders(dry_run=use_dry_run)
    _print_reminders(messages, settings, use_dry_run)


@app.command("poll-inbox")
def poll_inbox_cmd(data_dir: Path = typer.Option(Path("data"), "--data-dir")) -> None:
    """Download unseen PDF attachments from IMAP and extract them."""
    from doc_extractor.imap_inbox import ImapNotConfigured, poll_inbox

    settings = _data_settings(data_dir)
    configure_logging(settings.log_level)
    pipeline = Pipeline(settings)
    try:
        count = poll_inbox(pipeline)
    except ImapNotConfigured as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from exc
    typer.echo(f"Processed {count} PDF attachment(s).")


@app.command()
def watch(data_dir: Path = typer.Option(Path("data"), "--data-dir")) -> None:
    """Keep watching the inbox folder until you stop the process."""
    from doc_extractor.watcher import FolderWatcher

    settings = _data_settings(data_dir, watch_enabled=True)
    configure_logging(settings.log_level)
    pipeline = Pipeline(settings)
    watcher = FolderWatcher(pipeline, settings)
    watcher.scan_once()
    typer.echo(f"Watching {settings.watch_dir} every {settings.watch_interval_seconds:.0f}s. Press Ctrl+C to stop.")
    watcher.start()
    try:
        import time

        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        watcher.stop()
        typer.echo("Stopped.")


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind address. Defaults to HOST."),
    port: int = typer.Option(None, "--port", help="Port. Defaults to PORT."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir"),
) -> None:
    """Start the dashboard and API."""
    import uvicorn

    from doc_extractor.app import create_app

    settings = _data_settings(data_dir)
    configure_logging(settings.log_level)
    chosen_port = port or settings.port
    typer.echo(f"Dashboard: http://127.0.0.1:{chosen_port}")
    uvicorn.run(
        create_app(settings),
        host=host or settings.host,
        port=chosen_port,
        log_level=settings.log_level.lower(),
    )


def run_demo(settings: Settings, samples_dir: Path) -> int:
    if not samples_dir.exists() or not any(samples_dir.glob("*.pdf")):
        typer.echo("No sample PDFs found. Run: make samples")
        return 1
    pipeline = Pipeline(settings)
    result = pipeline.process_folder(samples_dir, source="sample")
    messages = pipeline.run_reminders(dry_run=True)
    typer.echo("")
    typer.echo("AI Document Extractor — offline demo")
    typer.echo("The mock extractor did not call a model. Dates and reminders were decided in code.")
    typer.echo("")
    header = f"{'Name':<34} {'Reference':<16} {'Date':<12} {'Status':<16} Review"
    typer.echo(header)
    typer.echo("-" * len(header))
    for record in sorted(result.records, key=lambda item: (item.schema_name, item.filename)):
        _print_record(record, settings.reminder_days)
    if result.failures:
        typer.echo("")
        for name, error in result.failures:
            typer.echo(f"FAILED  {name}: {error}")
    typer.echo("")
    _print_reminders(messages, settings, dry_run=True)
    typer.echo("Saved")
    typer.echo(f"  {settings.csv_path}")
    typer.echo(f"  {settings.database_path}")
    typer.echo(f"  {settings.reminder_preview_path}")
    typer.echo("")
    typer.echo("Dashboard: make serve")
    typer.echo(f"Then open http://127.0.0.1:{settings.port}")
    typer.echo("")
    return 1 if result.failures else 0


def _print_record(record, window_days: int) -> None:
    del window_days
    name = (record.title or record.filename)[:34]
    reference = (record.reference or "—")[:16]
    when = record.relevant_date.isoformat() if record.relevant_date else "—"
    phrase = status_phrase(record.schema_name, record.expiry_status)
    review = "yes" if record.needs_review else "no"
    typer.echo(f"{name:<34} {reference:<16} {when:<12} {phrase:<16} {review}")


def _print_reminders(messages, settings: Settings, dry_run: bool) -> None:
    mode = "Dry run. No email was sent." if dry_run else "Sent."
    typer.echo(f"Reminders: {len(messages)}. {mode}")
    if not messages:
        typer.echo("  None of the rows are inside the reminder window.")
    for message in messages:
        typer.echo(f"  - {message.subject}")
    typer.echo(f"  Preview file: {settings.reminder_preview_path}")


def _data_settings(data_dir: Path, **overrides: object) -> Settings:
    data_dir.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {
        "data_dir": data_dir,
        "database_path": data_dir / "extractor.db",
        "csv_path": data_dir / "extractions.csv",
        "reminder_preview_path": data_dir / "reminder_preview.txt",
    }
    values.update(overrides)
    return load_settings(**values)
