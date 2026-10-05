"""Input models and validation for the manual rendering API."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_TOTAL_CHARS = 20000
MAX_PARAGRAPHS = 100
MAX_MEASUREMENTS = 12
FIELD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


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


class MeasurementItem(BaseModel):
    """One measurement bound to a paragraph of the manual."""

    model_config = ConfigDict(extra="forbid")

    field_id: str
    paragraph: int  # 0-based paragraph index
    name: str
    unit: str
    lower: Decimal
    upper: Decimal
    required: bool = True

    @field_validator("field_id")
    @classmethod
    def field_id_valid(cls, v: str) -> str:
        if not FIELD_ID_RE.match(v):
            raise ValueError(
                "field_id must start with a letter and contain only "
                "ASCII letters, digits and underscores (max 32 chars)"
            )
        return v

    @field_validator("paragraph")
    @classmethod
    def paragraph_valid(cls, v: int) -> int:
        if v < 0:
            raise ValueError("paragraph index must not be negative")
        return v

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("measurement name must not be empty")
        if len(v) > 40:
            raise ValueError("measurement name too long (max 40 chars)")
        return _check_ascii_printable(v, "measurement name")

    @field_validator("unit")
    @classmethod
    def unit_valid(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("measurement unit must not be empty")
        if len(v) > 12:
            raise ValueError("measurement unit too long (max 12 chars)")
        return _check_ascii_printable(v, "measurement unit")

    @field_validator("lower", "upper")
    @classmethod
    def bound_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("bounds must be finite decimal numbers")
        return v

    @model_validator(mode="after")
    def range_not_inverted(self) -> "MeasurementItem":
        if self.lower > self.upper:
            raise ValueError("lower bound must not exceed upper bound")
        return self


class TemplateRequest(ManualRequest):
    """Manual content plus the measurement items of a fill-in template."""

    measurements: list[MeasurementItem]

    @field_validator("measurements")
    @classmethod
    def measurements_valid(cls, v: list[MeasurementItem]) -> list[MeasurementItem]:
        if not v:
            raise ValueError("at least one measurement item is required")
        if len(v) > MAX_MEASUREMENTS:
            raise ValueError(f"too many measurement items (max {MAX_MEASUREMENTS})")
        ids = [item.field_id for item in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate measurement field_id")
        paragraphs = [item.paragraph for item in v]
        if len(set(paragraphs)) != len(paragraphs):
            raise ValueError("at most one measurement item per paragraph")
        return v

    @model_validator(mode="after")
    def paragraphs_exist(self) -> "TemplateRequest":
        for item in self.measurements:
            if item.paragraph >= len(self.paragraphs):
                raise ValueError(
                    f"measurement {item.field_id!r}: paragraph index "
                    f"{item.paragraph} out of range"
                )
        return self
