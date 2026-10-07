"""SQLite is the source of truth. A CSV export mirrors it for people who do not want a database."""

from __future__ import annotations

import csv
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

CSV_HEADERS = [
    "id",
    "processed_at",
    "schema",
    "filename",
    "title",
    "reference",
    "secondary",
    "relevant_date",
    "status",
    "confidence",
    "needs_review",
    "review_reasons",
    "source",
    "text_status",
    "payload_json",
]


@dataclass
class DocumentRecord:
    id: str
    content_hash: str
    schema_name: str
    source: str
    filename: str
    title: str | None
    reference: str | None
    secondary: str | None
    relevant_date: date | None
    expiry_status: str
    confidence: float
    needs_review: bool
    review_reasons: list[str]
    payload: dict
    raw_text: str
    processed_at: str
    reminded_at: str | None
    text_status: str


class Repository:
    def __init__(self, database_path: Path, csv_path: Path):
        self.database_path = Path(database_path)
        self.csv_path = Path(csv_path)
        self._lock = threading.Lock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with self._lock, self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    title TEXT,
                    reference_value TEXT,
                    secondary TEXT,
                    relevant_date TEXT,
                    expiry_status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    needs_review INTEGER NOT NULL,
                    review_reasons TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    reminded_at TEXT,
                    text_status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def save(self, record: DocumentRecord) -> DocumentRecord:
        with self._lock:
            with self._session() as conn:
                existing = conn.execute(
                    "SELECT relevant_date, reminded_at FROM documents WHERE id = ?",
                    (record.id,),
                ).fetchone()
                if existing is not None:
                    previous_date = existing["relevant_date"]
                    current_date = record.relevant_date.isoformat() if record.relevant_date else None
                    if previous_date == current_date:
                        record.reminded_at = existing["reminded_at"]
                self._upsert(conn, record)
            self._export_csv_unlocked()
        return record

    def update_status(self, document_id: str, status: str) -> None:
        with self._lock, self._session() as conn:
            conn.execute("UPDATE documents SET expiry_status = ? WHERE id = ?", (status, document_id))

    def mark_reminded(self, document_id: str, reminded_at: str) -> None:
        with self._lock, self._session() as conn:
            conn.execute("UPDATE documents SET reminded_at = ? WHERE id = ?", (reminded_at, document_id))

    def has_hash(self, content_hash: str) -> bool:
        with self._lock, self._session() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._lock, self._session() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return _from_row(row) if row else None

    def list_all(self) -> list[DocumentRecord]:
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY processed_at DESC, filename ASC"
            ).fetchall()
        return [_from_row(row) for row in rows]

    def delete_samples_not_in(self, filenames: set[str]) -> None:
        with self._lock, self._session() as conn:
            if not filenames:
                conn.execute("DELETE FROM documents WHERE source = 'sample'")
                return
            marks = ",".join("?" for _ in filenames)
            conn.execute(
                f"DELETE FROM documents WHERE source = 'sample' AND filename NOT IN ({marks})",
                tuple(sorted(filenames)),
            )

    def export_csv(self) -> None:
        with self._lock:
            self._export_csv_unlocked()

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._session() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        with self._lock, self._session() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _export_csv_unlocked(self) -> None:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY schema_name, filename").fetchall()
        records = [_from_row(row) for row in rows]
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
            writer.writeheader()
            for record in records:
                writer.writerow(record_to_csv(record))

    def _upsert(self, conn: sqlite3.Connection, record: DocumentRecord) -> None:
        conn.execute(
            """
            INSERT INTO documents (
                id, content_hash, schema_name, source, filename, title, reference_value,
                secondary, relevant_date, expiry_status, confidence, needs_review,
                review_reasons, payload_json, raw_text, processed_at, reminded_at, text_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content_hash = excluded.content_hash,
                schema_name = excluded.schema_name,
                source = excluded.source,
                filename = excluded.filename,
                title = excluded.title,
                reference_value = excluded.reference_value,
                secondary = excluded.secondary,
                relevant_date = excluded.relevant_date,
                expiry_status = excluded.expiry_status,
                confidence = excluded.confidence,
                needs_review = excluded.needs_review,
                review_reasons = excluded.review_reasons,
                payload_json = excluded.payload_json,
                raw_text = excluded.raw_text,
                processed_at = excluded.processed_at,
                reminded_at = excluded.reminded_at,
                text_status = excluded.text_status
            """,
            _to_tuple(record),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def record_to_csv(record: DocumentRecord) -> dict[str, str]:
    return {
        "id": record.id,
        "processed_at": record.processed_at,
        "schema": record.schema_name,
        "filename": record.filename,
        "title": record.title or "",
        "reference": record.reference or "",
        "secondary": record.secondary or "",
        "relevant_date": record.relevant_date.isoformat() if record.relevant_date else "",
        "status": record.expiry_status,
        "confidence": f"{record.confidence:.2f}",
        "needs_review": "yes" if record.needs_review else "no",
        "review_reasons": "; ".join(record.review_reasons),
        "source": record.source,
        "text_status": record.text_status,
        "payload_json": json.dumps(record.payload, ensure_ascii=False),
    }


def _to_tuple(record: DocumentRecord) -> tuple:
    return (
        record.id,
        record.content_hash,
        record.schema_name,
        record.source,
        record.filename,
        record.title,
        record.reference,
        record.secondary,
        record.relevant_date.isoformat() if record.relevant_date else None,
        record.expiry_status,
        record.confidence,
        1 if record.needs_review else 0,
        json.dumps(record.review_reasons),
        json.dumps(record.payload, ensure_ascii=False),
        record.raw_text,
        record.processed_at,
        record.reminded_at,
        record.text_status,
    )


def _from_row(row: sqlite3.Row) -> DocumentRecord:
    raw_date = row["relevant_date"]
    return DocumentRecord(
        id=row["id"],
        content_hash=row["content_hash"],
        schema_name=row["schema_name"],
        source=row["source"],
        filename=row["filename"],
        title=row["title"],
        reference=row["reference_value"],
        secondary=row["secondary"],
        relevant_date=date.fromisoformat(raw_date) if raw_date else None,
        expiry_status=row["expiry_status"],
        confidence=float(row["confidence"]),
        needs_review=bool(row["needs_review"]),
        review_reasons=json.loads(row["review_reasons"]),
        payload=json.loads(row["payload_json"]),
        raw_text=row["raw_text"],
        processed_at=row["processed_at"],
        reminded_at=row["reminded_at"],
        text_status=row["text_status"],
    )
