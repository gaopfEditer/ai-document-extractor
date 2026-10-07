"""Expiry and due status. This module never calls a model."""

from __future__ import annotations

from datetime import date

EXPIRED = "expired"
EXPIRING_SOON = "expiring_soon"
VALID = "valid"
UNKNOWN = "unknown"

STATUSES = (EXPIRED, EXPIRING_SOON, VALID, UNKNOWN)


def compute_status(relevant: date | None, today: date, window_days: int) -> str:
    """Return a status from the date alone.

    A date inside the window includes today and the Nth day.
    Yesterday is expired. One day past the window is valid.
    """
    if window_days < 0:
        raise ValueError("reminder window must be zero or more days")
    if relevant is None:
        return UNKNOWN
    days = (relevant - today).days
    if days < 0:
        return EXPIRED
    if days <= window_days:
        return EXPIRING_SOON
    return VALID


def status_phrase(schema_name: str, status: str) -> str:
    if schema_name == "invoice":
        return {
            EXPIRED: "Past due",
            EXPIRING_SOON: "Due soon",
            VALID: "Not due yet",
            UNKNOWN: "No due date",
        }[status]
    return {
        EXPIRED: "Expired",
        EXPIRING_SOON: "Expiring soon",
        VALID: "In force",
        UNKNOWN: "No expiry date",
    }[status]


def explain_status(schema_name: str, relevant: date | None, today: date, window_days: int) -> str:
    noun = "due date" if schema_name == "invoice" else "expiry date"
    status = compute_status(relevant, today, window_days)
    phrase = status_phrase(schema_name, status)
    if relevant is None:
        return (
            f"No {noun} was found, so the status is \"{phrase}\" and no reminder is scheduled. "
            "This decision is made in code, not by the model."
        )
    days = (relevant - today).days
    when = relevant.isoformat()
    if status == EXPIRED:
        gap = f"{abs(days)} days before today" if abs(days) != 1 else "1 day before today"
    elif days == 0:
        gap = "today"
    elif days == 1:
        gap = "1 day after today"
    else:
        gap = f"{days} days after today"
    window = (
        f"inside the {window_days}-day reminder window"
        if status == EXPIRING_SOON
        else f"outside the {window_days}-day reminder window"
        if status == VALID
        else "before today"
    )
    return (
        f"The {noun} is {when}. Today is {today.isoformat()}, which is {gap} ({window}). "
        f"The status is \"{phrase}\". This decision is made in code, not by the model."
    )


def days_label(relevant: date | None, today: date) -> str:
    if relevant is None:
        return "—"
    days = (relevant - today).days
    if days == 0:
        return "Today"
    if days == 1:
        return "In 1 day"
    if days > 1:
        return f"In {days} days"
    if days == -1:
        return "1 day ago"
    return f"{abs(days)} days ago"
