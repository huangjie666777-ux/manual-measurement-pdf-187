"""Input models and validation for the manual rendering API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_TOTAL_CHARS = 20000
MAX_PARAGRAPHS = 100


def _check_ascii_printable(value: str, what: str) -> str:
    for ch in value:
        if not (0x20 <= ord(ch) <= 0x7E):
            raise ValueError(f"{what} contains non ASCII-printable character: {ch!r}")
    return value


class Part(BaseModel):
    """One ordered fragment of a paragraph: literal text or a footnote reference."""

    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = None
    footnote: Optional[str] = None

    @field_validator("text")
    @classmethod
    def text_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v == "":
            raise ValueError("text fragment must not be empty")
        return _check_ascii_printable(v, "text fragment")

    @field_validator("footnote")
    @classmethod
    def footnote_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v == "":
            raise ValueError("footnote reference id must not be empty")
        return _check_ascii_printable(v, "footnote reference id")

    @model_validator(mode="after")
    def exactly_one_kind(self) -> "Part":
        if (self.text is None) == (self.footnote is None):
            raise ValueError("each part must carry exactly one of 'text' or 'footnote'")
        return self


class Paragraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[Part]

    @field_validator("parts")
    @classmethod
    def parts_not_empty(cls, v: list[Part]) -> list[Part]:
        if not v:
            raise ValueError("paragraph must not be empty")
        return v


class ManualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraphs: list[Paragraph]
    footnotes: dict[str, str] = {}

    @field_validator("paragraphs")
    @classmethod
    def paragraphs_valid(cls, v: list[Paragraph]) -> list[Paragraph]:
        if not v:
            raise ValueError("paragraphs must not be empty")
        if len(v) > MAX_PARAGRAPHS:
            raise ValueError(f"too many paragraphs (max {MAX_PARAGRAPHS})")
        return v

    @field_validator("footnotes")
    @classmethod
    def footnotes_valid(cls, v: dict[str, str]) -> dict[str, str]:
        for fid, text in v.items():
            _check_ascii_printable(fid, "footnote id")
            _check_ascii_printable(text, "footnote text")
            if text.strip() == "":
                raise ValueError(f"footnote {fid!r} must not be empty")
        return v

    @model_validator(mode="after")
    def cross_checks(self) -> "ManualRequest":
        total = 0
        referenced: set[str] = set()
        for para in self.paragraphs:
            visible = False
            for part in para.parts:
                if part.text is not None:
                    total += len(part.text)
                    if part.text.strip():
                        visible = True
                else:
                    referenced.add(part.footnote)
                    visible = True
            if not visible:
                raise ValueError("paragraph must not be empty")
        for fid in referenced:
            if fid not in self.footnotes:
                raise ValueError(f"unknown footnote reference: {fid!r}")
        total += sum(len(t) for t in self.footnotes.values())
        if total > MAX_TOTAL_CHARS:
            raise ValueError(f"total text exceeds {MAX_TOTAL_CHARS} characters")
        return self

    def referenced_ids_in_order(self) -> list[str]:
        """Footnote ids in first-reference order (unreferenced ones excluded)."""
        seen: list[str] = []
        for para in self.paragraphs:
            for part in para.parts:
                if part.footnote is not None and part.footnote not in seen:
                    seen.append(part.footnote)
        return seen
