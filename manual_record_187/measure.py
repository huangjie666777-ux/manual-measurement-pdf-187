"""Font registration, text measurement and line wrapping.

All widths come from the real DejaVuSerif metrics via ReportLab so that
wrapping matches what is later drawn on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_NAME = "DejaVuSerif"

BODY_SIZE = 11.0
BODY_LEADING = 15.0
FOOT_SIZE = 9.0
FOOT_LEADING = 12.0
SUPER_SIZE = 7.7  # 0.7 * BODY_SIZE
SUPER_RISE = 4.0

_registered = False


def register_font(path: str) -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont(FONT_NAME, path))
        _registered = True


def text_width(text: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, FONT_NAME, size)


@dataclass
class Run:
    kind: str  # "text" or "ref"
    value: object  # str for text, int footnote number for ref

    @property
    def width(self) -> float:
        if self.kind == "text":
            return text_width(self.value, BODY_SIZE)
        return text_width(str(self.value), SUPER_SIZE)


@dataclass
class Line:
    # Items are run-lists (visible text/refs) or explicit whitespace tokens.
    items: list[object] = field(default_factory=list)
    width: float = 0.0
    new_refs: list[int] = field(default_factory=list)  # footnote numbers first seen here


def build_chunks(parts) -> list[list[Run]]:
    """Turn paragraph parts into unbreakable chunks.

    A chunk is a word plus any footnote references glued directly to it, so a
    superscript reference is never separated from its word by a line break.
    """
    chunks: list[list[Run]] = []

    def append_text(piece: str) -> None:
        nonlocal chunks
        if not chunks or isinstance(chunks[-1], LineSpace) or chunks[-1][-1].kind == "ref":
            chunks.append([Run("text", piece)])
        else:
            chunks[-1][0] = Run("text", chunks[-1][0].value + piece)

    for part in parts:
        if part.text is not None:
            tokens = re.findall(r"\S+|\s+", part.text)
            for token in tokens:
                if token.isspace():
                    chunks.append(LineSpace(token))
                else:
                    append_text(token)
        else:
            ref_run = Run("ref", part.footnote)  # id resolved to number later
            if chunks and isinstance(chunks[-1], LineSpace):
                chunks.pop()
            if chunks:
                chunks[-1].append(ref_run)
            else:
                chunks.append([ref_run])
    return chunks


@dataclass
class LineSpace:
    value: str

    @property
    def width(self) -> float:
        return text_width(self.value, BODY_SIZE)


def _chunk_width(chunk: list[Run]) -> float:
    return sum(run.width for run in chunk)


def _is_space_item(item) -> bool:
    return isinstance(item, LineSpace)


def _item_width(item) -> float:
    return sum(run.width for run in item) if isinstance(item, list) else item.width


def _split_text_run(run: Run, max_width: float) -> list[Run]:
    pieces: list[Run] = []
    current = ""
    for ch in run.value:
        if current and text_width(current + ch, BODY_SIZE) > max_width:
            pieces.append(Run("text", current))
            current = ch
        else:
            current += ch
    pieces.append(Run("text", current))
    return pieces


def wrap_chunks(chunks: list[list[Run]], max_width: float) -> list[Line]:
    """Greedy whole-word wrapping; over-wide words are split by character."""
    lines: list[Line] = []
    current = Line()
    for item in chunks:
        if _is_space_item(item):
            pieces = [item]
        else:
            width = _chunk_width(item)
            if width > max_width and item[0].kind == "text":
                first_runs = _split_text_run(item[0], max_width)
                refs = item[1:]
                pieces = [[first_runs[0]]]
                pieces.extend([[run] for run in first_runs[1:-1]])
                pieces.append([first_runs[-1]] + refs)
            else:
                pieces = [item]
        for piece in pieces:
            piece_width = _item_width(piece)
            is_space = _is_space_item(piece)
            if is_space and not current.items:
                continue
            extra = piece_width
            if current.items and not _is_space_item(current.items[-1]):
                # Existing adjacent text runs are intentionally glued with no
                # synthetic space; whitespace tokens supply real separators.
                pass
            if current.items and current.width + extra > max_width:
                lines.append(current)
                current = Line()
                if is_space:
                    continue
            current.items.append(piece)
            current.width += piece_width
    if current.items or not lines:
        lines.append(current)
    return lines


def wrap_footnote(text: str, number: int, max_width: float) -> list[str]:
    """Wrap a footnote body; returns the text lines (number prefix excluded)."""
    indent = text_width(f"{number}. ", FOOT_SIZE)
    avail = max_width - indent
    words = text.split()
    lines: list[str] = []
    current = ""
    space = text_width(" ", FOOT_SIZE)
    for word in words:
        while text_width(word, FOOT_SIZE) > avail:
            # split over-wide word by character
            cut = len(word)
            while cut > 1 and text_width(word[:cut], FOOT_SIZE) > avail:
                cut -= 1
            head, word = word[:cut], word[cut:]
            if current:
                lines.append(current)
                current = ""
            lines.append(head)
        candidate = word if not current else current + " " + word
        if current and text_width(current, FOOT_SIZE) + space + text_width(word, FOOT_SIZE) > avail:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def footnote_height(text: str, number: int, max_width: float) -> float:
    return len(wrap_footnote(text, number, max_width)) * FOOT_LEADING
