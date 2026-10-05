"""Draw paginated pages into a real PDF with ReportLab.

- DejaVuSerif embedded for body, superscripts and footnotes;
- clickable cross-page links: reference superscript -> footnote, footnote
  number -> first reference;
- page numbers in the bottom margin.
"""

from __future__ import annotations

import io

from reportlab.pdfgen import canvas

from .measure import (
    BODY_LEADING,
    BODY_SIZE,
    FONT_NAME,
    FOOT_LEADING,
    FOOT_SIZE,
    SUPER_RISE,
    SUPER_SIZE,
    text_width,
    wrap_footnote,
)
from .paginate import BODY_WIDTH, BOTTOM_Y, FOOT_SEP, MARGIN, PAGE_H, PAGE_W, TOP_Y, Page


def _ref_dest(number: int) -> str:
    return f"ref-{number}"


def _fn_dest(number: int) -> str:
    return f"fn-{number}"


def render_pdf(pages: list[Page], fn_texts: dict[int, str]) -> bytes:
    buffer = io.BytesIO()
    canv = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    canv.setTitle("Maintenance Manual")

    space = text_width(" ", BODY_SIZE)
    total = len(pages)

    for page in pages:
        # --- body lines ---
        for i, pl in enumerate(page.lines):
            baseline = TOP_Y - BODY_LEADING * (i + 1) + (BODY_LEADING - BODY_SIZE) / 2
            x = MARGIN
            for ci, chunk in enumerate(pl.line.chunks):
                if ci:
                    x += space
                for run in chunk:
                    if run.kind == "text":
                        canv.setFont(FONT_NAME, BODY_SIZE)
                        canv.drawString(x, baseline, run.value)
                        x += run.width
                    else:
                        num = run.value
                        label = str(num)
                        canv.setFont(FONT_NAME, SUPER_SIZE)
                        canv.drawString(x, baseline + SUPER_RISE, label)
                        w = run.width
                        canv.linkRect(
                            "", _fn_dest(num),
                            Rect=(x, baseline, x + w, baseline + SUPER_RISE + SUPER_SIZE),
                            Border="[0 0 0]",
                        )
                        # First reference on this page: anchor for "back" links.
                        if num in pl.line.new_refs:
                            canv.bookmarkHorizontal(_ref_dest(num), x, baseline + SUPER_RISE)
                        x += w

        # --- footnote block ---
        if page.footnotes:
            block = FOOT_SEP + sum(
                len(wrap_footnote(fn_texts[n], n, BODY_WIDTH)) * FOOT_LEADING
                for n in page.footnotes
            )
            rule_y = BOTTOM_Y + block - FOOT_SEP / 2
            canv.setLineWidth(0.5)
            canv.line(MARGIN, rule_y, MARGIN + BODY_WIDTH * 0.35, rule_y)
            y = BOTTOM_Y + block - FOOT_SEP
            for n in page.footnotes:
                lines = wrap_footnote(fn_texts[n], n, BODY_WIDTH)
                prefix = f"{n}. "
                indent = text_width(prefix, FOOT_SIZE)
                for li, text in enumerate(lines):
                    baseline = y - FOOT_LEADING + (FOOT_LEADING - FOOT_SIZE) / 2
                    canv.setFont(FONT_NAME, FOOT_SIZE)
                    if li == 0:
                        canv.drawString(MARGIN, baseline, prefix)
                        w = text_width(prefix, FOOT_SIZE)
                        canv.linkRect(
                            "", _ref_dest(n),
                            Rect=(MARGIN, baseline - 1, MARGIN + w, baseline + FOOT_SIZE),
                            Border="[0 0 0]",
                        )
                        canv.bookmarkHorizontal(_fn_dest(n), MARGIN, baseline)
                    canv.drawString(MARGIN + indent, baseline, text)
                    y -= FOOT_LEADING

        # --- page number ---
        canv.setFont(FONT_NAME, FOOT_SIZE)
        label = f"Page {page.number} of {total}"
        canv.drawCentredString(PAGE_W / 2, BOTTOM_Y / 2, label)

        canv.showPage()

    canv.save()
    return buffer.getvalue()
