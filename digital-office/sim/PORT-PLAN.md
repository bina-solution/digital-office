# Porting the simulation into the live platform

**Read this first if you are the person implementing the simulation for real.**

`ALIGNMENT-CHANGELOG.md` says WHAT changed and WHY, entry by entry. This file says **in what order**,
**how you know each one is done**, and **how to prove the live platform matches** rather than
declaring it does.

---

## 0 · The three rules

1. **The simulation is the specification.** Open `digital-office/platform-sim.html` in a browser and
   put it beside the live app. Where they disagree, the simulation is right — that is the entire
   point of it existing. It runs fully offline, so you can keep it open all day.
2. **Nothing in the simulation touched real source.** Every change lives either in the sim-owned fork
   (`sim/apps/indox/`) or in a runtime overlay (`sim/overlay/*.js`). So there
   is no merge to do and no conflict to resolve — each entry is a fresh edit you make in
   `apps/` or `platform-base/`, guided by the changelog's **Port** line. (A fork whose live app has
   taken all of it and gone further is retired: the simulation then embeds the live frontend
   itself. The drive's and the mail's were, on 2026-10-09 — see `PORT-STATUS.md` §3 and §4.)
3. **Do not port the fixtures.** `sim/business.js`, the generators in `sim/mocks/*.js`, and the
   ten-year corpora are test data. They exist so the UI had to survive real volume. The real
   platform has real data; porting the fixtures would be actively harmful.

## 1 · How to prove a port is finished

Two harnesses, both of which already exist and both of which can point at your deployment:

```bash
# every flow driven to its end, effect asserted — against the LIVE platform
python3 digital-office/sim/flow-qa.py --url https://your-host
python3 digital-office/sim/flow-qa.py --url https://your-host --mobile
python3 digital-office/sim/flow-qa.py --url https://your-host layout scroll
```

Non-zero exit on any failed flow or any JS error, so it drops straight into CI. The suites are
`drive · mail · indox · console · scroll · layout`; run one, several, or all.

```bash
# side-by-side pictures of every surface, at all three viewports
python3 digital-office/sim/ui-map.py --all       # 47 panels x 3 profiles, from the simulation
./bbox ui-map --profile desktop                  # the same panels, from the live stack
```

Compare panel N to panel N. The panel list and the viewports come from one tracked source
(`scripts/ui-coverage/view-profiles.yaml`), so the two maps cannot disagree about what "mobile"
means. **A port is done when the live panel and the sim panel are the same picture and the flow
suite is green against your URL** — not when the code looks right.

## 2 · Order

Dependency-ordered. Within a phase the items are independent, so they can be split across people.

### Phase 1 — foundations everything else assumes
| # | Entry | What | Acceptance |
|---|---|---|---|
| 1.1 | **A1** | one palette + one type stack across all apps | `layout` suite green; panels match on colour |
| 1.2 | **A2**, **A3** | Lucide icon pack replaces emoji-as-icons (A2 carries the complete glyph→icon map with source locations; A3 is the one canvas case the sim cannot reach) | no pictographic glyph left in any app |
| 1.3 | **C1** | brand rename + build-version footer | panel 00 matches |
| 1.4 | **B1** | RevoGrid bundled so the grid renders (otherwise INDOX hangs on "טוען נתונים…") | INDOX documents panel renders rows |

### Phase 2 — the shell
| # | Entry | What | Acceptance |
|---|---|---|---|
| 2.1 | **C16** | shell owns the viewport (`height:100dvh`), regions take the height they are given, the shared table gains `fill` | `scroll` suite green — this is the one that fails loudest if skipped |
| 2.2 | **C3**, **C15** | one connection switcher, mounted in the console top bar; delete `#acctBar` and the `.embedwrap.has-bar` rules | switcher panel matches; no full-width band |
| 2.3 | **C4** | connection health propagated + health/error-log panel | health panel matches |
| 2.4 | **B4**, **B7**, **C14.1** | responsive pass, 0 overflow, layered Escape, ≥44px touch targets on coarse pointers | `--mobile` run green |
| 2.5 | **B6** | a11y + theming (ARIA, keyboard nav, theme as CSS-variable cascade) | dark theme panels match |

### Phase 3 — the apps
| # | Entry | What | Acceptance |
|---|---|---|---|
| 3.1 | **C2** | de-INDOX Drive and Mail — they become standalone apps | Drive/Mail panels carry no INDOX chrome |
| 3.2 | **C11** | דרייב: places, breadcrumb, filter chips, grid, details pane, full document view, sharing, storage meter, star. **Backend:** `view=recent\|starred\|shared`, `POST api/star`, `GET api/storage`, and an `opened` column (Recent sorts by last-opened, NOT created) | `drive` suite green; 14 drive panels match |
| 3.3 | **C12**, **B2**, **C6** | מייל: system-label rail, move-not-destroy, undo everywhere, replace-in-place reading pane, conversation view, attachment cards, compose + reply/forward. **Backend:** persist starred/important/snoozed/archived, honour `view=`, `POST api/mark`, `GET api/thread/<id>` | `mail` suite green; 9 mail panels match |
| 3.4 | **C13** | the scale fixes: whole-mailbox counts in the list response, server-side system views, windowing, collapsible tree, decade-aware dates | counts correct on a real mailbox — the bug this fixes is invisible on small data |
| 3.5 | **C5**, **C7** | Drive file-type icons; my-docs faithful document renderer | those panels match |
| 3.6 | **B3**, **B5** | Chat as a multi-provider client; charset-first (the Hebrew mojibake fix) | chat panels match |

### Phase 4 — INDOX
| # | Entry | What | Acceptance |
|---|---|---|---|
| 4.1 | **C8** | instances: a whole INDOX per company — table, settings, registry, companies, tag rules and queries all switch together. Plus one click to the table, and no Kafka | switching an instance changes every one of those |
| 4.2 | **C9**, **C10** | one sync surface (author + watch + act), operator board at scale. **The full contract is in `INDOX-SYNC-PORT.md`** — read that, not just the changelog entry | `indox` suite green; sync panels match |

### Phase 5 — keep it true
| # | Entry | What |
|---|---|---|
| 5.1 | **D1** | `view-profiles.yaml` already feeds both maps — wire the CI matrix off `ci_matrix` |
| 5.2 | **C14**, **C16** | put `flow-qa.py --url <staging>` in CI. Every defect it catches is one that ships silently otherwise |

## 3 · What is deliberately NOT in the simulation

`DRIVE-MAIL-COMPONENTS.md` **Part F3** lists what was left out and why — real thumbnails, Gmail's
consumer category tabs, Drive's ML "Suggested" row, multi-level undo, offline states. Do not treat
their absence as an oversight to close: each has a reason, and two of them would require the
simulation to lie about what the platform can do.

## 4 · The one rule that caused the most damage here

**A component must never declare its own height.** `BinaTable` defaulted to `height = 520`; that
single number forced the page around it past the viewport and produced two scrollbars on one axis,
where the wheel obeyed whichever the pointer was over. The shell owns the viewport; every region
takes the height it is *given*. If you port nothing else from C16, port that.
