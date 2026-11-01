# INDOX Production Completion Plan

**Status:** canonical execution plan  
**Evidence cut:** 2026-08-03  
**Scope:** Sync, Document State Machine, data model, Console operations, tests,
observability, migration, recovery, and legacy retirement.

This is the one current INDOX plan. Historical analysis in
`indox-final-plan.md`, `indox-gap-audit-2026-08-03.md`, and older port plans is
input, not execution authority. A statement in this document is either a
verified current fact, a target contract, or an explicit gate; no historical
"done" claim is carried forward without current evidence.

## 1. Outcome and non-negotiable invariants

INDOX is complete when an operator can create a pipe in Console and every source
item moves through one observable, recoverable path:

```text
connection/profile -> source observation -> claim -> processor -> document record
                   -> projection -> verification -> terminal source state
```

The following invariants are release blockers:

1. **Immutable source identity** is
   `(instance, connection, source_type, platform_id)`.
2. **Provenance is not identity.** Source revision, connection profile revision,
   provider engine, processor/model/query version, run ID, input/output hashes,
   and timestamps may change without creating a second source identity.
3. **Observed source state, work state, and document state are separate facts.**
   `in_progress` is derived from a live claim; `recorded` is not `projected`.
4. **Every mutation is tenant-scoped and connection-scoped.** A bare
   `SOURCE_ID`, table row ID, pipe name, active UI instance, or stored URL is
   never sufficient authority for a source or document action.
5. **Provider credentials remain owned by Connections/Drive/Mail.** INDOX stores
   a stable connection reference and observed profile revision, never a secret.
6. **Retries are idempotent.** Replaying discovery, record, or projection cannot
   duplicate a document, processing run, or provider mutation.
7. **No false green.** An unavailable source is `checked:false`; an engine body
   with `ok:false` is failure; a delivered ledger row with an unprojected source
   is visible divergence.
8. **One owner per behavior.** UI capabilities come from the BFF, source actions
   come from Drive/Mail, work transitions come from Sync, and document decisions
   come from the processor contract.

## 2. Verified current state

### Working and retained

- The BFF resolves the active instance, scopes registry/config reads, lists the
  selected remote Drive connection, and reports partial source errors honestly.
- Board/status/reconcile use the declared connection. Reconcile reports every
  `delivered_not_moved` and `moved_not_recorded` item, but is read-only.
- Claims are durable `sync_ledger.status='claimed'` rows with `claimed_at`;
  `RECORD` promotes the claim and `RELEASE` removes only claims.
- BFF document reads and fallback type updates use `(CONNECTION, SOURCE_ID)` with
  a narrow, unambiguous null-connection compatibility fallback.
- Used pipe names cannot be renamed or deleted while ledger rows reference them.
- Board items expose `platform_id`; source links resolve at read time through
  `GET /sync/origin` and the selected connection.
- The server publishes manual transitions and both Sync UI surfaces consume the
  same capability matrix.
- `.github/workflows/indox-e2e.yml` runs `bbox indox test all` and then the
  existing 100% Sync-v3 node-coverage gate.
- Focused BFF sync contracts pass (12 tests) and the current frontend production
  build passes. These are focused proofs, not a full release proof.

### Incomplete or unsafe

| Area | Verified gap | Consequence |
|---|---|---|
| Projection | `syncV3Deliver0001` records, then moves/labels; there is no `sync_projection` state or repair endpoint. | A provider failure leaves a delivered row permanently in the input location. |
| Production divergence | Five rows in `drive-לסינכרון-3` are recorded but still observed in `to_sync`. | They are not fully delivered and must not be replayed. |
| Registry | Pipes remain one JSON value in `settings.sync_registry`. | Read-modify-write races, weak revision history, and awkward referential checks. |
| Identity schema | Documents have nullable `CONNECTION`, but no canonical source table or full-key uniqueness contract. | Legacy ambiguity and workflow-level bare-ID operations remain possible. |
| Processor contract | V3 Deliver invokes compatibility processors which call the v2 decision/action graph. | Instance, revision, and provenance are not guaranteed end to end. |
| Dynamic tenancy | Production workflows such as `indoxSettings01` and parts of the v2 graph still pin `incoming-documents-main`. | A second instance can read first-instance config. |
| Config writes | Some row PATCH paths select/update by surrogate row ID without adding the active instance predicate. | A crafted request can target another instance's row ID. |
| Provider ownership | INDOX workflows still perform Mail label operations and carry legacy Drive behavior. | Source semantics are duplicated outside the owning adapters. |
| State Machine evidence | Document/base, BS, GDoc, and pipeline suites exist, but there is no State Machine graph-coverage gate. | Green scenarios do not prove all decision/action branches executed. |
| Python CI | `requirements-dev.txt` and focused contracts exist, but incoming-documents pytest is not wired to CI. | BFF identity and transition regressions can merge. |
| Multi-instance proof | `prove-two-instances.sh` is manual, uses direct Docker/container assumptions and sleeps, mutates an A-instance canary, and mainly proves SQL namespacing. | It is not a safe CI or profile-isolation proof. |
| Operations | Projection alerts, structured run correlation, backup/restore rehearsal, and repair runbooks are absent. | Incidents depend on manual database/workflow archaeology. |

Two audit claims are explicitly rejected as stale: SCAN is now wired and guarded
against false success, and current reconcile does report all five audited Drive
divergences. Any future claim about live state must include a timestamped command
artifact because runtime evidence expires.

## 3. Target ownership and runtime architecture

| Owner | Owns | Forbidden responsibility |
|---|---|---|
| Connections | Stable connection ID, active profile, profile revision, health, credentials | Pipe state, document state |
| Drive/Mail | List, metadata, download, provider revision, move/labels, post-mutation verification | Classification, claims, ledger |
| INDOX BFF | Registry API, identity-safe document API, board, capabilities, reconcile/repair orchestration | Credentials, direct provider implementation |
| Sync-v3 | Discovery, claim, processor dispatch, record handoff, projection scheduling, retries | Active UI instance, provider-specific code |
| Processor | Versioned work item to deterministic result and provenance | Source moves, claim/ledger mutation, tenant discovery |
| Database | Durable registry, identity, work, projection, provenance, audit facts | Pretending cached provider state is live truth |
| Console | Connection-first authoring, status, evidence, explicit legal repair commands | Defaults invented independently of BFF contracts |

All source consumers use one adapter contract:

```text
LIST(instance, connection, source_type, location, cursor?)
  -> {checked, reason?, profile_revision, next_cursor?, items[]}

item = {platform_id, source_revision, name, mime_type, size, observed_at, metadata}
```

All source mutations use the same identity plus an idempotency key and return
observed postconditions. A timeout produces `unknown_outcome`, followed by a
read-before-retry; it never produces assumed success.

### Processor envelope

Every processor entrypoint, including temporary compatibility wrappers, accepts:

```json
{
  "contract_version": 1,
  "run_id": "uuid",
  "instance": "repo-id",
  "pipe_id": "uuid",
  "connection": "catalog-id",
  "connection_profile_revision": "opaque",
  "source_type": "drive|gmail",
  "platform_id": "provider-id",
  "source_revision": "opaque",
  "input_hash": "sha256",
  "processor": {"id": "published-id", "version": "content/version hash"},
  "document": {"repo": "repo-id", "existing_id": null}
}
```

It returns a typed result (`recorded`, `needs_review`, `rejected`, `retryable`,
or `terminal_failure`), document ID, output hash, decision/action events, and
error code. It cannot move/label the source or infer instance from global state.

## 4. Target data model

All changes are additive first. Foreign keys and `NOT NULL` constraints are
added only after backfill reports zero unresolved rows in the gated population.

### Registry

- `sync_pipes`: `id`, `instance`, immutable `name`, `source_type`, `connection_id`,
  `processor_id`, `projection_policy`, `enabled`, `revision`, timestamps and
  actor; unique `(instance, name)`.
- `sync_locations`: `id`, `pipe_id`, `role` (`to_sync`, `synced`, `failed`),
  provider location ID, display metadata, ordinal; unique `(pipe_id, role,
  ordinal)` and no path-as-ID fallback.
- `sync_pipe_revisions`: append-only before/after configuration and actor for
  audit/rollback. Runtime counters stay in `sync_pipe_state`, not config rows.

Writes use optimistic concurrency (`If-Match`/expected revision). Save validates
the connection, profile health, location existence and account ownership,
published processor capability, all required terminal locations, and disjoint
source/destination IDs. A pipe becomes identity-locked after its first claim;
changing identity fields creates a new pipe through an explicit migration.

### Source identity and documents

- `document_sources`: `id`, `instance`, `document_id`, `connection_id`,
  `source_type`, `platform_id`, first/last observed revisions and timestamps;
  unique `(instance, connection_id, source_type, platform_id)`.
- Existing per-instance document tables remain during this program. All access
  goes through the repo-scoped BFF; workflows no longer name a literal document
  table. `document_sources.document_id` is validated by the BFF because the
  physical target table is selected by instance.
- Null-connection legacy rows are excluded from source mutation. They remain
  readable through stored legacy links only when the lookup is unambiguous.

### Work, projection, and provenance

- Evolve `sync_ledger` through additive columns: `pipe_id`, `instance`,
  `connection_id`, `source_type`, `source_revision`, `run_id`, `recorded_at`,
  and `document_id`. During migration, namespaced `source` remains the
  compatibility key; target uniqueness is `(pipe_id, platform_id,
  source_revision)`.
- `sync_projection`: one desired projection per ledger delivery with status
  `pending|attempting|unknown_outcome|failed|verified`, target role/location,
  idempotency key, attempt count, last error/code, requested/verified timestamps;
  unique ledger-delivery reference.
- `sync_projection_attempts`: append-only request/result and observed
  postcondition for diagnosis.
- `document_processing_runs`: append-only envelope, processor/model/query and
  profile revisions, input/output hashes, typed result, errors, timestamps, and
  execution reference; unique `run_id`.
- `document_state_events`: append-only classification/action transitions with
  previous/new state, reason, run ID, actor and timestamp. The document row is a
  current projection of these events, not the only history.

`sync_attempt` remains retry scheduling during migration. It may be folded into
work/projection attempts only after a parity query proves no behavior or history
is lost. `sync_cursor` remains an optimization; deleting a cursor may increase
listing work but must never lose a document.

## 5. State and failure contracts

```text
source observation: to_sync | synced | failed | unavailable
work:               discovered -> claimed -> processed -> recorded
projection:         pending -> attempting -> verified
                                  |    +----> unknown_outcome -> observe -> retry|verified
                                  +---------> failed -> retry|terminal
document:           current status + append-only state/provenance events
```

Manual transitions remain server-owned:

| Command | Preconditions | Durable effect |
|---|---|---|
| `to_sync -> synced` | Source observed, no active claim; explicit skip confirmation | Projection/audit record with `skipped`, then verified provider move/label |
| `in_progress -> to_sync` | Matching unexpired/expired claim exists | Kernel `RELEASE`; never delete delivered work |
| `synced -> to_sync` | Verified source identity and explicit reprocess policy | New source revision/run intent; old provenance retained |
| `failed -> to_sync` | Failure is retryable or operator overrides with reason | Clear retry hold, project source, append audit event |
| repair projection | Recorded document exists and target is known | Observe first, mutate only if needed, verify, never rerun processor |

Required failure behavior:

| Failure point | Required result |
|---|---|
| LIST/profile unavailable | `checked:false`; no empty snapshot, cursor advance, or reconciliation claim |
| Claim race | Exactly one winner; loser is a no-op with evidence |
| Worker death after claim | Claim becomes stuck by age and is safely releasable |
| Processor retryable failure | No document/projection; claim released; backoff persisted |
| Processor terminal rejection | Typed failure and evidence; no false delivered row |
| Document write timeout | Read by full identity before retry; no duplicate document |
| Record failure after document write | Identity-safe recovery binds the existing document |
| Projection timeout | `unknown_outcome`; observe actual provider state before retry |
| Projection failure | Recorded document remains; visible repair item; no processor rerun |
| Connection/profile rotation | Same source identity; new profile revision in provenance |
| Zero-byte/corrupt input | Rejected/quarantined with typed reason before OCR/record success |

## 6. Dependency-ordered implementation program

Each phase has an executable acceptance gate and a rollback boundary. Do not
start a later write cutover until the prior gate is green.

### Phase 0 - Freeze truth and create recovery artifacts

1. Through Console only, correct the malformed `failed` folder for
   `drive-לסינכרון-3` and either configure a valid connection for `drive-bs` or
   explicitly disable it with a recorded reason. Save; do not run.
2. Capture timestamped read-only exports of registry revisions, provider folder
   contents/IDs/revisions, the five ledger rows, matching document rows, attempts,
   cursors, pipe state, reconcile response, and relevant n8n workflow versions.
3. Use repository-supported `bbox` backup/export paths. Record restore commands
   and checksums without embedding secrets. Rehearse restore on a disposable
   database/instance, never on production.
4. Freeze bulk reset/replay and pipe identity edits until Phase 5.

**Gate:** evidence manifest identifies every artifact and all five source IDs;
restore rehearsal recreates row counts and workflow versions.  
**Rollback:** none; this phase is read-only except reviewed Console config saves.

### Phase 1 - Lock contracts in CI

1. Expand Python tests for full identity collisions, tenant-scoped config writes,
   capabilities, origin resolution, registry revisions, and all refusal paths.
2. Wire incoming-documents pytest and frontend build into CI with JUnit/build
   artifacts. Keep the existing n8n suite and Sync-v3 coverage steps.
3. Add static lints for production hardcoded instance names, literal document
   tables, source mutations outside adapters, bare source-ID writes, and workflow
   references to unpublished processors. Allowlist only named disposable fixtures.
4. Replace `prove-two-instances.sh` with a `bbox`-dispatched, event-driven,
   disposable harness. It must not discover containers by name, sleep for
   correctness, mutate instance A, or issue raw Docker/SQL cleanup against live
   state.

**Gate:** CI fails on an injected identity/tenant violation and emits pytest,
frontend, lint, and current Sync coverage artifacts.  
**Rollback:** tests/lints can be reverted independently; no runtime change.

### Phase 2 - Add schema and dual-write identity/provenance

1. Add registry, source, processing, state-event, projection, and attempt tables
   plus nullable compatibility columns and indexes.
2. Introduce one BFF repository API for identity-safe document upsert/read/update.
   Convert the config grid's row existence check and update to include instance.
3. Dual-write `document_sources` and `document_processing_runs` while retaining
   current document/ledger writes. Compare every dual write and alert on drift.
4. Backfill deterministic rows from connection + source evidence. Put ambiguous,
   null, folder-ID-as-file-ID, and conflicting rows in a migration report; never
   guess or choose the first match.
5. Add constraints only for fully backfilled rows, then make the new path the
   read authority behind a reversible feature flag.

**Gate:** backfill is repeatable; zero duplicate full identities; dual-write
comparison is clean for all test lanes; ambiguous rows are enumerated.  
**Rollback:** disable new reads/dual writes; additive tables remain inert.

### Phase 3 - Migrate the registry without a split brain

1. Parse each instance's JSON registry into pipes/locations in one transaction;
   preserve names, connection IDs, processor IDs, enabled state and run state.
2. For one release, JSON remains read fallback only. Writes go to tables and
   update a generated compatibility JSON projection; compare normalized forms.
3. Switch scanner/BFF reads to tables, retain a kill switch to the frozen JSON
   snapshot, and reject stale revisions with `409`.
4. Add Console connection/profile health, canonical ID picker, conflict handling,
   revision history, validate/save-without-run, disable, and clone-as-new flows.
5. Stop compatibility JSON writes only after all readers are proven table-backed.

**Gate:** normalized old/new registries match; concurrent edits produce one
winner and one visible conflict; scanner units are byte-equivalent in fixtures.  
**Rollback:** feature flag reads the frozen JSON snapshot; table writes are kept
for forensic comparison.

### Phase 4 - Establish one processor and tenancy contract

1. Carry the processor envelope from Main through Unit, Deliver, compatibility
   wrappers, BFF document API, State Machine and provenance tables.
2. Replace production `incoming-documents-main` constants with envelope instance.
   Keep explicit test instance literals only in disposable fixtures.
3. Route every document mutation through the repo-scoped BFF; eliminate literal
   `incoming_documents` production writes and bare `SOURCE_ID` selectors.
4. Scope all settings/companies/tag-rules reads and writes by envelope instance.
   Make missing instance a hard processor error, not a default in scheduled work.
5. Convert v2 decision/actions behind a versioned processor facade without
   changing behavior. Capture decision/action events and compare old/new results.

**Gate:** two instances with colliding IDs and pipe names process concurrently
with zero config, document, ledger, provenance, link, or action leakage.  
**Rollback:** route envelope to compatibility facade; old behavior remains
callable, but all writes still pass the identity-safe BFF.

### Phase 5 - Make projection durable and repairable

1. Refactor Deliver to persist processor result and document binding, then create
   `sync_projection.pending`; projection is a separate retryable worker step.
2. Drive/Mail execute projection with idempotency key, then INDOX re-lists or
   reads metadata to verify the terminal location before marking `verified`.
3. Add identity-keyed repair preview and execute endpoints. Preview returns the
   observed source, desired target, document/run IDs, proposed no-op/mutation,
   and refusal reason. Execute requires expected projection revision.
4. Reconcile reads durable projection plus live source observation and exposes
   `recorded_not_projected`, `projected_not_recorded`, `unknown_outcome`, stuck
   claims and unavailable sources. It never auto-reprocesses.
5. Add Console repair queue, evidence drawer, retry/release controls, typed
   failures, and resolved origin link. Bulk action requires individually eligible
   items and shows partial results.

**Gate:** forced move/label timeout, worker death and response loss all converge
without a second processor run or document; repair replay is a no-op.  
**Rollback:** pause projection worker, retain pending rows, and continue read-only
reconcile; never revert to marking record as full delivery.

### Phase 6 - Move provider behavior to owners

1. Move Mail label creation/list/add/remove and verification behind Mail's
   connection-aware adapter. Move remaining Drive mutations behind Drive.
2. INDOX stores provider location IDs and desired roles only. Remove provider URL,
   credential, path-construction and label semantics from processors/BFF.
3. Resolve active profile at operation time and record its revision on every
   observation/mutation attempt.

**Gate:** adapter contract suites run against local and representative Google
profiles; changing profile revision neither duplicates identity nor crosses
accounts.  
**Rollback:** adapter facade can call the old implementation temporarily while
preserving the same contract and audit output.

### Phase 7 - Complete State Machine consolidation

1. Define typed document states, actions, failure codes and transition guards in
   one processor module/contract; remove UI/workflow copies.
2. Make decision functions pure over envelope + document snapshot + instance
   config. Make actions explicit commands with idempotency keys and event output.
3. Add a State Machine graph-coverage gate covering Decide, Global, BS, GDoc,
   Ship, query/upsert nodes and their suites. Exclude only triggers/responders and
   documented non-executable notes, matching the Sync gate policy.
4. Run old/new shadow comparison for all production document classes. Resolve
   every mismatch or explicitly version the intended behavior change.

**Gate:** all State Machine suites assert final document state and provenance;
100% eligible-node coverage comes from the same CI run; shadow mismatch is zero.  
**Rollback:** select prior processor version per pipe; events identify which
version produced every state.

### Phase 8 - Observability and operations

1. Emit structured events with request, run, n8n execution, instance, pipe,
   connection, full source identity, profile revision, processor version,
   transition, duration and typed error. Redact credentials and document content.
2. Publish metrics for list/claim/process/record/project latency and outcomes,
   claim age, retries, projection backlog, divergence age, unavailable sources,
   registry conflicts and identity ambiguity.
3. Alert on oldest claim/projection thresholds, repeated profile failure,
   nonzero unknown outcomes, growing divergence, no successful scheduled run,
   and graph/CI gate failure. Link alerts to Console evidence and runbooks.
4. Write and rehearse runbooks for source unavailable, stuck claim, record
   ambiguity, projection unknown/failure, credential rotation, bad registry,
   rollback and disaster restore.

**Gate:** injected failures create the expected metric, alert, evidence link and
successful runbook resolution in staging.  
**Rollback:** alerts can be muted with an incident record; durable events remain.

### Phase 9 - Staging, canary, and the five-file recovery

1. Run the full matrix on a fresh staging stack and a two-instance/two-connection
   canary with identical pipe names and colliding platform IDs. Include different
   profiles under one connection and a profile rotation during projection.
2. In production, select one non-zero audited file. Run repair preview, confirm
   full identity/document/projection target, then execute projection only.
3. Verify one document row, one source identity, unchanged processing run count,
   one verified projection, source present only in `בוצע`, correct origin link,
   and zero reconcile divergence for that ID. Observe through one schedule cycle.
4. Review the proof with the operator. Repair remaining valid files one at a time
   or in a reviewed eligible batch. Quarantine/reject the zero-byte JPEG with a
   typed reason; do not call it processed.
5. Do not reset ledger, rerun processors, or bulk-move all five as recovery.

**Gate:** signed canary artifact contains before/after API, DB, provider, UI and
execution evidence; replay changes nothing; pipe reconcile is clean except any
explicitly quarantined item.  
**Rollback:** a verified source move may be reversed only through the same
audited adapter command; document/provenance history is never deleted.

### Phase 10 - Legacy retirement and final cleanup

1. Generate an invocation graph for all INDOX workflows, hooks, webhooks, tests,
   app manifests and docs. Classify each legacy artifact as adapter, processor
   behavior, fixture, reset path, or dead export with an explicit replacement.
2. Remove old invocation edges first. Prove zero runtime, test, registry and
   webhook references before deleting an export.
3. Retire v1 scanners after every enabled pipe uses table registry + Sync-v3.
   Retire compatibility processors only after the processor envelope has parity.
   Retire v2 Decide/Actions only after the consolidated State Machine owns their
   behavior and coverage.
4. Remove compatibility JSON, namespaced `source` and legacy null-connection
   reads only after telemetry shows zero use for the agreed retention window and
   backups/restores no longer require them.
5. Delete obsolete reset/demo paths only after equivalent disposable fixture and
   recovery commands are documented and gated.

**Gate:** zero-reference lint, fresh-machine baseline, migration from the last
supported schema, restore rehearsal, full CI and production read-only audit pass.  
**Rollback:** deletion is a separate commit after a backup; restore uses the
verified export and prior processor/registry feature flags.

## 7. Required verification matrix

| Layer | Required proof |
|---|---|
| Static | Blueprint/schema validation; no production hardcoded tenant, literal document-table mutation, bare source mutation, or adapter bypass |
| Python/BFF | Identity collisions, tenant-scoped CRUD, registry revisions, legal/illegal transitions, origin bases, partial source errors, repair preview/execute/refusals |
| Sync kernel | Diff, claim race, record recovery, release, stuck expiry, attempts/backoff, cursor loss, ordering, revision change |
| Source adapters | Drive/Gmail local + Google profile, pagination, timeout/unknown outcome, idempotent mutation, postcondition verification, profile rotation |
| Processors | Every document type/result, deterministic replay, provenance, zero-byte/corrupt input, no provider mutation |
| State Machine | Decide/action transition matrix, invalid transitions, repeated action idempotency, final state and event stream |
| Failure injection | Worker death at each boundary, network loss, DB contention, response loss, provider failure, record/projection split |
| Multi-tenant/profile | Two instances, same pipe and platform IDs, two connections, two profiles, concurrent runs, zero cross-read/write/action/link |
| UI flow | Create/validate/save/run pipe, conflict, disable, board, evidence, source link, release, repair preview/execute, partial failure, keyboard/mobile layout |
| Coverage | Existing Sync-v3 and new State Machine eligible-node gates both 100% from the release CI run |
| Operations | Backup/restore, rollback feature flags, alerts/runbooks, fresh-machine `bbox run`, baseline and production read-only audit |

No single suite count is a release criterion. The artifact must name the commit,
workflow versions, environment, execution IDs, coverage denominator/numerator,
test results and timestamps.

## 8. CI and baseline wiring

The release pipeline must execute, in order:

1. Static platform gates plus the INDOX identity/tenancy/ownership lints.
2. Incoming-documents Python unit/integration contracts and frontend build.
3. Blueprint push to the disposable stack.
4. `bbox indox test all` with JUnit.
5. Sync-v3 100% graph coverage from that battery.
6. State Machine 100% graph coverage from that battery.
7. Replacement multi-instance/profile E2E harness.
8. Projection failure/recovery lane and UI flow QA.
9. Fresh migration + rollback/restore smoke test.

`bbox baseline` must report these as separate scorecard rows; it must not collapse
suite success, graph coverage, tenancy and projection recovery into one green
INDOX line. Production release additionally requires a timestamped read-only
registry/source/ledger/document/projection/reconcile audit.

## 9. Definition of done

INDOX is fully working, stable, consolidated and clean only when all are true:

- Every enabled pipe is table-backed, validated, revisioned, connection-bound,
  dynamically tenanted and editable through Console without hidden defaults.
- Every source identity has at most one document binding; every processing run
  and state transition has immutable provenance.
- Every recorded item is either projection-verified or visibly repairable; no
  delivered row can disappear from operator attention.
- Two instances, connections and profiles can collide deliberately without any
  cross-tenant read, write, source action, origin link or configuration leak.
- Sync and State Machine contracts, failure paths, UI flows and eligible graph
  nodes are mechanically covered in the release run.
- Backup, restore, rollback, alerts and runbooks have current rehearsal evidence.
- The five production files have explicit final outcomes without replay-based
  duplication; the zero-byte item is not falsely successful.
- Legacy invocation edges, exports, compatibility tables/columns and duplicated
  provider behavior are removed only after their stated deletion gates pass.
- A fresh `bbox run` plus the full baseline reaches the same behavior from the
  committed repository, and the production read-only audit is clean.

Anything less is an intermediate migration state and must be reported as such.