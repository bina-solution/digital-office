# `Incoming Documents v2` — "Invalid execution input" (~21/hr)

**Status:** diagnosed, not fixed. Fix is one Filter node; blast radius is the whole drain, so it is
written down rather than applied mid-run.

**Cost:** error-log noise only. **No work is lost and no document is stuck** — the failing calls are
fire-and-forget children (`waitForSubWorkflow: false`), so the parent execution is unaffected. This
matters for the "zero n8n errors" objective, not for throughput.

## What happens

`indoxV2Driver01` contains a node named **`Execute Workflow`** whose target is `={{ $workflow.id }}`
— the driver invoking **itself**, per item, fire-and-forget:

```
MAP ID1 (Set: ID = {{ $json.ID }})  ->  Execute Workflow  ->  ={{ $workflow.id }}
                                          mode: each item, waitForSubWorkflow: false
                                          maps: { "ID": "={{ $json.ID }}" }
```

When an item on that path carries no `ID`, `MAP ID1` still emits one and the self-call still fires.
The child's `When Executed by Another Workflow` trigger declares `ID`, `ACTION_LINE`, `ACTION_LINES`,
so it receives `{"ACTION_LINE": null, "ACTION_LINES": null}` with **no `ID` key at all**. The `Switch`
tests `ID`/`LINES`/`ACTION_LINES` for existence, matches none, and falls to `output[3]` ->
`Stop and Error1` -> *"Invalid execution input"*.

## Evidence

Decoded from `execution_data` (flatted-encoded; node names and messages dereferenced, not
string-matched):

| exec | trigger items | with ID | Switch routing |
|---|---|---|---|
| 1713528 | 1 | 0 | `out[3]=1` — error branch |
| 1714645 | 1 | 0 | `out[3]=1` — error branch |
| 1715344 | 1 | 0 | `out[3]=1` — error branch |
| 1714033 | 100 | **100** | `out[0]=100`, `out[3]=0` |
| 1714044 | 100 | **100** | `out[0]=100`, `out[3]=0` |
| 1715000 (success) | 100 | 100 | `out[0]=100`, `out[3]=0` |

Every bad payload is byte-identical: `{"ACTION_LINE":null,"ACTION_LINES":null}`.

## Three dead ends, recorded so nobody re-walks them

1. **"A leftover schedule trigger is firing it."** No. The driver's `Schedule Trigger` runs a
   different path entirely (`GETALL Req -> Call INDOX GETALL -> Lines Batching Loop`) and never
   reaches the `Switch`. Removing it would not have fixed this.
2. **"One bad item among 100 poisons the batch."** No. The large batches are `100/100` valid IDs
   with `out[3]=0`, and are shape-identical to successful runs. Those failures are a *separate*
   cause: `timeout exceeded when trying to connect` on `Call indox-v2 Decide` / `Check LOCKED`.
3. **"`indox api - supabase` is the caller."** No — artifact. It preceded 30/30 failures within 10s,
   but also **197 of 200 successes**: it runs 8,110 times per 6h (~22/min), so it precedes
   everything. It has 2,065 runs/hr with **0 errors**. Acting on that correlation would have meant
   changing a healthy workflow.

There is no external caller. `origin_execution` points at the execution itself.

## The fix

Insert a Filter between `MAP ID1` and `Execute Workflow` passing only items where `ID` is a
non-empty string.

Fix the **caller**, not the guard. `Stop and Error1` is behaving correctly — it is rejecting input it
genuinely cannot act on. Softening it (routing `output[3]` to a NoOp) would hide real malformed input
and let one bad row silently skip work.

Deploy note: the driver is executeWorkflow/webhook-invoked, so it picks up a new definition **at call
time** (~33s changeover) with no restart. Push via `bbox`, never `n8n import:workflow` — import sets
`active=false` and nulls `activeVersionId`.

## Related, still open

- `password authentication failed for user "postgres"` on `Call indox api (Get Line)` — a node
  pointed at the wrong DB credential (this deployment's user is `hacohen`). Low volume, clear bug.
- `timeout exceeded when trying to connect` on `Call indox-v2 Decide` / `Check LOCKED` — pressure,
  not logic. Postgres was **34/100** connections with zero lock waits when measured, so this is not
  connection-pool exhaustion.
- `Sync v3 Deliver` fired **32 executions in one minute** (22:28) against `Call Supabase`, all of
  which timed out and were cancelled — 37 cancellations. Needs a concurrency gate; the work is
  discarded at timeout and has to be redone.
