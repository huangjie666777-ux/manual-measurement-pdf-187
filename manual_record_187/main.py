"""FastAPI entry point: POST /render accepts the manual JSON, returns a PDF."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from .measure import register_font
from .paginate import LayoutError, paginate
from .render import render_pdf
from .schemas import ManualRequest

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
