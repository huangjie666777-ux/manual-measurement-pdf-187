"""Font registration, text measurement and line wrapping.

All widths come from the real DejaVuSerif metrics via ReportLab so that
wrapping matches what is later drawn on the page.
"""

from __future__ import annotations

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
    # chunks: list of run-lists; chunks are separated by one space when drawn.
    chunks: list[list[Run]] = field(default_factory=list)
    width: float = 0.0
    new_refs: list[int] = field(default_factory=list)  # footnote numbers first seen here


def _space_width() -> float:
    return text_width(" ", BODY_SIZE)


def build_chunks(parts) -> list[list[Run]]:
    """Turn paragraph parts into unbreakable chunks.

    A chunk is a word plus any footnote references glued directly to it, so a
    superscript reference is never separated from its word by a line break.
    """
    chunks: list[list[Run]] = []
    for part in parts:
        if part.text is not None:
            for word in part.text.split():
                chunks.append([Run("text", word)])
        else:
            ref_run = Run("ref", part.footnote)  # id resolved to number later
            if chunks:
                chunks[-1].append(ref_run)
            else:
                chunks.append([ref_run])
    return chunks


def _chunk_width(chunk: list[Run]) -> float:
    return sum(run.width for run in chunk)


def _split_word_chunk(chunk: list[Run], max_width: float) -> list[list[Run]]:
    """Split an over-wide word chunk by characters; refs stay on the last piece."""
    word_run = chunk[0]
    refs = chunk[1:]
    pieces: list[list[Run]] = []
    current = ""
    for ch in word_run.value:
        if current and text_width(current + ch, BODY_SIZE) > max_width:
            pieces.append([Run("text", current)])
            current = ch
        else:
            current += ch
    pieces.append([Run("text", current)] + refs)
    return pieces


def wrap_chunks(chunks: list[list[Run]], max_width: float) -> list[Line]:
    """Greedy whole-word wrapping; over-wide words are split by character."""
    space = _space_width()
    lines: list[Line] = []
    current = Line()
    for chunk in chunks:
        width = _chunk_width(chunk)
        if width > max_width and chunk[0].kind == "text":
            pieces = _split_word_chunk(chunk, max_width)
        else:
            pieces = [chunk]
        for piece in pieces:
            piece_width = _chunk_width(piece)
            extra = piece_width if not current.chunks else space + piece_width
            if current.chunks and current.width + extra > max_width:
                lines.append(current)
                current = Line()
                extra = piece_width
            current.chunks.append(piece)
            current.width += extra
    if current.chunks or not lines:
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
