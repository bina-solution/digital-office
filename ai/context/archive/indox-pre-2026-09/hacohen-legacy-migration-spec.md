# Hacohen client — legacy → new system migration spec

**Goal:** replace the legacy INDOX (Google-Sheets-backed, on `hacohen-vps` 31.97.196.129 /
`*.hacohen.bina-solutions.co.il`) with our release, preserving ALL history + settings.

## Legacy system = a Google Sheet

**The legacy DB is the spreadsheet `AutomationValues`**
(`1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo`), 35 tabs, readable with the
**person9@example.com** session in browser42. n8n drives it (`n8n.hacohen.bina-solutions.co.il`).

### Tab → new supabase table
| legacy tab | new table | gid |
|---|---|---|
| `מסמכים נכנסים` | `incoming_documents` | **542119184** |
| `חברות` / `Companies` | `companies` | — |
| `הגדרות` | `settings` | — |
| `הגדרות תגיות במייל` | `tag_rules` | — |

Others = logs (mail actions / drive naming / aging reports), dashboards, charts, and
Priority-ERP integration tabs (`מבנהAPIפריוריטי`, `העתקה חשבוניות לפריוריטי`).

## THE KEY FINDING — schemas already match

`מסמכים נכנסים` has **76 columns whose names are IDENTICAL to our supabase
`incoming_documents`**: `NAME, COMPANY_ID, SHORT_DOC_ID, TYPE, STATUS, COMPANY_DOC_ID, LINK,
DOC_DATE, DOC_TOTAL_AMOUNT, PURCHASE_ID, SHIPMENT_DOC_ID, LINKED_BS, BS_LINE_DATE,
BS_LINE_AMOUNT, SOURCE_TYPE, SOURCE_ID, SOURCE_LINK, SIZE, HASH, TIMESTAMP, COMPANY_NAME,
REQUIRED_ACTION, BS_EXTRACTED_LINES, TOTAL_AMOUNT, BS_EXTRACTION_VERIFIED, BS_LINE_NOTE,
FROM_OFFICE, FROM_OFFICE_CHECK, *_COMPLETED flags, API_TOOLS_ID, ID, EMPTY,
BS_EXTRACTION_USE_CACHE, EX_INVOICE_ID, …`

→ **Migration is a direct column-for-column load (sheets→supabase), not a transformation.**
Our schema was designed from this sheet. The backend differs only in storage
(`INDOX_DATA_BACKEND=sheets` → `supabase`).

## Volume (live, 2026-07) — 46,681 rows

STATUS: OLD 16299 · COMPLETED 13785 · DOUBLE 7205 · MISSING_COMPANY_ID 3617 ·
MISSING_TYPE 2719 · ACTION_RESTART 1124 · IN_PROGRESS 908 · MISSING_LINK 615 ·
MISSING_SHIPMENT 192 · UNKNOWN_COMPANY 94 · ACTION_REQUIRED 55 · EXTRACTION_FAILED 40

TYPE: INVOICE 29607 · SHIPMENT 8681 · UNKNOWN 5058 · BALANCE_SHEET 2615 · ORDER 709 · TRASH 10

**⚠ GAP:** our INDOX dashboard `status_group` map is missing **ACTION_RESTART**,
**MISSING_SHIPMENT**, **ACTION_REQUIRED** (they'd fall through to "attention"). Add them
(`development/incoming-documents/app/incoming_documents/api/__init__.py`).

## How sync is DECLARED (legacy `הגדרות` tab, 8 keys)

Sync = **Drive folder-ID routing per role** + Gmail→Drive landing folders. Same key names as ours:
- `DocumentsToProcessFolder` — Drive folder scanned for new files
- `ProcessedDocumentsFolder` / `ProcessedDocumentsFailsFolder` — success / fail destinations
- `GmailDownloadedDocumentsFolder` / `GmailDownloadedBalanceDocsFolder` — where Gmail
  attachments + aging reports (BS) land
- `GmailToWhatsappAllowedMails` (person11@example.com, person8@example.com),
  `GmailDocsDownloadIgnoredMails`, `WhatsappAdmins`

→ maps onto our `sync_registry` pair model (source/dest folder per state). Near-direct port.

## Reading the sheet (recipe that works)

gviz + the sheets UI TIME OUT on the 46k-row tab. Use the **CSV export + Playwright download**:
```python
url=f"https://docs.google.com/spreadsheets/d/{SID}/export?format=csv&gid={gid}&range=A1:E100000"
with page.expect_download(timeout=90000) as dl:
    try: page.goto(url, timeout=85000)
    except Exception: pass      # goto ALWAYS throws "Download is starting" — swallow it
dl.value.save_as("/data/downloads/x.csv")   # /data = host data/browser42/
```
Narrow the `range` to the columns you need. gviz `out:html` only works on small tabs (`הגדרות`).

## Access state
- ✅ browser42 signed in: person9@example.com + solomonBoltin → Sheet/Gmail/Drive readable.
  Profile survives `docker restart browser42-browser` (logins persist; tabs don't).
- ❌ **No SSH to `hacohen-vps`** — our key was rotated out; Hostinger panel add returns HTTP 400;
  its "Terminal" is a serial console at a `login:` prompt (needs root pw). Not blocking: the
  browser gives the legacy data.
- ✅ SSH to `bina-devops-vps` (31.97.196.82) works. DNS `console.bbox.dev.bina-solutions.co.il`
  → 31.97.196.82 already resolves.
- ⚠ CDP wedges under many rapid connections → `docker restart browser42-browser` clears it.

Related: [[indox-api-routing-and-architecture]], [[indox-supabase-pivot-existing-work]].
