"""Poll a folder for new PDFs. Subfolders named coi or invoice set the schema."""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

from doc_extractor.config import Settings
from doc_extractor.logging_config import log_event
from doc_extractor.pipeline import Pipeline

logger = logging.getLogger("doc_extractor.watcher")


class FolderWatcher:
    def __init__(self, pipeline: Pipeline, settings: Settings):
        self.pipeline = pipeline
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failed: set[str] = set()

    def start(self) -> None:
        self.settings.watch_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._loop, name="inbox-watch", daemon=True)
        self._thread.start()
        log_event(logger, logging.INFO, "watch_started", folder=str(self.settings.watch_dir))

    def stop(self) -> None:
        self._stop.set()

    def scan_once(self) -> int:
        root = self.settings.watch_dir
        if not root.exists():
            return 0
        processed = 0
        for path in sorted(root.rglob("*.pdf")):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in self._failed or self.pipeline.repo.has_hash(digest):
                continue
            hint = path.parent.name if path.parent.name in {"coi", "invoice"} else None
            try:
                self.pipeline.process_bytes(
                    data,
                    filename=path.name,
                    schema_hint=hint,
                    source="watch",
                    parent_name=path.parent.name,
                )
                processed += 1
            except Exception as exc:
                self._failed.add(digest)
                log_event(logger, logging.ERROR, "watch_file_failed", filename=path.name, error=str(exc))
                self.pipeline.alerts.send(f"Failed to process {path.name} from the inbox folder: {exc}")
        return processed

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                log_event(logger, logging.ERROR, "watch_scan_failed", error=str(exc))
            self._stop.wait(self.settings.watch_interval_seconds)


def watched_pdfs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.rglob("*.pdf"))
