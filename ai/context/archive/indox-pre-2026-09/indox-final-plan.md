# INDOX — the final version, and how to get there

> **Historical analysis.** The canonical current execution plan is
> [indox-mechanical-production-plan.md](indox-mechanical-production-plan.md).
> This file preserves the investigation and corrections that led to it; do not
> use the historical phase/status claims below as current completion evidence.

Written as INDOX product owner, 2026-07-29, after three parallel research passes (tenancy model, the
sim's intended design, the n8n execution side). Every claim is marked **[V]** verified against code or
a live query, or **[I]** inferred. Where an earlier document of mine was wrong, it is corrected here
explicitly rather than quietly.

---

## 2026-08-03 implementation review — supersedes stale status below

The architecture analysis below remains useful, but its implementation status is historical. A
code-and-production review on 2026-08-03 established and shipped the following **[V]**:

- Console registry CRUD now validates complete Drive/Gmail contracts, stores folder IDs rather than
  paths, requires archive/failure destinations for Drive, defaults production pipes to `engine:v3`,
  a real processor, and `projection:on`, and creates Drive folders through the owning service.
- SCAN is live. Main propagates either `connection` spelling, Deliver records each Drive file ID as
  `SOURCE_ID`, and the canonical blueprints were pushed to n8n.
- Board, status, and reconcile use the pipe's declared live connection. The audited Google folder has
  five files; all five are visible, status reports `waiting:5`, and reconcile reports all five as
  `delivered_not_moved` rather than returning the first divergence or a false zero.
- Status is scoped before source collection. `?sync=drive-לסינכרון-3` now reports only that pipe; its
  sole partial result is the known malformed failure location.
- Document joins and fallback classification now use `(CONNECTION, SOURCE_ID)` inside the active
  instance table. A bare `SOURCE_ID` cannot select another connection's row. Legacy rows with a null
  connection are readable only when unambiguous.
- Pipe names with ledger rows cannot be renamed or deleted. Live rename and delete attempts against
  the five-row pipe both return `400`, preventing orphaned idempotency state and re-delivery.

The five production files are intentionally not replayed or moved yet. Their ledger says delivered,
their document rows came from the old thin path, and the source files remain in the input folder.
That evidence is a repair case, not permission to reset the ledger.

### Final ownership and identity model

There are three different concepts; combining them creates either duplicates or frozen credentials:

1. **Source identity (immutable):** `(instance, connection, source_type, platform_id)`. This is the
   unique identity used by document joins, updates, downloads, moves, dedupe, and reconciliation.
2. **Source revision (versioned):** provider revision/ETag/content hash. A changed remote resource is
   a new processing input under the same identity, not a different source.
3. **Processing provenance (append-only):** engine, processor workflow ID, processor version,
   extraction model/query version, connection profile revision, run ID, and timestamps. Profiles and
   engines do not belong in source identity: rotating credentials or upgrading the processor must not
   make an unchanged file a new source document.

The `connection` is the stable Platform OS catalog reference. Drive/Mail/Connections own profile
resolution and credentials; INDOX stores no credential ID. This permits safe download and rename in
a multi-engine, multi-profile deployment without binding documents to expiring secrets.

### Final component boundaries

| Owner | Owns | Must not own |
|---|---|---|
| Connections | Stable connection ID, profile selection/revision, health, credentials | INDOX pipe state |
| Drive/Mail | List, metadata, download, rename, move/labels, provider revision | Document classification or ledger |
| INDOX BFF | Validated registry, source adapter, board, document identity, reconcile/repair API | Provider credentials or duplicate source logic |
| sync-v3 | Claim, processor invocation, document record, projection request, attempt state | UI-selected active instance |
| Processor | Pure `work item -> result`, including provenance | Source moves, ledger mutation, tenant discovery |
| Database | Registry/config, claims, ledger, projection state, documents, provenance | Cached provider truth presented as live state |
| Console UI | Connection-first authoring and explicit operator actions | Constructed folder paths or workflow defaults |

Every source-facing surface calls one primitive:

```text
LIST(instance, connection, source_type, location)
  -> checked + canonical items[(platform_id, revision, metadata)]
```

An unavailable source returns `checked:false` plus a reason, never an authoritative empty list.
Board, status, reconcile, run discovery, and repair use the same adapter contract. A short cache is an
implementation detail keyed by the full source identity and invalidated after mutations.

Delivery is a durable state machine, not an implied transaction across HTTP systems:

```text
discovered -> claimed -> processed -> recorded -> projected
                    |          |           |
                    +-------- failed / repairable divergence
```

`recorded` and `projected` are separate facts. A projection failure is persisted as
`recorded_not_projected`; retries project the existing document and never process or insert it again.
A provider timeout is reconciled by observing the actual source location before retrying the move.
The operator sees and can repair every nonterminal state.

### Ordered completion and deletion plan

1. **Repair prerequisites:** create/select the real `נכשל` sibling through Console; save the live
   pipe's source/archive/failure IDs, processor, and projection without running it. Preserve the five
   source listings, ledger rows, document rows, and folder contents as evidence.
2. **Projection repair:** add an idempotent `project existing delivery` operation keyed by the source
   identity. Prove one non-zero file moves to `בוצע`, retains one document row, and reconciles cleanly;
   then repair the other valid files. Quarantine or explicitly reject the zero-byte JPEG.
3. **Durable delivery state:** add projection status/error/timestamps and processor provenance. Make
   claim expiry, record retries, and projection retries explicit; never use `continueOnFail` to turn a
   partial delivery into success.
4. **Complete identity migration:** backfill connection/source type where evidence is deterministic;
   leave unknown origins null; add the unique/index contract for
   `(instance, connection, source_type, platform_id)`; convert every BFF and workflow read/write from
   bare `SOURCE_ID`. Add source revision and provenance separately.
5. **Registry concurrency:** replace the `settings.sync_registry` JSON read-modify-write with a
   validated table and optimistic version (or row lock). Keep pipe name immutable after first claim.
   Validate connection/location existence and published processor capability at save time.
6. **Dynamic tenancy:** work items carry instance from registry enumeration through Unit, processor,
   Deliver, ledger, and document write. Remove every hardcoded `incoming-documents-main`. Store active
   instance per authenticated operator; scheduled work never reads that UI preference.
7. **Config ownership:** scope settings, companies, and rules by instance. Mail owns provider labels;
   INDOX owns only the mapping from source location to processing action. Shared OCR caches remain
   content-addressed and intentionally cross-instance.
8. **Retire duplication:** after all live pipes use v3 and parity gates pass, remove v1/v2 invocation
   edges first, prove zero references, then delete their workflow exports and obsolete reset/demo
   harnesses. Do not delete old processors merely because their filenames look legacy.

### Mandatory release gates

- Contract tests: invalid registry data, immutable used pipe name, full identity collision, ambiguous
  legacy rows, connection-aware download/move/rename/classify.
- Parity test: BFF LIST, board, status, reconcile, and sync-v3 Unit return the same platform IDs.
- Failure injection: processor failure releases/expires claim; record retry creates no duplicate;
  move timeout reconciles actual state; projection failure remains visible and repairable.
- Tenancy test: two instances with identical pipe names and colliding platform IDs run concurrently on
  different connections with no config, ledger, document, or source-action leakage.
- Production canary: one document reaches one row and the archive, replay is a no-op, and reconcile is
  green. Only then scale the operation.
- Executable gates: focused Python contracts, frontend build, blueprint validation, `bbox indox test`,
  live flow QA, and a production read-only reconcile report.

The deletion criterion is behavioral parity plus zero invocation references, not age. Until these
gates pass, v1/v2 are migration inputs; after they pass, keeping them is ambiguity and they go.

---

## 0 · Corrections to what I previously reported

I wrote in `indox-product-state.md` that the sync screen "does all of it — verified call-by-call". That
sentence was true of the **UI** and false of the **system**. I checked that the client calls those
endpoints. I did not check that the endpoints do anything. Three of them do not:

| I said | Actually **[V]** |
|---|---|
| "run one / run all" works | **The run button is a no-op.** The BFF posts `{"INLINE_ACTION":"SCAN"}` to `/webhook/indox-manage`. That webhook's switch declares exactly three verbs — `RESET`, `STATUS`, `INJECT` — with `fallbackOutput:"extra"` wired to the *INJECT-not-implemented* node, which returns HTTP 200 `{ok:false,error:'…not yet implemented'}`. The BFF only treats transport errors as failure, finds no `claimed` key, returns `claimed: 0` — and then stamps `last_run`. A green button, a fresh timestamp, and nothing ran. |
| "move items between states" is a real 4-state machine | **`in_progress` is never occupied.** Under the v3 engine nothing claims: the `in_progress` label is only ever *removed*, never added, and `ctx.in_progress` is passed to the drive processor and never read. Items go `to_sync → synced\|failed` in one hop. |
| "`stuck` needs a `claimed_at` column" | True but understated: **there is no claim event to stamp one from.** `batch.timeout_min` is read by zero lines in the entire repo. The stuck banner, BigStat, filter chip and "תקוע" tag are permanently zero. |
| Instances are "real for documents" | **Read-only-real.** All 53 document-touching n8n nodes name `incoming_documents` literally; zero workflows call the repo-scoped `PUT /repos/<r>/documents`. A second instance's table would never be written to. |
| The creation wizard works | **It cannot provision a supabase instance.** `provision_repo` → `create_schema` → `POST /rest/v1/rpc/run_sql`, and that function does not exist (`404 PGRST202`; `pg_proc` has only `touch_updated_at`). Verified independently. |

I also said INDOX has "three surfaces, and only three". It has **six** tabs; three are the product
spine and `הגדרות`/`בדיקות`/`חילוץ מסמכים` are supporting surfaces.

The lesson I am taking from this, and the reason the plan below is ordered the way it is: **for this
app, "the UI calls it" and "it works" are independent facts, and only the second one counts.**

---

## 1 · What the system actually is today

**The pipeline is `sync-v3`, and its memory is a ledger, not a location. [V]**

```
Sync v3 Reconcile (schedule 15m) → reads settings.sync_registry → builds units
  → Sync v3 Source Unit  → LIST (drive folder | gmail search)
                         → DIFF  (SQL anti-join vs public.sync_ledger)
                         → take batch.take (default 25)
  → Sync v3 Deliver      → run processor_wf → RECORD to ledger → project label/folder
                         → on error: ATTEMPT (backoff) → quarantine at max_attempts
```

The unit comment says it outright: *"under v3 the ledger is the loop memory, labels are a billboard
(never read back for scheduling)"* **[V]**.

That **contradicts the design rule** the sim states —

> *"state lives in the source (folder/label); the table is downstream."* — `INDOX-SYNC-PORT.md` §0

— and the contradiction is not academic. It means the operator board's mental model ("move the card,
the source moves, the pipeline follows") does not describe this pipeline. Moving an item's label today
changes what `LIST` returns but **not** what `DIFF` admits, because `DIFF` consults the ledger.

**Two silent divergence modes exist and nothing detects either [V]:** a successful `RECORD` with a
failed move leaves the file in `to_sync` forever *and* invisible to DIFF; a successful move with a
failed `RECORD` leaves no ledger row and no listing — permanently lost.

**Data reality [V]:** `settings` is a 71-key flat key/value bag (`key` is the PK); `companies` (6 rows)
and `tag_rules` (23) are real tables; `incoming_documents` has 84 columns, 136 rows. RLS is off on all
19 tables, and `service_role`/`postgres` both carry `rolbypassrls` — so RLS cannot be the tenancy
mechanism. 112 n8n Postgres nodes share one static credential; 0 use PostgREST.

---

## 2 · The target

Unchanged in ambition, stated precisely:

> An INDOX **instance** is a tenant: one target table, one settings/companies/tag-rules/queries set,
> one sync registry. Exactly one active, switched from a top-bar chip that also creates new ones.
> **מסמכים** is the table, one click, with the instance's identity above it. **סנכרון** is the only
> place a pipe exists — config, live counts, connection health, failures grouped by cause, and every
> action — plus an operator board that moves items along a state machine the server enforces. Pipes
> are authored connection-first over the platform's shared Drive/Mail catalog.

**One deliberate change to the target.** The sim's 4-state board assumes a claim. This pipeline has no
claim. Rather than fake one, the board should present **the states the system actually has** —
`to_sync · synced · failed`, plus `in_progress` **only once a real claim exists** (phase 3). A column
that is structurally always empty is worse than an absent column: it teaches the operator that nothing
is ever in flight.

---

## 3 · The plan

Ordered by dependency, and by a rule: **make things true before making them richer.** Phases 0–2 make
the existing UI honest. Phases 3–5 add capability. Phase 6+ is tenancy, which nothing else depends on.

### Phase 0 — stop lying (small, urgent)

| # | Change | Why |
|---|---|---|
| 0.1 | `_scan` must treat `{ok:false}` as failure, not success, and must not stamp `last_run` on a no-op. | A green run that did nothing is worse than an error. |
| 0.2 | Until SCAN exists, the run buttons should say what they do — or be disabled with a reason. | The UI currently claims a capability the system lacks. |
| 0.3 | Hide the `in_progress` column, stuck banner, stuck BigStat, "תקוע" tag and `?stuck=1` chip behind a capability flag that is **off** until phase 3. | They are permanently zero; they train the operator to ignore the board. |
| 0.4 | Fix the three literal-table bugs: dashboard `:2718`, sync-board join `:940`, apply-fallback write `:2279` must use the active repo's table. | Today they read/write `incoming_documents` regardless of instance. |
| 0.5 | `GET /accounts` must pass `counts` (`:1595`) — it always reports `settings/companies/tag_rules = 0`. | The switcher shows three zeros for every instance. |
| 0.6 | Instance-key the four sync caches (`:902,931,951,1894`). | A switch inside the TTL serves the previous instance's data. |

**Verify:** run a pipe and assert the response is now an honest failure; snapshot `/dashboard/stats`
before/after with a second repo registered.

### Phase 1 — implement SCAN (the run button)

Wire a real `SCAN` verb: add it to `SyncApi0000000001`'s switch and to `indoxApiRouter01`'s
`If Management` list, dispatching to `syncV3Main0001`. Add a **source-name filter** to
`Build Units` — it currently builds units for the whole registry and accepts only `registry_key`, so
scoped run does not exist even in principle **[V]**.

**Verify:** `POST /sync/registry/<name>/run` returns a real `claimed` count; a second pipe's ledger is
untouched; the 15-minute schedule still behaves.

### Phase 2 — make the registry the whole contract

The live registry rows lack `enabled`, `last_run`, `connection`, `fallback_type` **[V]** — the exact
fields the new UI writes. The BFF's `setdefault` will materialise them on first PATCH, which means the
first edit through the UI silently changes the shape n8n reads.

- ~~Migrate the five rows explicitly rather than by side effect.~~ **Done, differently and better.**
  A migration is a thing someone has to remember to run, and a second write path is a second place the
  shape can drift. `_normalise_entry` in `_write_sync_registry` is the one gate every write goes
  through, so the rows repair themselves on first touch and no future endpoint can bypass it.
- ~~`enabled` honoured server-side~~ **Done in Phase 1** — `Scan Guard` refuses a paused pipe with
  `code:"disabled"`, and `Build Units` skips it on schedule, run-all and scoped run alike.
- ~~Decide `batch.page_size` vs `batch.chunk`~~ **Decided: neither is the bug.** v3 reads `page_size`
  and defaults to 50; `chunk` is v1's delivery batch and every live row is `engine:"v3"`, so `chunk`
  is read by nobody. The damage was not the naming, it was that the drawer *sent* both as hardcoded
  constants and the BFF replaced the whole `batch` object — so editing a schedule rewrote knobs the
  operator never saw. Fixed by merging `batch` key-wise and sending only what the drawer shows.
- ~~Split `fallback_type` from `type_hint`~~ **Done** — two controls, the hint following the fallback
  until they diverge.
- **Also found and fixed, not on the original list:** the editor and the engine used different names
  for a drive pair (`{from,to}` vs `{to_sync,synced}`), so existing pipes rendered as
  "תיקייה — → —" and UI-authored pipes listed nothing; opening a pipe pre-filled *empty* folders and
  saving wrote the blanks back; and saving a 3-pair pipe deleted two of its pairs.

**Moved to Phase 3: per-pipe `schedule_min`.** The sim gives every pipe its own cadence (5/10/15/20/
30/60). Live has one 15-minute `scheduleTrigger` on `syncV3Main0001` that sweeps the whole registry,
and `schedule_min` is read by zero lines. Honouring it needs a per-pipe `last_run` written by the
*scheduled* path — and n8n writing back into the single `settings.sync_registry` JSON blob races the
BFF's read-modify-write PATCH, which is a lost update. Phase 3 already has to build a state store for
`claimed_at`; per-pipe `last_run` belongs in it, with the same locking story, rather than bolted on
here. Until then the field stays (removing it would diverge from the sim) and the UI states the real
cadence instead of the stored intention.

**Verify:** `./bbox indox test` sync lanes green after each field lands.

### Phase 3 — a real claim, and only then a 4-state board

Introduce the claim the model needs: a pre-delivery row (ledger `status='claimed'` with `claimed_at`,
or a `sync_attempt`-shaped claim record). Then `stuck` = claim age vs `batch.timeout_min`, and
`batch.timeout_min` stops being decorative.

**Put per-pipe `last_run` in the same store** (moved here from Phase 2). It is the same problem —
pipeline-written state that the BFF must read without the two clobbering each other — and solving it
twice is how the two answers diverge. Once `last_run` is written per pipe by the scheduled path,
`Build Units` can skip a pipe that is not yet due, `batch.schedule_min` becomes real, and the
reconcile tick drops to the smallest configured cadence. Note the tick must be ≤ min(`schedule_min`)
or the smallest cadences are silently rounded up to the tick.

Re-enable the `in_progress` column and everything gated in 0.3.

**This phase is what makes 0.3 legitimate, and it is not optional.** The brief is that live INDOX
matches the simulation, and the simulation draws all four states. Gating them off makes live *honest*
about a capability it lacks, at the price of making it *smaller* than the sim — a deliberate trade
that only pays off if it is temporary. So the flag is a countdown, not a setting:

* The server flips `capabilities.claims` to `true` here. No UI change ships with the flip — every
  gated surface is still in the code, still styled, still tested, and returns unmodified. If a
  surface needs editing to come back, 0.3 hid it wrong.
* `NO_CAPABILITIES` must never become a supported configuration. There is no operator control for
  it, no setting, no env var: after this phase the only thing that can report `claims:false` is a
  BFF that is genuinely older than its engine.
* **Parity is not restored until the pixel diff of `INDOX · סנכרון` against the sim is clean again.**
  Until then, live is knowingly behind the sim on this one surface, and that debt belongs in the
  status report every time it is given — not silently carried.

**Verify:** kill a delivery mid-flight; the item shows `in_progress`, then `תקוע` after
`timeout_min`; `שחרר` returns it to `to_sync`. Then re-run the sim/live diff for the sync surface and
confirm the four-state board matches.

### Phase 4 — reconcile ledger and location

Close the two silent divergence modes: a move without a `RECORD`, and a `RECORD` without a move. A
periodic reconcile that reports (not auto-fixes) disagreements, surfaced on the sync screen.

**Why here:** phase 3 makes the board trustworthy for in-flight work; this makes it trustworthy for
work that already went wrong.

### Phase 5 — finish the authoring flows

- The creation wizard's step 3 should **reuse the pipe editor** (connection → that account's real
  labels/folders, with create-inline) rather than free-text. The design specified this and neither the
  sim nor live does it **[V]**. Add the review step (design says 4 steps).
- Surface `failed_folder` — it is seeded on drive pipes and read by no UI and no create path **[V]**.
- Put the **instance chip in the sync header**. The design's reason is the right one: *"the registry is
  per-instance, and forgetting that is how you edit the wrong company's pipes."*

### Phase 6 — tenancy

**Recommendation: an `instance` column on the INDOX-owned config tables; keep table-per-instance for
documents.** Two mechanisms, each where it fits, said out loud in the code.

Why a column and not a schema or a prefix:
- **No infrastructure change.** PostgREST exposes only the schemas in `SUPABASE_PGRST_DB_SCHEMAS`
  (verified: `Accept-Profile: auth` → `406 PGRST106`), so schema-per-instance needs an `.env` edit and
  a `supabase-rest` restart per client — an instance-creation flow the switcher cannot offer.
- **It rolls out additively.** `default '<first-instance>'` makes phase 6.1 a provable no-op: same 71
  settings rows, byte-identical API responses. Schema/prefix models are all-or-nothing per node,
  because the name is baked into 112 SQL strings.
- **It degrades in the right direction.** An unconverted n8n node keeps reading the default instance —
  wrong only once a second instance exists. Under schema/prefix it reads a table that no longer
  exists: a hard break for the whole deployment at push time.
- **It matches the grain.** `sync_ledger`/`sync_attempt`/`sync_cursor` are already scoped by a
  discriminator column (`source`). This is the same move one level up.

Documents stay table-per-instance because that is where a separate table earns its keep: 84 columns
that differ per client, a `gsheet` backend with no concept of a discriminator, per-client
export/delete, and `uq_incdoc_hash` whose dedupe semantics would have to change under a column model.

**Ordered steps** (each independently shippable; do not create a second instance before 6.6):

1. **Unblock provisioning** — add `public.run_sql` (`security definer`, `service_role` only) or route
   DDL through the fixtures path. Without this `POST /account/add` cannot work at all.
2. **DDL, additive** — `instance text not null default '<first-instance>'` on `settings`, `companies`,
   `tag_rules`; PK → `(instance,key)`; unique → `(instance,"מזהה 1")`. The default is the existing repo
   name, so **existing data carries over with no backfill and no cutover window.** Writers change in
   the same commit (`on_conflict` → `"instance,key"`).
3. **One resolver in the BFF** — `_scope() → (instance, doc_table)`, threaded through all 23 hardcoded
   sites. Make it a required argument so a missed site fails to compile, not at runtime.
4. **`sync_registry` per instance**, and **namespace the sync name** (`<instance>/<sync>`) — otherwise
   two instances with a pipe called `drive-gdoc` collide in `sync_ledger` (PK `(source, platform_id)`)
   and fight over `sync_cursor`.
5. **n8n via the chokepoints** — `Build Table Get`/`Build Table Upsert` in `indoxApiSupabase01` already
   gate the five config tables behind an `ALLOW` map; add `instance` there and **throw** when absent.
   That converts the whole v3 engine in two Code nodes. Then the finite v1/reset/test tail. The
   scanner is the one that must read *across* instances and fan out.
   Land a lint (`workflow-input-lint.py` already walks the blueprints) that fails any SQL naming
   `settings`/`companies`/`tag_rules` without an `instance` predicate — a forgotten filter is the one
   failure mode of this design, and it is silent.
6. **The documents write path** — route writes through the repo-scoped BFF endpoint rather than
   rewriting 53 nodes. It already carries the diff engine that `Build Match Index SQL` duplicates.
7. **Per-user active instance** — `active_instance.json` is one file per deployment **[V]**, so two SSO
   operators share one selection; one switching companies re-points the other's screen mid-task.

**A constraint that shapes phase 6 and must not be forgotten:** the UI's "active instance" and the
pipeline's "instance for this execution" are different resolutions of the same identity. A scheduled
scan cannot read a global active pointer — that would make a running pipeline follow whatever a human
last clicked. The pipeline must derive the instance from the work item; the only runtime identity it
already carries is the sync name.

---

## 4 · What cannot be per-instance, and why

- **`drive_files`** — owned by the Drive app. Two instances on the same Drive account see each other's
  folders unless their registry pairs differ. Configuration discipline, not something INDOX enforces.
- **Gmail labels** — owned by the mail service; per mail account. Independent label semantics require
  independent mail connections.
- **The 82 workflows and their credentials** — one copy per deployment, 111 nodes bound statically to
  one credential. Per-instance behaviour must be **data**, never a workflow fork.
- **`ai_extraction_cache` / `ocr_cache`** — keyed by content hash. Sharing across instances is the
  point: the same supplier PDF arriving at two clients should be OCR'd once. Keep global, deliberately.
- **`perf_*` settings** (9 keys) — they size the pipeline to the host, not the client.
- **Webhook paths** — two instances cannot both own `/webhook/indox-manage`.

---

## 5 · Also true, and worth fixing on the way past

- **Renaming a pipe is catastrophic and silent [V].** `name` is the ledger PK component, and all five
  processors hardcode `SYNC_NAME` as a literal. A rename orphans every ledger row → full re-delivery,
  with duplicate protection only on the thin path. The UI offers rename freely.
- **`Synced Label Ops` falls back to `||k`** — if the labels map is missing it applies the KEY string
  as a literal Gmail label, silently creating the wrong label rather than failing.
- **The label engine has not moved to the mail app** — only step 0 of the 8-step refactor is done.
  INDOX still owns `tag_rules` CRUD, and the engine calls back into `indoxApiRouter01` for its own
  rules (a layer inversion).
- **`PORT-STATUS.md` says "INDOX — not started"**, two days stale.
- A dormant Google Sheets branch in `indoxDocBatchUpsert01` carries a hardcoded spreadsheet id.

---

## 5b · Added to the brief after phase 2 (2026-07-29)

Three requirements arrived mid-flight. Two of them change decisions, so they are recorded before the
work that would otherwise have to be redone.

### Phase 6b — *prove* parallel instances, don't assert them

"Make sure the n8n engine is fully compatible with the multi-instance plan **and prove it**." Phase 6
as written stops at "tenancy exists". That is not the ask. The deliverable is a reproducible script
and its output showing two instances — each with its own target table, settings, companies, tag rules
and registry, on different connections — reconciling **at the same time**, with a canary in each
proving no leakage in either direction. Every workflow on the path (`syncV3Main0001`,
`syncV3Unit0001`, `syncV3Deliver0001`, `syncLedgerApi01`) has to carry the instance end to end.

The sharpest constraint is the ledger PK. `sync_ledger` is keyed `(source, platform_id)` where
`source` is the *pipe name*. Two instances that both define a pipe called `drive-gdoc` — which is
exactly what duplicating an INDOX gives you — would share ledger rows and each would see the other's
deliveries as already-done. **The instance has to be part of that key**, or duplication silently
cross-wires the two instances' idempotency.

### Phase 7 — connection identity, so two drives cannot mix

Raised by the user, and correct: once a pipe chooses its connection, two *different* drive
connections (local drive and gdrive) can feed one INDOX table. Three things break, all quietly.

1. **`platform_id` is only unique within a connection.** File id `123` can exist in both. The ledger
   is namespaced by pipe name so it survives, but any dedup or join on `platform_id` alone does not.
2. **`LINK` bakes an absolute URL** for whichever backend delivered the row, so the column means
   different things on different rows of the same table.
3. **"Open the original" has no way to know which drive it meant.**

The fix is the one the user named — abstract it at the API layer. Carry `connection` on the registry
entry, through `RECORD` into the document row, and resolve links through a `(connection,
platform_id) -> URL` resolver rather than storing a resolved URL. Verified by pointing two pipes with
a deliberately colliding `platform_id` at one table and showing both still resolve correctly.

### Phase 8 — the dashboard has to go somewhere

Every dashboard observation should open the documents table **filtered to exactly that observation**,
and the quick actions should be reachable both from there and from a multi-select in the table:
jump to the line, add as a test document, add the company in settings, apply the fallback type,
retry. The single-document view must be the extraction testing UI's view — drawn extraction image,
OCR drawing, original document — **reusing those components, not reimplementing a thinner copy**. A
second implementation of the same view is how the two drift, and the extraction UI is already the
better one.

---

## 6 · The shortest honest summary

The UI for the final INDOX is largely built and, in places, ahead of the system underneath it. The
gap is not screens — it is that **the run button does not run, nothing is ever in progress, and a
second instance would be written to by nothing.** Phases 0–3 close that gap and cost far less than the
UI already did. Tenancy (phase 6) is a bigger piece, but it is additive, provably a no-op on day one,
and independent of everything above it — so it should not block making today's single instance true.
