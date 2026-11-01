# INDOX — the unified n8n architecture

**Target:** 5,000+ documents/month sustained, 180,000 over three years, with burst capacity for a
32,000-document backfill. One pattern for data, one for API, workflows uniform enough to review at a
glance.

This is the executable specification. Each section states the rule, why it exists (naming the real
defect it prevents), and how a gate enforces it.

---

## The governing decision

**Unify on n8n — but no workflow may touch the database directly.**

Today 65 of 66 workflows write Postgres directly; exactly 1 of 55 API routes is called by n8n over
HTTP. Every validation, identity rule and schema guard in the Python service is therefore *optional
in practice*. That one fact produced:

- four divergent `SHORT_DOC_ID` formulas and 729 rows stranded in `DOUBLE`
- 1,503 rows with a raw 502 HTML page stored as document data
- `NEXT_RETRY_AT` populated on 0 of 6,207 rows — retry scheduling never worked, silently
- eight switches discarding documents with no error

n8n is not the problem. **Unmediated writes are.** Everything below follows from closing that.

---

## 1 · The data gateway

**Rule.** Exactly one sub-workflow — `indoxDataGateway01` — performs writes. Every other workflow
calls it. No Postgres node exists anywhere else.

**It owns:** schema validation (reject unknown or malformed fields loudly), identity assignment,
status-transition legality, error-shaped-value rejection (an HTTP error body is never document data),
and an audit trail of who wrote what.

**Why.** A single door means one place to fix a bug, one place to add a column, and no possibility of
a workflow's private idea of the schema. It directly prevents the 502-HTML class, the silent field
drop, and schema drift.

**Gate G42 — `direct-db-write-lint`. RETIRED 2026-08-07.** It failed when any workflow other than
the gateway contained a Postgres node or a direct PostgREST call — but `indoxDataGateway01` was
invented by an agent lane, rejected by the owner as "not part of the existing architecture", never
executed once, and disarmed on 2026-08-07. A gate demanding that everything route through a workflow
that does not exist could never go green. Script in `data/_attic_agent_drafts/`; reasoning in
`scripts/refactor/GATES.md`, "Two gates retired". **The single-writer invariant itself may still be
worth having — against `indoxApiSupabase01`, the REAL writer, under a new number.**

> Migration note: `executeWorkflowTrigger` declares an explicit input schema and n8n **silently drops
> undeclared fields**. The gateway's trigger schema must be generated from
> `information_schema.columns`, never hand-maintained — that is precisely how `THUMBNAIL`,
> `CONNECTION`, `NEXT_RETRY_AT` and `RETRY_COUNT` were lost. Gate G39 already checks this drift.

---

## 2 · One identity

**Rule.** One sub-workflow, `indoxIdentity01`, computes document identity. Nothing else may.

`SHORT_DOC_ID` — last five alphanumeric characters — is not an identity; it is a collision generator
with known sinks (`'00000'` from an empty value padded, `'61520'` from a vendor template, `'22026'`
from any February-2026 date). Four implementations exist.

**Target key:** `(source_system, source_id)` as the natural key — stable, meaningful, and already
carried. Content `HASH` detects true duplicates. `SHORT_DOC_ID` survives only as a display label,
never as a key. `DOUBLE` becomes a decision recorded against a real key rather than a bucket for
anything that collided.

**Gate G43 — `single-identity-lint`. RETIRED 2026-08-07**, with G42 and for the same reason:
`indoxIdentity01` was agent-invented, owner-rejected, never executed, and disarmed. See
`scripts/refactor/GATES.md`, "Two gates retired". The collision evidence below is real and is the
part worth keeping — the divergent `SHORT_DOC_ID` formulas and the `'00000'`/`'61520'`/`'22026'`
sinks were measured live, whatever workflow ends up owning the fix.

---

## 3 · Incremental discovery

**Rule.** No full re-listing on a schedule. Ever.

`sync_cursor` exists with **zero rows**. There are no matches for Gmail `historyId` or Drive
`startPageToken` anywhere. Every pass re-lists 78,651 files and 83,442 messages — the root cause of
every timeout, and untenable at three years of data.

| Source | Cursor | Cold start | Gap / expiry |
|---|---|---|---|
| Gmail | `historyId` | full scan once, store the high-water mark | on `404 historyId too old`, full rescan and re-anchor |
| Drive | `startPageToken` | full scan once, store the token | on invalid token, full rescan and re-anchor |

A cursor row records `(connection_id, source, cursor, updated_at, last_full_scan_at)`. Cursor
expiry must be a *handled* path, not an exception — a cold start is normal after any outage.

**Gate G44 — `no-unbounded-listing-lint`.** Fails on a source listing with no cursor and no explicit
`full_scan=true` justification.

---

## 4 · The sync layer: elastic, not permanently hot

Sustained 5,000/month is ~7 documents/hour. The backfill needs ~3,000/hour — **400× the steady rate.**
So the answer is elasticity, not a permanently high `take`.

- `take` sized per run from queue depth, bounded by a configured ceiling
- real worker concurrency (`n8n-worker-1/2` already exist — confirm queue mode is actually in use)
- **backpressure**: when a downstream (apitools, Gemini, Drive) slows or errors, reduce `take` and
  lengthen the interval rather than stampeding. Today ~20 `drive api` errors/hour consume throughput
  in retries.
- the ledger's claim SQL is already race-safe and exactly-once — **keep it**. The bug was never the
  claim; it was that nothing reaped abandoned ones. The reaper now runs on a 5-minute schedule.
- every claim carries a lease; `NEXT_RETRY_AT` and `RETRY_COUNT` must actually work, with real
  backoff and a terminal dead-letter state. `needs_review` needs an exit path — 66 items sit there
  today with nothing to move them.

---

## 5 · The read path: computed on write

At 180,000 rows the UI lives or dies here. Live-walking sources on page load already failed twice
(`/sync/items` 20.4s → 39.1s → 56.1s, degrading *as the pipeline got healthier*).

- **counts maintained on write**, in a stats table, never counted at request time
- **keyset pagination**, never `OFFSET` — offset degrades linearly with depth
- month buckets precomputed, not derived by scanning (the month badge undercounted 6× by sampling
  one page)
- every source walk behind an explicit per-pipe opt-in (`?sync=<name>`), never a page-load default
- anything unmeasured returns `null` + `*_computed:false`. **Never a 0** — a fabricated zero reads as
  truth and is this codebase's single most repeated defect

---

## 6 · Workflows "pure as gold"

Uniform, not clever. Every workflow: trigger → claim → call shared sub-workflow → transition → done.

- **no branching business logic in a workflow** — it belongs in a shared sub-workflow with one copy
- **every switch has a fallback that raises a visible error.** Eight silent drops exist today; a
  dropped document is strictly worse than a failed one, because a failure is visible and retryable
- **no hardcoded allowlists.** `Switch1`'s 18-action list contains a typo — evidence it is
  hand-maintained and will keep drifting. Actions must be data.
- **no client-specific values.** Folder ids, labels and emails live in config, never in a node
- test and fixture workflows must never be `active` in production — **9 are today**

**Gate G41 — `switch-fallback-lint`** already exists and is currently red on those 8 gaps.

---

## 7 · Config with one owner

`sync_registry` is the single source of truth, validated on write, versioned, and **immune to
seeding**. It was overwritten by demo fixture data today; `seed.sh` is now insert-only and 18
live-operational keys were removed from the fixture. Gate G40 enforces it.

Every QA run snapshots `sync_registry` and diffs it afterwards — that check stays permanent, because
the loss mechanism is still not fully explained.

---

## 8 · Observability

Two questions must be answerable from a dashboard, because both went unnoticed for months:

1. *"Is a source returning fewer items than it should?"* — a pagination bug hid **43,326 of 78,651**
   drive files with no error.
2. *"Has a pipe stopped delivering?"* — `drive-gdoc` delivered **2 documents in its lifetime**.

Minimum: per-pipe delivery rate with an alert on a drop to zero; source item count vs previous run;
claim age distribution; per-hop latency; error rate by workflow **and** by node. Alerting itself must
be monitored — the error handler was silently dead for the system's entire life.

---

## Migration order

Each phase is independently verifiable. **Phases 1–4 are prerequisites for the backfill** — pushing
32,000 documents through 65 unvalidated writers would bake today's defects into three years of data.

| # | Phase | Buys | Prereq for backfill |
|---|---|---|---|
| 1 | Throughput + drive misconfiguration | a working pipeline at real rate | ✅ |
| 2 | Switch fallbacks + `needs_review` exit | no silent document loss | ✅ |
| 3 | Data gateway + generated trigger schema | no unmediated writes | ✅ |
| 4 | Single identity + `DOUBLE` migration | no collision-hidden documents | ✅ |
| 5 | Incremental discovery | cost stops scaling with history | — |
| 6 | Read path computed-on-write | UI holds at 180,000 rows | — |
| 7 | Workflow uniformity + gates | the architecture enforces itself | — |
| 8 | Backfill 32,000 | full coverage | — |

---

## Definition of done

A document dropped into any of the 7 sources reaches `COMPLETED` unattended · sustained 5,000/month
with burst to 3,000/hour · every UI endpoint under 40s cold at 180,000 rows · no unmediated write, no
second identity, no silent drop, no fabricated count · every gate green and able to fail · and a
dashboard that would have caught both the 43,326 hidden files and the pipe that delivered two
documents in its life.
