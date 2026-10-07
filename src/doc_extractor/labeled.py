"""Read the labeled layout printed on the sample PDFs.

Real provider mode does not use this module. The mock provider does, so the
offline demo still returns the same JSON shape as a model.
"""

from __future__ import annotations

import re

from doc_extractor.models import parse_date

COI_LABELS = (
    "Named Insured",
    "Policy Number",
    "Insurance Company",
    "Insurer",
    "Effective Date",
    "Expiry Date",
    "Expiration Date",
    "Certificate Holder",
    "Coverages",
    "Remarks",
)

INVOICE_LABELS = (
    "Vendor",
    "Invoice Number",
    "Invoice Date",
    "Due Date",
    "Currency",
    "Bill To",
    "Items",
    "Total",
    "Remarks",
)


def render_coi_lines(fields: dict) -> list[str]:
    lines = [
        f"Named Insured: {fields['company_name']}",
        f"Policy Number: {fields['policy_number']}",
        f"Insurance Company: {fields['insurer']}",
        f"Effective Date: {fields['effective_date']}",
    ]
    if fields.get("expiry_date"):
        lines.append(f"Expiry Date: {fields['expiry_date']}")
    if fields.get("certificate_holder"):
        lines.append(f"Certificate Holder: {fields['certificate_holder']}")
    lines.append("Coverages:")
    for coverage in fields.get("coverages", []):
        lines.append(f"- {coverage['coverage_type']}: {coverage['limit']}")
    return lines


def render_invoice_lines(fields: dict) -> list[str]:
    currency = fields.get("currency", "USD")
    lines = [
        f"Vendor: {fields['vendor']}",
        f"Invoice Number: {fields['invoice_number']}",
        f"Invoice Date: {fields['invoice_date']}",
        f"Due Date: {fields['due_date']}",
        f"Currency: {currency}",
    ]
    if fields.get("bill_to"):
        lines.append(f"Bill To: {fields['bill_to']}")
    lines.append("Items:")
    for item in fields.get("line_items", []):
        qty = _format_qty(item["quantity"])
        lines.append(
            f"- {item['description']}: qty {qty}, unit {item['unit_price']:.2f}, amount {item['amount']:.2f}"
        )
    lines.append(f"Total: {fields['total']:.2f} {currency}")
    return lines


def parse_coi(text: str) -> dict:
    normalized = _normalize(text, COI_LABELS)
    coverages = []
    for bullet in _section_bullets(normalized, "Coverages"):
        if ": " in bullet:
            name, limit = bullet.split(": ", 1)
        else:
            name, limit = bullet, ""
        name = name.strip()
        if not name:
            continue
        coverages.append({"coverage_type": name, "limit": limit.strip()})
    return {
        "company_name": _field(normalized, "Named Insured"),
        "policy_number": _field(normalized, "Policy Number"),
        "insurer": _field(normalized, "Insurance Company") or _field(normalized, "Insurer"),
        "coverage_types": [item["coverage_type"] for item in coverages],
        "limits": coverages,
        "effective_date": parse_date(_field(normalized, "Effective Date")),
        "expiry_date": parse_date(_field(normalized, "Expiry Date") or _field(normalized, "Expiration Date")),
    }


def parse_invoice(text: str) -> dict:
    normalized = _normalize(text, INVOICE_LABELS)
    items = []
    for bullet in _section_bullets(normalized, "Items"):
        items.append(_parse_item(bullet))
    total, total_currency = _parse_total(_field(normalized, "Total"))
    currency = _field(normalized, "Currency") or total_currency or "USD"
    return {
        "vendor": _field(normalized, "Vendor"),
        "invoice_number": _field(normalized, "Invoice Number"),
        "invoice_date": parse_date(_field(normalized, "Invoice Date")),
        "due_date": parse_date(_field(normalized, "Due Date")),
        "line_items": items,
        "total": total,
        "currency": currency.upper(),
    }


_ITEM_RE = re.compile(
    r"^(?P<desc>.+?):\s*qty\s*(?P<qty>[\d.,]+),\s*unit\s*(?P<unit>[\d.,]+),\s*amount\s*(?P<amt>[\d.,]+)\s*$",
    re.IGNORECASE,
)


def _parse_item(bullet: str) -> dict:
    match = _ITEM_RE.match(bullet.strip())
    if not match:
        return {
            "description": bullet.strip(),
            "quantity": None,
            "unit_price": None,
            "amount": None,
        }
    return {
        "description": match.group("desc").strip(),
        "quantity": _money(match.group("qty")),
        "unit_price": _money(match.group("unit")),
        "amount": _money(match.group("amt")),
    }


def _parse_total(raw: str | None) -> tuple[float | None, str | None]:
    if not raw:
        return None, None
    currency_match = re.search(r"\b([A-Z]{3})\b", raw)
    currency = currency_match.group(1) if currency_match else None
    return _money(raw), currency


def _money(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.*?)\s*$", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _section_bullets(text: str, header: str) -> list[str]:
    bullets: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if not collecting:
            if stripped.lower() in {header.lower(), f"{header.lower()}:"}:
                collecting = True
            continue
        if not stripped:
            break
        if stripped.startswith("-"):
            bullets.append(stripped[1:].strip())
            continue
        # A new label, a footer, or any other prose ends the list.
        break
    return bullets


def _normalize(text: str, labels: tuple[str, ...]) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for label in labels:
        normalized = re.sub(
            rf"[ \t]+({re.escape(label)}\s*:)",
            r"\n\1",
            normalized,
            flags=re.IGNORECASE,
        )
    # PDF text sometimes indents the first bullet ("\n - Item"), which used to
    # become a blank line and end the section. Inline bullets ("Coverages: - Item")
    # are split onto their own line as well.
    normalized = re.sub(r"\n[ \t]+-\s+", "\n- ", normalized)
    normalized = re.sub(r"[ \t]+-\s+", "\n- ", normalized)
    return normalized


def _format_qty(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"
