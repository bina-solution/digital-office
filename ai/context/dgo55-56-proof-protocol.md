# DGO-55 / DGO-56 — the comparison, and what counts as proof

Prepared while waiting for the quiet window. Nothing here is a result yet: the cells are empty on
purpose, and the protocol is what fills them.

## The one command (DGO-55)

```bash
bash scripts/ui-coverage/dgo55-score.sh          # desktop + 390, bina-ds + mailview, one table
```

It refuses to start on <6 GiB free or load1 > 20, captures `UI_MAP_APPS="bina mailview"
UI_MAP_SHARDS=1` one profile at a time, scores into `ci-artifacts/dgo55/<profile>/` (never into
`ci-artifacts/ui-score.json`, which is the whole-platform desktop baseline), and prints the table
below filled in. **The bina-ds recreate must precede it** — the script photographs bina-ds as it is
running, so a recreate mid-run would capture half of one version and half of another.

## The table — filled 2026-10-12 by that command (commit `2173806f`, hp-laptop)

Scores are the seven weighted dimensions from `scripts/ui-coverage/score.py`:
layout 25 · clipping 15 · touch 10 · type 15 · contrast 15 · consistency 10 · states 10 = 100.

Each dimension in brackets is **its own share** of that dimension's maximum. That is the only reading
the 70 floor can have: `score.py` punishes a view whose *total* is under 70, and a dimension whose
maximum IS 10 can never be read as "70 points". On this reading contrast 9.0/15 is 60%.

### bina-ds

| profile | views | layout /25 | clipping /15 | touch /10 | type /15 | contrast /15 | consistency /10 | states /10 | **total** |
|---|---|---|---|---|---|---|---|---|---|
| desktop 1440×900 | 1 | 25.0 (100%) | 9.8 (**65%**) | 10.0 (100%) | 15 (100%) | 9.0 (**60%**) | 10 (100%) | 10.0 (100%) | **88.8** |
| phone 390×844 | 1 | 25.0 (100%) | 15.0 (100%) | 1.0 (**10%**) | 15 (100%) | 10.0 (67%) | 10 (100%) | 10.0 (100%) | **85.9** |

### mailview

| profile | views | layout /25 | clipping /15 | touch /10 | type /15 | contrast /15 | consistency /10 | states /10 | **total** |
|---|---|---|---|---|---|---|---|---|---|
| desktop 1440×900 | — | — | — | — | — | — | — | — | **not measured** |
| phone 390×844 | — | — | — | — | — | — | — | — | **not measured** |

**Why mailview is empty, and it is not "no findings".** The capture is per office: `mailview` is not
in THIS office's map — the inventory says it plainly (`not in this office's map: … mailview (9)`),
because hp-laptop does not run the mail app. Only the vps1 office does (`mailview.vps1` appears here
as a LINKED tile, and a linked tile is not a view of this office). So the mail half of the comparison
needs the office that runs mail — the scan there, or the mail app enabled here. Until then, half of
DGO-55's own table has no measurement, and no number may be inferred for it.

### The per-view detail the command prints

| profile | app | view | score | weakest dimension |
|---|---|---|---|---|
| desktop | bina | בינה ודעת — הסוכן (main) | 88.8 | contrast 9.0/15 (60%) |
| 390 | bina | בינה ודעת — הסוכן (main) | 85.9 | touch 1.0/10 (10%) |

Filled from `ci-artifacts/dgo55/<profile>/ui-score.json` — every scored view, worst first, with the
dimension that lost the most **of its own** total (8/10 hurts more than 18/25).

**The defects behind those three numbers, named** (the samples live in
`data/ui-map/<profile>/ui-capture-results.json`, and they are all in the harness UI's own components):

| profile | dimension | what | the element |
|---|---|---|---|
| desktop | contrast | 3.55:1 (needs AA 4.5:1) | `span.bhn1Oq_sectionLabel.bhn1Oq_wide` — rgb(129,133,140) on rgb(249,250,251) |
| desktop | contrast | **2.13:1** | `div.uV2eYG_placeholder` — rgb(173,178,184) on rgb(255,255,255) |
| desktop | clipping | one box cut with no scrollbar | `div.bhn1Oq_search` |
| phone 390 | touch | 9 of 9 interactive targets under 44px, so the dimension is 1/10 | `button.hHd-Xa_iconButton` 36×36 · `button.bhn1Oq_searchButton` 36×36 · `button.VOzbGW_trigger` 36×36 · `button.pXSMma_workspace` 163×28 · `button.cubgiG_seat` 85×28 · `button.uV2eYG_add` 28×28 |

### Where the five proofs stand (2026-10-14)

| proof | state | the evidence |
|---|---|---|
| 1. both profiles, non-empty `ui-score.json` | **half** | `ci-artifacts/dgo55/desktop/ui-score.json` (1 view) and `.../mobile/ui-score.json` (1 view) exist and are fresh — both for **bina-ds**. mailview did not run here at all (the section above). |
| 2. ≥85 overall, no dimension under 70 | **totals pass, four dimension-readings fail** | desktop 88.8 ✓ / mobile 85.9 ✓; below 70% of its own maximum: desktop clipping 65% and contrast 60%, mobile touch 10% and contrast 67% — each with the element named above. |
| 3. a desktop + 390 screenshot pair per window | **half** | `ci-artifacts/ui-map/mobile/screenshots-ui/bina__main.png` and `ci-artifacts/ui-map/desktop/screenshots-ui/bina__main.png` — the same window at both sizes, from the same capture's runs. mailview has neither. |
| 4. `flow-qa.py --mobile` green | **GREEN** | 485/485 flows, `JS errors: 0` (2026-10-14). It was 484/485 on 2026-10-12 with `layout/apps no control of the panel it opens (#drawer) is smaller than a finger — button.x 26x27`: the drawer's close was 26×27 in `platform-base/app-management/static/index.html` (DGO-529 had been closed while the debt stayed in `flow-qa.py`'s `TAP_OWED`). The control now takes the office's floors (30px mouse, 44px coarse), the simulation was rebuilt so the fix reached the artifact the suite reads, and the paid entry was removed from `TAP_OWED` — the list cannot outlive its debts, and a debt that does fails the run. |
| 5. claim + caveat together | **done in this file** | every score above carries its profile, its view count (1), and the commit (`2173806f`). |

**The one command, for the next run** (it is the same one, and it refuses to start on a loaded engine):
`bash scripts/ui-coverage/dgo55-score.sh` — and the four cells that are still empty (mailview, both
profiles) are the reason DGO-55's own table is half-filled, not a reason to read a number into them.

## What DGO-56 accepts as proof

1. **Both profiles, both apps** — one `ui-score.json` per profile under `ci-artifacts/dgo55/`, and a
   non-zero view count in each. A profile that produced no file is a profile that did not run; it is
   reported as missing, never as "no findings".
2. **≥85 overall per app per profile, and no dimension below 70.** Below 70 is a defect with a name,
   not a taste question — the dimension and the view are in the table.
3. **Two screenshots per window** (desktop + 390) from the same run's `screenshots-ui/`, because the
   owner's ask was about how the two windows look side by side, not about a number alone.
4. **`python3 digital-office/sim/flow-qa.py --mobile` green** — the offline flow suite, which is the
   only browser check that does not need the stack. It covers the SIM's mail fork, not the live
   mailview; it is evidence about the component's behaviour at phone size, and the report must say so
   rather than implying it photographed the live app.
5. **The claim and the caveat together, always**: every score is reported with its profile, its view
   count and the commit it was measured on. The desktop baseline in the plan (median 89.5 over 71
   views, 9 apps) stands as the platform reference; the DGO-55 table is two apps measured the same
   way, and is not a new platform median.

## The one open piece before DGO-54 can be called complete

indox is the only adopter whose shell is not `.bnv-host`/`.appgrid` (it is `app-shell flex`), so it
is the only one of the five without container-driven sizes — recorded as `sized: false` in
`platform-base/bina-ui/test_bina_nav.mjs`, not skipped. The component's half is done and in use by the other
four: `@container bnav` rail at 600–839px, drawer below 600px, Priority+ (`showMore`), 44px under
`(pointer:coarse)`, and one line with an ellipsis in every row.
