"""Choose who gets a reminder, and either print the email or send it.

Selection rules are fixed:
- the expiry or due date is today or within N days
- the row has not already been reminded for this date
- the row is not waiting for a person to review it
"""

from __future__ import annotations

import json
import logging
import smtplib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from email.message import EmailMessage

from doc_extractor.config import Settings
from doc_extractor.logging_config import log_event
from doc_extractor.status import EXPIRING_SOON, compute_status, explain_status, status_phrase
from doc_extractor.storage import DocumentRecord, Repository

logger = logging.getLogger("doc_extractor.reminders")


@dataclass(frozen=True)
class ReminderMessage:
    document_id: str
    to_addr: str
    subject: str
    body: str


def plan_reminders(
    records: list[DocumentRecord],
    *,
    today: date,
    window_days: int,
    to_addr: str,
) -> list[ReminderMessage]:
    messages: list[ReminderMessage] = []
    for record in records:
        status = compute_status(record.relevant_date, today, window_days)
        if status != EXPIRING_SOON:
            continue
        if record.reminded_at:
            continue
        if record.needs_review:
            continue
        if record.relevant_date is None:
            continue
        messages.append(_compose(record, today, window_days, to_addr))
    messages.sort(key=lambda item: item.subject)
    return messages


def deliver(
    messages: list[ReminderMessage],
    *,
    settings: Settings,
    repo: Repository,
    dry_run: bool,
    sender=None,
) -> list[ReminderMessage]:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    preview = render_preview(messages, dry_run=dry_run, created_at=created_at)
    settings.reminder_preview_path.parent.mkdir(parents=True, exist_ok=True)
    settings.reminder_preview_path.write_text(preview, encoding="utf-8")
    repo.set_meta(
        "last_reminder_run",
        json.dumps(
            {
                "created_at": created_at,
                "dry_run": dry_run,
                "messages": [asdict(message) for message in messages],
            }
        ),
    )
    if dry_run:
        log_event(logger, logging.INFO, "reminder_dry_run", count=len(messages))
        return messages
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is empty. Add SMTP settings, or leave REMINDER_DRY_RUN=true.")
    send = sender or _smtp_send
    for message in messages:
        send(settings, message)
        repo.mark_reminded(message.document_id, created_at)
        log_event(logger, logging.INFO, "reminder_sent", document_id=message.document_id, to=message.to_addr)
    return messages


def refresh_statuses(
    records: list[DocumentRecord],
    *,
    today: date,
    window_days: int,
    repo: Repository,
) -> list[DocumentRecord]:
    changed: list[DocumentRecord] = []
    for record in records:
        status = compute_status(record.relevant_date, today, window_days)
        if status != record.expiry_status:
            repo.update_status(record.id, status)
            record.expiry_status = status
            changed.append(record)
    if changed:
        repo.export_csv()
    return changed


def render_preview(messages: list[ReminderMessage], *, dry_run: bool, created_at: str) -> str:
    mode = "DRY RUN — nothing was sent" if dry_run else "SENT"
    lines = [
        "AI Document Extractor reminder preview",
        f"Mode: {mode}",
        f"Created: {created_at}",
        f"Messages: {len(messages)}",
        "",
    ]
    if not messages:
        lines.append("No document is inside the reminder window.")
        lines.append("")
        return "\n".join(lines)
    for index, message in enumerate(messages, start=1):
        lines.extend(
            [
                f"----- Message {index} -----",
                f"To: {message.to_addr}",
                f"Subject: {message.subject}",
                "",
                message.body.rstrip(),
                "",
            ]
        )
    return "\n".join(lines)


def _compose(record: DocumentRecord, today: date, window_days: int, to_addr: str) -> ReminderMessage:
    assert record.relevant_date is not None
    days = (record.relevant_date - today).days
    day_word = "day" if days == 1 else "days"
    if record.schema_name == "invoice":
        when = "today" if days == 0 else f"in {days} {day_word}"
        subject = f"Invoice due {when}: {record.reference} ({record.title})"
        intro = "An invoice in your tracker is coming due."
        date_label = "Due date"
    else:
        when = "today" if days == 0 else f"in {days} {day_word}"
        subject = f"Certificate expiring {when}: {record.title}"
        intro = "A certificate of insurance in your tracker is approaching its expiry date."
        date_label = "Expiry date"
    rows = [
        f"Name: {record.title or 'Unknown'}",
        f"Reference: {record.reference or 'Unknown'}",
    ]
    if record.schema_name == "coi" and record.secondary:
        rows.append(f"Insurer: {record.secondary}")
    rows.append(f"{date_label}: {record.relevant_date.isoformat()}")
    rows.append(f"Days remaining: {days}")
    rows.append(f"Status: {status_phrase(record.schema_name, EXPIRING_SOON)}")
    body = "\n".join(
        [
            "Hello,",
            "",
            intro,
            "",
            *rows,
            "",
            explain_status(record.schema_name, record.relevant_date, today, window_days),
            "",
            "This reminder was selected by a fixed rule: the date falls inside the configured window, "
            "the row has not already been reminded, and it was not flagged for review.",
            "",
            "Please follow up before the date passes.",
            "",
        ]
    )
    return ReminderMessage(
        document_id=record.id,
        to_addr=to_addr,
        subject=subject,
        body=body,
    )


def _smtp_send(settings: Settings, message: ReminderMessage) -> None:
    email = EmailMessage()
    email["Subject"] = message.subject
    email["From"] = settings.reminder_from
    email["To"] = message.to_addr
    email.set_content(message.body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(email)
