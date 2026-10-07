from datetime import date, timedelta

from doc_extractor.reminders import plan_reminders
from doc_extractor.storage import DocumentRecord


TODAY = date(2026, 10, 6)


def _record(**overrides) -> DocumentRecord:
    base = dict(
        id="coi:1",
        content_hash="abc",
        schema_name="coi",
        source="upload",
        filename="coi.pdf",
        title="Northwind Scaffolding LLC",
        reference="GL-1",
        secondary="Pinnacle Mutual Insurance",
        relevant_date=TODAY + timedelta(days=10),
        expiry_status="expiring_soon",
        confidence=0.95,
        needs_review=False,
        review_reasons=[],
        payload={},
        raw_text="",
        processed_at="2026-10-06T00:00:00+00:00",
        reminded_at=None,
        text_status="ok",
    )
    base.update(overrides)
    return DocumentRecord(**base)


def test_only_the_window_is_selected():
    records = [
        _record(id="soon"),
        _record(id="later", relevant_date=TODAY + timedelta(days=40), title="Harbor"),
        _record(id="past", relevant_date=TODAY - timedelta(days=2), title="Blue Mesa"),
        _record(id="review", needs_review=True, title="Summit"),
        _record(id="sent", reminded_at="2026-10-01T00:00:00+00:00"),
        _record(id="nodate", relevant_date=None, schema_name="invoice", title="No date"),
    ]
    messages = plan_reminders(records, today=TODAY, window_days=30, to_addr="pm@example.com")
    assert [message.document_id for message in messages] == ["soon"]
    assert "Certificate expiring in 10 days" in messages[0].subject
    assert "fixed rule" in messages[0].body


def test_invoice_subject_and_singular_day():
    record = _record(
        id="inv",
        schema_name="invoice",
        title="Lumen Office Supply",
        reference="INV-10482",
        secondary=None,
        relevant_date=TODAY + timedelta(days=1),
    )
    message = plan_reminders([record], today=TODAY, window_days=30, to_addr="pm@example.com")[0]
    assert message.subject == "Invoice due in 1 day: INV-10482 (Lumen Office Supply)"


def test_dry_run_does_not_mark_sent_and_send_does(settings):
    from doc_extractor.pipeline import Pipeline

    pipeline = Pipeline(settings)
    record = _record(id="coi:sample:one")
    pipeline.repo.save(record)
    messages = pipeline.run_reminders(dry_run=True, today=TODAY)
    assert len(messages) == 1
    assert pipeline.repo.get(record.id).reminded_at is None
    sent = []

    def sender(current_settings, message):
        sent.append(message.subject)

    settings_live = settings.model_copy(update={"smtp_host": "smtp.example.com"})
    pipeline.settings = settings_live
    pipeline.run_reminders(dry_run=False, today=TODAY, sender=sender)
    assert sent
    assert pipeline.repo.get(record.id).reminded_at is not None
    assert pipeline.run_reminders(dry_run=True, today=TODAY) == []
