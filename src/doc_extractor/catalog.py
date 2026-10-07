"""Fictional sample documents. Dates are relative to the day the files are generated."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from doc_extractor.labeled import render_coi_lines, render_invoice_lines

HOLDER = "Apex General Contractors"


@dataclass(frozen=True)
class SampleDocument:
    filename: str
    schema_name: str
    heading: str
    kicker: str
    fields: dict
    extra_lines: tuple[str, ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        if self.schema_name == "coi":
            body = render_coi_lines(self.fields)
        else:
            body = render_invoice_lines(self.fields)
        return tuple(body + list(self.extra_lines))


def sample_documents(today: date | None = None) -> list[SampleDocument]:
    today = today or date.today()
    return [
        _northwind(today),
        _harbor(today),
        _blue_mesa(today),
        _summit(today),
        _lumen(today),
        _cedar(today),
    ]


def _northwind(today: date) -> SampleDocument:
    return SampleDocument(
        filename="coi-northwind-scaffolding.pdf",
        schema_name="coi",
        heading="Certificate of Insurance Summary",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL POLICY",
        fields={
            "company_name": "Northwind Scaffolding LLC",
            "policy_number": "GL-88421-NW",
            "insurer": "Pinnacle Mutual Insurance",
            "effective_date": _iso(today - timedelta(days=260)),
            "expiry_date": _iso(today + timedelta(days=18)),
            "certificate_holder": HOLDER,
            "coverages": [
                {
                    "coverage_type": "General Liability",
                    "limit": "$1,000,000 each occurrence / $2,000,000 aggregate",
                },
                {"coverage_type": "Workers Compensation", "limit": "Statutory limits"},
            ],
        },
    )


def _harbor(today: date) -> SampleDocument:
    return SampleDocument(
        filename="coi-harbor-pine-electrical.pdf",
        schema_name="coi",
        heading="Certificate of Insurance Summary",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL POLICY",
        fields={
            "company_name": "Harbor & Pine Electrical Co.",
            "policy_number": "CPL-22019-HP",
            "insurer": "Cedar State Assurance",
            "effective_date": _iso(today - timedelta(days=40)),
            "expiry_date": _iso(today + timedelta(days=220)),
            "certificate_holder": HOLDER,
            "coverages": [
                {
                    "coverage_type": "General Liability",
                    "limit": "$1,000,000 each occurrence / $2,000,000 aggregate",
                },
                {
                    "coverage_type": "Automobile Liability",
                    "limit": "$1,000,000 combined single limit",
                },
                {"coverage_type": "Umbrella Liability", "limit": "$5,000,000 each occurrence"},
            ],
        },
    )


def _blue_mesa(today: date) -> SampleDocument:
    return SampleDocument(
        filename="coi-blue-mesa-roofing.pdf",
        schema_name="coi",
        heading="Certificate of Insurance Summary",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL POLICY",
        fields={
            "company_name": "Blue Mesa Roofing Inc.",
            "policy_number": "BOP-10933-BM",
            "insurer": "Red Canyon Indemnity",
            "effective_date": _iso(today - timedelta(days=410)),
            "expiry_date": _iso(today - timedelta(days=45)),
            "certificate_holder": HOLDER,
            "coverages": [
                {
                    "coverage_type": "General Liability",
                    "limit": "$1,000,000 each occurrence / $2,000,000 aggregate",
                },
                {"coverage_type": "Workers Compensation", "limit": "Statutory limits"},
            ],
        },
    )


def _summit(today: date) -> SampleDocument:
    return SampleDocument(
        filename="coi-summit-drywall-incomplete.pdf",
        schema_name="coi",
        heading="Certificate of Insurance Summary",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL POLICY",
        fields={
            "company_name": "Summit Drywall Partners",
            "policy_number": "GL-44012-SD",
            "insurer": "High Desert Specialty Insurance",
            "effective_date": _iso(today - timedelta(days=100)),
            "expiry_date": None,
            "certificate_holder": HOLDER,
            "coverages": [
                {
                    "coverage_type": "General Liability",
                    "limit": "$1,000,000 each occurrence / $2,000,000 aggregate",
                }
            ],
        },
        extra_lines=("Remarks: Expiry date was not printed on the certificate.",),
    )


def _lumen(today: date) -> SampleDocument:
    items = [
        _item("Copy paper, letter (case)", 10, 42.00),
        _item("Black toner cartridge", 4, 189.50),
        _item("File folders, box of 100", 6, 18.75),
    ]
    return SampleDocument(
        filename="invoice-lumen-office-supply.pdf",
        schema_name="invoice",
        heading="Invoice",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL BILL",
        fields={
            "vendor": "Lumen Office Supply",
            "invoice_number": "INV-10482",
            "invoice_date": _iso(today - timedelta(days=8)),
            "due_date": _iso(today + timedelta(days=12)),
            "currency": "USD",
            "bill_to": HOLDER,
            "line_items": items,
            "total": round(sum(item["amount"] for item in items), 2),
        },
    )


def _cedar(today: date) -> SampleDocument:
    items = [
        _item("Job-site banners, 3x6 ft", 4, 85.00),
        _item("Business cards, box", 10, 32.00),
        _item("Safety posters", 15, 20.00),
    ]
    return SampleDocument(
        filename="invoice-cedar-co-printing.pdf",
        schema_name="invoice",
        heading="Invoice",
        kicker="SAMPLE DOCUMENT  ·  FICTIONAL  ·  NOT A REAL BILL",
        fields={
            "vendor": "Cedar & Co. Printing",
            "invoice_number": "INV-5591",
            "invoice_date": _iso(today - timedelta(days=2)),
            "due_date": _iso(today + timedelta(days=75)),
            "currency": "USD",
            "bill_to": HOLDER,
            "line_items": items,
            "total": round(sum(item["amount"] for item in items), 2),
        },
    )


def _item(description: str, quantity: float, unit_price: float) -> dict:
    return {
        "description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": round(quantity * unit_price, 2),
    }


def _iso(value: date) -> str:
    return value.isoformat()
