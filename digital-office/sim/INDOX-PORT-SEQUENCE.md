# Porting INDOX — the order, and what makes each step safe

INDOX is 283 of the 651 remaining component gaps: the largest single block, and the riskiest, because
it is a compiled React app whose sim version is a **fork** rather than an overlay. This records the
sequence and the reasoning, so the work can be picked up or paused without re-deriving it.

Measured with `scripts/ui-coverage/sim-live-parity.py --profile desktop`.

## What the diff actually is

```
only in SIM   pages/SyncBoard.tsx                     the merged sync surface (C9/C10)
only in LIVE  pages/KafkaTailPage.tsx                 Kafka is already gone from the backend
              pages/RepoListPage.tsx                  repos → instances is the C8 product change
              pages/RepoCreatePage.tsx
              pages/RepoDetailPage.tsx                its content moved into "instance details"

differ        pages/SyncStatePage.tsx   815 vs 308    ← the bulk of the work
              api.ts                    876 vs 661    instance-scoped endpoints
              App.tsx                   166 vs 120    routing + instance switching
              main.tsx                   39 vs  18
              index.css                 647 vs 624
              components/BinaTable.tsx 1070 vs 1064
              pages/DashboardPage.tsx   372 vs 370
              pages/DocumentBrowserPage.tsx 341 vs 333
```

## Checked before starting, because a wholesale copy would have been wrong

* **The sim is AHEAD, not behind.** Its `api.ts` carries more extraction surface than live (26 vs 23
  references), so this is a port forward, not a revert.
* **The tag_rules editor survives.** Live's `SettingsPage` is *larger* than the sim's (667 vs 578),
  which looked like the sim had dropped the label-engine rules UI. It has not — both carry
  `tag_rules` ×4 and `BinaConfigGrid` ×3. The size difference is elsewhere. Had that been wrong, a
  file-level copy would have deleted a feature that was explicitly asked for.
* **The backend needs nothing new.** `ai/context/sim-to-live-backend-audit.md`: *"the largest UI
  change but the smallest backend question… It needs care, not invention."* `incoming_documents` and
  `sync_registry` are real tables and the instance model is a scoping concern over existing queries.
* **The build works.** `npm run build` → 78 modules, RevoGrid bundled, ~22s. Worth proving first: a
  port that cannot be compiled cannot be shipped, and `dist/` is gitignored so the image build is the
  only thing that produces it.

## Order

**1 — `index.css` + `BinaTable.tsx` (+23 / +6 lines).** Pure additive styling and grid tweaks, no
routing or data changes. Smallest possible change that moves real tokens (`bina-table`, `bt-*`,
`bar-*`, `bigstat`, `barlist` appear on every INDOX panel). Verifies the build-and-deploy loop end to
end before anything structural.

**2 — `DashboardPage` (+2) and `DocumentBrowserPage` (+8).** Still small, still leaf pages. Closes
panels 28 and 29, the two largest single-panel gaps (38 and 66).

**3 — `api.ts`.** Additive: instance-scoped endpoints alongside the existing ones. Nothing calls them
yet, so it cannot regress a working screen.

**4 — `SyncStatePage` + `SyncBoard`.** The real work (C9/C10). Read `INDOX-SYNC-PORT.md` first — the
port plan says the contract lives there, not in the changelog entry.

**5 — `App.tsx` + `main.tsx`, and only then the four page removals.** LAST, deliberately: routing and
deletion are the only irreversible-feeling steps, and removing RepoList/RepoCreate changes the
product's top-level concept from *repos* to *instances*. Everything before this point is additive and
independently verifiable; this step is the one that needs a decision rather than a diff.

## Rules for this port

* **Rebuild the image every time.** `docker cp` into a running container is not a deployment — it
  reverts on the next recreate, and an entire session's UI work was lost that way once already. See
  `ai/context/running-on-wsl.md`.
* **Re-measure after each step.** The parity number is the acceptance test; if a step does not move
  it, the step did not do what it claimed.
* **Never `docker compose -f apps/indox/...` directly** — that forks a second compose project sharing
  container names and takes the stack down.
