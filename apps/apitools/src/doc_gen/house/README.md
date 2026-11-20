# house — every business document of the office, in one house style (DGO-2029)

The renderer the ledger issues with. It is the ledger's emerald look of July 2026 (`../htmlgen.py`, the
documents the owner chose), raised and extended to every type. `htmlgen.py` stays for INDOX's synthetic
corpus (`/docGen`); the ledger (`src/doc_data/store.py`) and `/docGen/house` render with this.

| File | What it is |
|---|---|
| `catalogue.py` | every type: its Hebrew name, family, series, who may issue it, what it carries (flags) |
| `view.py` | the arithmetic (Decimal, half-up to agorot) and the formatting; templates compute nothing |
| `templates/*.j2` | `base` + `_parts` (macros) + one template per kind: ledger, receipt, statement, proposal, agreement, letter, certificate |
| `house.css` | the one stylesheet: paged media for WeasyPrint, a sheet of paper for a browser preview (`@media screen`) |
| `tokens.json` | every colour, face and size, by role; an office's brand overrides keys (settings → `brand`) |
| `samples.py` | one whole document of every type (made-up customer) — the gallery, the tests, the screen's previews |
| `starters.py` | what a new document of a type starts with on the screen (chapters, clauses, terms) |
| `gallery.py` | `python3 -m src.doc_gen.house.gallery <out>` — every sample as PDF + page PNGs + HTML |

## What it prints, and why

- **PDF/A-3b, with the document's own data inside** (`dgo-document.json`), so the file says what it is,
  in data, years from now (research_notes/DGO-2029 …/05).
- **«מקור» / «העתק»** on documents of the books only (tax invoice, invoice-receipt, credit note, receipt,
  delivery note); a quote, a payment request or an agreement prints none (Instruction 36; research 04). The
  ledger draws both when it issues one and keeps both: a copy is never drawn again by a later renderer.
  `POST /docGen/house` draws these types only as a draft. Only an issued document says «מסמך ממוחשב»; none says
  «נחתם דיגיטלית» while the ledger's signature is kept beside the file and not in it
  (issues/ledger-issued-pdf-carries-no-embedded-signature.yaml).
- **A brand is data in a fixed shape**: a hex colour, one of the two faces, a size. A logo is drawn as an
  image, never written into the page, and WeasyPrint reads only the two font files and `data:` URIs.
- **A running footer on every page** — the business, the document, the label, the minute it was produced,
  «עמוד X מתוך Y» — and «סוף המסמך» at its end.
- **The allocation number** with its 9 rightmost digits apart, as the Tax Authority asks it printed; a tax
  invoice or invoice-receipt only (a credit note asks for none).
- **A credit note names the invoice it credits**, its date and the reason (§9(ה)), with a true minus.
- **An עוסק פטור** charges no VAT («עוסק פטור — לא נגבה מע״מ») and issues no tax document (`may_issue`).
- **Hebrew order**: every number, date, e-mail and document number is a left-to-right isolate; facts on one
  line are each isolated (`view.parts`), so «כרטיס המסתיים ב־4417 · 3 תשלומים» never reorders.

## Traps (each measured, 2026-11-19)

- WeasyPrint lays out an absolutely placed flex box in RTL off the page, and drifts a wrapping flex row:
  the cover is in normal flow, and module cards are a table.
- Heebo and Rubik carry no ✓ — the mark is an inline SVG (`_parts.check`).
- Hebrew is not letter-spaced wide (at most .06em on small labels).
- A browser preview gets its faces from `font_base` (apitools serves them at `/docGen/house/fonts/<name>`).

Tests: `tests/test_house_documents_unit.py` (every type: numbers, Hebrew order, PDF/A, page footer),
`tests/test_ledger_house_unit.py` (issue, original then copy, credit note, the deal from proposal to receipt).
