from datetime import date

from doc_extractor.catalog import sample_documents
from doc_extractor.labeled import parse_coi, parse_invoice, render_coi_lines, render_invoice_lines
from doc_extractor.models import get_schema
from doc_extractor.review import preliminary_judgement


def test_sample_lines_round_trip():
    for sample in sample_documents(date(2026, 10, 6)):
        text = "\n".join(sample.lines)
        if sample.schema_name == "coi":
            parsed = parse_coi(text)
            assert parsed["company_name"] == sample.fields["company_name"]
            assert parsed["policy_number"] == sample.fields["policy_number"]
            assert parsed["expiry_date"] == sample.fields["expiry_date"]
        else:
            parsed = parse_invoice(text)
            assert parsed["vendor"] == sample.fields["vendor"]
            assert parsed["invoice_number"] == sample.fields["invoice_number"]
            assert parsed["total"] == sample.fields["total"]
            assert parsed["due_date"] == sample.fields["due_date"]
            assert len(parsed["line_items"]) == len(sample.fields["line_items"])


def test_labels_still_parse_when_joined_by_spaces():
    lines = render_coi_lines(
        {
            "company_name": "Northwind Scaffolding LLC",
            "policy_number": "GL-88421-NW",
            "insurer": "Pinnacle Mutual Insurance",
            "effective_date": "2026-01-01",
            "expiry_date": "2026-10-24",
            "coverages": [{"coverage_type": "General Liability", "limit": "$1,000,000"}],
        }
    )
    parsed = parse_coi(" ".join(lines))
    assert parsed["company_name"] == "Northwind Scaffolding LLC"
    assert parsed["limits"][0]["limit"] == "$1,000,000"


def test_invoice_render_matches_total():
    lines = render_invoice_lines(
        {
            "vendor": "Lumen Office Supply",
            "invoice_number": "INV-10482",
            "invoice_date": "2026-09-28",
            "due_date": "2026-10-18",
            "currency": "USD",
            "line_items": [
                {"description": "Copy paper", "quantity": 10, "unit_price": 42.0, "amount": 420.0}
            ],
            "total": 420.0,
        }
    )
    parsed = parse_invoice("\n".join(lines))
    judged = preliminary_judgement(parsed, get_schema("invoice"))
    assert judged["needs_review"] is False
    assert judged["total"] == 420.0
