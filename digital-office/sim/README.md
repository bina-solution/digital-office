# Single-file platform simulator — `platform-sim.html`

The **real** platform UI, packed into one self-contained HTML file with a **mocked backend**.
No running services, no network: each app's actual frontend is embedded verbatim and an injected
`fetch`/XHR mock serves its API from in-memory data.

## Architecture
- **Shell** = the real `development/console` app (nav from the real `modules.yaml`).
- **Apps** = each real frontend, base64-embedded, loaded into the console iframe via **srcdoc**
  (real parent origin, so localStorage / `location.hash` / `new URL` work) with an injected
  `<base href="about:srcdoc">` so the app's own hash/relative links resolve in-document.
- **Business spine** = `sim/business.js` (`window.__biz`), injected before each mock. One canonical
  "running business" seed — the incoming supplier documents (invoice/receipt/bill, with supplier,
  number, amount, status) shared across apps so **mail, INDOX and notifications tell ONE story**: the
  electric bill mail shows as "נכשל" (חברת חשמל, 44521) is the same document notifications alerts about
  AND the same one INDOX lists as `EXTRACTION_FAILED`. Each mock projects its own response shape from
  the shared entities (`__biz.mailLabel/statusIndox/kindHeOne/...`); the spine holds data, not formats.
  my-docs (outgoing invoices) joins the spine in a later increment.
- **Mocks** = `sim/mocks/<id>.js`, injected as an early `<head>` script per app (patch fetch/XHR).
- **Shared mock harness** (`MOCK_PRELUDE` in `build.mjs`, injected before each mock): one
  implementation of the fetch save/replace/Response dance. A mock calls
  `window.__mock(routes, fallback)` — `routes = [[RegExp|fn(u), handler(url,opts,match)], …]`, a
  handler may return a plain object (auto-JSON), a `Response`, or a Promise; `fallback(u,opts)`
  serves unmatched calls or returns null to defer to the real fetch. `window.__json(obj,status,type)`
  builds the Response. **Migrated so far:** `console`, `any-concurrency`, `machine`. The other 8 mocks
  still hand-roll their fetch wrapper and can be migrated incrementally (each QA'd on its own).
- **Overlay layer** = `sim/overlay/{tokens,icons,brand}.js`, injected **after** each mock (was the
  single `align.js`). Sim-only runtime normalization — design tokens, one icon pack, brand + version:
  one canonical light-theme token set (palette + type stack, scoped to `prefers-color-scheme:light`)
  and one Lucide-style icon pack replacing emoji-as-icons. Edits nothing in real source; every change
  is catalogued in **`ALIGNMENT-CHANGELOG.md`** as a porting spec for the live frontends.
- **Shims** (in `build.mjs` `STORAGE_SHIM`): localStorage/sessionStorage fallback, a `URL`-constructor
  fallback, `pushState/replaceState` error-swallow, a hash-nav click fallback, and an
  `<img>/<iframe>/<embed>` `src` router that sends app-API resource loads through the mocked fetch
  (native resource loads a fetch monkey-patch alone can't intercept — PDF preview, OCR/draw images, QR).

## The sim-owned fork — edit it, NOT the live app
ONE app still lives as a fork under `sim/apps/`, seeded byte-identical to the platform build so the
simulation could take it past what the live app did, without touching it:

| App | Fork | Kind |
|---|---|---|
| INDOX (`incoming`) | `sim/apps/indox/` | React/Vite SPA, compiled by `build.mjs` on demand |

Editing `apps/indox/app/webapp/` will NOT change the simulation — `build.mjs` reads the fork. Every
fork change is catalogued in `ALIGNMENT-CHANGELOG.md` as a porting spec.

**The drive and the mail are no longer forks.** Each fork (`sim/apps/localdrive/`, `sim/apps/mailview/`)
was ported into its live app wholesale, and the live app then went further — until the fork was the
older of the two and the simulation's screen was not the one anyone is served (2026-10-09: the drive
fork's phone layout still had the fault the live app had fixed, and its storage meter read a field no
adapter sends; the mail fork had no tag rules, no mailbox settings, no guided connect). The simulation
now embeds the live frontends themselves — `apps/drive/static/` behind `sim/mocks/localdrive.js`,
`apps/mail/mailview/static/` behind `sim/mocks/mailview.js` — each over a mock that answers what the
live SERVICE answers (`apps/drive/app.py`; `apps/mail/mailview/app.py` and the mail service behind it),
refusals included. So an edit to the live drive or mail IS an edit to the simulation's, and a fault the
live screen has is one the simulation's flows and map can find: embedding the mail found seven of its
own (among them a drawer left open over the screen a phone had just chosen, and a save the service
refused after the person had agreed to it) and one of the office's side menu (a brand line cut at
its beginning). A fork is retired the same way once its live app has passed it.

One thing a page framed from a file cannot do is change its address, and the mail keeps each screen at
one: where the live app re-reads itself from the address (after switching the active account), the
simulation lands on the inbox instead of staying where it was.

## Build
```bash
# build.mjs compiles the INDOX fork automatically whenever its src is newer than its dist-sim, so one
# command does everything — INCLUDING installing the fork's node_modules if they are missing or were
# installed on the other OS (see "Windows ↔ WSL" below). Nothing to set up by hand.
cd digital-office && node sim/build.mjs           # → digital-office/platform-sim.html
#   The build FAILS if any app does not embed, rather than shipping a grey placeholder in its place
#   (set BBOX_ALLOW_PARTIAL=1 if a partial file is genuinely what you want).
#   Inside the srcdoc iframe the app routes with MemoryRouter; BrowserRouter cannot work there —
#   see sim/apps/indox/src/main.tsx (an empty #root with no error is that bug's signature).
```
Open `platform-sim.html` in any browser — fully offline.

### Windows ↔ WSL: the fork's `node_modules` belongs to ONE platform

`sim/apps/indox/node_modules` is gitignored and platform-specific: vite's rollup and esbuild ship
their native binary as an *optional*, per-OS package (`@rollup/rollup-linux-x64-gnu`,
`@esbuild/win32-x64`, …), and npm installs only the one for the machine that ran the install —
then, per a long-standing npm bug ([npm/cli#4828](https://github.com/npm/cli/issues/4828)), never
adds the other. A tree installed on Windows and then built under WSL died with

```
Error: Cannot find module @rollup/rollup-linux-x64-gnu
```

which says nothing about the actual cause and left the sim unbuildable on that machine. `build.mjs`
now detects the mismatch before compiling — it checks `@rollup/`/`@esbuild/` for a build matching
`process.platform`-`process.arch` — prints what is missing, and repairs it with `npm ci` (the
committed lockfile carries every platform's entry). Switching back to the other OS repairs it back,
at the cost of one reinstall. If the install itself fails, the error names the exact command to run.

## Verify
```bash
node sim/verify-sim.mjs                  # which apps are real vs placeholder in a built file, + md5
python3 sim/flow-qa.py                   # every flow driven to its end, effect asserted (desktop)
python3 sim/flow-qa.py --mobile          # the same at 390x844 — drawers, overlays, touch targets
python3 sim/flow-qa.py scroll layout     # layout invariants only (one scroll axis, nothing spills)
python3 sim/ui-map.py --all              # 47 panels x mobile/tablet/desktop
```
`flow-qa.py` exits non-zero on any failed flow or any JS error, so it can gate CI.

## Coverage
All 10 apps embedded with real UI on mock data: my-docs, localdrive, mailview,
any-concurrency, notifications(alerts), machine, connections, feature-validation, incoming(INDOX),
wadmin(whatsapp). Native resource loads (`<img>/<iframe>/<embed>` src at an app API) are routed
through the mocked fetch by the shim, so PDF preview / OCR / draw / QR images render from mock data.

Mock coverage is complete for every app: each mock serves every endpoint its real frontend calls, and
writes are stateful (CRUD / tagging / mark-read / test+extraction runs / bot subscribers persist
in-memory and reflect on reload). The localdrive cloud-connections drawer is fully live too — the
`providers` list is populated and the connect flow (OAuth via a `window.open` hook, or a key form)
provisions a stateful connection. Faithful-by-design stubs: `machine` cleanup returns the real
"disabled" 403; the `connections` app's external OAuth "Connect" opens a real new tab (no offline
consent). See `ui-map.py` for the offline UI-map generator and `ALIGNMENT-CHANGELOG.md` for sim-only
design changes staged to port to the live frontends.
