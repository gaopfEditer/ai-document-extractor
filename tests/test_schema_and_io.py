import json
from email.message import EmailMessage
from pathlib import Path

from doc_extractor.alerts import AlertHook
from doc_extractor.imap_inbox import pdf_attachments
from doc_extractor.models import CertificateFields, InvoiceFields, load_json_schema
from doc_extractor.pdf_text import extract_pdf_text
from doc_extractor.sample_pdf import draw_sample_pdf
from doc_extractor.catalog import sample_documents
from datetime import date

import httpx

from doc_extractor.sheets import SheetsSink
from doc_extractor.storage import DocumentRecord


def test_schema_files_match_models():
    pairs = [("coi", CertificateFields), ("invoice", InvoiceFields)]
    for name, model in pairs:
        schema = load_json_schema(name)
        assert set(schema["properties"]) == set(model.model_fields)
        assert "expiry_status" not in schema["properties"]
        assert schema["additionalProperties"] is False


def test_pdf_text_contains_labeled_fields(tmp_path: Path, settings):
    sample = next(item for item in sample_documents(date(2026, 10, 6)) if item.filename.startswith("invoice-"))
    path = tmp_path / sample.filename
    draw_sample_pdf(path, sample)
    extracted = extract_pdf_text(path.read_bytes(), settings)
    assert extracted.status == "ok"
    assert "Vendor: Cedar & Co. Printing" in extracted.text or "Vendor: Lumen Office Supply" in extracted.text
    assert "Invoice Number:" in extracted.text


def test_imap_attachment_helper():
    message = EmailMessage()
    message["Subject"] = "Certificate attached"
    message.set_content("See the PDF.")
    message.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="coi/../northwind.pdf")
    message.add_attachment(b"not a pdf", maintype="text", subtype="plain", filename="notes.txt")
    found = pdf_attachments(message)
    assert found == [("northwind.pdf", b"%PDF-1.4 fake")]


def test_slack_alert_posts_text(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True})

    settings = settings.model_copy(
        update={"alert_webhook_url": "https://hooks.example.test/slack", "alert_webhook_type": "slack"}
    )
    hook = AlertHook(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert hook.send("Certificate import failed") is True
    assert seen["json"] == {"text": "Certificate import failed"}


def test_sheets_skip_and_failure_are_safe(settings, tmp_path: Path):
    record = DocumentRecord(
        id="coi:1",
        content_hash="abc",
        schema_name="coi",
        source="upload",
        filename="coi.pdf",
        title="Northwind",
        reference="GL-1",
        secondary=None,
        relevant_date=None,
        expiry_status="unknown",
        confidence=0.4,
        needs_review=True,
        review_reasons=["Missing expiry date."],
        payload={},
        raw_text="",
        processed_at="2026-10-06T00:00:00+00:00",
        reminded_at=None,
        text_status="ok",
    )
    sink = SheetsSink(settings, AlertHook(settings))
    sink.upsert(record)
    broken = settings.model_copy(
        update={
            "google_service_account_file": str(tmp_path / "missing.json"),
            "google_sheet_id": "sheet-id",
        }
    )
    SheetsSink(broken, AlertHook(broken)).upsert(record)
