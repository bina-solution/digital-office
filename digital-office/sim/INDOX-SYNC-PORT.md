# INDOX sync board → real platform · port contract

What the simulation's sync UI calls, what the **real** system already has, and exactly what has to be
built to support this UI for real. Read together with:
- `ai/context/indox-sync-control-plane.md` — the real target architecture (sync-refactor-v2)
- `sim/INDOX-SYNC.md` — why the UI is shaped this way
- `sim/mocks/incoming.js` — the mock implementation of everything below

## 0 · The good news: the UI was built on the real primitive

The control-plane design already states the core insight:

> There is exactly **one** generic operation against a sync's source: act on the items in a given
> **state**. It decomposes per source type and is driven entirely by `sync_registry`.

| primitive | drive | gmail |
|---|---|---|
| **LIST**(sync, state) | `op:list` folderId = `pairs[].{state}` | `op:search` `label:{state}` |
| **CLAIM**(sync, items → in_progress) | `op:move` → in_progress folder | `op:addLabels [in_progress]` |
| **ADVANCE**(sync, items → synced/failed) | `op:move` → synced/failed folder | `removeLabels` + `addLabels` |

**The board is a UI over exactly those three verbs.** Listing a column = LIST. Running = CLAIM.
Dragging a card = ADVANCE. Nothing in this UI requires a new *concept* — the gaps below are routes,
registry fields, and one genuinely new signal.

A second design rule the UI deliberately honours: **state lives in the source (folder/label); the table
is downstream.** Every board action writes the source and lets the table follow — the board never
"fixes" a document by editing the table row, which is the mistake the refactor doc calls out.

## 1 · Endpoint map

Legend — **EXISTS**: already served today · **ROUTE**: primitive exists, needs a BFF endpoint ·
**NEW**: needs real new capability.

| Sim endpoint | Real equivalent | Status |
|---|---|---|
| `GET /sync/status` | `sync api` **STATUS** verb (`/indox-manage`) | **EXISTS** |
| `GET /sync/registry` | read `settings.sync_registry` | **EXISTS** (but see §2 — must return live counts) |
| `GET /sync/items?sync&state&…` | **LIST**(sync, state) | **ROUTE** — primitive defined; add paging/filter |
| `POST /sync/items/move` → `in_progress` | **CLAIM** | **ROUTE** |
| `POST /sync/items/move` → `synced`/`failed` | **ADVANCE** | **ROUTE** |
| `POST /sync/items/move` → `to_sync` | **ADVANCE**(to_sync) = move/relabel *back* | **ROUTE** — the retry/release path; confirm the source ops allow reverse moves (they do: same `op:move` / label swap) |
| `POST /sync/registry/:name/run` | **SCAN** verb scoped by sync name | **EXISTS** (doc §61: scoping by sync name) |
| `POST /sync/run` | **SCAN** all | **EXISTS** |
| `POST /sync/registry` (create) | write `settings.sync_registry` | **NEW** — today the registry is hand-edited (`scripts/_reg.json`) |
| `PATCH /sync/registry/:name` (incl. `enabled`) | same | **NEW** |
| `DELETE /sync/registry/:name` | same | **NEW** |
| `GET /connections/:id/locations` | drive `op:list` (folders) / gmail `labels.list` | **ROUTE** — both ops exist in `sync source` |
| `POST /connections/:id/locations` | drive `op:createFolder` / gmail `labels.create` | **NEW** (small) |
| `GET /connections` | the platform's Drive/Mail account catalog | **EXISTS** elsewhere — INDOX must *consume* it, not keep its own |
| `POST /sync/items/apply-fallback-type` | ADVANCE(to_sync) + type override | **NEW** — see §3 |

## 2 · `GET /sync/registry` must return live state

The UI reads config and state in **one** call: each entry carries `counts`, `stuck`, `failures[]` and
its connection's health. Today the registry read is pure config and STATUS is separate.

Either fold STATUS into the registry read, or have the BFF fan out to both and merge. The important
part is that **the client never correlates two lists** — that correlation is what produced the old
two-tab split where a pipe's health and a pipe's definition lived apart.

## 3 · New `sync_registry` fields

| field | why | port note |
|---|---|---|
| `connection` | which Drive/Mail account this pipe pulls from | today implied by workflow wiring; make it explicit so the editor can browse the right account |
| `enabled` | pause a noisy source without deleting its config | scheduler + SCAN must skip disabled entries |
| `fallback_type` | **the highest-value field.** When extraction can't classify a document, the pipe's own location answers it — anything in `נכנס/קבלות` is a receipt (the real `bs-gdrive-sync` case). Converts a whole failure class into a one-click fix. | additive; `type_hint` already exists and can carry it, but a *separate* field keeps "hint for the classifier" distinct from "assume this when classification fails" |
| `failed_folder` | drive pipes need a failed destination like gmail's failed label | gmail already has `labels.failed`; drive only has `pairs{from,to}` |

## 4 · New item fields — and where each really comes from

`GET /sync/items` returns items, not counts. Per item:

| field | source in production |
|---|---|
| `id`, `title`, `size` | drive file metadata / gmail message metadata — free from LIST |
| `state` | which folder/label it is in — that IS the state |
| `sync` | the registry entry whose location it was listed from |
| `company`, `kind` | the extracted row if it reached the table; otherwise unknown |
| `detected` | false when the classifier returned no type — needed to offer the fallback fix |
| `error` / **`error_code`** / `error_group` | **the one real gap — see §5** |
| `claimed_at` → `stuck` | **the second real gap — see §5** |

## 5 · The two genuine gaps

**(a) Failure *codes*, not free text.** The board groups failures by cause so one action clears a
class (26 × "סוג לא זוהה" is one click, not 26). That needs processors to return a small enumerated
code alongside the message. Today failure information ends up as prose. Proposed enum, matching what
the pipeline can actually distinguish:
`ocr` · `type` · `company` · `connection` · `timeout` · `duplicate` · `corrupt`,
each mapped to `fixable | type | terminal` so the UI knows whether re-running could plausibly help.
Where to put it: the processors already report success/failure to the sync layer (doc §52 — "the sync
layer calls ADVANCE(synced|failed) based on the processor's return"), so the code rides on that return
and is written wherever the failure reason is already recorded.

**(b) Claim age, for stuck detection.** "Stuck" = claimed into `in_progress` longer ago than the pipe's
`batch.timeout_min` — nothing is coming back for it. Drive gives a modified time on move; **gmail does
not expose when a label was added**, so claim time cannot be derived from the source for mail pipes.
Options, cheapest first:
1. record `claimed_at` in the table row at CLAIM time (the sync layer already writes at claim);
2. or a claim marker label carrying a coarse bucket (`…/בעיבוד-<hour>`), which is ugly but sourceful;
3. or accept a coarser signal for gmail: `in_progress` older than N× schedule with no table update.
Recommendation: **(1)** — it is one column, and the CLAIM step already writes.

Without (b) the board still works; it just cannot mark stuck items for gmail pipes, and the
"פריטים תקועים" banner would under-report. That is a real reduction in the guarantee this view is
meant to give, so it is worth the column.

## 6 · What the mock does that production must NOT copy

- The mock keeps items in memory and derives counts from them. Production must keep deriving state
  **from the source** (folder/label). The mock's item array is a stand-in for LIST, not a new store.
- The mock's background ticker advances items to simulate workers. Production has real workers.
- The mock enforces the legal-move table in the handler. Production should too — the UI already
  refuses illegal moves, but the server is the one that must not invent a claim no worker holds
  (`to_sync → in_progress` is reserved for CLAIM; see `INDOX-SYNC.md` §4).

## 7 · Suggested build order

1. **LIST route** (`GET /sync/items`) — unlocks the whole board read-only.
2. **ADVANCE/CLAIM route** (`POST /sync/items/move`) — unlocks retry / release / skip / re-sync.
3. **Registry live counts** folded into `GET /sync/registry` — unlocks the pipe cards.
4. **`fallback_type`** + `apply-fallback-type` — the single biggest reduction in operator toil.
5. **Failure codes** from processors — turns triage from per-item to per-cause.
6. **Registry CRUD + locations browse/create** — unlocks authoring pipes from the UI.
7. **`claimed_at`** — completes the stuck guarantee.

Steps 1–3 already make the current two-tab, read-only experience obsolete. 4–5 are where the operator
time actually goes. 6–7 make it self-service and trustworthy.
