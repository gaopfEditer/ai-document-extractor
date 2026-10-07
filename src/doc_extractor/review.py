"""Deterministic checks applied after the model returns JSON.

The model may set confidence and needs_review. These rules can only raise
the review flag. They never clear a flag the model already set, and they
never invent an expiry status.
"""

from __future__ import annotations

from pydantic import BaseModel

from doc_extractor.models import SchemaSpec, missing_field_reason


def is_blank(value: object) -> bool:
    return value is None or value == "" or value == []


def preliminary_judgement(parsed: dict, schema: SchemaSpec) -> dict:
    """Mock-model output: a confidence score plus a review flag for missing fields."""
    result = dict(parsed)
    missing = [name for name in schema.required_fields if is_blank(result.get(name))]
    if missing:
        result["confidence"] = 0.44
        result["needs_review"] = True
        result["review_reasons"] = [missing_field_reason(name) for name in missing]
    else:
        result["confidence"] = 0.95
        result["needs_review"] = False
        result["review_reasons"] = []
    return result


def apply_review(model: BaseModel, schema: SchemaSpec) -> BaseModel:
    data = model.model_dump()
    reasons = [str(item) for item in data.get("review_reasons") or [] if str(item).strip()]
    needs_review = bool(data.get("needs_review"))
    confidence = float(data.get("confidence") or 0)

    for field_name in schema.required_fields:
        if is_blank(data.get(field_name)):
            needs_review = True
            _append(reasons, missing_field_reason(field_name))
            confidence = min(confidence, 0.45)

    if schema.name == "coi":
        effective = data.get("effective_date")
        expiry = data.get("expiry_date")
        if effective and expiry and effective > expiry:
            needs_review = True
            _append(reasons, "Effective date is after the expiry date.")
            confidence = min(confidence, 0.4)

    if schema.name == "invoice":
        total = data.get("total")
        amounts = [
            item.get("amount")
            for item in (data.get("line_items") or [])
            if isinstance(item, dict) and item.get("amount") is not None
        ]
        if total is not None and amounts:
            summed = round(sum(float(amount) for amount in amounts), 2)
            if abs(summed - float(total)) > 0.05:
                needs_review = True
                _append(reasons, "Line items do not add up to the total.")
                confidence = min(confidence, 0.5)

    if confidence < 0.7:
        needs_review = True
        _append(reasons, "Confidence is below 0.70.")

    if needs_review and not reasons:
        _append(reasons, "The model flagged this document for review.")

    confidence = max(0.0, min(1.0, confidence))
    data["confidence"] = round(confidence, 2)
    data["needs_review"] = needs_review
    data["review_reasons"] = reasons
    return schema.model.model_validate(data)


def _append(reasons: list[str], message: str) -> None:
    if message not in reasons:
        reasons.append(message)
