from doc_extractor.models import CertificateFields, InvoiceFields, get_schema
from doc_extractor.review import apply_review, preliminary_judgement


def test_review_keeps_a_clean_certificate():
    model = CertificateFields(
        company_name="Northwind Scaffolding LLC",
        policy_number="GL-1",
        insurer="Pinnacle Mutual Insurance",
        effective_date="2026-01-01",
        expiry_date="2026-12-01",
        confidence=0.95,
        needs_review=False,
    )
    reviewed = apply_review(model, get_schema("coi"))
    assert reviewed.needs_review is False
    assert reviewed.review_reasons == []
    assert reviewed.confidence == 0.95


def test_review_flags_missing_field_even_if_model_is_confident():
    model = CertificateFields(
        company_name="Summit Drywall Partners",
        policy_number=None,
        insurer="High Desert Specialty Insurance",
        expiry_date="2026-12-01",
        confidence=0.99,
        needs_review=False,
    )
    reviewed = apply_review(model, get_schema("coi"))
    assert reviewed.needs_review is True
    assert reviewed.confidence <= 0.45
    assert "Missing policy number." in reviewed.review_reasons


def test_review_flags_date_order():
    model = CertificateFields(
        company_name="Blue Mesa Roofing Inc.",
        policy_number="BOP-1",
        insurer="Red Canyon Indemnity",
        effective_date="2026-12-01",
        expiry_date="2026-01-01",
        confidence=0.95,
        needs_review=False,
    )
    reviewed = apply_review(model, get_schema("coi"))
    assert "Effective date is after the expiry date." in reviewed.review_reasons
    assert reviewed.needs_review is True


def test_review_flags_invoice_total_mismatch():
    model = InvoiceFields(
        vendor="Lumen Office Supply",
        invoice_number="INV-1",
        due_date="2026-10-20",
        total=10,
        line_items=[{"description": "Paper", "quantity": 1, "unit_price": 40, "amount": 40}],
        confidence=0.95,
        needs_review=False,
    )
    reviewed = apply_review(model, get_schema("invoice"))
    assert "Line items do not add up to the total." in reviewed.review_reasons


def test_model_review_flag_is_kept():
    model = CertificateFields(
        company_name="Harbor & Pine Electrical Co.",
        policy_number="CPL-1",
        insurer="Cedar State Assurance",
        expiry_date="2027-01-01",
        confidence=0.91,
        needs_review=True,
        review_reasons=["The signature block was unreadable."],
    )
    reviewed = apply_review(model, get_schema("coi"))
    assert reviewed.needs_review is True
    assert "The signature block was unreadable." in reviewed.review_reasons


def test_preliminary_judgement_marks_missing_expiry():
    parsed = {
        "company_name": "Summit Drywall Partners",
        "policy_number": "GL-44012-SD",
        "insurer": "High Desert Specialty Insurance",
        "coverage_types": ["General Liability"],
        "limits": [],
        "effective_date": "2026-01-01",
        "expiry_date": None,
    }
    judged = preliminary_judgement(parsed, get_schema("coi"))
    assert judged["needs_review"] is True
    assert judged["confidence"] == 0.44
