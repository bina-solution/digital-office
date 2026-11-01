# `Sync v3 Deliver` — 76.5% of its work is discarded by a parent/child timeout inversion

**Status:** diagnosed, not fixed. The fix is a one-number change, but it is on the live sync path.

**Cost:** real, unlike the driver's error noise. Cancelled executions did work that is thrown away
and must be redone. Over 6 hours: **39 cancelled / 10 success / 2 error — 76.5% discarded.**

## The inversion

```
Sync v3 Deliver       (child)   executionTimeout = 900s
Sync v3 Source Unit   (parent)  executionTimeout = 840s   <-- 60s SHORTER than its child
sync-v3 Full Test     (parent)  executionTimeout = 860s   <-- also shorter (test workflow)
```

`Sync v3 Source Unit` fans out via `Loop Deliveries` (splitInBatches, `batchSize: 4`) into
`Deliver Each` (`mode: each`, `waitForSubWorkflow: false`). A child is granted 900s inside a parent
that is only granted 840s, so any child still working when the parent expires is killed mid-flight —
after doing most of its work, and with nothing recorded as complete.

## The evidence that identified it

The giveaway is that **cancelled children die YOUNGER than successful ones live**:

| status | avg runtime | max runtime |
|---|---|---|
| canceled | 101s | **135s** |
| success | 169s | **322s** |
| error | 200s | 237s |

That is backwards for a self-inflicted timeout: with a fixed limit T, nothing under T dies and
nothing over T survives. Children reaching 322s while others are killed at 135s means the clock that
kills them is not their own. The parent's is the only other one, and it is set lower.

Burst shape (starts per 5 min, 6h): two bursts of ~40, at 18:35 and 22:25. Trigger is
`executeWorkflowTrigger` only — Deliver has no schedule of its own; it fans out when a parent runs.

The visible symptom was `Call Supabase :: The execution was cancelled because it timed out` on 10
sampled executions, plus knock-on errors in `indox api`, `indox api - supabase`, `mail api` and
`Sync Ledger API`, which share that path. Supabase is a victim here, not the cause.

## The fix

Raise `Sync v3 Source Unit`'s `executionTimeout` above the child's 900s (and `sync-v3 Full Test`'s
860s likewise), **or** lower the child's below the parent's. The invariant worth stating in whichever
place someone will read it: **a parent's timeout must exceed the timeout of anything it spawns**, or
the child's own limit is decorative and its work is discardable at any moment.

A concurrency gate on the fan-out is a *separate*, additive improvement — 40 simultaneous children
against one Supabase endpoint is its own pressure problem — but the gate alone would not fix this,
and raising the parent's timeout alone would.

## Ruled out

- **Not Postgres exhaustion.** 34 of 100 connections, zero lock waits, measured during the incident.
- **Not a restart.** n8n, n8n-postgres, redis, workers and apitools all `restarts=0`.
- **Not the platform-os-net fork.** 157 MiB against the live platform's 7,483 MiB (~2%).
- **Not slow Supabase per se.** Successful runs on the same path reached 322s without issue.
