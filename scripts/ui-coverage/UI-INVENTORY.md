# Platform UI Inventory — the visible-coverage denominator

Authoritative catalogue of **every user-visible UI region** across all first-party apps,
derived from an exhaustive source audit (not from what a screenshot happened to show). This
is the denominator for visible-region coverage: a region counts as *covered* only when a
screenshot actually renders it visible. The goal is one composite image that displays every
one of these regions.

## Totals (distinct visible regions per app)

| app | regions | source root |
|---|---:|---|
| incoming-documents (INDOX) | 111 | development/incoming-documents/app/webapp/src |
| console (המרכז) | 63 | development/console/static |
| drive (דרייב) | 55 | apps/drive/static |
| connections (חיבורים) | 54 | development/connections/ui.html |
| mailview (מייל) | 34 | apps/mailview/static |
| machine (מכונה) | 33 | platform-base/machine/static |
| chat (צ׳אט) | 32 | apps/chat/src |
| my-docs (מסמכים שלי) | ~30 | apps/my-docs/static |
| notifications (התראות) | 24 | platform-base/notifications/static |
| any-concurrency (כל מקביל) | 24 | platform-base/any-concurrency/static |
| feature-validation | 20 | development/feature-validation |
| **total** | **~480** | |

## Coverage reachability buckets

Not every region can be photographed in a healthy, seeded local run. Honest coverage tracks
these buckets separately rather than claiming a flat 100%:

1. **Default / navigable** — visible on load or by clicking a tab/nav. Always coverable.
2. **Interaction-revealed** — modals, drawers, menus, command palette, expandable rows,
   collapsible sections, wizard steps. Coverable by driving the app's own open/toggle.
3. **Data-dependent** — needs seeded records (documents, messages, files, connections,
   subscribers, benchmarks). Coverable **after seeding** (see seed_demo.py + per-app seeds).
4. **Empty / loading states** — appear specifically when data is absent or mid-fetch.
   Coverable, but mutually exclusive with the populated state of the same region.
5. **Failure-injection states** — error banners, unreachable services, timeouts, verify-fail.
   Require faulting a backend; NOT coverable in a healthy run without deliberate breakage.
6. **External / native** — OAuth consent screens (third-party), and native `alert()` /
   `confirm()` / `prompt()` dialogs. NOT screenshot-coverable via CDP.

Target: **100% of buckets 1–4** (everything reachable in a healthy, seeded local run),
with buckets 5–6 enumerated and labelled as out-of-frame rather than silently counted.

## Per-app region catalogue

The full per-region tables (id/selector · label · reveal trigger · needs-seed) are captured
by the deep-audit and mirror the runtime probe keys in ui-code-coverage.json →
`visible_regions.hidden`. Highlights of the hidden-by-default (interaction/data) regions the
capture pipeline must drive to reach full visible coverage:

- **console**: ⌘K command palette (`.pal-ov`), connect-wizard modal with 5 steps
  (`.modal-ov.cw-ov` → provider/method/oauth-wait/verify/done), QR pairing modal (`showQr`),
  account switcher dropdown (`.acct-menu`), install wizard + advanced connections
  `<details.adv>`, business form (`.bizform`), apps catalog, rail-collapsed.
- **incoming-documents**: 12 routes; UpsertDrawer, column-picker menu, BinaTable toolbar/
  toasts/empty/no-match, settings sub-tabs (sync/queries/system/companies/tags), extraction
  run panels, doc-detail viewer panes, Kafka tail, playground (feature-validation shares this).
- **drive**: preview drawer (`#preview`), context menu (`#ctx`), bulk bar (`#bulkbar`),
  account menu (`#acctMenu`), drop veil/strip, move/rename/new-folder/delete modals, connect
  flow (provider→method→oauth→form→verify), toast.
- **mailview**: message reader drawer (`#reader` + `#rDoc`/`#rBody`/`#rAtts`), tag-picker
  modal, other-labels expand, thread expand, test-mail toggle, day headers, toast.
- **connections**: 86 expandable credential editors (`#ex_<id>`), audit drawer, add-secret
  modal, confirm/rotate/wipe modals, QR modal, reveal-secret, per-pillar tabs, toast.
- **machine**: chart hover tooltip, storage bars, docker-storage, cleanup action cards,
  BinaTable column-picker/density/export, grid empty/no-match, skeleton.
- **any-concurrency**: detail drawer (`#drawer`+scrim), span tooltip (`#tip`), expand system
  rows, fan-out process rows, zoom/reset, minimap viewport, empty/error overlays.
- **notifications**: unread/level/source filter chips, row hover actions, toast, day groups,
  3 empty states + error state.
- **my-docs**: document detail drawer (`openDoc` → `#dConv`/`#dEvents`/`#dPdf`/`#dStatus`),
  new-doc editor modal, customer/item editors, per-view tables (needs seeded docs/customers).

## How this maps to the pipeline

`capture.py` probes every shot with `REGION_PROBE` and records which significant regions were
actually visible; `report.py` unions them per app into `visible_regions` and lists every
region no shot ever displayed. Reveal states in `inventory.py` (and seeded demo data) drive
the hidden regions visible so the composite map shows them. Buckets 5–6 above are the honest
ceiling: they are catalogued here but not counted against a healthy-run 100%.
