# THE PLAN v2 — the scale build

**2026-08-06.** Consolidates every objective from the owner's last 10 messages into one parallel
implementation plan. Supersedes `THE-PLAN.md` for forward work; that document remains the record of
what was fixed on 08-05.

---

## The mandate, in the owner's words

> "make this app really scale and maximise available resources and sync and process time and batching
> to make this a realistic very high load indox machine — always stable, always ready to handle
> extreme loads."

Targets: **5,000+ documents/month sustained**, 180,000 over three years, with burst capacity for a
**50,000-document E2E**. Keep n8n. Unify and minimise. One pattern for data, one for API. ERP-grade UI
that stays **sub-0.5s regardless of load**.

---

## The governing constraint

**The parallelism and batching settings are already tuned** for 8–16 GB laptop/VPS hardware —
`take`, `chunk`, `schedule_min`, worker count, n8n concurrency. **Nobody changes them.** If a value
looks wrong, report it; do not edit it.

Three independent measurements confirm the tuning is not the problem:
peak concurrency **38** on `indoxProcessDocument01`; average slot utilisation **101.9%**; nothing
serialised. **The machine is fast when it runs. It stops running.** That is the target.

---

## What actually limits throughput

**1 · Per-document cost, not parallelism.** ~150–250s per document, of which **~95% is apitools**:

    Document OCR → apitools/documentOcr                        75.7s   53%
    Figure COMPANY_ID → Upload OR Get API_TOOLS_ID → apitools   60.1s   42%
    everything else                                              6.5s    5%

Adding workers buys nothing. **Halving per-document cost twice beats 10x the hardware, and costs
nothing at runtime.**

**2 · The hash-miss path is the real cost.** `Upload OR Get API_TOOLS_ID` hash-checks — it never
re-uploads. Median **0.06s** on a hit; **256–302s on a miss**. Those samples came from a ~90%-cached
workload. **In a backfill or the 50k E2E, essentially every document is a miss**, so the miss path is
the norm, not a 10% tail. True fresh-document cost is closer to **330s+**, and every projection so far
has been optimistic. *(Verification in flight.)*

**3 · Uptime, not speed.** **60.7 slot-hours idle while backlog existed** in an 8-hour window — 90% of
it one contiguous **4h05m stretch at ~20% utilisation**. And during the 19:00 hour,
`indoxProcessDocument01` logged **85 crashed + 10 error + 1 success out of 96 — a 94% failure rate**.
A 50k run against that is a week of retries.

---

## Workstreams — all parallel, fenced so none collide

### A · Keep the machine running *(highest priority)*
Explain the 4h05m collapse with evidence. Fix the lock TTL we introduced today — `processLock01` holds
600s but reconcile's median runtime is **956s**, so the lock expires mid-pass and a second can start.
Build a zombie reaper for n8n's `execution_entity` (none exists — only ledger claims are covered).
Define "the machine has stopped" measurably and recover automatically. Close schedule gaps **without
touching the tuned intervals** — a pass finding a full batch continues immediately rather than exiting
to wait.

### B · Per-document cost
Break down the 211.8s inside `indoxProcessDocument01`. It is a strictly serial **7-hop chain**, and
three hops (`Extract InvoceId` / `ShipmentId` / `Purchase ID`) are separate calls to the **same**
`apitools/documentJsonQuery` endpoint — **apitools already ships the fix pattern unused** in
`/documentDraw` (load once, iterate queries). Determine why a hash miss costs 256–302s: synchronous
OCR inside upload, queueing, or a timeout. Batch every N-calls-where-1-would-do site.

### C · Remove the thumbnail step *(owner-specified)*
Delete `indoxV2GenerateThumbnail01` entirely. The apitools upload already returns an image link — the
document preview page renders exactly that. `indoxProcessDocument01` captures it and writes
`THUMBNAIL`. **−116s from a ~200s budget**, one fewer workflow, thumbnails populate as a byproduct.
Verify `THUMBNAIL` is declared in `indoxDocBatchUpsert01`'s trigger schema or the write vanishes
silently.

### D · Extraction refactor *(owner-specified)*
Two phases only — **base doc** (company, type) and **per-type** (invoice/shipment/bs) — each doing
**both AI and local**, writing `AI_VAL` and `LOCAL_VAL`. A selection step picks and writes plain `VAL`.
**All `SELECTED_*`/`SELECTION_*` columns deleted.** AI is driven *from the local JSON query
definition*, so a field is defined once instead of twice. BS follows the same pattern plus local
date/basic extraction. Keep settings toggles: AI on/off, local on/off, extraction model, and the
selection confidence threshold — via the existing `_EDITABLE_SETTINGS_KEYS` allowlist (boolish values
auto-render as toggles, no frontend change). **Prerequisite:** the kv-storage cache-invalidation
webhook must be live, or a toggle takes 20 minutes to apply and reads as broken.

### E · UI sub-0.5s at any load *(owner-specified)*
Dashboard and sync UI both **stuck loading** right now. Target **under 0.5s cold, at 180,000 rows**.
Structural, not cached: counts maintained on write in a stats table; keyset pagination, never OFFSET;
precomputed month buckets; live source walks behind a per-pipe opt-in; unmeasured returns `null` +
`*_computed:false`, **never a fabricated 0**. Progressive fill after first paint.

### F · The 50k E2E *(owner-specified shape)*
Real documents through the real pipeline — no SQL seeding. 25,000 via the local mail engine as emails
carrying 1–3 documents each; 25,000 via the second source path; ~24:1 gdoc:bs both sides. Generated by
**apitools `POST /docGen`** (typed models → real PDF/PNG with ground truth) — **`my-docs` is not a
generator**, confirmed by reading it. Injected through the existing **`bbox indox demo`** declarative
blueprint mechanism, extended additively — not a parallel harness. **Prove at 1,000 first.**

### G · Consolidation
**66 workflows → 38.** The v1 legacy engine (`SyncScanner00001`, `SyncScanUnit0001`) is still `active`
and running alongside v3 — `Sync Scanner` returns 0s on all 22 runs. 9 test/E2E workflows are active in
production; 3 have no trigger node and n8n retries them every 256 seconds forever. One data gateway
(`indoxDataGateway01`, deployed), one identity function, generated trigger schemas, gates that make
each defect class unrepresentable.

### H · Small features
Open-execution button in any-concurrency span previews → `n8n/workflow/<wfId>/executions/<execId>`,
shown only for n8n-backed spans with both ids.

---

## Prerequisites for the 50k E2E

Non-negotiable — running before these land produces garbage:

1. The 94% failure mode explained and recovered from automatically **(A)**
2. Per-document cost understood, hash-miss path quantified **(B)**
3. Thumbnail step removed **(C)**
4. Incremental discovery wired live — built and proven at **12.1s → 1.7s, ~7x**, with exact
   message-set equivalence, but `SyncSource000001` still calls the full-window path
5. Data gateway rewired so 65 unvalidated writers cannot bake defects into 3 years of data

---

## Honest ceilings

- **3,000/hour is not reachable** on this architecture: scheduling ceiling 800/hr (`Take X` bounds by
  `chunk`), realistic 230–380/hr on a 16-slot pool. Reaching it needs dozens of worker slots and host
  RAM to match — **infrastructure, not workflows**.
- **5,000/month (~7/hr) is very reachable.**
- **50,000 documents at 230–380/hr is 5.5–9 days.** At the true fresh-document cost it may be longer.
  That is why the ceiling work (B) precedes the E2E (F).

---

## Blocked on the owner

1. **Drive folders** — `מסמכים כללים` does not exist and the service account cannot create it (by
   design: it only moves files). Create and share with
   `person7@example.com`. Same for dedicated
   `synced`/`failed` folders to resolve the `drive-gdoc-warehouse`/`drive-bs` collision.
2. **`gh auth login`** — GitHub Actions status otherwise unobtainable.
3. **A real `TELEGRAM_BOT_TOKEN`** — `.env:299` is the literal placeholder; Error Handler fires but
   Telegram 404s, which is why it still shows red.
4. **Where the 5,555 `(בוריס)` files route** — wired to no registry, so "move them back" has no
   destination anyone can name.
5. **One `UPDATE`** the permission classifier blocked, to repoint `indoxDocUploader01`'s dangling
   `errorWorkflow` at `errorHandler01`.

---

## Standing rules

Snapshot `sync_registry` before every QA run and diff after — it has caught two regressions already ·
measure **cold**, never warm · assert effects, not appearances · never a fabricated `0` · every gate
proven able to fail · deploy only via `bbox n8n push`, **one at a time** · do not touch the tuned
batching settings.
