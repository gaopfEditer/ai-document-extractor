from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from doc_extractor.app import create_app
from doc_extractor.catalog import sample_documents
from doc_extractor.dashboard import render_dashboard
from doc_extractor.sample_pdf import draw_sample_pdf
from doc_extractor.storage import DocumentRecord


def test_upload_and_dashboard(settings, tmp_path: Path):
    sample = sample_documents(date.today())[0]
    pdf_path = tmp_path / sample.filename
    draw_sample_pdf(pdf_path, sample)
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["provider"] == "mock"
        response = client.post(
            "/api/documents",
            files={"file": (sample.filename, pdf_path.read_bytes(), "application/pdf")},
            data={"schema_name": "coi"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Northwind Scaffolding LLC"
        assert body["status"] == "expiring_soon"
        page = client.get("/")
        assert page.status_code == 200
        assert "Northwind Scaffolding LLC" in page.text
        assert "Expiring soon" in page.text
        assert "Offline demo" in page.text
        listed = client.get("/api/documents")
        assert listed.json()[0]["reference"] == "GL-88421-NW"
        rejected = client.post(
            "/api/documents",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"schema_name": "coi"},
        )
        assert rejected.status_code == 400


def test_dashboard_escapes_names(settings):
    record = DocumentRecord(
        id="coi:xss",
        content_hash="x",
        schema_name="coi",
        source="upload",
        filename="coi.pdf",
        title="<script>alert(1)</script>",
        reference="GL-1",
        secondary=None,
        relevant_date=None,
        expiry_status="unknown",
        confidence=0.2,
        needs_review=True,
        review_reasons=["Check <b>this</b>"],
        payload={"company_name": "<script>alert(1)</script>"},
        raw_text="",
        processed_at="2026-10-06T00:00:00+00:00",
        reminded_at=None,
        text_status="ok",
    )
    html = render_dashboard(
        records=[record],
        reminder_run=None,
        settings=settings,
        view="all",
        error="<img src=x onerror=alert(1)>",
        today=date(2026, 10, 6),
    )
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
