# Manual Measurement PDF 187

Pure-backend service that turns ordered paragraphs with same-page footnotes
into a searchable, linked A4 PDF. Python 3.10.12, FastAPI 0.115.12,
ReportLab 4.4.5, DejaVuSerif (embedded from `fonts/`).

## Run

```bash
.venv/bin/uvicorn manual_record_187.main:app --port 8371
```

## API

`POST /render` — request body:

```json
{
  "paragraphs": [
    {"parts": [
      {"text": "Check the oil level "},
      {"footnote": "oil"},
      {"text": " before starting."}
    ]}
  ],
  "footnotes": {"oil": "Use SAE 10W-40 oil only."}
}
```

- `paragraphs`: ordered list; each paragraph is an ordered list of `parts`.
  A part is exactly one of `{"text": "..."}` or `{"footnote": "<id>"}`.
  Text is literal (no HTML), ASCII printable characters only.
- `footnotes`: id -> text map. Unknown references, empty paragraphs and
  empty footnotes are rejected with HTTP 422. Unreferenced footnotes are
  accepted but not rendered.
- Limits: at most 100 paragraphs and 20000 characters of total text.
- Response: `application/pdf`. If a reference and its footnote cannot fit
  together even on a fresh page, the request is rejected with 422 instead
  of clipping or looping.

## Layout rules

- A4, single column, 20 mm margins on all sides.
- Body 11 pt / 15 pt leading; footnotes 9 pt / 12 pt leading.
- Wrapping uses real DejaVuSerif widths; whole words are kept when possible,
  over-wide words are split by character. Reference numbers are superscripts
  measured at their real width.
- Footnotes are numbered from 1 in first-reference order; repeated
  references reuse the original number. Each footnote is typeset once, in
  number order, at the bottom of the page of its first reference, separated
  from the body by a rule, and never split across pages. Footnote height is
  deducted from the body capacity; lines that no longer fit move (with
  their footnotes) to the next page.
- A paragraph split across pages keeps at least 2 lines on each page
  (single-line paragraphs excepted).
- Every page carries a `Page N of M` page number. Clicking a superscript
  reference jumps to its footnote; clicking a footnote number jumps back to
  the first reference.

## Code layout

- `manual_record_187/schemas.py` — request models and validation (input rules).
- `manual_record_187/measure.py` — font registration, metric-based measurement, wrapping.
- `manual_record_187/paginate.py` — footnote numbering and page breaking.
- `manual_record_187/render.py` — PDF drawing, links, page numbers.
- `manual_record_187/main.py` — FastAPI wiring.
- `tests/test_api.py` — API and layout tests.

## Test & example

```bash
.venv/bin/python -m pytest -q
curl -X POST localhost:8371/render -H 'Content-Type: application/json' \
     --data @/tmp/manual.json -o manual.pdf
```

Repository: https://github.com/huangjie666777-ux/manual-measurement-pdf-187
