# Manual Measurement PDF 187

Pure-backend service that turns ordered paragraphs with same-page footnotes
into a searchable, linked A4 PDF. It can also issue offline-fillable AcroForm
measurement templates and redraw returned readings into finalized records.
Python 3.10.12, FastAPI 0.115.12, ReportLab 4.4.5 and pypdf 6.19.0. Body and
footnotes use DejaVuSerif embedded from `fonts/`; form inputs use Helvetica.

## Run

```bash
.venv/bin/uvicorn manual_record_187.main:app --port 8371
```

Persistent files default to `./instance_data`. Override the directory with:

```bash
MANUAL_RECORD_STORAGE_DIR=/var/lib/manual-records \
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

`POST /templates` — same manuscript and footnote payload, plus 1–12
`measurements`:

```json
{
  "paragraphs": [{"parts": [{"text": "Check the oil gap."}]}],
  "footnotes": {},
  "measurements": [{
    "field_id": "oil_gap",
    "paragraph": 1,
    "name": "Oil gap",
    "unit": "mm",
    "lower_bound": 1.0,
    "upper_bound": 2.5,
    "required": true
  }]
}
```

- `paragraph` is 1-based and each paragraph can have at most one item.
- IDs must be unique and start with an ASCII letter; only letters, digits
  and underscore are allowed. Invalid paragraph numbers, inverted or
  non-finite bounds are rejected with 422.
- The response is the fillable PDF. The template ID is in `X-Template-ID`.
  `GET /templates/{template_id}` downloads the same saved template.
- Measurement metadata is drawn after its paragraph. Its two-row block and
  the paragraph's last two lines are kept together; a one-line paragraph
  stays entirely with the block. Block height participates in normal
  footnote-aware page breaking and never covers body text or footnotes.
- Forms contain no JavaScript. Technicians can save values in a standard
  PDF reader's AcroForm support.

`POST /templates/{template_id}/records` — multipart upload with file field
`file` containing the filled PDF:

- Values are read from AcroForm fields, never extracted from page text.
- Missing, extra, duplicate and non-text fields, damaged files and encrypted
  PDFs are rejected with 422.
- Readings accept signed ordinary decimals only (`12`, `-1.5`, `+.25`);
  exponential notation, `NaN` and infinity are rejected.
- Blank required fields are rejected; blank optional fields return
  `null` and `not measured`. Out-of-range decimal values are accepted and
  return `fail`; in-range values return `pass`.
- JSON returns each original `raw` string, parsed `value` and `judgment`,
  plus `record_id` and `record_url`. The record PDF is newly drawn from the
  server-side manuscript and reading data: uploaded page graphics are not
  reused, no AcroForm/Widget remains, and footnote links are regenerated.
- `GET /records/{record_id}` downloads the non-fillable record PDF.

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
- Adjacent text fragments without whitespace are concatenated exactly; only
  whitespace explicitly present in the manuscript creates a visual gap.

## Code layout

- `manual_record_187/schemas.py` — request models and validation (input rules).
- `manual_record_187/measure.py` — font registration, metric-based measurement, wrapping.
- `manual_record_187/paginate.py` — footnote numbering and page breaking.
- `manual_record_187/render.py` — PDF drawing, links, page numbers.
- `manual_record_187/forms.py` — AcroForm parsing, measurement rules and persistence.
- `manual_record_187/main.py` — FastAPI wiring and download endpoints.
- `tests/test_api.py` — API and layout tests.

## Test & example

```bash
.venv/bin/python -m pytest -q
curl -X POST localhost:8371/render -H 'Content-Type: application/json' \
     --data @/tmp/manual.json -o manual.pdf

# Issue a template and retain its ID header.
curl -i -X POST localhost:8371/templates \
  -H 'Content-Type: application/json' \
  --data @/tmp/template.json -o /tmp/template.pdf

# Fill /tmp/template.pdf offline in a PDF reader (or with pypdf), then return it.
curl -X POST "localhost:8371/templates/$TEMPLATE_ID/records" \
  -F 'file=@/tmp/filled.pdf;type=application/pdf'

# Download the finalized PDF from the returned record_url.
curl localhost:8371/records/$RECORD_ID -o record.pdf
```

Repository: https://github.com/huangjie666777-ux/manual-measurement-pdf-187
