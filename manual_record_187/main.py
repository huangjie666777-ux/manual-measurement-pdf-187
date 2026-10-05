"""FastAPI endpoints for static rendering, form issuance and form return."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response

from .forms import FormError, TemplateStore, finalize_pdf, read_form_values, validate_measurements
from .measure import register_font
from .paginate import LayoutError, paginate
from .render import render_pdf
from .schemas import ManualRequest, TemplateRequest

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "DejaVuSerif.ttf"

register_font(str(FONT_PATH))

app = FastAPI(title="Manual Record 187")
store = TemplateStore()


def _pdf_response(pdf: bytes, filename: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/render")
def render(request: ManualRequest) -> Response:
    try:
        pages, fn_texts = paginate(request)
        pdf = render_pdf(pages, fn_texts)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _pdf_response(pdf, "manual.pdf")


@app.post("/templates")
def create_template(request: TemplateRequest) -> Response:
    try:
        stored = store.create(request)
    except FormError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    response = _pdf_response(stored.pdf, f"template-{stored.template_id}.pdf")
    response.headers["X-Template-ID"] = stored.template_id
    response.headers["Location"] = f"/templates/{stored.template_id}"
    return response


@app.get("/templates/{template_id}")
def download_template(template_id: str) -> Response:
    try:
        stored = store.get(template_id)
    except FormError:
        raise HTTPException(status_code=404, detail="template not found")
    return _pdf_response(stored.pdf, f"template-{template_id}.pdf")


@app.post("/templates/{template_id}/records")
async def submit_record(template_id: str, file: UploadFile) -> Response:
    try:
        stored = store.get(template_id)
    except FormError:
        raise HTTPException(status_code=404, detail="template not found")

    if file.content_type and file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="a PDF upload is required")
    uploaded = await file.read()
    if not uploaded.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="uploaded file is not a PDF")

    expected_ids = [item.field_id for item in stored.request.measurements]
    try:
        values = read_form_values(uploaded, expected_ids)
        measurements, judgments = validate_measurements(stored.request.measurements, values)
        record_pdf = finalize_pdf(stored, values, judgments)
    except FormError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    record_id = uuid.uuid4().hex
    try:
        store.save_record(template_id, record_id, record_pdf)
    except OSError:
        raise HTTPException(status_code=500, detail="could not persist record")

    return {
        "template_id": template_id,
        "record_id": record_id,
        "record_url": f"/records/{record_id}",
        "measurements": measurements,
    }


@app.get("/records/{record_id}")
def download_record(record_id: str) -> Response:
    matches = list(store.directory.glob(f"*/record-{record_id}.pdf"))
    if not matches:
        raise HTTPException(status_code=404, detail="record not found")
    return _pdf_response(matches[0].read_bytes(), f"record-{record_id}.pdf")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
