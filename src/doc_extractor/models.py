"""Schemas the model is allowed to fill in.

Expiry status is intentionally absent. Code computes it from the date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from doc_extractor.config import get_settings


def parse_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "none", "unknown", "-", "null"}:
        return None
    formats = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _coerce_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValueError(f"Unrecognized date: {value}")
    return date.fromisoformat(parsed)


def _coerce_confidence(value: object) -> float:
    if value is None or value == "":
        return 0.0
    number = float(value)
    if number > 1:
        number = number / 100.0
    return number


class CoverageLimit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    coverage_type: str
    limit: str


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class CertificateFields(BaseModel):
    model_config = ConfigDict(extra="ignore")
    company_name: str | None = None
    policy_number: str | None = None
    insurer: str | None = None
    coverage_types: list[str] = Field(default_factory=list)
    limits: list[CoverageLimit] = Field(default_factory=list)
    effective_date: date | None = None
    expiry_date: date | None = None
    confidence: float = 0
    needs_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)

    @field_validator("effective_date", "expiry_date", mode="before")
    @classmethod
    def _dates(cls, value: object) -> date | None:
        return _coerce_date(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _coerce_confidence(value)


class InvoiceFields(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    total: float | None = None
    currency: str | None = "USD"
    confidence: float = 0
    needs_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def _dates(cls, value: object) -> date | None:
        return _coerce_date(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _coerce_confidence(value)


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    title: str
    model: type[BaseModel]
    required_fields: tuple[str, ...]
    date_field: str
    title_field: str
    reference_field: str
    secondary_field: str | None
    kind: str


SPECS: dict[str, SchemaSpec] = {
    "coi": SchemaSpec(
        name="coi",
        title="Certificate of insurance",
        model=CertificateFields,
        required_fields=("company_name", "policy_number", "insurer", "expiry_date"),
        date_field="expiry_date",
        title_field="company_name",
        reference_field="policy_number",
        secondary_field="insurer",
        kind="certificate",
    ),
    "invoice": SchemaSpec(
        name="invoice",
        title="Invoice",
        model=InvoiceFields,
        required_fields=("vendor", "invoice_number", "total", "due_date"),
        date_field="due_date",
        title_field="vendor",
        reference_field="invoice_number",
        secondary_field=None,
        kind="invoice",
    ),
}


def get_schema(name: str) -> SchemaSpec:
    key = name.lower().strip()
    if key not in SPECS:
        known = ", ".join(sorted(SPECS))
        raise KeyError(f"Unknown schema '{name}'. Use one of: {known}.")
    return SPECS[key]


def schema_directory() -> Path:
    settings = get_settings()
    candidates = [
        settings.schema_dir,
        Path("schemas"),
        Path(__file__).resolve().parents[2] / "schemas",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).joinpath("coi.schema.json").exists():
            return Path(candidate)
    return Path(candidates[0])


def load_json_schema(name: str) -> dict:
    path = schema_directory() / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run commands from the project root, or set SCHEMA_DIR."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def missing_field_reason(field_name: str) -> str:
    return f"Missing {field_name.replace('_', ' ')}."
