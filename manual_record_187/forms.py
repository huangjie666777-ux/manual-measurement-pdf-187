"""Fillable PDF parsing, validation and persistent template storage."""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import IndirectObject

from .render import render_pdf
from .paginate import LayoutError, paginate
from .schemas import TemplateRequest

DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


class FormError(ValueError):
    pass


@dataclass
class StoredTemplate:
    template_id: str
    request: TemplateRequest
    pdf: bytes


class TemplateStore:
    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        root = Path(directory or os.environ.get("MANUAL_RECORD_STORAGE_DIR", "instance_data"))
        self.directory = root / "templates"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, StoredTemplate] = {}
        self._load()

    def _load(self) -> None:
        for manifest_path in self.directory.glob("*/manifest.json"):
            template_id = manifest_path.parent.name
            pdf_path = manifest_path.parent / "template.pdf"
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                request = TemplateRequest.model_validate(payload)
                pdf = pdf_path.read_bytes()
            except (OSError, json.JSONDecodeError, ValidationError):
                continue
            self._templates[template_id] = StoredTemplate(template_id, request, pdf)

    def create(self, request: TemplateRequest) -> StoredTemplate:
        try:
            pages, footnote_texts = paginate(request, request.measurements)
            pdf = render_pdf(pages, footnote_texts, request.measurements, editable=True)
        except LayoutError as exc:
            raise FormError(str(exc)) from exc
        except ValueError as exc:
            raise FormError(str(exc)) from exc

        template_id = uuid.uuid4().hex
        target = self.directory / template_id
        target.mkdir(parents=True, exist_ok=False)
        (target / "manifest.json").write_text(
            request.model_dump_json(), encoding="utf-8"
        )
        (target / "template.pdf").write_bytes(pdf)
        stored = StoredTemplate(template_id, request, pdf)
        self._templates[template_id] = stored
        return stored

    def get(self, template_id: str) -> StoredTemplate:
        try:
            return self._templates[template_id]
        except KeyError:
            raise FormError("template not found") from None

    def record_pdf_path(self, template_id: str, record_id: str) -> Path:
        return self.directory / template_id / f"record-{record_id}.pdf"

    def save_record(self, template_id: str, record_id: str, pdf: bytes) -> Path:
        path = self.record_pdf_path(template_id, record_id)
        path.write_bytes(pdf)
        return path


def _resolve_object(value: Any) -> Any:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _field_name(parent: str, field: Any) -> str:
    partial = str(field.get("/T", ""))
    return f"{parent}.{partial}" if parent else partial


def _collect_fields(node: Any, inherited_ft: str | None = None, prefix: str = "") -> list[dict[str, Any]]:
    node = _resolve_object(node)
    field_type = node.get("/FT", inherited_ft)
    name = _field_name(prefix, node)
    children = node.get("/Kids")
    if children:
        result: list[dict[str, Any]] = []
        for child in children:
            result.extend(_collect_fields(child, field_type, name))
        return result
    return [{
        "name": name,
        "type": str(field_type) if field_type is not None else None,
        "value": node.get("/V"),
    }]


def read_form_values(pdf: bytes, expected_ids: list[str]) -> dict[str, str]:
    try:
        reader = PdfReader(BytesIO(pdf), strict=True)
        if reader.is_encrypted:
            raise FormError("encrypted PDFs are not accepted")
        acro_form = reader.trailer["/Root"].get("/AcroForm")
        if acro_form is None:
            raise FormError("uploaded PDF has no AcroForm")
        roots = _resolve_object(acro_form).get("/Fields", [])
        fields: list[dict[str, Any]] = []
        for root in roots:
            fields.extend(_collect_fields(root))
    except FormError:
        raise
    except PdfReadError as exc:
        raise FormError("uploaded PDF is damaged or unreadable") from exc
    except Exception as exc:
        raise FormError("uploaded PDF is damaged or unreadable") from exc

    names = [field["name"] for field in fields]
    if len(names) != len(set(names)):
        raise FormError("duplicate form fields are not accepted")
    actual = set(names)
    expected = set(expected_ids)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise FormError(f"missing form fields: {', '.join(missing)}")
    if extra:
        raise FormError(f"unexpected form fields: {', '.join(extra)}")

    values: dict[str, str] = {}
    for field in fields:
        if field["type"] != "/Tx":
            raise FormError(f"field {field['name']!r} is not a text field")
        value = field["value"]
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise FormError(f"field {field['name']!r} does not contain text")
        values[field["name"]] = value
    return values


def validate_measurements(specs, values: dict[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    judgments: dict[str, str] = {}
    for spec in specs:
        raw = values.get(spec.field_id, "")
        normalized = raw.strip()
        if normalized == "":
            if spec.required:
                raise FormError(f"required measurement {spec.field_id!r} is blank")
            numeric = None
            judgment = "not measured"
        else:
            if not DECIMAL_RE.fullmatch(normalized):
                raise FormError(f"measurement {spec.field_id!r} is not an ordinary decimal")
            numeric = float(normalized)
            if not math.isfinite(numeric):
                raise FormError(f"measurement {spec.field_id!r} is not finite")
            judgment = "pass" if spec.lower_bound <= numeric <= spec.upper_bound else "fail"
        result.append({
            "field_id": spec.field_id,
            "raw": raw,
            "value": numeric,
            "judgment": judgment,
        })
        judgments[spec.field_id] = judgment
    return result, judgments


def finalize_pdf(stored: StoredTemplate, values: dict[str, str], judgments: dict[str, str]) -> bytes:
    pages, footnote_texts = paginate(stored.request, stored.request.measurements)
    return render_pdf(
        pages,
        footnote_texts,
        stored.request.measurements,
        values=values,
        judgments=judgments,
        editable=False,
    )
