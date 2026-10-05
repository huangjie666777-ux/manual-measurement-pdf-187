"""Pagination: assign lines and same-page footnotes to A4 pages.

Rules implemented here:
- footnotes are numbered by first reference in reading order;
- a footnote is typeset once, on the page of its first reference, and never
  split across pages;
- footnote height is deducted from the page's body capacity; when a line
  does not fit it moves (with its new footnotes) to the next page;
- a paragraph split across pages keeps at least 2 lines on each page,
  unless the paragraph is a single line;
- if even a fresh page cannot hold a line plus the footnotes it introduces,
  the document is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from .measure import (
    BODY_LEADING,
    Line,
    build_chunks,
    footnote_height,
    wrap_chunks,
)

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
BODY_WIDTH = PAGE_W - 2 * MARGIN
BODY_HEIGHT = PAGE_H - 2 * MARGIN
TOP_Y = PAGE_H - MARGIN
BOTTOM_Y = MARGIN
FORM_HEIGHT = BODY_LEADING * 2

# Separator between body and footnote block: gap + rule + gap.
FOOT_SEP = 14.0


class LayoutError(Exception):
    """Raised when the document cannot be paginated within the rules."""


@dataclass
class PageLine:
    para_index: int
    line: Line


@dataclass
class Page:
    number: int
    items: list[object] = field(default_factory=list)
    footnotes: list[int] = field(default_factory=list)  # footnote numbers, ascending

    @property
    def lines(self) -> list[PageLine]:
        return [item for item in self.items if isinstance(item, PageLine)]

    @property
    def forms(self) -> list["FormBlock"]:
        return [item for item in self.items if isinstance(item, FormBlock)]


@dataclass
class FormBlock:
    measurement_index: int


def assign_numbers(request) -> dict[str, int]:
    """Map footnote id -> 1-based number in first-reference order."""
    return {fid: i + 1 for i, fid in enumerate(request.referenced_ids_in_order())}


def _numbered_parts(request, numbers):
    """Paragraph parts with footnote ids replaced by their numbers."""
    result = []
    for para in request.paragraphs:
        parts = []
        for part in para.parts:
            if part.text is not None:
                parts.append(part)
            else:
                parts.append(SimpleNamespace(text=None, footnote=numbers[part.footnote]))
        result.append(parts)
    return result


def _page_footnotes(lines: list[PageLine]) -> list[int]:
    seen: list[int] = []
    for pl in lines:
        for n in pl.line.new_refs:
            if n not in seen:
                seen.append(n)
    return sorted(seen)


def _item_height(item: object) -> float:
    return FORM_HEIGHT if isinstance(item, FormBlock) else BODY_LEADING


def _items_lines(items: list[object]) -> list[PageLine]:
    return [item for item in items if isinstance(item, PageLine)]


def _block_height(footnotes: list[int], fn_texts: dict[int, str]) -> float:
    if not footnotes:
        return 0.0
    total = FOOT_SEP
    for n in footnotes:
        total += footnote_height(fn_texts[n], n, BODY_WIDTH)
    return total


def _fits(items: list[object], fn_texts: dict[int, str]) -> bool:
    lines = _items_lines(items)
    height = sum(_item_height(item) for item in items)
    height += _block_height(_page_footnotes(lines), fn_texts)
    return height <= BODY_HEIGHT + 1e-6


def _fits_with_reservation(items: list[object], fn_texts: dict[int, str], reservation: float) -> bool:
    if reservation == 0:
        return _fits(items, fn_texts)
    lines = _items_lines(items)
    height = sum(_item_height(item) for item in items) + reservation
    height += _block_height(_page_footnotes(lines), fn_texts)
    return height <= BODY_HEIGHT + 1e-6


def paginate(request, measurements=None) -> list[Page]:
    numbers = assign_numbers(request)
    fn_texts = {numbers[fid]: text for fid, text in request.footnotes.items() if fid in numbers}
    measurements = list(measurements or [])
    forms_by_paragraph = {
        item.paragraph - 1: FormBlock(measurement_index=index)
        for index, item in enumerate(measurements)
    }

    # Wrap every paragraph into lines and record first-reference numbers.
    seen_refs: set[int] = set()
    paragraphs: list[list[Line]] = []
    for parts in _numbered_parts(request, numbers):
        chunks = build_chunks(parts)
        lines = wrap_chunks(chunks, BODY_WIDTH)
        for line in lines:
            for chunk in line.items:
                if not isinstance(chunk, list):
                    continue
                for run in chunk:
                    if run.kind == "ref" and run.value not in seen_refs:
                        seen_refs.add(run.value)
                        line.new_refs.append(run.value)
        paragraphs.append(lines)

    pages: list[Page] = []
    current: list[object] = []

    def flush() -> None:
        if current:
            current_lines = _items_lines(current)
            pages.append(Page(number=len(pages) + 1, items=list(current),
                              footnotes=_page_footnotes(current_lines)))
            current.clear()

    for para_index, lines in enumerate(paragraphs):
        total = len(lines)
        for li, line in enumerate(lines):
            page_line = PageLine(para_index, line)
            trailing = [forms_by_paragraph[para_index]] if (
                para_index in forms_by_paragraph and li == total - 1
            ) else []
            candidate = current + [page_line] + trailing
            reservation = (
                (total - 1 - li) * BODY_LEADING + FORM_HEIGHT
                if para_index in forms_by_paragraph and li >= total - 2
                else 0.0
            )
            if _fits_with_reservation(candidate, fn_texts, reservation):
                current.append(page_line)
                current.extend(trailing)
                continue

            # The line does not fit: break the page before it and pull back
            # lines of the same paragraph to satisfy the 2-line rule.
            move = 0
            if total > 1:
                on_page = 0
                for pl in reversed(_items_lines(current)):
                    if pl.para_index == para_index:
                        on_page += 1
                    else:
                        break
                need_next = 2 if trailing and total >= 2 else 1
                move = max(move, need_next)
                if trailing and move > on_page:
                    raise LayoutError(
                        "cannot keep a measurement with the last two paragraph lines on one page"
                    )
                if not trailing and on_page - move == 1:
                    move += 1  # do not leave a single line behind either
                move = min(move, on_page)
            elif total == 1 and not trailing:
                move = 0

            if move:
                kept_line_count = max(0, len(_items_lines(current)) - move)
                if kept_line_count == 0:
                    split_at = 0
                else:
                    kept_ids = {id(item) for item in _items_lines(current)[:kept_line_count]}
                    split_at = 0
                    for index, item in enumerate(current):
                        if isinstance(item, PageLine) and id(item) not in kept_ids:
                            split_at = index
                            break
                moved = list(current[split_at:])
                del current[split_at:]
            else:
                moved = []
            flush()
            current.extend(moved)
            current.append(page_line)
            current.extend(trailing)
            if not _fits(current, fn_texts):
                raise LayoutError(
                    "cannot place a line together with the footnotes it "
                    "introduces even on a fresh page; document rejected"
                )
    flush()
    return pages, fn_texts
