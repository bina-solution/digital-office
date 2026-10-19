# HANDOFF — building & verifying the המרכז mockup (session context)

## Goal
Reproduce the "המרכז / Business Center" platform (RTL Hebrew business suite) 1:1 as a single
navigable HTML mockup, and PROVE fidelity by rebuilding the product's ui-map from the mockup
and pixel-diffing it against the real screenshots.

## What exists
- Source of truth = the product's ui-map (a montage of 1440×900 screenshots, one per view).
- The real screenshots (54) are the project's `data/browser42/output/ui/*.png`, captured by
  `scripts/ui-coverage/capture.py` at viewport 1440×900 in a Linux Chromium.
- The montage is assembled by `scripts/ui-coverage/compose_map.py` (grouped by app section).
  Copies of both are in `reference/` for parity.

## Architecture of the mockup
- One self-contained HTML file. `index.base.html` holds the design system (CSS vars, shell, router,
  floating screen-navigator) with a `<!--TEMPLATES-->` marker.
- Every screen is a `<section class="screen" data-screen="ID">…full viewport…</section>` in `frag/ID.html`.
- `assemble.js` concatenates all frags into the marker → `dist.html` (the deliverable).
- `gen-core.js` generates the core המרכז frags (dashboard, apps, my-docs, INDOX root, mail, connections,
  notifications) using a shared sidebar/top-bar helper so the shell is identical everywhere.
- Router: sidebar links + in-screen tabs use `data-nav="ID"`; a floating "מפת מסכים" lists all screens.

## Verification loop
- `run.py` renders all 54 screens from dist.html at 1440×900 into `mine/screenshots-ui/`.
- `one.py <id> <basename> <tag>` renders ONE screen and writes a `[REAL | MINE | DIFF]` image; prints
  the % of pixels differing (threshold 28 on max channel abs-diff). Use this to iterate a single screen.
- `compose_map.py` rebuilds the ui-map from a chosen screenshot set (real vs mockup) → identical layout,
  so any difference is purely content.
- Diffs are red = differing pixels, blue = identical.

## LESSONS THAT MATTERED (pixel-fidelity, in impact order)
1. **Trust the diff, use a 2-channel overlay.** Put real in the RED channel and mine in GREEN:
   overlap = yellow, offsets show as red/green fringes. This is what exposed the biggest bug that a
   side-by-side and SSIM both hid.
2. **One global geometry bug dwarfs everything.** The dark sidebar was on the WRONG side: an inverted
   RTL flex `order` put it on the LEFT (x 0–229) while the real app has it on the RIGHT (x 1202–1439),
   shifting every screen ~238px. Fixing `order` (side must have the LOWER order so RTL flex-start=right)
   + matching the exact **238px** width took the mean pixel-diff from **30.9% → 8.3%**. Get global
   geometry right (sidebar side+width, top-bar height) before any per-screen polish.
3. **Match the environment's font, not the design's.** The product CSS font stack is
   `"Segoe UI", system-ui, -apple-system, "Noto Sans Hebrew", "Assistant", Arial, sans-serif`.
   The Linux capture rendered Hebrew as **Noto Sans Hebrew** — install it (`apt-get install fonts-noto-core`)
   and use that stack (NOT Heebo). The identical sidebar region then diffs only ~1.3% (the true font floor).
4. **Stat cards: label on TOP, big number BELOW** (verified from crops). Global rule:
   `.stat:not(.stat-big){display:flex;flex-direction:column-reverse;align-items:flex-end}`.
5. **Exclude mockup-only chrome from the diff render.** The floating nav button (#navBtn) isn't in the
   real product — hide it before the screenshot (`add_style_tag('#navBtn{display:none!important}')`),
   keep it in the deliverable.
6. **The pixel-diff floor is ~5–6%** on text-dense Hebrew screens: genuine anti-aliasing + live data the
   static mockup approximates. Screens with simple/static content (browser42, glitchtip, redis) sit ~3–4%.
   authentik-login is ~77% only because its background is a photo that can't be embedded.
7. **Parallelize per-screen with isolated renders.** Independent screens fan out cleanly when each has its
   own render+diff (`one.py` writes a unique `/tmp/dist_<tag>.html`), and the shared shell is no-touch.

## Current numbers
mean 7.18% | excl authentik-login photo 5.85% | median 5.99% | 45/54 under 8%. Per-screen in METRICS.md.
Worst remaining (all at content-density floor): incoming-documents dense tables ~9%, portainer-containers 9%,
authentik-admin 8%.

## PHASE 2 — the ~40 NEW screens (not yet built)
The project's `bbox ui-map` branch (`claude/local-setup-pm-9pm3yz`, a clean fast-forward on top of the
captured HEAD) enumerates ~40 new **state/modal/drawer/toast** views. Their only current reference is
`reference/localmap_view__new-screens.png` (a montage; tiles ~4× downscaled, fine text not legible).
New ids (from OCR of that montage), grouped:
- my-docs: new-doc-modal, customer-modal, item-modal, state-doc-drawer, state-customer-drawer,
  state-item-drawer, state-onboarding, state-toast, state-grid-menu
- drive: folder, file, state-menus, state-new-folder, state-preview, state-upload,
  state-connect-method, state-connect-verify, state-move, state-nopreview
- connections: state-expanded-all, state-audit-drawer, state-add-secret, state-qr, state-rotate
- machine: state-storage, state-grid-menu, state-chart-tip
- mailview: state-reader, state-tagpicker, state-toast
- notifications: state-toast, state-empty
- any-concurrency: state-drawer, state-tip
- console: state-apps, state-install-adv
- incoming-documents: repos-new, extraction-draw, extraction-doc

To build them pixel-perfect you need the full-res individual PNGs. Generate on a machine with Docker:
```bash
git merge --ff-only origin/claude/local-setup-pm-9pm3yz
bbox ui-map            # ensure it writes data/browser42/output/ui/*.png (not only the montage)
```
Then reproduce each as its base screen + overlay (modal/drawer/toast), add a `frag/<id>.html`, wire a
`data-nav` trigger, and re-run the verify loop. Most are overlays on bases already reproduced accurately.
