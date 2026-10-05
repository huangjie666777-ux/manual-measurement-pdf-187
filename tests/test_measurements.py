import io
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from manual_record_187.main import app
from manual_record_187.measure import build_chunks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MR187_DATA_DIR", str(tmp_path))
    return TestClient(app)


def manual_body():
    return {
        "paragraphs": [
            {"parts": [{"text": "Check the oil level "}, {"footnote": "oil"},
                        {"text": " before starting."}]},
            {"parts": [{"text": "Measure the belt tension."}]},
        ],
        "footnotes": {"oil": "Use SAE 10W-40 oil only."},
    }


def template_body():
    body = manual_body()
    body["measurements"] = [
        {"field_id": "oil_level", "paragraph": 0, "name": "Oil level",
         "unit": "mm", "lower": "10.5", "upper": 12, "required": True},
        {"field_id": "belt_tension", "paragraph": 1, "name": "Belt tension",
         "unit": "N", "lower": -5, "upper": 5.25, "required": False},
    ]
    return body


def make_template(client, body=None):
    r = client.post("/templates", json=body or template_body())
    assert r.status_code == 200, r.text
    return r.headers["x-template-id"], r.content


def fill_pdf(pdf_bytes, values):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def submit(client, template_id, pdf_bytes):
    return client.post(f"/templates/{template_id}/submit",
                       files={"file": ("filled.pdf", pdf_bytes, "application/pdf")})


def test_create_template_returns_id_and_fillable_pdf(client):
    template_id, pdf = make_template(client)
    assert re.fullmatch(r"[0-9a-f]{32}", template_id)
    fields = PdfReader(io.BytesIO(pdf)).get_fields()
    assert set(fields) == {"oil_level", "belt_tension"}
    assert all(f.field_type == "/Tx" for f in fields.values())


def test_template_validation(client):
    body = template_body()
    body["measurements"][1]["field_id"] = "oil_level"
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"][1]["paragraph"] = 0
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"][0]["paragraph"] = 7
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"][0]["lower"] = 20
    body["measurements"][0]["upper"] = 10
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"] = []
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"] = [
        {"field_id": f"m{i}", "paragraph": 0, "name": "M", "unit": "mm",
         "lower": 0, "upper": 1} for i in range(13)]
    assert client.post("/templates", json=body).status_code == 422

    body = template_body()
    body["measurements"][0]["field_id"] = "not ok!"
    assert client.post("/templates", json=body).status_code == 422


def test_submit_roundtrip_and_record_pdf(client):
    template_id, pdf = make_template(client)
    filled = fill_pdf(pdf, {"oil_level": "11.25", "belt_tension": "7.5"})
    r = submit(client, template_id, filled)
    assert r.status_code == 200, r.text
    data = r.json()
    readings = {x["field_id"]: x for x in data["readings"]}
    assert readings["oil_level"]["raw"] == "11.25"
    assert readings["oil_level"]["value"] == 11.25
    assert readings["oil_level"]["verdict"] == "pass"
    # out of range is accepted but marked as failed
    assert readings["belt_tension"]["verdict"] == "fail"

    record = client.get(data["record_url"])
    assert record.status_code == 200
    assert record.headers["content-type"] == "application/pdf"
    assert b"/Widget" not in record.content  # flattened, not fillable
    reader = PdfReader(io.BytesIO(record.content))
    assert reader.get_fields() is None
    text = "".join(p.extract_text() for p in reader.pages)
    assert "11.25" in text and "PASS" in text and "FAIL" in text
    assert "Use SAE 10W-40 oil only." in text  # footnotes redrawn


def test_submit_optional_blank_and_required_blank(client):
    template_id, pdf = make_template(client)
    filled = fill_pdf(pdf, {"oil_level": "11", "belt_tension": ""})
    r = submit(client, template_id, filled)
    assert r.status_code == 200
    readings = {x["field_id"]: x for x in r.json()["readings"]}
    assert readings["belt_tension"]["verdict"] == "unmeasured"
    assert readings["belt_tension"]["value"] is None

    filled = fill_pdf(pdf, {"oil_level": "", "belt_tension": "1"})
    assert submit(client, template_id, filled).status_code == 422


@pytest.mark.parametrize("bad", ["1e3", "1E-2", "nan", "inf", "0x10", "1,5", "abc", "1.2.3"])
def test_submit_rejects_non_plain_decimal(client, bad):
    template_id, pdf = make_template(client)
    filled = fill_pdf(pdf, {"oil_level": bad, "belt_tension": "1"})
    assert submit(client, template_id, filled).status_code == 422


@pytest.mark.parametrize("good", ["+1.5", "-0.25", ".5", "12", "10.500"])
def test_submit_accepts_plain_decimal(client, good):
    template_id, pdf = make_template(client)
    filled = fill_pdf(pdf, {"oil_level": good, "belt_tension": "0"})
    assert submit(client, template_id, filled).status_code == 200


def test_submit_rejects_bad_files(client):
    template_id, pdf = make_template(client)
    assert submit(client, template_id, b"not a pdf").status_code == 422
    assert client.post("/templates/" + "0" * 32 + "/submit",
                       files={"file": ("f.pdf", pdf, "application/pdf")}
                       ).status_code == 404

    # encrypted
    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    assert submit(client, template_id, buf.getvalue()).status_code == 422


def test_submit_rejects_missing_and_extra_fields(client):
    template_id, _ = make_template(client)
    _, other_pdf = make_template(client, {**template_body(), "measurements": [
        {"field_id": "other", "paragraph": 0, "name": "X", "unit": "mm",
         "lower": 0, "upper": 1}]})
    r = submit(client, template_id, fill_pdf(other_pdf, {"other": "1"}))
    assert r.status_code == 422


def _custom_form_pdf(build):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    canv = canvas.Canvas(buf)
    build(canv)
    canv.showPage()
    canv.save()
    return buf.getvalue()


def test_submit_rejects_duplicate_and_nontext_fields(client):
    template_id, _ = make_template(client)

    def dup(canv):
        canv.acroForm.textfield(name="oil_level", x=50, y=700, width=80, height=12)
        canv.acroForm.textfield(name="oil_level", x=50, y=650, width=80, height=12)
        canv.acroForm.textfield(name="belt_tension", x=50, y=600, width=80, height=12)
    assert submit(client, template_id, _custom_form_pdf(dup)).status_code == 422

    def nontext(canv):
        canv.acroForm.checkbox(name="oil_level", x=50, y=700, size=12)
        canv.acroForm.textfield(name="belt_tension", x=50, y=600, width=80, height=12)
    assert submit(client, template_id, _custom_form_pdf(nontext)).status_code == 422


def test_adjacent_parts_not_spaced():
    parts = [SimpleNamespace(text="abc", footnote=None),
             SimpleNamespace(text=None, footnote=1),
             SimpleNamespace(text="def ghi", footnote=None)]
    chunks = build_chunks(parts)
    rendered = []
    for chunk in chunks:
        rendered.append("".join(str(run.value) for run in chunk))
    assert rendered == ["abc1def", "ghi"]


def test_measurement_placeholder_pagination(client):
    # A paragraph near the page bottom keeps its last lines with the input box.
    filler = "The quick brown fox jumps over the lazy dog near the river. "
    paragraphs = [{"parts": [{"text": filler * 3}]} for _ in range(12)]
    paragraphs.append({"parts": [{"text": "Final measured paragraph. " + filler}]})
    body = {"paragraphs": paragraphs, "footnotes": {},
            "measurements": [{"field_id": "m1", "paragraph": 12,
                              "name": "Tension", "unit": "N",
                              "lower": 0, "upper": 10}]}
    template_id, pdf = make_template(client, body)
    reader = PdfReader(io.BytesIO(pdf))
    # find the page carrying the widget
    box_page = None
    for i, page in enumerate(reader.pages):
        if page.get("/Annots"):
            box_page = i
    assert box_page is not None
    text = reader.pages[box_page].extract_text()
    assert "Final measured paragraph." in " ".join(text.split())
