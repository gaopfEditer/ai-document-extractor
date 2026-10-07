"""Server-rendered tracker page. The table is HTML, so it works with JavaScript off."""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

from doc_extractor.config import Settings
from doc_extractor.status import compute_status, days_label, explain_status, status_phrase
from doc_extractor.storage import DocumentRecord

_TEMPLATE = Path(__file__).with_name("templates") / "dashboard.html"


def render_dashboard(
    *,
    records: list[DocumentRecord],
    reminder_run: dict | None,
    settings: Settings,
    view: str,
    error: str | None,
    today: date,
) -> str:
    window = settings.reminder_days
    prepared = [_decorate(record, today, window) for record in records]
    visible = [item for item in prepared if _matches(item, view)]
    visible.sort(key=lambda item: (item["rank"], item["sort_date"], item["title"]))
    template = _TEMPLATE.read_text(encoding="utf-8")
    mode = "Offline demo · no model call" if settings.llm_provider == "mock" else f"Live model · {settings.llm_provider}"
    replacements = {
        "[[MODE]]": escape(mode),
        "[[ERROR]]": _error_banner(error),
        "[[STATS]]": _stats(prepared),
        "[[FILTERS]]": _filters(prepared, view),
        "[[ROWS]]": _rows(visible) if visible else _empty(view),
        "[[REMINDERS]]": _reminders(reminder_run),
        "[[TODAY]]": escape(today.isoformat()),
        "[[WINDOW]]": str(window),
        "[[PROVIDER_NOTE]]": _provider_note(settings),
    }
    html = template
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


def _decorate(record: DocumentRecord, today: date, window: int) -> dict:
    status = compute_status(record.relevant_date, today, window)
    return {
        "record": record,
        "status": status,
        "phrase": status_phrase(record.schema_name, status),
        "rank": {"expiring_soon": 0, "expired": 1, "unknown": 2, "valid": 3}[status],
        "sort_date": record.relevant_date or date.max,
        "title": record.title or record.filename,
        "days": days_label(record.relevant_date, today),
        "explanation": explain_status(record.schema_name, record.relevant_date, today, window),
    }


def _matches(item: dict, view: str) -> bool:
    record: DocumentRecord = item["record"]
    if view == "coi":
        return record.schema_name == "coi"
    if view == "invoice":
        return record.schema_name == "invoice"
    if view == "review":
        return record.needs_review
    return True


def _stats(items: list[dict]) -> str:
    soon = sum(1 for item in items if item["status"] == "expiring_soon")
    expired = sum(1 for item in items if item["status"] == "expired")
    review = sum(1 for item in items if item["record"].needs_review)
    cards = [
        ("Documents", str(len(items)), "PDFs read into the tracker"),
        ("Inside the window", str(soon), "Will be included in the reminder run"),
        ("Past the date", str(expired), "Shown here, not emailed again"),
        ("Needs review", str(review), "A person should check the fields"),
    ]
    return "".join(
        "<article class='stat'><p class='stat-label'>{label}</p><p class='stat-value'>{value}</p><p class='stat-note'>{note}</p></article>".format(
            label=escape(label),
            value=escape(value),
            note=escape(note),
        )
        for label, value, note in cards
    )


def _filters(items: list[dict], view: str) -> str:
    counts = {
        "all": len(items),
        "coi": sum(1 for item in items if item["record"].schema_name == "coi"),
        "invoice": sum(1 for item in items if item["record"].schema_name == "invoice"),
        "review": sum(1 for item in items if item["record"].needs_review),
    }
    labels = {
        "all": "All",
        "coi": "Certificates",
        "invoice": "Invoices",
        "review": "Needs review",
    }
    parts = []
    for key, label in labels.items():
        cls = "filter is-active" if key == view else "filter"
        href = "/" if key == "all" else f"/?view={key}"
        parts.append(
            f"<a class='{cls}' href='{href}'>{escape(label)} <span>{counts[key]}</span></a>"
        )
    return "".join(parts)


def _rows(items: list[dict]) -> str:
    blocks = []
    for item in items:
        record: DocumentRecord = item["record"]
        review = "<em class='review-flag'>Needs review</em>" if record.needs_review else "<em class='quiet'>Ready</em>"
        blocks.append(
            f"""
            <article class="row-card status-{escape(item['status'])}">
              <div class="row-main">
                <div>
                  <p class="kicker">{escape(_kind(record.schema_name))} · {escape(record.filename)}</p>
                  <h2>{escape(record.title or 'Untitled document')}</h2>
                  <p class="meta">{escape(record.reference or 'No reference')}{escape(_secondary(record))}</p>
                </div>
                <div class="row-status">
                  <span class="pill pill-{escape(item['status'])}">{escape(item['phrase'])}</span>
                  <span class="when">{escape(item['days'])}</span>
                  {review}
                </div>
              </div>
              <dl class="facts">
                <div><dt>Date</dt><dd>{escape(record.relevant_date.isoformat() if record.relevant_date else '—')}</dd></div>
                <div><dt>Confidence</dt><dd>{record.confidence * 100:.0f}%</dd></div>
                <div><dt>Source</dt><dd>{escape(record.source)}</dd></div>
                <div><dt>Text</dt><dd>{escape(record.text_status)}</dd></div>
              </dl>
              <p class="why">{escape(item['explanation'])}</p>
              {_reasons(record)}
              <details>
                <summary>Fields copied from the document</summary>
                {_payload_html(record)}
              </details>
            </article>
            """
        )
    return "".join(blocks)


def _empty(view: str) -> str:
    messages = {
        "all": "No documents yet. Run the demo, drop a PDF in the inbox folder, or upload one here.",
        "coi": "No certificates in the tracker yet.",
        "invoice": "No invoices in the tracker yet.",
        "review": "Nothing is waiting for review.",
    }
    return f"<p class='empty'>{escape(messages.get(view, messages['all']))}</p>"


def _reasons(record: DocumentRecord) -> str:
    if not record.review_reasons:
        return ""
    items = "".join(f"<li>{escape(reason)}</li>" for reason in record.review_reasons)
    return f"<ul class='reasons'>{items}</ul>"


def _payload_html(record: DocumentRecord) -> str:
    payload = record.payload
    if record.schema_name == "coi":
        coverages = payload.get("limits") or []
        coverage_html = "".join(
            f"<li>{escape(str(item.get('coverage_type', '')))}: {escape(str(item.get('limit', '')))}</li>"
            for item in coverages
            if isinstance(item, dict)
        ) or "<li>None listed</li>"
        return f"""
        <dl class="payload">
          <div><dt>Company</dt><dd>{escape(_show(payload.get('company_name')))}</dd></div>
          <div><dt>Policy</dt><dd>{escape(_show(payload.get('policy_number')))}</dd></div>
          <div><dt>Insurer</dt><dd>{escape(_show(payload.get('insurer')))}</dd></div>
          <div><dt>Effective</dt><dd>{escape(_show(payload.get('effective_date')))}</dd></div>
          <div><dt>Expiry</dt><dd>{escape(_show(payload.get('expiry_date')))}</dd></div>
        </dl>
        <ul class="coverages">{coverage_html}</ul>
        """
    items = payload.get("line_items") or []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr><td>{desc}</td><td>{qty}</td><td>{unit}</td><td>{amount}</td></tr>".format(
                desc=escape(str(item.get("description") or "")),
                qty=escape(_show(item.get("quantity"))),
                unit=escape(_show(item.get("unit_price"))),
                amount=escape(_show(item.get("amount"))),
            )
        )
    table = (
        "<table class='lines'><thead><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Amount</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=\"4\">No line items</td></tr>'}</tbody></table>"
    )
    total = payload.get("total")
    currency = payload.get("currency") or "USD"
    total_text = "—" if total is None else f"{currency} {float(total):,.2f}"
    return f"""
    <dl class="payload">
      <div><dt>Vendor</dt><dd>{escape(_show(payload.get('vendor')))}</dd></div>
      <div><dt>Invoice</dt><dd>{escape(_show(payload.get('invoice_number')))}</dd></div>
      <div><dt>Invoice date</dt><dd>{escape(_show(payload.get('invoice_date')))}</dd></div>
      <div><dt>Due</dt><dd>{escape(_show(payload.get('due_date')))}</dd></div>
      <div><dt>Total</dt><dd>{escape(total_text)}</dd></div>
    </dl>
    {table}
    """


def _reminders(run: dict | None) -> str:
    if not run:
        return "<p class='empty'>No reminder run yet.</p>"
    messages = run.get("messages") or []
    mode = "Dry run — nothing was sent." if run.get("dry_run", True) else "Sent over SMTP."
    created = escape(str(run.get("created_at") or ""))
    if not messages:
        return (
            f"<p class='reminder-mode'>{escape(mode)}</p>"
            f"<p class='empty'>No document is inside the reminder window. Checked {created}.</p>"
        )
    cards = []
    for message in messages:
        cards.append(
            f"""
            <article class="mail">
              <p class="kicker">To {escape(str(message.get('to_addr') or ''))}</p>
              <h3>{escape(str(message.get('subject') or ''))}</h3>
              <pre>{escape(str(message.get('body') or ''))}</pre>
            </article>
            """
        )
    return f"<p class='reminder-mode'>{escape(mode)} Checked {created}.</p>" + "".join(cards)


def _error_banner(error: str | None) -> str:
    if not error:
        return ""
    return f"<p class='banner' role='alert'>{escape(error)}</p>"


def _provider_note(settings: Settings) -> str:
    if settings.llm_provider == "mock":
        return (
            "Demo mode reads the sample layout locally and can fall back to canned JSON. "
            "No API key is used. Expiry status and reminder choice never come from a model."
        )
    return (
        f"Fields are read by {settings.llm_provider}. "
        "Expiry status and reminder choice are still calculated in code."
    )


def _kind(schema_name: str) -> str:
    return "Certificate" if schema_name == "coi" else "Invoice"


def _secondary(record: DocumentRecord) -> str:
    if record.secondary:
        return f" · {record.secondary}"
    return ""


def _show(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def reminder_run_from_meta(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
