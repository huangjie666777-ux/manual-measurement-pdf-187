import re

import reportlab.rl_config as rl_config
import pytest
from fastapi.testclient import TestClient

rl_config.pageCompression = 0

from manual_record_187.main import app

client = TestClient(app)


def make_paragraph(text, refs=()):
    parts = [{"text": text}]
    parts += [{"footnote": r} for r in refs]
    return {"parts": parts}


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type" + rb"\s" + rb"*/Page[^s]", pdf))


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
