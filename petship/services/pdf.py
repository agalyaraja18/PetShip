"""PDF generation using ReportLab (free, no account).

Provides a small helper to render a titled, sectioned document to a byte
buffer. Used for the Terms PDF (Task 4) and later for adoption agreements
and medical record exports.
"""
from __future__ import annotations

import io

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

TERRACOTTA = HexColor("#A85D43")
ESPRESSO = HexColor("#46352F")


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "PSTitle",
            parent=base["Title"],
            textColor=TERRACOTTA,
            fontSize=22,
            spaceAfter=4,
            alignment=TA_LEFT,
        ),
        "meta": ParagraphStyle(
            "PSMeta",
            parent=base["Normal"],
            textColor=HexColor("#7a6a62"),
            fontSize=9,
            spaceAfter=16,
        ),
        "heading": ParagraphStyle(
            "PSHeading",
            parent=base["Heading2"],
            textColor=ESPRESSO,
            fontSize=13,
            spaceBefore=12,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "PSBody",
            parent=base["BodyText"],
            textColor=ESPRESSO,
            fontSize=10.5,
            leading=15,
            spaceAfter=6,
        ),
    }
    return styles


def render_document(title: str, subtitle: str, sections: list[tuple[str, str]]) -> bytes:
    """Render a document to PDF bytes.

    :param title: document title.
    :param subtitle: small meta line (e.g. effective date).
    :param sections: list of ``(heading, body_text)`` tuples.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=title,
    )
    styles = _styles()
    story = [
        Paragraph(title, styles["title"]),
        Paragraph(subtitle, styles["meta"]),
    ]
    for heading, body in sections:
        story.append(Paragraph(heading, styles["heading"]))
        story.append(Paragraph(body, styles["body"]))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "PetShip — Beyond Fur &amp; Feather; It's a Family.", styles["meta"]
        )
    )

    doc.build(story)
    return buffer.getvalue()
