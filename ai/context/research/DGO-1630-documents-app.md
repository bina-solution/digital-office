# DGO-1630 — one documents app instead of «מסמכים נכנסים» and «המסמכים שלי»

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28, 2026-11-09),
lane handed over by the MacBook's coordinator. **Nothing below was installed, enabled or changed on a
live office**: every claim about our own code is a read of the files named beside it, every claim about
Morning is a citation with its date. The meeting's own plan file
(`apps/project-pln/plans/meeting-bina-261109-vjlwcr.yaml`) is **not in the HP's checkout**; the
meeting's words below are the ones carried on the item itself (`bbox project-pln tasks show DGO-1630
--body`), with the recording's timestamps.

**Recommendation: build ONE tile called «מסמכים» (`documents`) that is a document *store of record*
across two directions (issued / incoming) and N providers — `local` (today's apitools ledger),
`indox` (today's incoming pipeline) and, optionally, `morning` (a business that already invoices
there) — and move no data to do it.** The two existing screens stop being tiles (`tile: false` keeps
their doors and their data), the 75 INDOX workflows and the 19 ledger tables are left exactly as they
are, and the owner sees one place, one search and one "create a document". The pieces that must be
BUILT rather than composed are three, and they are the actual deliverable: **document types as data**
(with a per-type template), **branding as data** (logo + colours + template per company, not the one
hardcoded palette), and **the inbound list inside the same screen**. Details and the migration follow.

---

## 1. What the owner asked, in his words

> «כרגע יש לנו מסמכים נכנסים ומסמכים שלי … להגיד ביניהם, פשוט לאפליקציית מסמכים אחת, פשוטה, שגם אתה
> יכול ליצור במסמכים, והיא גם מתחברת למייל ואוספת לך את הכל» [11:01–11:27]
>
> «לדאוג שהיא מושלמת … עומדת בכל הסטנדרטים של השוק … להתחיל ממש מחר … לנהל שם עסק קטן וגדול … ב-100%
> את כל המענה שמורנינג נותן … פלוס … המסמכים הנכנסים והאוטומציות» [11:34–11:52]
>
> «יש סוגי מסמכים, ויהיה מוכן … איך כל מסמך יראה, בהתאם ללוגו של החברה ולצבעים שלה ולמיתוג שלה»
> [12:48–12:55] — אפיון, ייעוץ עסקי, דרישת תשלום, כל אחד עם תבנית [12:26–12:45]

The item's acceptance (which is the definition of done, not the title):
one app (INDOX + my-docs) with **Morning's feature list and what of it is covered**, **creating a
document of a chosen type in a branded template**, and **the incoming documents from mail in the same
place**. Related: DGO-1454 (the customer document line).

Read plainly, there are four asks and one constraint:

1. one tile, not two;
2. it must give **100% of what Morning gives** — a full invoice/customer/expense/report product, for a
   one-person עוסק פטור and for a חברה בע״מ;
3. document **types** with a **template per type**, drawn in the company's own branding;
4. the incoming documents (mail, Drive) land in the same place, with their automations;
5. constraint: **it must be perfect from tomorrow** — i.e. it may not be a six-month rewrite of the
   thing that already files Example's books.

(1) and (4) are composition. (2) is a feature gap to be closed in slices. (3) is genuinely missing
today — §4. (5) is what forbids the obvious-but-wrong answer ("port INDOX into the new app").

---

## 2. What exists today, measured

Three back ends, two tiles, one shared database. Nothing here is described from memory: each row names
the file the fact was read in.

### 2.1 The outbound half — apitools' `ledger`, shown by `my-docs`

| | |
|---|---|
| engine | `apps/apitools/src/doc_data/` — `store.py` (468 lines, lifecycle), `db.py` (362, schema + gapless numbering), `entities.py` (139, business/customers/items), `allocation.py` (112, חשבוניות ישראל), `pcn874.py` (78, the unified-structure VAT report), `signing.py` (124) |
| rendering | `src/doc_gen/htmlgen.py` (356) — Hebrew-native HTML/CSS → WeasyPrint PDF; `src/doc_gen/render.py` (455) — the legacy fitz renderer it falls back to, loudly |
| storage | the office's Postgres (`supabase-db`), tables declared in `apps/apitools/app.json` `data.sql`; the rendered artifact is kept with the row |
| types | `doc_models/models.py:353` — `DOC_TYPES = {Invoice, InvoiceReceipt, Order, Quote, ShipmentCert, BalanceSheet, Receipt}`; a credit note is an `INVOICE` in series `CN` (`store.py:311`) |
| screen | `apps/my-docs` — 135-line Flask pass-through (every `/api/*` path forwarded to `http://apitools:8080`), one `Idempotency-Key` lock, and a 4-view SPA: `dash`, `docs`, `customers`, `items`, `settings` (`static/app.js`) |
| tile | group `עסק`, order **1**, alias `my-docs`, `url_env: MY_DOCS_URL` |
| agent | `apps/my-docs/AGENT.md` — issue/cancel/allocation only on the owner's words; download is a write («מקור» is spent once) |

The ledger is not a toy: `src/doc_models/COMPLIANCE.md` maps ten verified Israeli requirements to
implementation (`§9(a)` nine mandatory invoice fields, `קבלה §5`, `תעודת משלוח §8`, `מסמך ממוחשב
§1+§18ב`, gapless numbering per `(type, series, tax_year)`, the permanent file, מקור-once, 7-year
retention, allocation numbers, the ITA API v2.0 print rule). `allocation.py` implements
`needs_allocation(total, date)` against the thresholds 25k (2024) → 20k (2025) → 10k (1.1.2026) → 5k
(1.6.2026) and talks to the ITA with `ALLOCATION_BACKEND=live|stub`.

### 2.2 The inbound half — `indox`

| | |
|---|---|
| engine | `apps/indox/app/incoming_documents/` — BFF + state machine; the work itself is **75 n8n workflows** in `apps/indox/blueprint/n8n/` (sync discover/deliver for Drive, Gmail and link; `indoxV2Driver01` drain; per-type extract/decide/actions for invoice, receipt, order, shipment, base and balance sheet) |
| engine map | `apps/indox/blueprint/engine-manifest.json`, GENERATED from the workflows (`scripts/gen-engine-manifest.py`) — the screen draws the pipeline from it |
| data | per **instance** (מופע): schema `indox_<id>`, listed in `public.indox_instances`; 19 tables declared in `app.json` `data.sql`; instances declared in `platform.state.yaml` (`example`, `test`) |
| files | `apps/indox/storage` — a **bind mount into the checkout** (29 MB on this office), `data.volumes: []` |
| API | `http://incoming-documents:8080/incomingDocuments` — `GET /instances`, `POST /repos/<repo>/documents/query|month-index|export`, `GET /repos/<repo>/documents/<id>|/history`, `GET /sync/registry`, `/pipeline/status`, `/dashboard/stats|actions`, `/config/settings` |
| screen | `apps/indox/app/webapp/` (React/Vite) — 10 pages: dashboard, documents browser, document detail, action log, sync state, settings, extraction ×2, tests, 404 |
| tile | group `עסק`, order **0**, alias `incoming`, `url_env: INCOMING_UI_URL` |
| agent | `apps/indox/AGENT.md` — always `?instance=<id>`; the drain stays on; `config/stop-all` never called |

Two facts that decide the whole migration:
the state machine is a **hundred workflows**, and it is the asset; and the documents it files are
**another business's books under a schema per instance**, which is a tenancy model the ledger does not
have (the ledger is explicitly one-business: `entities.py:3`, «This deployment serves ONE business»).

### 2.3 Morning's own feature list (read 2026-11-09)

From [morning/greeninvoice](https://www.greeninvoice.co.il/),
[digital invoicing](https://www.greeninvoice.co.il/digital-invoices/) and
[business management](https://www.greeninvoice.co.il/business-management-tools/):

**Issuing** — חשבוניות, קבלות, חשבונית מס/קבלה, חשבוניות מס, דרישות תשלום (חשבון עסקה), הצעות מחיר,
תעודות משלוח, זיכויים, מקדמות, הזמנות עבודה; **חשבונית ריטיינר** (a fixed amount on a schedule,
automatically); **a designed invoice** — templates with the business's logo, colours and groov;
payment reminders and dunning with ready-made wording; automatic sending to the customer by e-mail and
WhatsApp; fixed attachments on every outgoing mail (אישור ניהול ספרים, ניכוי מס במקור); English
documents and 0% VAT for foreign customers; a digital signature on every document; **חשבוניות ישראל
allocation numbers automatically above the threshold**; a payment link inside the invoice (credit,
bit, wallets) when clearing is connected; webhooks + API.

**Managing** — expenses (receipts in from WhatsApp/mail, an expense report to the accountant),
permissions (an accountant works on defined actions), reports (income, expenses, tax payments,
year-end), customers and suppliers, sale pages, an e-commerce integration, a mobile app.

### 2.4 Coverage, honestly

| Morning | today | where |
|---|---|---|
| invoice, invoice-receipt, receipt, quote, order, shipment, balance sheet | **yes** | `doc_models/models.py:353` |
| credit note | **yes** (as series `CN`) | `store.py:308–328` |
| gapless legal numbering, מקור/העתק, 7-year keep, audit chain | **yes** | `db.py`, `COMPLIANCE.md` 5–8 |
| digital signature on the document | **partly** — `signing.py`; a certified CA must be supplied, the stub is marked NON-CERTIFIED | `signing.py` |
| חשבוניות ישראל allocation number | **yes**, with the ITA API and the print rule | `allocation.py`, `COMPLIANCE.md` 9–10 |
| PCN874 (מבנה אחיד) | **yes** | `pcn874.py`, `GET /reports/pcn874` |
| customers, items, one business's settings | **yes** | `entities.py` |
| **document types as data** («אפיון», «ייעוץ עסקי», a new type next month) | **no** — seven Python classes; a new type is a code change | `doc_models/models.py` |
| **branding: logo, colours, template per type** | **logo only** — `business_settings.logo_b64`; the palette is hardcoded `--brand:#0E5A48` in `htmlgen._css()` | `entities.py:22`, `htmlgen.py:52` |
| recurring document (חשבונית ריטיינר) | **no** | — |
| payment reminders / dunning | **no** | — |
| automatic send by mail/WhatsApp | **no** — `send` only marks the document sent | `my-docs/AGENT.md` |
| English documents, 0% VAT per document | **VAT rate is per document** (`vat_pct`); the renderer is Hebrew-RTL only | `entities.py`, `htmlgen.py` |
| payment link / clearing | **no** | — |
| expenses, expense report to the accountant | **no** in the ledger (INDOX reads receipts *in*, it does not expense them out) | — |
| permissions (accountant/employee roles) | **no** — the office's SSO is the only role | — |
| reports: income, expense, tax paid, year-end | **PCN874 only** | `pcn874.py` |
| incoming documents from mail/Drive, OCR, filing, actions | **yes**, a separate app | `apps/indox` |
| webhooks / API | **yes** — the ledger API, no webhooks, no `flow.v1` stream | `src/api/__init__.py` |

So: **the legal and issuing core is already at Morning's standard — arguably past it, because the
compliance is written down requirement by requirement — and the product surface around it is not.**
The gap is not "rebuild Morning"; it is exactly the five rows the owner named plus what a business
notices in the first week: types, branding, recurring, sending, reports.

---

## 3. The three things that are actually missing (and are the design)

### 3.1 Document types as DATA, with a template per type

Today `DOC_TYPES` is a dict of seven Pydantic-ish classes, each with its own fields and its own
renderer function, and the renderer dispatches on the type string in two places
(`render.py:423`, `htmlgen.py:342`). That is why «אפיון» and «ייעוץ עסקי» cannot exist: they are not
classes.

The design: a **document type registry** the business owns, one row per type —
`{id, name_he, series, direction, template_id, needs_allocation, vat_mode, number_format}` — and a
**line model** every type shares (description, quantity, unit, unit price, discount, VAT) plus an
optional `type_fields` JSON for the type's own few fields (a quote's `valid_until`, a receipt's
payment method). A new type is then a row, not a release.

Crucially this is **additive**: the seven existing types become seven declared rows with the same
`DOC_TYPE` codes, so every issued document, every number series and every stored artifact keeps
meaning. The compliance validators stay where they are, keyed by code — a type that declares
`needs_allocation: true` gets the `allocation.py` path whether or not a Python class exists for it.

### 3.2 Branding as DATA — the template

`htmlgen._css()` hardcodes one palette («deep-emerald», 2026) and one layout. The design: a
**template** is `{id, name, logo, colours {ink, brand, accent, paper}, font_pair, layout}` stored per
business and referenced by the type; `htmlgen.build_html(model, label='', branding=None)` takes it as
CSS custom properties (the palette ALREADY lives in `:root` variables — `htmlgen.py:52` — so this is a
swap of one dict, not a rewrite of the document), and the logo already exists as `logo_b64`. What the
owner asked for («לפי הלוגו, הצבעים והמיתוג») is then two facts the business sets once and every
document of every type inherits.

Gate: G27 says only `theme-tokens.css` may name a colour — that is about the office's own screens.
A customer's invoice is not the office's screen; the template's colours are customer data. Stated
here because the first reader will ask.

### 3.3 One screen over both directions

The unified model, and it is small:

```
document {
  id, direction: "out" | "in",
  type_id,                    # from the registry (§3.1)
  provider: {id: "local"|"morning"|"indox", ref},   # where it really lives
  number, issued_at, party {name, tax_id},
  total, vat, currency, allocation_number,
  state,                      # draft|issued|sent|paid|cancelled  ·  new|filed|needs_review|actioned
  files[], template_id, tags[], events[]
}
```

An issued invoice is `direction: out, provider: local`. A supplier's receipt pulled from Gmail is
`direction: in, provider: indox, ref: {instance, repo, doc_id}`. A document in a business that
invoices on Morning is `direction: out, provider: morning, ref: {id}` — read through Morning's API,
never copied into our ledger (their books are their books of record; a copy would be a second books).

The screen has one list, one search, one drawer, and one «מסמך חדש» that opens the type picker. The
incoming half keeps INDOX's own screens reachable (a deep link into the instance's document) for the
operator work that is genuinely INDOX's — extraction debugging, sync state — but not as a tile.

---

## 4. The design of the app

Per `ai/context/app-engine-pattern.md` (three nouns, four planes, five slots) and the four channels of
`ai/context/build-your-first-app.md` §"The four channels".

```
id documents · layer 3 · kind service · capability documents (interface documents.v1)
endpoint http://documents:8080 · tile: group עסק, order 0, alias documents
```

### 4.1 Providers (`engine` + profiles in app.json)

```json
"engine": {
  "id": "documents_local",
  "profiles": [{"id": "admin", "display_name": "מנהל", "admin": true}]
}
```

and a provider registry, `role`-tagged because the two halves are not the same kind of thing:

| provider | role | how | credential |
|---|---|---|---|
| `local` | **issue** | the apitools `ledger` API (`http://apitools:8080`) — the private engine | private profile's key (vault) |
| `morning` | **issue** (remote) | Morning's own API (`/api/v1`, key in a header) | `morning-api-key` in the vault |
| `indox` | **intake** | `http://incoming-documents:8080/incomingDocuments` with `?instance=<id>` | the office's own service identity |
| `upload` | **intake** | the app's own volume, for a file the owner drops | — |

Rules the app must obey, from the pattern: **one `resolve(profile_id)` choke point** (precedence:
explicit argument > binding > error), `/readyz` uses that same choke point, and **absence of a method
is how a provider says "unsupported"** — a `morning` provider simply does not implement `issue` if the
business's Morning plan forbids it, and the UI hides the button instead of failing at click time.

`local` is the default binding; nothing in the code may branch on "is default".

### 4.2 The four channels

**API** (`documents.v1`, ops the platform requires a service to declare):

```
documents.list {direction, type, provider, from, to, q, limit, cursor}
documents.get <id>
documents.create {type_id, party, lines[], template_id?, direction:"out"}   -> draft
documents.issue <id>          ·  documents.cancel <id> {reason}
documents.send <id> {to}      ·  documents.markPaid <id> {evidence}
documents.types                GET/POST/PATCH — the registry (§3.1)
documents.templates            GET/POST/PATCH
documents.intake.sync {instance?}  ·  documents.intake.file <ref> {type_id, party}
documents.search {q}           # one query across both directions
```

Every op accepts `provider` and `profile_id` so one call can address a non-bound provider — that is
what makes «עובדים מול שני עסקים שונים» work later without a second app.

**CLI** — `./bbox documents` (one verb file, the same ops): `list | show <id> | new -t <type> |
issue | cancel | send | types | templates | intake sync | search`. Reads are free; `issue`, `cancel`
and `send` are the owner's words only, exactly as `my-docs/AGENT.md` says today.

**Flow** (`flow.v1`, `dgo:flow:documents`) — what a person and another agent need to see happen:
`document.created`, `document.issued`, `document.sent`, `document.paid`, `document.cancelled`,
`document.allocation.held`, `document.intake.filed`, `document.intake.needs_review`. The dashboard
group relay (`apps/dashboard/group.py`, DGO-1329) already posts per-kind and gets these for free; the
«כל מקביל» timeline gets a span per issuing call.

**UI** — one screen, five views: `dash` (what needs a hand today: drafts, held allocations, intake
needing review, unpaid over 30 days), `documents` (the one list, both directions, a direction toggle),
`new` (type picker → the branded preview), `customers` (customers and suppliers in one list by
direction), `settings` (business, templates, types, numbering series). Phone-first: the owner's own
words were «לנהל שם עסק קטן וגדול», and INDOX's grid is a desktop grid.

### 4.3 What the app owns, and what it does not

| | owner |
|---|---|
| the unified read model (an index of `{id, direction, provider.ref, state}`) | **documents** — its own table on its own volume (SQLite, one file, `esign`'s choice: `apps/project-pln/plans/esign.yaml`) |
| issued documents, numbers, artifacts | apitools `ledger` (unchanged) or Morning (remote, not copied) |
| incoming documents, extraction, state machine | INDOX (unchanged) |
| type registry, templates, branding | **documents** |
| audit, allocation, PCN874 | apitools `ledger` (unchanged) |

The index is derived and disposable: it can be rebuilt from the two providers, which is what makes a
provider outage degrade a list rather than lose a book.

---

## 5. The migration that loses nothing

The order is the whole safety argument: **the new app is enabled and proven BEFORE either old app
changes**, and no schema, table, file or workflow is moved at any step.

**Phase 0 — measure (before any change).**
Record on the Exampleu office: INDOX's instances and per-instance document counts
(`GET /instances`), the ledger's document count and the last number per `(type, series, tax_year)`
(`GET /documents/verify`), the storage size of `apps/indox/storage`, and the list of enabled
automations that call either app (`bbox n8n tags` + the sync registry). This is the baseline a
post-migration check compares against — a number, not an opinion.

**Phase 1 — the app exists (nothing else changes).**
`documents` is built with `local` + `indox` providers, `tile: true` at order 0, and **no** write path
that is not already the providers'. Every issued document still goes through the ledger's `issue`;
every incoming one is still INDOX's. Enable it. The two old tiles stay. Proof: the same document read
through `my-docs` and through `documents` shows identical number, total, allocation and events.

**Phase 2 — one tile.**
`apps/indox/app.json` and `apps/my-docs/app.json` get `routing[0].module.tile: false`
(DGO-890's mechanism: the `/a/<alias>/` door, the API, the CLI and the data all stay; the launcher
shows nothing). The owner sees one tile. Nothing else moves. Proof: the launcher lists «מסמכים» once;
`/a/my-docs/` and `/a/incoming/` still answer for anyone with a bookmark, and every `bbox indox` /
`bbox my-docs` verb still works.

**Phase 3 — creation moves in.**
`documents.new` renders the branded template (new §3.1/§3.2), and posting it calls
`provider.local.create` — i.e. the same ledger API `my-docs` forwards to today. The file, the number,
the allocation and the audit are identical to a `POST /api/documents` on `my-docs`. Nothing to
migrate: `my-docs` holds no state (135 lines, a proxy).

**Phase 4 — intake in the same list.**
The documents index subscribes to INDOX's own stream / polls `documents/query` per instance and
writes index rows with `provider.ref`. INDOX's files stay in `apps/indox/storage`, its tables stay in
`indox_<id>`, its 75 workflows are not touched. Proof: an invoice that arrives in Gmail appears in the
one list with the same `doc_id`, and INDOX's own browser shows the same document.

**Phase 5 — only if the owner asks.** A business that keeps its books on Morning binds the `morning`
provider and reads its documents there; a business that wants a ledger of record and no Morning binds
`local`. No migration of anybody's existing documents is implied, and **no client's document is ever
copied between providers**.

What is deliberately NOT in this migration, and why:
- **No port of INDOX's workflows.** They are the proven asset; a rewrite is a quarter of work with a
  real chance of losing a client's filings. The one app composes over them.
- **No move of `indox_<id>` schemas into the ledger.** The ledger is one-business by design
  (`entities.py:3`); merging would either break INDOX's tenancy or invent a tenancy the ledger does not
  need. The unified *read* model is enough for one screen.
- **No big-bang disable.** If phase 2 has to be undone, it is one line back in two `app.json`s.

Rollback, each phase: phase 2 → flip `tile` back; phase 3 → the screen's «מסמך חדש» posts to
`/a/my-docs/` (the door is still there); phase 4 → the intake half of the list stops refreshing; the
data was never moved, so nothing is restored.

---

## 6. Risks, and what would make this wrong

1. **The index goes stale and nobody knows.** Mitigation: the index is rebuilt from the providers on
   every `/readyz` degradation and carries `provider_synced_at` per row; the dash view shows «לא
   סונכרן מאז …» rather than an empty list. An empty list that means "provider down" is the single
   worst outcome for this screen.
2. **A second books of record.** Copying Morning's documents into the ledger would create two sets of
   numbers for one business. Forbidden by design (§4.3) and written as a rule in the app's AGENT.md.
3. **`tile: false` on INDOX hides the operator's escape hatch.** The operator needs the extraction
   debugging and sync state. The documents app must deep-link them (`/a/incoming/` stays routed), and
   its own AGENT.md must name the door — otherwise the first broken extraction becomes a hunt.
4. **Scope.** "100% of Morning" is a product, not a slice. The plan below is explicit that phases 1–4
   are the one-app answer and that recurring/dunning/expenses/reports/permissions are separate items
   with their own acceptance. Promising them in this item is how the whole item stalls.
5. **Branding colours colliding with G27.** A customer template is customer data, not our palette —
   stated in §3.2 so a gate reader does not relitigate it.

---

## 7. Recommendation, in one paragraph (Hebrew, for the item)

מומלץ לאחד את «מסמכים נכנסים» ו«המסמכים שלי» לאפליקציית **«מסמכים» אחת** שהיא מחסן-הרישום של העסק לשני
כיוונים — מסמכים מונפקים ונכנסים — מעל ספקים: `local` (פנקס apitools של היום), `indox` (צינור הנכנסים של
היום) ו`morning` כאופציה לעסק שמנפיק שם. שלד המשפטי וההנפקה כבר עומד בסטנדרט של Morning — חשבוניות,
קבלות, תעודות משלוח, זיכויים, מספור רציף, מקור/העתק, מספרי הקצאה מול רשות המסים, PCN874 וחתימה — ולכן
העבודה האמיתית היא שלושה דברים ולא שכתוב: **סוגי מסמכים כנתונים** (כך «אפיון» ו«ייעוץ עסקי» נולדים בלי
קוד), **מיתוג כתבנית** (לוגו, צבעים ותבנית לכל סוג — היום יש רק לוגו ופלטה אחת קשיחה), ו**רשימה אחת
לשני הכיוונים** עם חיבור למייל. שום נתון לא זז: שני המסכים הישנים מפסיקים להיות אריחים
(`tile: false` — הדלת, ה-API, ה-CLI והנתונים נשארים), 75 תהליכי n8n של INDOX ו-19 טבלאות הפנקס נשארים
במקומם, והאפליקציה החדשה מצביעה עליהם. היחיד שמשלם על זה הוא המשתמש: אריח אחד, חיפוש אחד, ויצירת מסמך
אחד — וזה בדיוק מה שביקש. מה שלא נכנס בפריט הזה — ריטיינר, תזכורות תשלום, הוצאות, דוחות והרשאות —
מפורט ב-plan כפריטים נפרדים עם קבלה משלהם, כדי שלא ייבלעו בהבטחה.
