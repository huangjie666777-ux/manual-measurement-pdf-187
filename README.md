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

### Measurement templates (offline fill-in)

`POST /templates` — same body as `/render` plus a `measurements` list
(1 to 12 items):

```json
{
  "paragraphs": [{"parts": [{"text": "Check the oil level."}]}],
  "footnotes": {},
  "measurements": [
    {"field_id": "oil_level", "paragraph": 0, "name": "Oil level",
     "unit": "mm", "lower": 10.5, "upper": 12, "required": true}
  ]
}
```

- Each item: unique English `field_id` (letter, then letters/digits/`_`),
  0-based `paragraph` index, `name`, `unit`, finite decimal `lower`/`upper`
  bounds (`lower <= upper`) and a `required` flag. At most one item per
  paragraph. Invalid indexes, duplicate ids, non-finite bounds and inverted
  ranges are rejected with 422.
- Response: `application/pdf` with an `X-Template-Id` header. After each
  measured paragraph the PDF shows the name, unit, allowed range and an
  AcroForm text field (Helvetica) that any PDF reader can fill and save;
  no JavaScript is used. The input box stays on the same page as the last
  two lines of its paragraph (or the whole paragraph if it is one line).
- Templates are stored under `$MR187_DATA_DIR/templates` (default
  `./data/templates`) and survive restarts.

`POST /templates/{template_id}/submit` — multipart form with the filled
PDF as `file`. Field values are read from the AcroForm fields, never from
page text. Missing, extra, duplicate or non-text fields, and corrupt or
encrypted PDFs, are rejected with 422. Readings must be plain decimals
with an optional sign (`+1.5`, `-0.25`, `.5`); exponents and non-finite
values are rejected. An empty required field is rejected; an empty
optional field is recorded as `unmeasured`; out-of-range values are
accepted but marked `fail`. Response:

```json
{
  "template_id": "...",
  "record_id": "...",
  "readings": [{"field_id": "oil_level", "raw": "11.25",
                 "value": 11.25, "verdict": "pass"}],
  "record_url": "/records/..."
}
```

`GET /records/{record_id}` — the finalized record PDF. It is redrawn from
the server-side original manual (uploaded page content is discarded),
shows the readings and verdicts instead of the input fields, keeps the
footnote jump links and contains no Widget annotations, so it cannot be
edited further. Records are stored under `$MR187_DATA_DIR/records`.

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
- `manual_record_187/forms.py` — AcroForm extraction and reading evaluation.
- `manual_record_187/store.py` — template/record persistence (configurable directory).
- `manual_record_187/main.py` — FastAPI wiring.
- `tests/test_api.py`, `tests/test_measurements.py` — API and layout tests.

## Test & example

```bash
.venv/bin/python -m pytest -q
 curl -X POST localhost:8371/render -H 'Content-Type: application/json' \
      --data @/tmp/manual.json -o manual.pdf
 ```

Template flow:

```bash
# 1. issue a template (id comes back in the X-Template-Id header)
curl -s -D - -X POST localhost:8371/templates -H 'Content-Type: application/json' \
     --data @/tmp/template.json -o template.pdf
# 2. fill template.pdf off-line in any PDF reader and save as filled.pdf
# 3. collect it
curl -s -X POST localhost:8371/templates/<template-id>/submit -F file=@filled.pdf
# 4. download the finalized, non-fillable record
curl -s localhost:8371/records/<record-id> -o record.pdf
```

Repository: https://github.com/huangjie666777-ux/manual-measurement-pdf-187
