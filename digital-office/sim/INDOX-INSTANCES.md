# INDOX instances — plan (sim-only)

> **STATUS: shipped in v0.23.0.** What actually landed differs from the plan below in four ways, all
> for the better — recorded here so the doc doesn't lie:
> 1. **No overlay/runtime routing hack was needed.** The plan assumed INDOX's source was off-limits and
>    budgeted a `pushState`+`popstate` trick with a fallback. Instead INDOX was **forked into the sim**
>    (`sim/apps/indox/`), so the screens were removed at the source — cleaner, no desync risk.
> 2. **Settings are per-instance too.** The plan scoped an instance to table + registry + settings keys;
>    the shipped version also gives each instance its own **companies table, tag-rules table and
>    extraction queries**.
> 3. **Kafka was deleted, not preserved.** W4 planned to keep the Kafka tail reachable; it has since
>    been removed entirely as unused.
> 4. **The open question is resolved** — `/repos/new` (RepoCreatePage) was **removed**, not redirected:
>    it was orphaned once the repo list went, and it couldn't select sync registries.
>
> A latent bug also surfaced during the work: react-router v6 renders **null** under `about:srcdoc`
> (basename normalisation vs the opaque `srcdoc` pathname), so any fresh INDOX build produced an empty
> page. Fixed with MemoryRouter. See `ALIGNMENT-CHANGELOG.md` C8 for the shipped record.

Two goals, one underlying model change:

1. **Kill the two dead-end screens.** Clicking INDOX → **מסמכים** must land on the *table*, not on
   "pick a מאגר" → "open the table".
2. **Make INDOX multi-instance**, using the same connected-instances pattern Drive / Mail / Chat already
   use (`CONNECTED-INSTANCES.md`): an instance = a fully duplicated INDOX (own table, own settings, own
   sync registries), one active at a time, switched from the top service bar, new ones creatable —
   so INDOX can run for several companies side by side.

---

## 0 · The hard constraint that shapes everything

| | |
|---|---|
| App id | `incoming` (build.mjs `APPS`) |
| Real source | `development/incoming-documents/app/webapp/src/**` — **off-limits** |
| What the sim embeds | `…/dist-sim/index.html` — a **compiled, single-file React bundle** built by the tracked `vite.config.sim.ts`. `dist-sim` itself is **untracked** (a build artifact). |
| Router | `react-router-dom` **v6.27**, **`BrowserRouter`** (not hash) |

**Consequence:** we cannot change a single line of INDOX's UI. Every change lands in exactly two
places — `sim/mocks/incoming.js` (what the API says) and a new `sim/overlay/indox.js` (runtime
behaviour) — plus `switcher.js` for the top-bar chip. This is the same envelope Drive/Mail/Chat use.

## 1 · Current routes (what the compiled app actually does)

```
/                        DashboardPage       ← console lands here
/repos                   RepoListPage        ← screen 1 "select db"   ✂ to remove from the path
/repos/:repo             RepoDetailPage      ← screen 2 "open table"  ✂ to remove from the path
/repos/:repo/documents   DocumentBrowserPage ← THE TABLE (the destination)
/repos/:repo/documents/:id  DocumentDetailPage
/repos/new               RepoCreatePage      (backend/columns only — no registry step)
/sync  /settings  /tests  /extraction
```
Nav tab **מסמכים** (`App.tsx` `SECTIONS`) points at `/repos`. That single link is the whole problem.

## 2 · The good news — the real model already has both concepts

We are **not inventing** a data model; we're surfacing one the real app already has.

- **`RepoConfig`** (`api.ts:34`) — `name`, `backend: 'gsheet'|'supabase'`, `primary_key`, `columns[]`,
  `supabase.table` / `gsheet.sheet_name`, `active`, `poll_interval_seconds`. **A repo *is* an INDOX
  instance** — own final table, own columns, own settings. Multi-repo is already supported end to end
  (`GET/POST/PATCH/DELETE /repos`).
- **`SyncRegistryEntry`** (`api.ts:181`) — `name`, `source: 'drive'|'gmail'`, `type_hint`, `batch{…}`,
  and the two shapes the user described verbatim:
  - `labels: {to_sync, in_progress, synced, failed}` + `claim_label` → **gmail tags**
  - `pairs: [{from, to}]` + `dest_folder` → **drive folders**

So "select the connection and its tags/folders to sync" = **authoring a `SyncRegistryEntry`**. The port
story is therefore strong: we're building UI over an existing contract, not fictional endpoints.

## 3 · What's actually wrong in the mock today

`sim/mocks/incoming.js` holds **one** repo and makes everything else **global**:

| Now | Needed |
|---|---|
| `REPOS = [ …one… ]` (:106) | N instances |
| `DOCS = [ … ]` (:144) — global | **per instance** (different table per company) |
| `REGISTRY = [ … ]` (:327) — global | **per instance** |
| `SETTINGS` (:503) — global | **per instance** |

`/sync/registry`, `/config/settings` and `/sync/status` take **no repo param** — they must resolve
against the **active** instance. That's what makes an instance feel "fully duplicated" rather than a
repo picker.

---

## 4 · Work items

### W1 — Restructure the mock to per-instance state
**File:** `sim/mocks/incoming.js`
```js
INSTANCES = [{ id, label, company, color, status, repo: RepoConfig,
               docs: [...], registry: [...], settings: {...} }]
ACTIVE = 'indox-sabach'
```
Every handler resolves `inst = byId(:repo param) || byId(ACTIVE)`. Seed **two** instances from the
companies already in the mock (`סבח סוכנויות בע״מ`, `אגן שיווק`) with genuinely different tables,
column sets, registries and row counts — otherwise switching proves nothing.
> Reading of "for now with only 1 active": exactly **one active at a time** (two exist, one is live).
> If you meant "ship one instance only", it's a one-line seed change.

### W2 — Instance API in the Drive/Mail/Chat shape
**File:** `sim/mocks/incoming.js`
Add `api/accounts`, `api/account/select`, `api/account/add` (+ `api/account/remove`) projecting
`INSTANCES`. This keeps `switcher.js` generic instead of teaching it `/repos`. `select` flips `ACTIVE`;
all no-param endpoints follow it.

### W3 — Skip the two screens
**File:** new `sim/overlay/indox.js`
- **Intercept** capture-phase clicks on the `מסמכים` nav link → navigate to `/repos/<ACTIVE>/documents`.
- **Redirect** anyone landing on `/repos` or `/repos/:repo` (back button, deep link) to the same place,
  so the removed screens are unreachable rather than merely unlinked.

**Mechanism + risk (the one genuinely uncertain bit).** v6's `BrowserRouter` listens to `popstate`, so
`history.pushState(...)` + `dispatchEvent(new PopStateEvent('popstate'))` drives it from outside. The
risk is v6's history package keeping an internal index in `history.state`; a raw `pushState(null, …)`
can desync it. **Fallback if that misbehaves:** let the click through to `/repos`, then have the overlay
synthesise a click on the active repo's own `<a href="…/documents">` that `RepoListPage` already
renders — React Router's *own* navigation, zero desync, at the cost of a one-frame flash. I'll verify
the clean path with Playwright first and fall back only if it actually breaks.

### W4 — Don't lose the RepoDetail information
`RepoDetailPage` is the only place showing backend, target table, columns and stats. Removing it from
the path must not delete that information: fold it into an **"פרטי המופע" panel** in the switcher
dropdown, exactly like Mail's health panel (`switcher.js` already has `healthPanel()` to model on).

### W5 — INDOX branch in the shared switcher
**File:** `sim/overlay/switcher.js`
Add `isIndox` alongside `isDrive/isMail/isChat` (detect the INDOX shell: `.tabstrip` + brand
`מסמכים נכנסים`). It joins the existing `acctApi` group (same `api/accounts` contract as Mail/Chat).
Post-switch: re-navigate to the new instance's documents route and refetch via `window.__indoxReload`
(mirroring `window.__chatReload`). Chip shows company label + color + status dot.

### W6 — Create-instance flow **with sync-registry selection**
**File:** `sim/overlay/switcher.js` (own modal — `/repos/new` can't be extended, it's compiled)
A 4-step flow in the existing modal frame (Esc + focus-trap already implemented):
1. **Identity** — instance name, company, color.
2. **Target table** — backend `supabase`/`gsheet` + table/sheet name + column preset → the "final INDOX table".
3. **Sync registries** — the core step. Add N entries; each: pick a **connection** from the accounts
   Drive/Mail already expose, then
   - gmail → **tag/label set** (`labels` + `claim_label`)
   - drive → **folder pairs** (`pairs[{from,to}]` + `dest_folder`)
   plus `type_hint` and `batch.schedule_min`.
4. **Review → create** — `POST api/account/add` provisions a full instance (repo + empty table + registry).

**Cross-app dependency:** step 3 must list the *same* connections Drive/Mail show. Mocks are per-iframe,
so the connection catalog belongs in the shared spine `sim/business.js` (already the canonical entity
source) rather than being duplicated a third time.

### W7 — Settings + Sync pages follow the active instance
No app change needed — once W1 lands, `/config/settings`, `/sync/registry` and `/sync/status` resolve
per instance, so `SettingsPage` and `SyncStatePage` become per-instance for free. Verify `/sync` shows
the active instance's registry entries only.

### W8 — Responsive + a11y parity
`sim/overlay/responsive.js` currently handles INDOX only via the **generic** mobile fallback. With a new
switcher chip + a 4-step create modal, give it the same treatment Mail/Chat got: full-width modal steps,
44px targets, no horizontal overflow at 390px. Switcher ARIA already exists and is inherited.

### W9 — Bookkeeping (standing rule)
Bump `DO_VERSION` in `overlay/brand.js`; add **C8 · INDOX instances** to `ALIGNMENT-CHANGELOG.md`
(WHAT/WHERE/**PORT**); register `indox.js` in `build.mjs` `OVERLAY_FILES` — **after** `switcher.js`.

---

## 5 · Verification (before I call it done)

| Check | Method |
|---|---|
| מסמכים → table in **one** click, from every tab | Playwright, count navigations |
| `/repos` + `/repos/:repo` unreachable (back button too) | Playwright history walk |
| Switching instance changes table rows, columns, settings **and** registry | assert row counts + table name differ |
| Create flow provisions an instance that then appears in the switcher | end-to-end run |
| No React Router desync (no console errors/warnings) | console capture |
| 0 horizontal overflow at 390px; desktop 1440 unchanged | existing mobile harness |
| Other 9 apps untouched | full ui-map diff |

## 6 · Port path (why this is safe to build)

Everything above maps onto contracts the real backend already has: multi-repo CRUD exists, and
`sync_registry` is a real settings key. The genuine source work to ship it for real is
(a) point the **מסמכים** tab at the active repo's documents route and demote `RepoListPage` to a
switcher, (b) add a registry-authoring step to `RepoCreatePage`, (c) scope `/config/settings` +
`/sync/registry` by repo. No new data model.

## 7 · Open question (does not block starting)

`RepoCreatePage` currently provisions the backend table. Our W6 modal supersedes it. Leave the route
reachable as-is, or redirect it into the new flow? **Recommendation: redirect** — one creation path,
no drift. Say the word if you'd rather keep both.
