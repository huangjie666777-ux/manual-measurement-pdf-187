"""Filesystem persistence for templates and finalized record PDFs.

The base directory is configurable via the MR187_DATA_DIR environment
variable (default: ./data). Templates survive restarts, so filled PDFs
can be collected against a template created by an earlier process.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _base() -> Path:
    return Path(os.environ.get("MR187_DATA_DIR", "data"))


def valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value))


def save_template(template_id: str, payload_json: str) -> None:
    directory = _base() / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{template_id}.json").write_text(payload_json, encoding="utf-8")


def load_template(template_id: str) -> str | None:
    if not valid_id(template_id):
        return None
    path = _base() / "templates" / f"{template_id}.json"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def save_record(record_id: str, pdf: bytes) -> None:
    directory = _base() / "records"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{record_id}.pdf").write_bytes(pdf)


def load_record(record_id: str) -> bytes | None:
    if not valid_id(record_id):
        return None
    path = _base() / "records" / f"{record_id}.pdf"
    if not path.is_file():
        return None
    return path.read_bytes()

