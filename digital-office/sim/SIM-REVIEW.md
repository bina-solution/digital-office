# Platform simulation — deep review & roadmap to "perfect"

_State as of this pass. The simulation is `platform-sim.html` (one self-contained file, 10 real app
frontends on mocked backends). This doc is the standing assessment + prioritized next steps. It pairs
with `ALIGNMENT-CHANGELOG.md` (sim→live design port list) and `README.md` (architecture)._

---

## 1. Where it stands

**Structurally done and verified:**
- **10/10 apps embedded** with their real frontends, framed by the real console shell, fully offline.
- **Navigation:** 0 double-nav, 0 JS errors across every app (Playwright nav-QA).
- **Mock coverage is complete** — every endpoint each real frontend calls is served; writes are
  stateful (CRUD, tagging, mark-read, test/extraction runs, bot subscribers all persist in-memory and
  reflect on reload). Confirmed by a full per-app endpoint sweep.
- **Design is one system** — verified visually across all 15 panels of the generated UI-map: one
  dark-green sidebar, one accent, one Lucide-style stroke icon pack (no emoji-as-icons), one type
  stack, consistent card/topbar/RTL treatment. Business identity is consistent everywhere
  (בינה פתרונות בע״מ · ת.פ 514789234 · person127@example.com).

**Alignment layer (`align.js`, sim-only, tracked for live port):** canonical light-theme tokens +
icon pack, applied at runtime, editing no real source. Every change catalogued in the changelog.

**Consolidation so far:** shared mock harness (`window.__mock`/`__json`); 3 of 11 mocks migrated.

The simulation is already a high-fidelity, fully-navigable, offline 1:1 of the platform. What remains
is about **depth of realism** and **finishing the consolidation**, not basic function.

---

## 2. The one big lever — a coherent "running business" data spine (P1)

Today each mock is internally stateful but **independent**: mailview's inbox, INDOX's documents,
my-docs' invoices, drive's files, and notifications' feed each tell their own story with their own
entities. The business _identity_ is shared, but the business _events_ are not linked.

A perfect business simulation is one narrative seen from every app:

> An email from **ישראל קרטון בע״מ** arrives in **mail** → **INDOX** ingests + extracts it (invoice
> #20458, ₪3,450) → it becomes a document in **my-docs** → the source PDF lands in **drive** → a
> **notification** fires → the run shows on the **any-concurrency** timeline.

The pieces already exist in isolation (mail message #20458 already references INDOX; INDOX already has
extraction runs; my-docs already has invoices). **Unifying them behind one seed dataset** — a shared
`business.js` module of companies, documents, and events that every mock reads from — is the single
highest-value step toward "perfect." It turns 10 convincing screens into one convincing company.

- **Effort:** medium-high (define the canonical entities; point each mock's seed at them; keep each
  mock's endpoint shapes unchanged so no UI regresses).
- **Risk:** medium — do it mock-by-mock behind the shared harness, QA each.
- **Payoff:** the highest. This is what makes the demo feel _alive and real_ rather than _mocked_.

---

## 3. Remaining functional gaps (P2)

| Gap | App | State | Recommendation |
|---|---|---|---|
| ~~Cloud-connections drawer dead (`providers:[]`, add no-op)~~ | localdrive | **FIXED this pass** — real providers + stateful connect + OAuth via window.open hook | done |
| External OAuth "Connect" opens a blank tab | connections | `oauth/{id}/start` is a real `window.open`, unhandled | Apply the same `window.open` hook pattern used in localdrive: recognize the marker, provision the credential, show an in-frame "connected" state. Low-med effort. |
| Cleanup buttons always 403 "disabled" | machine | Faithful to the real default (`MACHINE_CLEANUP_ALLOWED_ACTIONS` empty) | Optional: add a sim-only "demo mode" that lets one prune succeed and shows freed space tick down. Only if you want to demo a happy-path cleanup. |
| Downloaded invoice PDF is Latin-only | my-docs | The generated PDF uses a Latin core font; Hebrew fields don't render in the PDF itself (they do in the app UI) | Embed a Hebrew TrueType subset in the generated PDF, or render the preview as the existing SVG invoice instead of a PDF. Med effort, cosmetic. |

---

## 4. Depth-of-realism opportunities (P3)

- **More live motion.** Some apps already "breathe" (concurrency spans reshuffle each poll, machine
  metrics tick, INDOX runs advance). Extend it: a new mail arriving every N seconds, a notification
  appearing, an INDOX doc moving from "processing"→"done". Ties directly into the P1 data spine — one
  event generator drives motion in every app at once.
- **Cross-app deep-links.** mail's "open in drive", INDOX's "view source document", my-docs'
  "open original" — make these actually jump to the right app+item in the console (the console already
  routes by `#/m/<id>`; extend to `#/m/<id>/<deep-target>`).
- **Empty/error/loading states.** The sim always shows the happy, populated state. A few seeded
  edge cases (an empty repo, a failed sync, a disconnected bot) make it feel real and demo the UI's
  full range. INDOX and wadmin already model some of this; spread it.

---

## 5. Consolidation & cleanup remainder (P3)

- **Finish the mock-harness migration** — 8 of 11 mocks still hand-roll `window.fetch`
  (mailview, notifications, connections, my-docs, incoming, feature-validation, wadmin, localdrive).
  Migrate incrementally to `window.__mock`, QA each. Pure internal DRY, no user-visible change — do it
  opportunistically, never in a risky sweep.
- **Icon pack completeness** — semantic glyphs (→ ✓ ✕ ⚠ ☰ ↗ ↻ …) are deliberately left as text. If we
  want _total_ pack consistency, map the affordance glyphs (hamburger, chevrons, external-link) too.
  Low value, low risk.
- **Token naming in real source** — `any-concurrency` uses `--r` where every other app uses
  `--radius`; a few dark-theme neutrals still drift. Documented in the changelog for the live port; no
  runtime override needed.

---

## 6. Porting readiness (for the live-implementation phase)

`ALIGNMENT-CHANGELOG.md` is the bridge: every sim-only design change is written as a concrete source
edit (which file, which glyph/token, what to change it to). When we implement for real, that file is
the work-list. The mock/data changes in this review are **sim-only by nature** (the live platform has
real backends) and do **not** port — they exist to make the offline demo complete.

---

## 7. Suggested order

1. **P1 — business data spine** (`business.js` seed shared by all mocks). Biggest realism jump.
2. **P3 — event generator on top of the spine** (live motion everywhere from one source).
3. **P2 — connections OAuth hook** + **my-docs Hebrew PDF** (finish the last dead/rough edges).
4. **P3 — mock-harness migration** + **cross-app deep-links** (polish, opportunistic).
5. **Then** the live-implementation pass, driven by `ALIGNMENT-CHANGELOG.md`.

_Regenerate the UI-map any time with `python3 sim/ui-map.py` (offline)._
