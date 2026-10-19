# legacy/ — kept so you can see it, not shipped

> **No live consumer reads from this directory** — as of 2026-07-30, and only as of then. Parked is
> not the same as unreferenced, and the previous archive (`attic/`) was deleted on the strength of a
> README that blurred the two. Every reference is declared here, and in gate **G34**, so that never
> happens again:
>
> | Consumer | Reads | Why it is still here |
> |---|---|---|
> | *(none)* | — | — |
>
> Until now there were two, and both were `feature-validation` — the estate's only OCR/extraction
> coverage, which was parked here while a live CI lane still booted its compose stack and ran its
> harness out of it. A live lane reading from an archive is precisely the defect that kept `attic/`
> alive for 293 files, so the suites moved to the app they validate:
>
> | Was | Is now |
> |---|---|
> | `legacy/feature-validation/**` | `apps/apitools/feature-validation/**` |
> | `legacy/feature-validation/run-suites.sh` | `apps/apitools/hooks/test` — the platform's ONE test entrypoint (`bbox test apitools`) |
> | `.github/workflows/indox-e2e.yml` booting the compose stack + runner | one step: `./bbox test apitools` (still advisory, `continue-on-error`) |
> | `digital-office/sim/build.mjs` reading `api/dashboard.html` | reads `apps/apitools/feature-validation/api/dashboard.html` |
>
> There is one **mention** left, and it is not a consumer: `apps/indox/blueprint/n8n/indoxHealth00001.json`
> carries `legacy/n8n/google-integration-health/` inside an n8n stickyNote, recording where a
> predecessor workflow was parked. Nothing reads it — but a stickyNote is not syntactically a
> comment, so gate **G34** declares it rather than guessing at the role of a JSON string. **G34 is
> the authoritative inventory; this table is the human summary.** The gate also fails on a declared
> entry that matches nothing, so a retired consumer forces its declaration to be deleted.
>
> `attic/` used to hold 17 parked projects, 16 of them with zero inbound references. It was removed;
> its one live tenant, `feature-validation`, came here with its harness
> (`scripts/ci-feature-validation.sh` → `run-suites.sh`) and has since gone where it belonged all
> along — `apps/apitools/`, as that app's own tooling. Three homes, three different depths for the
> same script (`${SCRIPT_DIR}/..`, `/../..`, `/../../..`): a script's depth is part of its contract
> with its location, and each move silently re-pointed the repo root until it was fixed.
> Everything deleted remains in git history.

Nothing here is part of an app. The apps (`platform-base/*`, `apps/*`) are the product; this
directory is the archive of what used to live inside them. No manifest resolves a *path* into it,
so `blueprints.n8n` never reads from here and no push can import these files.

> **That is not the same as "nothing points at it."** `active_workflows` in
> `platform-base/n8n/blueprint.yml` names workflows by **name**, not by path, and **22 of its 86
> unique entries are stale**: 20 name workflows whose only remaining file is under `legacy/`
> (`_pdbg`, `_pgs`, the eight `_diag_*` probes, the four `[FV] Test Integration` suites,
> `Balance Sheet Extractor`, `Balance Sheet Extractor - v2`, `BS_EX_1`, `My workflow 15`,
> `Gmail Documents Scanner`, `Gmail Balance Sheets Scanner`), and 2 more
> (`drive api - local`, `gmail api - oauth`) match no tracked workflow JSON anywhere.
>
> **Do not "fix" it by hand.** `active_workflows` is not an authored input — `platform-base/n8n/hooks/pull`
> *regenerates the whole blueprint*, this field included, from whatever the live instance reports, so
> any hand-edit is erased by the next `bbox n8n pull`. And nothing consumes it: `hooks/push` derives
> the set to re-activate from each workflow file's own `active` flag (`w.active`, hooks/push:429),
> never from this list. Its inline comment — "re-activated on push" — is simply wrong about its own
> role, which is why the staleness looked alarming and is in fact inert.
>
> So this is a captured snapshot that has not been re-captured, not drift in an input. The real
> options are to re-pull it, or to stop tracking a field nothing reads. Measured 2026-07-30 by
> matching each entry against the `name` field of every tracked workflow JSON.

Everything moved here was moved on **evidence**, not opinion — `scripts/n8n-node-coverage.py` was
run against a full `bbox baseline` (6,689 executions) and reported which workflows executed zero
nodes. See `ci-artifacts/n8n-node-coverage.txt`.

| Path | What | Why |
|---|---|---|
| `n8n/base-workflows/` | 16 workflows from the n8n app's blueprint | Measured dead: 8 `_diag_*` probes, `_pdbg`, `_pgs`, 4 `[FV] Test Integration` (feature-validation itself is already retired to `attic/`), `My workflow 15`, `concTestSleeper` |
| `n8n/blueprint-junk/` | `_hard.pkl`, `_hli_*`, `_v2_precentralize_bak` | Non-workflow files sitting inside the blueprint dir, which should contain workflow JSON only |
| `n8n/archive/workflows-archive/` | 34 files | An archive dir that lived *inside* the n8n app |
| `n8n/trash/n8n-trash/` | 6 files | Ditto — literally named `trash/` |
| `n8n/kafka-retired/` | 1 workflow + 2 credential files | Kafka/Redpanda removed platform-wide — see below |
| `n8n/mcp-duplicates/` | 2 workflows | The `archive, duplication`-tagged halves of the MCP pairs — see below |
| `n8n/indox-sheets-era/` | `Batch API GSheet Cache Table` | 117-node Sheets↔Postgres cache from before the Supabase backend; `indox-dev`-tagged, zero callers |
| `n8n/indox-unreferenced/` | 5 workflows | Zero executions **and** zero callers anywhere in the repo |
| `n8n/google-integration-health/` | archived original | Replaced by `indox integration health` — see below |

## `n8n/retired-20261007/` — twelve workflows that kept coming back into the base (2026-10-07)

A workflow "retired" by moving its file away is still on every n8n instance that ever imported it,
and `bbox n8n pull all` exports the whole instance — so it comes straight back, untagged, into the
**central** blueprint, and from there ships to every office. Twelve were sitting there: four scratch
probes (`IPqTtikNP1sLxoka`, `ZZAbGemProbe01`, `sG9bU0ER2yVitKXR` "delete me", `zzDecideSweep01`
"temp"), `indoxApiSupabase01` (retired 2026-08-12, its id became `indoxApi01`), the draft pair
`indoxDataGateway01` / `indoxIdentity01` (moved to an attic on 2026-08-06, back within the month),
and the five v1 extractors `indoxV2Query*01` (replaced by JQExV3 on 2026-08-17; three already had
a copy under `extractors-retired-20260817/`). Each was inactive, called by no node of any shipped
blueprint, and quoted by no tracked code. Between them they failed four gates: G9 (five dialled
apitools from the base), G42, G45, G47.

What makes it stick this time is **`platform-base/n8n/retired-workflows.txt`**: `hooks/pull` never
brings a listed id back, G38 fails if one has a blueprint file again, and
`bbox n8n base unpush --retired` removes them from an instance — a verb, because it deletes from a
live database and each office's operator chooses when. The generator of the draft gateway's schema
(`gen-gateway-trigger-schema.py`, whose CI step had been ending in FATAL) is parked with them.

**Not retired, whatever its name says:** `indoxApiRouter01` ("RETIRED 2026-08-12 - folded into
indoxApiSupabase01"). No node names it — `apps/indox/hooks/demo.py` executes it by id and four
test suites call it through `routerId` in their Config. "Who calls this workflow" must look for
the quoted id as well as for nodes.

## `n8n/kafka-retired/` — Kafka is gone platform-wide (2026-07-27)

There was never a broker. No compose file in this repo has ever defined `redpanda`, so
`KAFKA_BOOTSTRAP_SERVERS=redpanda:9092` pointed at a host that does not resolve. The cost was not
zero: n8n retried activating `Incoming Documents — Kafka Trigger Verify` forever
(`Connection timeout … retry in 64 seconds`, visible in `.refactor/ci-verify*.log`).

Removed: the workflow, credential `bo3QVODx0Wjv91e5` (+ its `.credentials-state` twin), the
`credential_overrides` entry and `active_workflows` line in `platform-base/n8n/blueprint.yml`, the
`kafka` provider in `platform-base/connections/providers/20-n8n.yaml`, `KAFKA_*` from `.env`/`.env.ex`,
the pinned empty `KAFKA_BOOTSTRAP_SERVERS=` in `apps/indox/docker-compose.yml`, and the orphaned
disabled `kafkaTrigger` node inside the live `Incoming Documents v2` driver.

**Not removed:** the Python broker abstraction in `apps/indox/app/incoming_documents/kafka/` and its
`Null*` implementations. It is load-bearing structure in a *running* service (`main.py`,
`repo_factory.py`, `poller.py`, the SPA's Kafka-tail page) and already resolves to the Null path when
no broker is configured. Ripping it out is a code refactor plus a container rebuild, not a file move.

## `n8n/mcp-duplicates/` — resolved, was "needs a human decision"

An earlier pass left both MCP pairs alone because same-name/different-content looked risky. Measuring
them settled it:

| Retired | Kept | Relationship |
|---|---|---|
| `gDriveMcpAgent01` (17 nodes) | `gDriveMcpAgent01` (17 nodes) | **identical** node sets |
| `gSheetMcpAgent01` (15 nodes) | `gSheetMcpAgent01` (23 nodes) | retired one is a **strict subset** |

Both retired files are tagged `archive, duplication`, and each shared not just the MCP path
(`gdrive-agent` / `gsheet-agent`) but the **same `webhookId`** as its live twin — two `active: true`
workflows racing for one registration. Nothing is lost and a real collision goes away.

## `n8n/google-integration-health/`

`Google Integration Health` (`gwaHealthCheck01`) probed Google directly — the Gmail router, a
hardcoded Sheet id, a hardcoded Drive folder id — and lived in `google-workspace-agent`, which
`platform.state.yaml` has `enabled: false`. A disabled app's blueprint is never pushed, so it could
not have run even on schedule.

Its replacement is **`indox integration health`** (`indoxHealth00001`) in the *enabled* `indox` app.
It probes the contracts INDOX actually depends on — **drive api** (`createFromText` → `download` →
`delete`, self-cleaning, no hardcoded folder id) and **mail api** (`GET /webhook/mail-api/doc-context`
with an unmatchable `source_id`, expecting `{found:0, docs:[]}`) — and is runnable from a baseline via
`POST /webhook/trigger-indox-health`, which returns the verdict JSON.

## 2026-08-04 — Google Sheets is fully legacy (indox-sheets-era)

User directive: Google Sheets is fully legacy. `indoxApiRouter01` was reworked to call ONLY
`indoxApiSupabase01`, and the `INDOX_DATA_BACKEND` toggle was removed from `platform-base/n8n/hooks/push`,
`.env.ex`, `scripts/ci-env.sh`, `scripts/automations-reset.py` — so nothing can point a deployment
back at a sheets backend anymore. All four moves were on evidence (zero executions in 14 days, and
the router workflows unreachable after the surgery).

Moved to `n8n/indox-sheets-era/`:

| Workflow | What | Why |
|---|---|---|
| `indoxApiSheets01` | `indox api - sheets` | Zero executions in 14 days; unreachable after router surgery — `indoxApiRouter01` now calls only `indoxApiSupabase01` |
| `indoxDocCreate01` | `Create Incoming Document` | Sheets-only create/get webhooks (`/webhook/incoming_document` POST+GET); zero executions in 14 days. Superseded by INDOX API `POST /incomingDocuments/documents` |
| `indoxDocUploader01` | `Document Uploader` | n8n webhook uploader (`/webhook/upload-document`); consolidated into INDOX API `POST /incomingDocuments/documents/upload` (which uploads directly via drive app API) |
| `indoxSetupWF001` | `Incoming Documents — Setup` | Sheets-era provisioner (Drive tree + spreadsheets + labels); zero callers, zero executions |
| `logger01` | `Logger` (lived in `platform-base/n8n/workflows/`) | Sheets-only log writer (all four googleSheets nodes were already disabled); its four callers were rewired to bypass it: `SyncProcGDoc0001`, `indoxGmailActionProcessor01`, `indoxGmailBSDownloader01`, `indoxGmailDocDownloader01` |

Sheets-arm excisions — workflow KEPT, dead sheets arms removed:

- `indoxDocGet01` — webhook + all sheets query arms removed; only the executeWorkflow → supabase GET path remains.
- `indoxDocBatchUpsert01` — manual/webhook sheets update arms removed; only executeWorkflow → UPSERT Adapter → `indoxApiSupabase01` path remains.
- `indoxV2Driver01` — disabled Google Sheets Trigger + empty_row arm (Empty Lines → Get row(s) in sheet2 → Group Consecutive Rows1 → Delete Row Ranges1) + orphan sheet readers removed.
- `indoxV2QueryTotalAmt01` — manual-trigger sheet arm removed.
- `mailLabelEngine01` — orphan `Get Tags Settings1` sheets node removed.

## 2026-08-04 (later same day) — chat intake consolidated into the indox app API

`indoxDocCreate01` + `indoxDocUploader01` had ZERO executions in 14 days, yet the retired-code table
flagged them as chat-called — and after the sheets retirement chat's record-create call pointed at the
already-dead `/webhook/incoming_document`. Both intake legs consolidated into the indox app API (the
same BFF chat already reads companies from):

- New route `POST /incomingDocuments/documents/upload` (`{fileName, mimeType, content(b64)}` →
  `{success, webViewLink}`) uploads via the drive app (`POST http://drive:8975/upload`, folder from
  `INDOX_UPLOAD_FOLDER_ID`). Record creation uses the existing `PUT /repos/<repo>/documents` batch
  upsert against repo `incoming-documents-main`.
- Chat rewired: `document_storage.js` + `incoming_documents_api.js` → indox API; the six dead webhook
  env vars removed from `config.js`; `INDOX_DOCS_REPO` added; startup checks probe the indox API;
  `app.json` uses `indox-api` with strength `requires` (ops: companies/upload/documents).
- `indoxDocUploader01.json` moved to `legacy/n8n/indox-sheets-era/`; live DB row deleted.

## Deliberately NOT moved

- **`Document Uploader`** (`indoxDocUploader01`) — was genuinely live on 2026-08-04 morning (chat
  called `N8N_UPLOAD_DOC_WEBHOOK`), but was consolidated into the indox app API later the same day —
  see "2026-08-04 (later same day)" below. It is now in `legacy/n8n/indox-sheets-era/`.
- **`Sync Scan Unit`** (`SyncScanUnit0001`) — the v1 scan path. All five `sync_registry` sources are
  currently `engine: v3`, so `Sync Scanner` builds zero units and this never runs; it stays as the
  rollback lane for flipping a source back off v3.
- **The JQExV3 family** — zero executions because the callers are the Python BFF
  (`apps/indox/app/incoming_documents/extraction.py`), not the n8n pipeline. `Order JQ Ex V3` has no
  runner webhook, but `order` **is** a live category in the `q_v3_routing` settings row.
  `Balance Sheet JQ Ex V3` (`JQExV3BS00000001`) stays active: it is the Execute-Workflow target of
  `JQExV3RunBS00001` (`cachedResultName: "Balance Sheet JQ Ex V3"`), so retiring it would break that
  runner — documented, not retired (2026-08-04 cleanup Phase 2.4 decision).
- **Real but unexercised**: `ExecutionStopEvent`, `Gmail MCP Server`, `mail api`,
  `WhatsApp Send Document`. These are production surface the baseline simply never
  drove — the fix is coverage, not deletion.
- **`ztest gmail api`** went to `apps/mail/tests/`, not here: it tests the mail app's API, so it
  belongs with the app it tests (`bbox test mail`).

## `n8n/indox-superseded/`

Three predecessors of a workflow that is still live. `Balance Sheet Extractor - v2- shmuel`
(57 nodes) is the one that actually runs (39% of its nodes executed during the baseline); these
three were all `active: true` and executed **zero** nodes:

| Workflow | nodes |
|---|---|
| `Balance Sheet Extractor` | 57 |
| `Balance Sheet Extractor - v2` | 57 |
| `BS_EX_1` | 47 |

A personally-named variant became production while its predecessors were left enabled — 161 dead
nodes still registered as active workflows in n8n.

### Added 2026-07-27 — same pattern, seven more

Each has a *named live successor*, so nothing here is a judgement call:

| Workflow | nodes | Superseded by |
|---|---|---|
| `Document Management - Optimal` | 49 | `Batch Upsert` (`indoxDocBatchUpsert01`) — the retired file holds three near-duplicate copies of the same lock→diff→batch pipeline, i.e. three design iterations left side by side |
| `sv3 Live Inject` | 31 | `sv3 Inject 3x Every Registry Source` (`sv3Inject3x001`); `active: false` |
| `Mannual Documents Namer` | 26 | `Sync Processor - drive-gdoc` (`SyncProcGDoc0001`); self-tagged `legacy` |
| `Extract via OCR` | 16 | apitools `/documentJsonQuery` + the JQExV3 extractors |
| `Update Incoming Document` | 9 | `Batch Upsert`; served `PUT /incoming_document` and no caller uses PUT |
| `INDOX BS Sync (Processor v2)` | 6 | sync-v3; `active: false`, tagged `legacy` |
| `INDOX GDoc Sync (Processor v2)` | 6 | sync-v3; `active: false`, tagged `legacy` |

And in `n8n/indox-unreferenced/` — zero executions **and** no caller anywhere:

| Workflow | nodes | Note |
|---|---|---|
| `Actions API - Complete Implementation` | 78 | a complete Redis-backed REST API on 7 webhook paths that nothing has ever called |
| `Query IS_BALANCE_SHEET` | 15 | its caller `Figure Document Type` was refactored to drop the call; only a pre-refactor snapshot still references it |
| `Deep Loop Reset EX` | 11 | tagged `examples`; contains a node literally named `Replace Me` |
| `Find Document In GDrive` | 9 | Sheets-era link resolution |
| `Orchestrator - Parallel Document Processor` | 7 | **cannot execute** — its inner `workflowId` is still the literal string `REPLACE_WITH_INNER_WORKFLOW_ID`. Its `perf-manifest.json` knob entry was removed with it. |
