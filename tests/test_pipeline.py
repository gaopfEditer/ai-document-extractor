import csv
import json
from datetime import date
from pathlib import Path

from reportlab.pdfgen import canvas

from doc_extractor.catalog import sample_documents
from doc_extractor.llm import MockProvider
from doc_extractor.pipeline import Pipeline
from doc_extractor.sample_pdf import draw_sample_pdf
from doc_extractor.status import EXPIRED, EXPIRING_SOON, UNKNOWN, VALID


def _write_samples(folder: Path, today: date) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for sample in sample_documents(today):
        draw_sample_pdf(folder / sample.filename, sample)


def test_sample_pdfs_extract_and_classify(settings, tmp_path: Path):
    today = date.today()
    samples = tmp_path / "samples"
    _write_samples(samples, today)
    settings = settings.model_copy(update={"samples_dir": samples})
    pipeline = Pipeline(settings)
    result = pipeline.process_folder(samples, source="sample")
    assert result.failures == []
    by_name = {record.filename: record for record in result.records}
    assert by_name["coi-northwind-scaffolding.pdf"].expiry_status == EXPIRING_SOON
    assert by_name["coi-northwind-scaffolding.pdf"].needs_review is False
    assert by_name["coi-harbor-pine-electrical.pdf"].expiry_status == VALID
    assert by_name["coi-blue-mesa-roofing.pdf"].expiry_status == EXPIRED
    summit = by_name["coi-summit-drywall-incomplete.pdf"]
    assert summit.needs_review is True
    assert summit.expiry_status == UNKNOWN
    assert "Missing expiry date." in summit.review_reasons
    assert by_name["invoice-lumen-office-supply.pdf"].expiry_status == EXPIRING_SOON
    assert by_name["invoice-cedar-co-printing.pdf"].expiry_status == VALID
    lumen = by_name["invoice-lumen-office-supply.pdf"].payload
    assert lumen["total"] == 1290.5
    assert len(lumen["line_items"]) == 3
    limits = by_name["coi-northwind-scaffolding.pdf"].payload["limits"]
    assert [item["coverage_type"] for item in limits] == ["General Liability", "Workers Compensation"]

    messages = pipeline.run_reminders(dry_run=True, today=today)
    subjects = " ".join(message.subject for message in messages)
    assert "Northwind Scaffolding LLC" in subjects
    assert "INV-10482" in subjects
    assert "Blue Mesa" not in subjects
    assert "Summit" not in subjects
    assert "Harbor" not in subjects
    preview = settings.reminder_preview_path.read_text(encoding="utf-8")
    assert "DRY RUN" in preview
    assert settings.csv_path.exists()
    with settings.csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert any(row["title"] == "Northwind Scaffolding LLC" for row in rows)

    again = pipeline.process_folder(samples, source="sample")
    assert len(again.records) == 6
    assert len(pipeline.repo.list_all()) == 6


def test_model_cannot_override_expiry_status(settings, tmp_path: Path):
    class Stub:
        name = "stub"

        def extract(self, text, schema, *, filename="", attempt_feedback=""):
            return {
                "company_name": "Test Co",
                "policy_number": "GL-1",
                "insurer": "Test Mutual",
                "coverage_types": [],
                "limits": [],
                "effective_date": "2024-01-01",
                "expiry_date": "2020-01-01",
                "confidence": 0.99,
                "needs_review": False,
                "review_reasons": [],
                "expiry_status": "valid",
            }

    pdf = tmp_path / "coi-override.pdf"
    _write_samples(tmp_path / "unused", date.today())
    draw_sample_pdf(pdf, sample_documents(date.today())[0])
    pipeline = Pipeline(settings, provider=Stub(), sleep=lambda _seconds: None)
    record = pipeline.process_path(pdf, schema_hint="coi", source="upload")
    assert record.expiry_status == EXPIRED
    assert "expiry_status" not in record.payload


def test_blank_pdf_does_not_call_the_model(settings, tmp_path: Path):
    class Boom:
        name = "boom"

        def extract(self, *args, **kwargs):
            raise AssertionError("model should not run without text")

    pdf = tmp_path / "scan.pdf"
    blank = canvas.Canvas(str(pdf))
    blank.rect(40, 40, 80, 40)
    blank.save()
    pipeline = Pipeline(settings, provider=Boom())
    record = pipeline.process_path(pdf, schema_hint="coi", source="upload")
    assert record.text_status == "empty"
    assert record.needs_review is True
    assert "text layer" in " ".join(record.review_reasons).lower() or "scan" in " ".join(record.review_reasons).lower()


def test_watcher_reads_a_pdf_once(settings, tmp_path: Path):
    from doc_extractor.watcher import FolderWatcher

    sample = sample_documents(date.today())[0]
    inbox = settings.watch_dir / "coi"
    inbox.mkdir(parents=True)
    draw_sample_pdf(inbox / "dropped.pdf", sample)
    pipeline = Pipeline(settings)
    watcher = FolderWatcher(pipeline, settings)
    assert watcher.scan_once() == 1
    assert watcher.scan_once() == 0
    rows = pipeline.repo.list_all()
    assert len(rows) == 1
    assert rows[0].schema_name == "coi"
    assert rows[0].source == "watch"
    assert rows[0].title == "Northwind Scaffolding LLC"


def test_canned_fallback_when_labels_are_missing(settings, tmp_path: Path):
    canned = tmp_path / "samples" / "canned"
    canned.mkdir(parents=True)
    payload = {
        "company_name": "Northwind Scaffolding LLC",
        "policy_number": "GL-88421-NW",
        "insurer": "Pinnacle Mutual Insurance",
        "coverage_types": ["General Liability"],
        "limits": [{"coverage_type": "General Liability", "limit": "$1,000,000"}],
        "effective_date": "2026-01-01",
        "expiry_date": "2026-10-24",
        "confidence": 0.95,
        "needs_review": False,
        "review_reasons": [],
    }
    (canned / "coi-northwind-scaffolding.json").write_text(
        json.dumps(
            {
                "schema": "coi",
                "filename": "coi-northwind-scaffolding.pdf",
                "needle": "Northwind Scaffolding LLC",
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    provider = MockProvider(settings)
    from doc_extractor.models import get_schema

    parsed = provider.extract(
        "Please see the attached certificate for Northwind Scaffolding LLC.",
        get_schema("coi"),
        filename="notes.txt",
    )
    assert parsed["policy_number"] == "GL-88421-NW"
