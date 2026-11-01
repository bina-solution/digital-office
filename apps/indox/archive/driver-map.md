# INDOX Driver Map — drainer / driver / router responsibilities + the junk audit
*(2026-08-16, from the pulled live graphs + 7-day execution evidence. Companion to NEXT.md.)*

## Responsibilities (the intended architecture)

| layer | workflow | job | it does NOT |
|---|---|---|---|
| **Drainer** | `indoxV2BaseDrain01` (18 nodes, clean) | Every 5 min: gate on `indoxDrainOn` → capacity check → lock-aware candidate pick → call **Driver: Run By ID** per candidate (executeWorkflow) · hourly full-table sweep | decide, lock, or dispatch anything itself |
| **Driver** | `indoxV2Driver01` (131 nodes, **~60 junk**) | Fetch doc state → **decide** (Call indox-v2 Decide) → dup-guard → **lock** (`processLock01` doc_action `<ID>::<ACTION>`) → **group** (≤25/action) → **POST the Action Router webhook** per group → fire check_next re-entries | execute actions (that was split out to the router — the in-driver copy is dead, see below) |
| **Action Router** | `indoxV2ActionRouter01` (19 nodes, clean) | Webhook/direct entry → normalize lines → log bracket (start) → Switch by DOC_TYPE → executeWorkflow the 4 action workflows (**waits for them**) → log bracket (end) → unlock | decide or lock; and today it does NOT advance (check_next) — that's the Group B gap |

**The driver's four live entries**: schedule (30k sweep via GETALL), webhook `incoming-documents-017`
(check_next re-entry, chunked IDs), executeWorkflow (drainer's Run-By-ID), manual.

**The live spine** (all entries converge): `Start → If UNDEFINED NAME → Call indox-v2 Decide →
Dup Guard → IF NOT SAME ACTION TWICE → If ACTION → Action Filter → Taking Action →
{Check LOCKED + Join LOCKED} → If NOT LOCKED → Lock Map Set + Execute Action →
If group action → Group By ACTION → Loop37 → POST Action Router (group)` — and, **in parallel
with dispatch** (= the Group B defect, next work item): `Check Next Action → Next Action IDs →
POST Next Action (by id)`.

## The junk audit — 61 of 131 nodes are removable, four families

**A. The in-driver Action Router duplicate (13 nodes) — the never-cleaned split.**
`Map ACTION_LINE → ACTION LINE → Actions Dispacher → Switch1 → Call indox-v2 Actions —
DOC BASE/GDoc/BS/Shipment + Skip empty_row + Stop and Error`, plus the old `Redis`/`Redis1`
action brackets and `Execution Data3`. Reachable only by POSTing `ACTION_LINES` to the driver's
own webhook — **0 executions in 7 days, 0 redis bracket keys**. This is the pre-split dispatcher
the router replaced verbatim (same Switch rules, same 4 calls). After removal, an ACTION_LINES
body fails loudly ("Invalid execution input").

**B. The parallel-subworkflow callback prototype (19 nodes).** `Simulate Multi-Item…`,
`Loop Over Items36`, finishedSet machinery, `Webhook Callback Wait`, `Start Sub-Workflow via
Webhook`, disabled `Webhook1`/`Webhook2`, and — grafted onto the LIVE webhook fan — `If1 → Wait →
Call Resume on Parent Workflow → If → Unable to unlock…` (fires only when `requestItemId` is in
the body: never) and `If3 → Wait1` (`params.wait_before`: never present). Sticky notes 2/3/4/5
document it ("Cut/Paste this into a separate workflow"). This was an earlier attempt at exactly
the wait-for-completion semantics now planned — parked, half-grafted, never finished.

**C. The in-driver decide test rig (3 nodes).** `Determine Action Tests` (orphan generator),
`Determine Action Tests1` (an IF on the HOT PATH separating test items), `…Assertions`.
Redundant: `indoxV2DecideTest01` exists. Removal rewires `Call indox-v2 Decide → Dup Guard`
directly.

**D. Scrapyard (26 nodes).** A full copy of the shipment-link lane (lives in GDoc01 now:
`Action: Link Shipments … Mark Invoice Completed`), selection-scoring leftovers, priority-sync
leftovers (`Post Priority Table1`, `map response → pririty sync1`), an orphan self-POST
(`HTTP Request`), dead loops (`Loop Over Items25/38/39`, `Replace Me(1)`, `Batch x Start`),
unwired noOps (`No Action: …` ×3), orphan `Execution Data`, disabled `Merge`, and their stickies.

## Group B fix direction (after cleanup — per owner: dispatch must wait for completion)
The router already **waits** for its action workflows (executeWorkflow, waitForSubWorkflow) and
brackets completion in `indox_action_execution_log`. The advance step (check_next) moves to the
router AFTER `Log Action End` — so a doc's next action is decided only against post-completion
state. The driver's dispatch-time `Check Next Action` branch is then removed. No polling, no
callback machinery (what family B attempted), no stale snapshots — per-doc freshness guaranteed
by construction.
