from datetime import date

import pytest

from doc_extractor.status import EXPIRED, EXPIRING_SOON, UNKNOWN, VALID, compute_status, explain_status


TODAY = date(2026, 10, 6)


def test_status_boundaries():
    assert compute_status(None, TODAY, 30) == UNKNOWN
    assert compute_status(date(2026, 10, 5), TODAY, 30) == EXPIRED
    assert compute_status(TODAY, TODAY, 30) == EXPIRING_SOON
    assert compute_status(date(2026, 11, 5), TODAY, 30) == EXPIRING_SOON
    assert compute_status(date(2026, 11, 6), TODAY, 30) == VALID


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        compute_status(TODAY, TODAY, -1)


def test_explanation_mentions_code_not_model():
    text = explain_status("coi", date(2026, 11, 5), TODAY, 30)
    assert "code" in text
    assert "model" in text
    assert "Expiring soon" in text


def test_invoice_phrase():
    text = explain_status("invoice", date(2026, 10, 5), TODAY, 30)
    assert "Past due" in text
