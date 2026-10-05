"""FastAPI entry point: POST /render accepts the manual JSON, returns a PDF."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi import File, UploadFile
from fastapi.responses import Response

from . import store
from .forms import evaluate_measurements, extract_field_values
from .measure import register_font
from .paginate import LayoutError, paginate
from .render import render_pdf
from .schemas import ManualRequest, TemplateRequest

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "DejaVuSerif.ttf"

register_font(str(FONT_PATH))

app = FastAPI(title="Manual Record 187")


@app.post("/render")
def render(request: ManualRequest) -> Response:
    try:
        pages, fn_texts = paginate(request)
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    pdf = render_pdf(pages, fn_texts)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="manual.pdf"'},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _measurement_map(request: TemplateRequest) -> dict:
    return {item.paragraph: item for item in request.measurements}


@app.post("/templates")
def create_template(request: TemplateRequest) -> Response:
    try:
        pages, fn_texts = paginate(request, measurements=_measurement_map(request))
    except LayoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    template_id = uuid.uuid4().hex
    store.save_template(template_id, request.model_dump_json())
    pdf = render_pdf(pages, fn_texts)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "X-Template-Id": template_id,
            "Content-Disposition": f'attachment; filename="template-{template_id}.pdf"',
        },
    )


@app.post("/templates/{template_id}/submit")
async def submit_template(template_id: str, file: UploadFile = File(...)) -> dict:
    payload = store.load_template(template_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="unknown template id")
    request = TemplateRequest.model_validate_json(payload)
    data = await file.read()
    values = extract_field_values(data)
    results = evaluate_measurements(request.measurements, values)
    # Redraw from the server-side original; uploaded page content is ignored.
    pages, fn_texts = paginate(request, measurements=_measurement_map(request))
    readings = {r["field_id"]: (r["raw"], r["verdict"]) for r in results}
    pdf = render_pdf(pages, fn_texts, readings=readings)
    record_id = uuid.uuid4().hex
    store.save_record(record_id, pdf)
    return {
        "template_id": template_id,
        "record_id": record_id,
        "readings": results,
        "record_url": f"/records/{record_id}",
    }


@app.get("/records/{record_id}")
def get_record(record_id: str) -> Response:
    pdf = store.load_record(record_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="unknown record id")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="record-{record_id}.pdf"'},
    )
