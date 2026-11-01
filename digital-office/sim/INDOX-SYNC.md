# INDOX · one sync surface — design

Merge **סנכרון** (live state, read-only) and **הגדרות → תצורת מקורות הסנכרון** (config, read-only) into a
single **סנכרון** page that is the complete sync-management surface: author the pipes, watch them run,
move stuck items, and run them by hand.

---

## 1 · Why the split is wrong today

The same `sync_registry` is rendered **twice**, both read-only, in two different tabs:

| Tab | Shows | Missing |
|---|---|---|
| סנכרון | live 4-state counts per sync | what the sync actually *is* |
| הגדרות | name, source, batch, `pairs` as raw JSON, `labels` as key/value dump | whether it's running, or anything actionable |

So answering "is `drive-orders` healthy, and what folder does it watch?" needs two tabs, and *changing*
it needs neither — there is no edit path at all. The config half is also the less honest half: folder
pairs print as `{"from":"Incoming/Orders","to":"Archive/Orders"}`.

**A found defect this rebuild must fix:** `registry` became per-instance in v0.23.0 but `SYNC_COUNTS`
stayed global. Verified: switching to אגן שיווק lists **סבח's** three syncs as its live state. The sync
page currently *lies* for every instance but the first.

## 2 · The object the page is really about

A registry entry is a **pipe**:

```
[ connection ]──(location: gmail labels │ drive folder pairs)──▶[ INDOX instance's table ]
                         schedule + batch
```

Config and state are two halves of one thing, so the page is **one card per pipe** carrying both — not
a config list beside a state list. Everything else follows from that.

## 3 · Items are the source of truth (not counts)

Today the mock holds `{to_sync, in_progress, synced, failed}` integers that drift randomly. You cannot
build "move items between states" on integers — there is nothing to move, and a moved count would
contradict the next random tick.

So each pipe owns a **queue of real items**:

```js
{ id, title, kind, size, state, updated_at, error?, doc_id? }
```

Counts are **derived** (`items.filter(state).length`). One source of truth means a move updates the bar
instantly and truthfully, the drill-down shows the actual things, and a manual run is a visible state
transition rather than a number jump.

## 4 · State machine — and which moves are legal

```
        ┌──────────── retry / re-queue ────────────┐
        ▼                                          │
   to_sync ──run──▶ in_progress ──ok──▶ synced ────┘
                          │
                          └──error──▶ failed ──retry──▶ to_sync
```

| From → To | Meaning | Offered as |
|---|---|---|
| `failed` → `to_sync` | retry after fixing the cause | **נסה שוב** (the common one) |
| `in_progress` → `to_sync` | release a stuck claim (worker died holding it) | **שחרר** |
| `synced` → `to_sync` | re-ingest (extraction changed) | **סנכרן מחדש** |
| `to_sync` → `synced` | skip — accept it without processing | **דלג** |
| anything → `failed` | — | not offered; failure is an outcome, not a choice |

`to_sync → in_progress` is deliberately **not** a manual move: that transition is what *running* means,
so it belongs to the run button. Letting a user hand-place an item into `in_progress` would invent a
claim no worker holds — exactly the stuck state the `שחרר` move exists to clean up.

## 5 · The page

```
┌ סנכרון · [סבח סוכנויות ▾ incoming_documents]        [● חי] [השהה] [▶ הרץ הכל] ┐
│                                                                               │
│  לסנכרון 6      בתהליך 2      סונכרן 337      נכשל 3     ← click = filter     │
├───────────────────────────────────────────────────────────────────────────────┤
│  [+ מקור סנכרון חדש]                                                          │
│                                                                               │
│  ╭ ✉ gmail-invoices    Gmail · person134@example.com   INVOICE   [●] ⋯ ╮        │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░  2 לסנכרון · 1 בתהליך · 184 סונכרן · 1 נכשל       │        │
│  │ תוויות  INDOX/לסנכרון → INDOX/סונכרן  · נכשל: INDOX/נכשל           │        │
│  │ כל 5 דק׳ · take 20 · הרצה אחרונה לפני 3 דק׳                        │        │
│  │ [▶ הרץ עכשיו] [עריכה] [פריטים ▾]                                   │        │
│  ╰────────────────────────────────────────────────────────────────────╯        │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Instance chip in the header** — the registry is per-instance, and forgetting that is how you edit
  the wrong company's pipes. It names the active instance and its target table.
- **The 4-state bar is the primary control**, not decoration: each segment is clickable and opens the
  items drawer filtered to that state. Status → the things behind it in one click.
- **Enable toggle per pipe** — pausing one noisy source without deleting its config is the most common
  real operation, and today it is impossible.

**Items drawer** (per pipe, per state): a checkbox list — title, kind, age, error reason for failures —
with select-all and a **העבר ל…** bulk action offering only the legal targets from §4.

## 6 · The editor — connection first, then browse

The user's explicit requirement, and it is also the only order that can work: you cannot list the
folders/labels to pick from until you know **which account** you are picking them in.

**Step 1 · חיבור.** Provider-coloured cards from the platform's real connection catalog (`/connections`
— the same list Drive and Mail show, served from the shared spine). Choosing one fixes the *kind* of
location for step 2: a gmail connection means labels, a drive connection means folders.

**Step 2 · מה לסנכרן.** Browse the chosen connection's **actual** locations
(`/connections/:id/locations`), with item counts, and pick from them — plus **+ צור** to make a new one
inline (`POST` the same endpoint) without leaving the flow.
- gmail → pick the `to_sync` label, and optionally distinct `synced` / `failed` labels; a `claim_label`
  is derived so a worker can mark what it holds.
- drive → pick a **source** folder and an **archive** folder (`pairs[{from,to}]`); the archive may be
  created on the spot, which is the normal case for a new pipe.

**Step 3 · סוג ותזמון.** `type_hint`, `schedule_min`, `take`. Small on purpose — these have sane
defaults and are the least interesting decision.

The same editor serves **create and edit**, and it is the same component the instance-create flow uses
for its registry step — one implementation, so an instance's first pipe and its tenth are authored
identically.

## 7 · Endpoint contract (mock; shapes the real BFF can adopt)

```
GET    /connections                        → [{id, source:'gmail'|'drive', label, identity, color}]
GET    /connections/:id/locations          → {kind:'labels'|'folders', items:[{id,path,count}]}
POST   /connections/:id/locations {path}   → {item}                      create a label/folder
GET    /sync/registry                      → {registry:[…entry+live…]}   config AND state together
POST   /sync/registry {entry}              → {entry}
PATCH  /sync/registry/:name {patch}        → {entry}                     incl. {enabled:false}
DELETE /sync/registry/:name                → {success}
POST   /sync/registry/:name/run            → {claimed}                   to_sync → in_progress
POST   /sync/run                           → {claimed}                   every enabled pipe
GET    /sync/items?sync=&state=            → {items:[…]}
POST   /sync/items/move {sync, ids[], to}  → {moved}
GET    /sync/status                        → per-instance, derived from items
```

## 8 · How it integrates

- **Instances** — every pipe belongs to the active instance; switching companies swaps the whole board.
  Fixes the §1 defect by making counts derive from per-instance items.
- **Connections** — pipes reference the platform's Drive/Mail connections rather than re-declaring
  accounts, so INDOX consumes the same catalog the rest of the console shows.
- **The documents table** — `synced` is not a terminal number: an item that syncs becomes a row in the
  instance's table. Sync and מסמכים are two views of one pipeline, which is why the run button belongs
  here and the results belong there.
- **Settings** — loses its read-only registry section entirely and points at סנכרון, so there is exactly
  one place a pipe is described.

## 9 · Port notes

`sync_registry` is a real settings key, and `labels` / `pairs` are the real shapes — the editor writes
the same structure the live pipeline already consumes, so porting is UI plus four small endpoints
(locations browse/create, registry CRUD, run, item move). The one genuinely new backend concept is the
**item queue**: production infers state from gmail labels / drive folder membership, so `GET
/sync/items` maps to "list messages carrying label X" / "list files in folder Y", and a move maps to
relabel / move-file — not a new store.
