import re
from io import BytesIO

import reportlab.rl_config as rl_config
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

from manual_record_187.forms import TemplateStore

rl_config.pageCompression = 0

from manual_record_187.main import app

client = TestClient(app)


def make_paragraph(text, refs=()):
    parts = [{"text": text}]
    parts += [{"footnote": r} for r in refs]
    return {"parts": parts}


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type" + rb"\s" + rb"*/Page[^s]", pdf))


def template_body():
    return {
        "paragraphs": [
            make_paragraph("Check the oil gap."),
            make_paragraph("Check system voltage."),
            make_paragraph("Optional spare measurement."),
        ],
        "footnotes": {},
        "measurements": [
            {"field_id": "oil_gap", "paragraph": 1, "name": "Oil gap",
             "unit": "mm", "lower_bound": 1, "upper_bound": 2.5},
            {"field_id": "voltage", "paragraph": 2, "name": "Voltage",
             "unit": "V", "lower_bound": 10, "upper_bound": 14},
            {"field_id": "spare", "paragraph": 3, "name": "Spare",
             "unit": "mm", "lower_bound": 0, "upper_bound": 1, "required": False},
        ],
    }


def fill_pdf(pdf: bytes, values: dict[str, str]) -> bytes:
    writer = PdfWriter(clone_from=BytesIO(pdf))
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_simple_document_returns_pdf():
    body = {
        "paragraphs": [
            {"parts": [{"text": "Check the oil level "}, {"footnote": "oil"},
                        {"text": " before starting the engine."}]},
            make_paragraph("Tighten the bolts evenly."),
        ],
        "footnotes": {"oil": "Use SAE 10W-40 oil only."},
    }
    r = client.post("/render", json=body)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert page_count(r.content) == 1
    assert b"DejaVuSerif" in r.content  # embedded font


def test_multi_page_with_repeated_reference():
    filler = "The quick brown fox jumps over the lazy dog near the river bank. " * 3
    paragraphs = [{"parts": [{"text": filler}, {"footnote": "a"}, {"text": filler}]}
                  for _ in range(30)]
    paragraphs.append({"parts": [{"text": "See again "}, {"footnote": "a"}, {"text": "."}]})
    r = client.post("/render", json={"paragraphs": paragraphs,
                                     "footnotes": {"a": "First note."}})
    assert r.status_code == 200
    assert page_count(r.content) >= 2
    # footnote text appears exactly once
    assert r.content.count(b"First note.") == 1


def test_unknown_reference_rejected():
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "x "}, {"footnote": "nope"}]}],
        "footnotes": {}})
    assert r.status_code == 422


def test_empty_paragraph_rejected():
    r = client.post("/render", json={
        "paragraphs": [{"parts": []}], "footnotes": {}})
    assert r.status_code == 422
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "   "}]}], "footnotes": {}})
    assert r.status_code == 422


def test_empty_footnote_rejected():
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "x "}, {"footnote": "a"}]}],
        "footnotes": {"a": "  "}})
    assert r.status_code == 422


def test_unreferenced_footnote_not_rendered():
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "hello"}]}],
        "footnotes": {"unused": "should not appear"}})
    assert r.status_code == 200
    assert b"should not appear" not in r.content


def test_non_ascii_rejected():
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "caf\u00e9"}]}], "footnotes": {}})
    assert r.status_code == 422


def test_limits():
    too_many = [make_paragraph("x") for _ in range(101)]
    r = client.post("/render", json={"paragraphs": too_many, "footnotes": {}})
    assert r.status_code == 422
    big = make_paragraph("a" * 20001)
    r = client.post("/render", json={"paragraphs": [big], "footnotes": {}})
    assert r.status_code == 422


def test_long_word_split_and_fits():
    word = "supercalifragilisticexpialidocious" * 3
    r = client.post("/render", json={
        "paragraphs": [make_paragraph(word)], "footnotes": {}})
    assert r.status_code == 200


def test_huge_footnote_rejected_gracefully():
    note = "word " * 5000
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "ref "}, {"footnote": "big"}]}],
        "footnotes": {"big": note}})
    assert r.status_code == 422


def test_template_issues_named_helvetica_text_fields():
    r = client.post("/templates", json=template_body())
    assert r.status_code == 200
    template_id = r.headers["X-Template-ID"]
    reader = PdfReader(BytesIO(r.content))
    fields = reader.get_fields()
    assert list(fields) == ["oil_gap", "voltage", "spare"]
    assert all(field["/FT"] == "/Tx" for field in fields.values())
    assert b"/Helv" in r.content
    assert client.get(f"/templates/{template_id}").status_code == 200


def test_filled_template_returns_values_and_flat_record_pdf():
    issued = client.post("/templates", json=template_body())
    template_id = issued.headers["X-Template-ID"]
    filled = fill_pdf(issued.content, {
        "oil_gap": "2.6", "voltage": "12", "spare": ""
    })
    r = client.post(
        f"/templates/{template_id}/records",
        files={"file": ("filled.pdf", filled, "application/pdf")},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["measurements"] == [
        {"field_id": "oil_gap", "raw": "2.6", "value": 2.6, "judgment": "fail"},
        {"field_id": "voltage", "raw": "12", "value": 12.0, "judgment": "pass"},
        {"field_id": "spare", "raw": "", "value": None, "judgment": "not measured"},
    ]
    record = client.get(payload["record_url"])
    assert record.status_code == 200
    reader = PdfReader(BytesIO(record.content))
    assert reader.get_fields() is None
    assert all(page.get("/Annots") is None for page in reader.pages)


def test_required_blank_and_exponent_are_rejected():
    issued = client.post("/templates", json=template_body())
    template_id = issued.headers["X-Template-ID"]
    blank = fill_pdf(issued.content, {"oil_gap": "", "voltage": "12", "spare": ""})
    r = client.post(f"/templates/{template_id}/records",
                    files={"file": ("blank.pdf", blank, "application/pdf")})
    assert r.status_code == 422

    exponent_pdf = fill_pdf(issued.content,
                            {"oil_gap": "1e0", "voltage": "12", "spare": ""})
    r = client.post(f"/templates/{template_id}/records",
                    files={"file": ("exponent.pdf", exponent_pdf, "application/pdf")})
    assert r.status_code == 422


def test_template_validation_rules():
    def post(**changes):
        body = template_body()
        body["measurements"][0].update(changes)
        return client.post("/templates", json=body)

    assert post(paragraph=0).status_code == 422
    assert post(paragraph=99).status_code == 422
    assert post(lower_bound=3).status_code == 422
    duplicate = template_body()
    duplicate["measurements"][1]["paragraph"] = 1
    assert client.post("/templates", json=duplicate).status_code == 422
    duplicate_id = template_body()
    duplicate_id["measurements"][1]["field_id"] = "oil_gap"
    assert client.post("/templates", json=duplicate_id).status_code == 422
    import json
    nan_body = template_body()
    nan_body["measurements"][0]["lower_bound"] = None
    payload = json.dumps(nan_body).replace(":null", ":NaN")
    nan_response = client.post("/templates", content=payload,
                               headers={"Content-Type": "application/json"})
    assert nan_response.status_code == 422


def test_adjacent_text_fragments_have_no_inserted_space():
    r = client.post("/render", json={
        "paragraphs": [{"parts": [{"text": "foo"}, {"text": "bar"}]}],
        "footnotes": {},
    })
    assert r.status_code == 200
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(r.content)).pages)
    assert "foobar" in text
    assert "foo bar" not in text


def test_templates_persist_across_store_restart(tmp_path):
    from manual_record_187.schemas import TemplateRequest

    first_store = TemplateStore(tmp_path)
    stored = first_store.create(TemplateRequest.model_validate(template_body()))
    second_store = TemplateStore(tmp_path)
    assert second_store.get(stored.template_id).pdf == stored.pdf


def test_damaged_missing_extra_and_encrypted_pdf_rejected(tmp_path):
    issued = client.post("/templates", json=template_body())
    template_id = issued.headers["X-Template-ID"]
    assert client.post(f"/templates/{template_id}/records",
                       files={"file": ("bad.pdf", b"%PDF-broken", "application/pdf")}).status_code in (400, 422)

    reader = PdfReader(BytesIO(issued.content))
    missing = PdfWriter(clone_from=BytesIO(issued.content))
    for page in missing.pages:
        missing.update_page_form_field_values(page, {"voltage": "12", "spare": ""}, auto_regenerate=False)
    root = missing._root_object["/AcroForm"]
    root[NameObject("/Fields")] = ArrayObject([
        field for field in root["/Fields"] if field.get_object()["/T"] != "oil_gap"
    ])
    output = BytesIO()
    missing.write(output)
    assert client.post(f"/templates/{template_id}/records",
                       files={"file": ("missing.pdf", output.getvalue(), "application/pdf")}).status_code == 422

    encrypted_writer = PdfWriter(clone_from=BytesIO(fill_pdf(
        issued.content, {"oil_gap": "1", "voltage": "12", "spare": ""}
    )))
    encrypted_writer.encrypt("secret")
    encrypted = BytesIO()
    encrypted_writer.write(encrypted)
    assert client.post(f"/templates/{template_id}/records",
                       files={"file": ("encrypted.pdf", encrypted.getvalue(), "application/pdf")}).status_code == 422
