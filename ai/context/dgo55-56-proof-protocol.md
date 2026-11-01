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

## The table — empty, to be filled by that command

Scores are the seven weighted dimensions from `scripts/ui-coverage/score.py`:
layout 25 · clipping 15 · touch 10 · type 15 · contrast 15 · consistency 10 · states 10 = 100.

### bina-ds

| profile | views | layout /25 | clipping /15 | touch /10 | type /15 | contrast /15 | consistency /10 | states /10 | **total** |
|---|---|---|---|---|---|---|---|---|---|
| desktop 1440×900 | | | | | | | | | |
| phone 390×844 | | | | | | | | | |

### mailview

| profile | views | layout /25 | clipping /15 | touch /10 | type /15 | contrast /15 | consistency /10 | states /10 | **total** |
|---|---|---|---|---|---|---|---|---|---|
| desktop 1440×900 | | | | | | | | | |
| phone 390×844 | | | | | | | | | |

### The per-view detail the command prints

| profile | app | view | score | weakest dimension |
|---|---|---|---|---|
| | | | | |

Filled from `ci-artifacts/dgo55/<profile>/ui-score.json` — every scored view, worst first, with the
dimension that lost the most **of its own** total (8/10 hurts more than 18/25).

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
