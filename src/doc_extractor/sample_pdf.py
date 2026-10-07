"""Draw a one-page sample PDF whose text extraction stays line-oriented."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from doc_extractor.catalog import SampleDocument

INK = HexColor("#221E19")
MUTED = HexColor("#5E584E")
PINE = HexColor("#1E4D3C")
RULE = HexColor("#E4DCCB")
PAPER = HexColor("#F7F3EA")
CREAM = HexColor("#F4F0E6")


def draw_sample_pdf(path: Path, sample: SampleDocument, *, stamp: str = "D:20261006000000+00'00'") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    pdf.setTitle(sample.heading)
    pdf.setAuthor("AI Document Extractor demo")
    pdf.setCreator("AI Document Extractor demo")
    pdf.setSubject("Fictional sample document")
    _freeze_info(pdf, stamp)

    width, height = letter
    pdf.setFillColor(PAPER)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(PINE)
    pdf.setLineWidth(1.5)
    pdf.rect(32, 32, width - 64, height - 64, fill=0, stroke=1)

    pdf.setFillColor(PINE)
    pdf.rect(32, height - 118, width - 64, 86, fill=1, stroke=0)
    pdf.setFillColor(CREAM)
    pdf.setFont("Times-Bold", 18)
    pdf.drawString(52, height - 72, sample.heading)
    pdf.setFont("Times-Roman", 9)
    pdf.drawString(52, height - 92, sample.kicker)

    y = height - 150
    for line in sample.lines:
        if y < 58:
            pdf.showPage()
            _freeze_info(pdf, stamp)
            y = height - 72
        if line.endswith(":") and not line.startswith("-"):
            pdf.setFont("Times-Bold", 12)
            pdf.setFillColor(PINE)
            pdf.drawString(52, y, line)
            y -= 20
            continue
        if line.startswith("- "):
            pdf.setFont("Times-Roman", 11)
            pdf.setFillColor(INK)
            pdf.drawString(66, y, line)
            y -= 16
            continue
        if line.startswith("Remarks:"):
            pdf.setFont("Times-Italic", 10)
            pdf.setFillColor(MUTED)
            pdf.drawString(52, y, line)
            y -= 18
            continue
        pdf.setFont("Times-Roman", 11)
        pdf.setFillColor(INK)
        pdf.drawString(52, y, line)
        pdf.setStrokeColor(RULE)
        pdf.setLineWidth(0.4)
        pdf.line(52, y - 4, width - 52, y - 4)
        y -= 20

    pdf.setFillColor(MUTED)
    pdf.setFont("Times-Italic", 8)
    pdf.drawString(
        52,
        44,
        "Fictional names for a software demo. Not a policy, certificate, or invoice.",
    )
    pdf.save()


def _freeze_info(pdf: canvas.Canvas, stamp: str) -> None:
    info = pdf._doc.info
    info.created = stamp
    info.modified = stamp
    info.creator = "AI Document Extractor demo"
