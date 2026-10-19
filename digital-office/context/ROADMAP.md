# Digital Office — functional single-file platform mockup: ROADMAP

Goal: evolve `digital-office/platform-mockup.html` from 95 static screens into a **fully functional,
self-contained platform** driven by a central mock-data engine that simulates a running Israeli
business — full UI skin, live data, hover, drag-and-drop, moving features — while pushing fidelity to
100% 1:1 with the real platform ui-map.

Single file. No external runtime deps (Google-fonts link degrades to system fonts).

## Architecture
- **Engine** (`window.DO`, in the shell `<script>`): central reactive state (business, customers,
  items, documents, mail, drive, INDOX repos+pipeline+syncs, notifications, jobs, metrics, clock) +
  get/set/subscribe + mutation actions + a `tick()` simulation loop for "live" movement.
- **Interaction layer**: event-delegated `data-*` hooks — `data-open`/`data-close` (modals/drawers),
  `data-tab`, `data-action` (mutations), `data-drag`/`data-drop`, `data-bind`/`data-list` (render).
- **Screens** stay as fragments; they get progressively bound to the engine (static → live).
- **Router**: `go(id)` shows a screen then `DO.hydrate(scr)` binds + wires it.

## North star
A **self-contained platform simulator** (front-end/product simulator) — the whole platform UI +
behavior driven by the standalone `DO` mock engine, **decoupled from the production code**, in one
file, at **100% simulation coverage**. Keep the engine's data shapes + action names contract-accurate
to the real API so the modeling transfers back to the real build later.

## Verification (the acceptance test — run every iteration)
- **V1 · Visual 1:1 (main gate)** — render the simulator ui-map, pixel-diff each view vs the real
  capture (`verify/ui_map_diff.py`). Target: every view at/near the ~5–6% content floor. Artifact:
  real|mock|diff montage + per-view scores.
- **V2 · Functional 1:1** — canonical flows per app run by Playwright on BOTH the real platform and the
  simulator, recorded as `flow.webm` + checkpoint screenshots, composed side-by-side (ffmpeg) and
  checkpoint-diffed. Mock-side now; real-side when the stack is healthy.
- **V3 · Coverage ledger** — every `ui-inventory` view × every interaction checked present+functional.
- **Loop exits** when V1 (all views) + V2 (all flows) + V3 pass.

## Iterations (each = one loop turn; check off when committed)
- [x] **I1 — Foundation**: engine + reactive store + tick loop + interaction primitives
  (modal/toast/tabs/drag CSS+JS) in the shell; live dashboard (bound stats, ticking clock, real
  live-pill); ROADMAP. Assemble + render-verify + commit.
- [x] **I2 — my-docs live**: docs/customers/items rendered from the store; "+ מסמך חדש" opens a real
  inline modal that creates a document → table + counters + toast update; row drawers open live.
- [x] **I3 — INDOX live**: repos/documents grids from store; the incoming-documents **pipeline moves**
  (NEEDS_REVIEW→IN_PROGRESS→COMPLETED) on tick; new docs arrive; dashboard counters + extraction score
  derive live.
- [x] **I4 — drive drag-and-drop**: files/folders from store; drag files into folders (real move),
  upload sim, folder-select filters the panel; empty-state matches capture; colored sync chips.
- [x] **I5 — mail live**: inbox (14 seeded) from store; new mail arrives on tick; openMail/readAll.
- [x] **I6 — dashboards & infra**: any-concurrency spans advancing, machine metrics animating + live
  containers, kabil lanes, bot stats; notifications arrive live.
- [x] **I7 — hover/polish + command palette (Ctrl-K) working** (fuzzy-jump to any screen).
- [x] **I8 — fidelity pass**: overlay-scrim cascade → V1 mean 10.47%; only 2 third-party/asset screens left.
- [ ] **I9 — remaining long-tail fidelity** (connections-qr dialog; authentik photo is a hard limit);
  real-side V2 capture after `./bbox run`; final QA.

## Status log (newest first)
- FIDELITY CASCADE — V1 mean 14.23% → **10.47%** (median 6.7%). Root-caused the worst cluster: real
  modal/drawer overlays dim the background to a **dark green scrim** (~`rgba(18,32,25,.35–.42)`) but the
  mock used a near-white scrim. Fixed across mail readers+tagpicker (tagpicker 78%→3.7%), mydocs
  new-doc/customer/item modals, and the 3 mydocs drawers — the whole overlay family dropped to the floor.
- I4–I7 landed via the 4-agent parallel push + engine foundation: drive drag-move/upload/trash live,
  mail inbox (14 seeded) live with openMail/readAll, machine containers + any-concurrency spans breathing,
  notifications stream in live (empty at load to match capture), Ctrl-K command palette, I7 hover/polish.
- Known V1 limits (2 screens, both third-party/asset): **authentik-login 77.6%** — real uses a proprietary
  snowy-road stock PHOTO; mock keeps a generic abstract background (won't/shouldn't reproduce the photo).
  **connections-state-qr 76.4%** — QR-dialog internal layout still off after rebuild; candidate for another pass.
- Everything else is at/near the ~6–7% content floor. V2 flows re-recorded on the fully-wired build.
- V2 harness BUILT (mock side): `verify/flow_mock.py` drives 5 canonical flows on the simulator
  (mydocs-create-invoice, indox-pipeline-moves, drive-drag-move, mail-read, command-palette), recording a
  webm + checkpoint screenshots each (`verify/out/flows/`, gitignored). Verified functionally — e.g. the
  mydocs flow checkpoint shows the freshly-created INV row + "המסמך נשמר" toast. `verify/compose_flows.py`
  stacks real|mock side-by-side (webm/vp9; bundled ffmpeg is libvpx-only) once the real side exists;
  `verify/flow_real.py` is the real-platform counterpart (run after `./bbox run`; selectors to confirm live).
- Engine foundation for I4–I7 committed: `drive` (folders/files/trash + drag-move/upload/trash actions),
  `infra` (machine metrics + any-concurrency spans + kabil lanes + bot, all breathing on tick), `mail`
  actions (openMail/readAll), and a working **Ctrl-K command palette** (fuzzy jump to any screen; also opens
  on header-search click). Binding contract written: `context/ENGINE-CONTRACT.md`.
- Parallel push IN FLIGHT: 4 subagents wiring disjoint fragment sets to the engine simultaneously —
  A=drive, B=mail, C=infra/bot, D=console/connections/notifications — plus fidelity fixes on the worst
  screens (connections-state-qr, mail-state-tagpicker, kabil-state-drawer, drive-state-nopreview, mail
  readers). Orchestrator assembles + runs V1 + commits when they return.
- I3 DONE — INDOX wired to the engine: `indox.incoming` documents flow through the real status enum
  (NEEDS_REVIEW→IN_PROGRESS→COMPLETED) on each tick, new docs land in the repo periodically. indox-repo-docs
  table + indox-repos counts + indox-root dashboard (total/completed/review/failed/companies/score + pipeline
  bar) all derive live via `ix.*` computed vals. Verified in Chromium (5→6 docs, completed 0→4, score 0%→67%).
  V1 no-regression (mean 14.25→14.23; INDOX screens 5.6–10.8%, near floor). NOTE build step: edit `frag/*` +
  `tooling/index.base.html`, then **`cp index.base.html index.html`** before `node assemble.js` (assembler reads
  index.html).
- V1 gate built (verify/ui_map_diff.py): baseline mean 14.25%%, median 7.16%% across 95 screens (worst = new subagent-authored state screens; will fix via real frontend code). Spawned a subagent to map the real app frontends → context/REAL-FRONTEND-MAP.md.
- I2 DONE — my-docs wired to the engine: documents/customers/items tables render from DO via data-list; "+ מסמך/לקוח/פריט" open real inline modals that mutate the store (verified docs 5→6 + toast, no errors); rows get context menus.
- I1 DONE — engine (window.DO): reactive store, live tick (clock/msgs/INDOX pipeline/mail/jobs), actions (addDocument/Customer/Item), interaction layer (modal/drawer/toast/menu/tabs/drag delegation), hydration (data-bind/data-list). Dashboard live: bound stats, ticking clock+live pill, real-time activity feed, business summary. Verified in Chromium (msgs/clock/feed advance; addDocument mutates store).
- I1 started.
