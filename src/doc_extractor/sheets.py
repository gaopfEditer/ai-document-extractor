"""Google Sheets sink. Local CSV and SQLite are written even when this is not configured."""

from __future__ import annotations

import logging

from doc_extractor.alerts import AlertHook
from doc_extractor.config import Settings
from doc_extractor.logging_config import log_event
from doc_extractor.storage import CSV_HEADERS, DocumentRecord, record_to_csv

logger = logging.getLogger("doc_extractor.sheets")


class SheetsSink:
    def __init__(self, settings: Settings, alerts: AlertHook):
        self.settings = settings
        self.alerts = alerts
        self._worksheet = None
        self._warned = False

    @property
    def enabled(self) -> bool:
        return bool(self.settings.google_service_account_file and self.settings.google_sheet_id)

    def upsert(self, record: DocumentRecord) -> None:
        if not self.enabled:
            if not self._warned:
                log_event(logger, logging.INFO, "sheets_not_configured")
                self._warned = True
            return
        try:
            worksheet = self._open()
            self._ensure_header(worksheet)
            row = [record_to_csv(record)[column] for column in CSV_HEADERS]
            cell = worksheet.find(record.id, in_column=1)
            if cell:
                end = _column_letter(len(CSV_HEADERS))
                worksheet.update(
                    values=[row],
                    range_name=f"A{cell.row}:{end}{cell.row}",
                    value_input_option="RAW",
                )
            else:
                worksheet.append_row(row, value_input_option="RAW")
            log_event(logger, logging.INFO, "sheets_upserted", document_id=record.id)
        except Exception as exc:
            log_event(logger, logging.ERROR, "sheets_upsert_failed", document_id=record.id, error=str(exc))
            self.alerts.send(f"Google Sheets update failed for {record.filename}: {exc}")

    def _open(self):
        if self._worksheet is not None:
            return self._worksheet
        import gspread
        from gspread.exceptions import WorksheetNotFound

        client = gspread.service_account(filename=self.settings.google_service_account_file)
        spreadsheet = client.open_by_key(self.settings.google_sheet_id)
        try:
            worksheet = spreadsheet.worksheet(self.settings.google_worksheet)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                self.settings.google_worksheet,
                rows=1000,
                cols=len(CSV_HEADERS),
            )
        self._worksheet = worksheet
        return worksheet

    def _ensure_header(self, worksheet) -> None:
        current = worksheet.row_values(1)
        if current == CSV_HEADERS:
            return
        if current and current[0] not in {"", "id"}:
            return
        worksheet.update(values=[CSV_HEADERS], range_name="A1", value_input_option="RAW")


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
