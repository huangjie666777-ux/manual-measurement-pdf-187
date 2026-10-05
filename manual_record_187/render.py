"""Draw paginated manuscripts, fillable templates and finalized records."""

from __future__ import annotations

import io

from reportlab.lib.colors import black, white
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
from .paginate import (
    BODY_WIDTH,
    BOTTOM_Y,
    FOOT_SEP,
    FORM_HEIGHT,
    MARGIN,
    PAGE_H,
    PAGE_W,
    TOP_Y,
    FormBlock,
    Page,
    PageLine,
)


def _ref_dest(number: int) -> str:
    return f"ref-{number}"


def _fn_dest(number: int) -> str:
    return f"fn-{number}"


def _baseline_for_slot(slot: int) -> float:
    return TOP_Y - BODY_LEADING * (slot + 1) + (BODY_LEADING - BODY_SIZE) / 2


def _format_bound(value: float) -> str:
    text = format(value, ".12g")
    return text


def _metadata_text(spec) -> str:
    return (
        f"{spec.name} [{spec.unit}] "
        f"({_format_bound(spec.lower_bound)} to {_format_bound(spec.upper_bound)})"
    )


def render_pdf(
    pages: list[Page],
    fn_texts: dict[int, str],
    measurements=None,
    values: dict[str, str] | None = None,
    judgments: dict[str, str] | None = None,
    editable: bool = True,
) -> bytes:
    measurements = list(measurements or [])
    values = values or {}
    judgments = judgments or {}
    buffer = io.BytesIO()
    canv = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    canv.setTitle("Maintenance Manual")
    total = len(pages)

    for page in pages:
        slot = 0
        for item in page.items:
            baseline = _baseline_for_slot(slot)

            if isinstance(item, PageLine):
                x = MARGIN
                for piece in item.line.items:
                    if not isinstance(piece, list):
                        canv.setFont(FONT_NAME, BODY_SIZE)
                        canv.drawString(x, baseline, piece.value)
                        x += piece.width
                        continue

                    for run in piece:
                        if run.kind == "text":
                            canv.setFont(FONT_NAME, BODY_SIZE)
                            canv.drawString(x, baseline, run.value)
                            x += run.width
                        else:
                            number = run.value
                            canv.setFont(FONT_NAME, SUPER_SIZE)
                            canv.drawString(x, baseline + SUPER_RISE, str(number))
                            width = run.width
                            canv.linkRect(
                                "", _fn_dest(number),
                                Rect=(x, baseline, x + width, baseline + SUPER_RISE + SUPER_SIZE),
                                Border="[0 0 0]",
                            )
                            if number in item.line.new_refs:
                                canv.bookmarkHorizontal(_ref_dest(number), x, baseline + SUPER_RISE)
                            x += width
                slot += 1

            elif isinstance(item, FormBlock):
                spec = measurements[item.measurement_index]
                metadata = _metadata_text(spec)
                metadata_width = text_width(metadata, BODY_SIZE)
                if metadata_width > BODY_WIDTH:
                    raise ValueError("measurement description is too wide for one body line")
                canv.setFont(FONT_NAME, BODY_SIZE)
                canv.drawString(MARGIN, baseline, metadata)

                second_baseline = _baseline_for_slot(slot + 1)
                canv.setFont(FONT_NAME, BODY_SIZE)
                label = "Reading:"
                canv.drawString(MARGIN, second_baseline, label)

                if editable:
                    field_x = MARGIN + text_width(label + " ", BODY_SIZE)
                    field_width = min(170.0, MARGIN + BODY_WIDTH - field_x)
                    canv.acroForm.textfield(
                        name=spec.field_id,
                        tooltip=spec.name,
                        x=field_x,
                        y=second_baseline - 3.0,
                        width=field_width,
                        height=BODY_LEADING - 2.0,
                        borderStyle="solid",
                        borderColor=black,
                        fillColor=white,
                        textColor=black,
                        forceBorder=True,
                        fontName="Helvetica",
                        fontSize=10,
                        maxlen=100,
                    )
                else:
                    raw = values.get(spec.field_id, "")
                    reading = label if raw == "" else f"{label} {raw}"
                    canv.drawString(MARGIN, second_baseline, reading)
                    result = f"Result: {judgments.get(spec.field_id, 'not measured')}"
                    result_width = text_width(result, BODY_SIZE)
                    canv.drawString(MARGIN + BODY_WIDTH - result_width, second_baseline, result)

                slot += int(FORM_HEIGHT / BODY_LEADING)

        if page.footnotes:
            block = FOOT_SEP + sum(
                len(wrap_footnote(fn_texts[n], n, BODY_WIDTH)) * FOOT_LEADING
                for n in page.footnotes
            )
            rule_y = BOTTOM_Y + block - FOOT_SEP / 2
            canv.setLineWidth(0.5)
            canv.line(MARGIN, rule_y, MARGIN + BODY_WIDTH * 0.35, rule_y)
            y = BOTTOM_Y + block - FOOT_SEP
            for number in page.footnotes:
                lines = wrap_footnote(fn_texts[number], number, BODY_WIDTH)
                prefix = f"{number}. "
                indent = text_width(prefix, FOOT_SIZE)
                for line_index, text in enumerate(lines):
                    baseline = y - FOOT_LEADING + (FOOT_LEADING - FOOT_SIZE) / 2
                    canv.setFont(FONT_NAME, FOOT_SIZE)
                    if line_index == 0:
                        canv.drawString(MARGIN, baseline, prefix)
                        prefix_width = text_width(prefix, FOOT_SIZE)
                        canv.linkRect(
                            "", _ref_dest(number),
                            Rect=(MARGIN, baseline - 1, MARGIN + prefix_width, baseline + FOOT_SIZE),
                            Border="[0 0 0]",
                        )
                        canv.bookmarkHorizontal(_fn_dest(number), MARGIN, baseline)
                    canv.drawString(MARGIN + indent, baseline, text)
                    y -= FOOT_LEADING

        canv.setFont(FONT_NAME, FOOT_SIZE)
        canv.drawCentredString(PAGE_W / 2, BOTTOM_Y / 2, f"Page {page.number} of {total}")
        canv.showPage()

    canv.save()
    return buffer.getvalue()
