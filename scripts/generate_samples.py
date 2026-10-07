#!/usr/bin/env python3
"""Write fictional sample PDFs and the canned JSON the offline demo can fall back to."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doc_extractor.catalog import sample_documents  # noqa: E402
from doc_extractor.labeled import parse_coi, parse_invoice  # noqa: E402
from doc_extractor.models import get_schema  # noqa: E402
from doc_extractor.review import preliminary_judgement  # noqa: E402
from doc_extractor.sample_pdf import draw_sample_pdf  # noqa: E402
from doc_extractor.status import compute_status  # noqa: E402


def main() -> None:
    today = date.today()
    destination = ROOT / "samples"
    canned_dir = destination / "canned"
    canned_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"D:{today.strftime('%Y%m%d')}000000+00'00'"
    manifest_docs = []
    for sample in sample_documents(today):
        draw_sample_pdf(destination / sample.filename, sample, stamp=stamp)
        text = "\n".join(sample.lines)
        schema = get_schema(sample.schema_name)
        parsed = parse_coi(text) if schema.name == "coi" else parse_invoice(text)
        payload = preliminary_judgement(parsed, schema)
        needle = sample.fields.get("company_name") or sample.fields.get("vendor")
        entry = {
            "schema": schema.name,
            "filename": sample.filename,
            "needle": needle,
            "payload": payload,
        }
        (canned_dir / f"{Path(sample.filename).stem}.json").write_text(
            json.dumps(entry, indent=2) + "\n",
            encoding="utf-8",
        )
        relevant = payload.get(schema.date_field)
        status = compute_status(
            date.fromisoformat(relevant) if relevant else None,
            today,
            30,
        )
        manifest_docs.append(
            {
                "filename": sample.filename,
                "schema": schema.name,
                "title": needle,
                "relevant_date": relevant,
                "status_if_window_is_30_days": status,
                "needs_review": payload["needs_review"],
            }
        )
    manifest = {
        "generated_on": today.isoformat(),
        "note": "Fictional documents. Dates are relative to generated_on so a 30-day window stays illustrative.",
        "documents": manifest_docs,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest_docs)} sample PDFs to {destination}")


if __name__ == "__main__":
    main()
