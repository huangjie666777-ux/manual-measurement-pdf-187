"""Read and evaluate AcroForm values from a filled template PDF.

Values come from the PDF form fields, never from page text. Anything
structurally unexpected (corrupt or encrypted file, missing/extra/
duplicate fields, non-text fields) is rejected with HTTP 422.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from io import BytesIO

from fastapi import HTTPException
from pypdf import PdfReader

# Plain decimal with optional sign; no exponent, no hex, no inf/nan.
DECIMAL_RE = re.compile(r"^[+-]?(\d+(\.\d+)?|\.\d+)$")


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def extract_field_values(data: bytes) -> dict[str, str]:
    """Return {field_name: raw_value} for every AcroForm field in the PDF."""
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        encrypted = reader.is_encrypted
        root = reader.trailer["/Root"]
    except HTTPException:
        raise
    except Exception:
        raise _unprocessable("corrupt or unreadable PDF")
    if encrypted:
        raise _unprocessable("encrypted PDF rejected")

    values: dict[str, str] = {}

    def walk(node) -> None:
        obj = node.get_object()
        name = obj.get("/T")
        if name is not None:
            name = str(name)
            field_type = obj.get("/FT")
            parent = obj.get("/Parent")
            while field_type is None and parent is not None:
                parent = parent.get_object()
                field_type = parent.get("/FT")
                parent = parent.get("/Parent")
            if field_type != "/Tx":
                raise _unprocessable(f"non-text form field rejected: {name!r}")
            if name in values:
                raise _unprocessable(f"duplicate form field: {name!r}")
            raw = obj.get("/V")
            values[name] = "" if raw is None else str(raw)
        for kid in obj.get("/Kids", []) or []:
            walk(kid)

    acroform = root.get("/AcroForm")
    if acroform is not None:
        for field in acroform.get_object().get("/Fields", []) or []:
            walk(field)
    return values


def evaluate_measurements(items, values: dict[str, str]) -> list[dict]:
    """Match submitted values against the template and grade each reading."""
    expected = {item.field_id for item in items}
    received = set(values)
    missing = sorted(expected - received)
    extra = sorted(received - expected)
    if missing:
        raise _unprocessable(f"missing form fields: {', '.join(missing)}")
    if extra:
        raise _unprocessable(f"unexpected form fields: {', '.join(extra)}")

    results = []
    for item in items:
        raw = values[item.field_id].strip()
        if raw == "":
            if item.required:
                raise _unprocessable(f"required field {item.field_id!r} is empty")
            results.append({
                "field_id": item.field_id,
                "raw": "",
                "value": None,
                "verdict": "unmeasured",
            })
            continue
        if not DECIMAL_RE.match(raw):
            raise _unprocessable(
                f"field {item.field_id!r}: not a plain decimal number: {raw!r}"
            )
        try:
            number = Decimal(raw)
        except InvalidOperation:
            raise _unprocessable(
                f"field {item.field_id!r}: not a plain decimal number: {raw!r}"
            )
        if not number.is_finite():
            raise _unprocessable(f"field {item.field_id!r}: non-finite value")
        verdict = "pass" if item.lower <= number <= item.upper else "fail"
        results.append({
            "field_id": item.field_id,
            "raw": raw,
            "value": float(number),
            "verdict": verdict,
        })
    return results

