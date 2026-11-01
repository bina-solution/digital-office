# INDOX testing — how the suites, the CLI, and CI relate

Authored 2026-07-07 (release-v2-lockin Phase 1b). Companion: `release-lockin-plan.md`,
`indox-v2.1-state-machine-plan.md`.

## The one entrypoint

```
bbox indox test [all | doc_base | bs | gdoc | pipeline] [--junit <path>]
```

`scripts/indox-test.py` runs each n8n suite headlessly (REST login → manual-run from the
suite's manual trigger — NOT `indox-trigger-wf`, whose start-node regex misses the `▶ Run …`
trigger names), waits for the execution, parses the `🏁 Test Summary` node output straight
from the n8n DB (flattened `execution_data` → deflatten), prints a scorecard, exits non-zero
on any red. `--junit` writes JUnit XML (one `<testsuite>` per suite, one `<testcase>` per
summary check) for CI publication.

## The suites (n8n workflows, blueprint-committed)

| key | workflow | pins |
|---|---|---|
| `doc_base` | `indoxV2DocBaseTest01` — decide coverage (18 branches, ONE batch) · execute coverage (9 handlers) · full lifecycle on 4 real files | router_doc_base, 100% node cov |
| `bs` | `indoxV2BSTest01` — lifecycle→COMPLETED · link branches (create/update/skip) · 10-handler coverage · failure path | router_bs, 100% node cov |
| `gdoc` | `indoxV2GDocTest01` — timed lifecycle · bounded-5 parallel extraction · 17-handler coverage · partial-error isolation · batch-15 GT===AI===KW | router_gdoc (invoice/order/shipment) |
| `pipeline` | `indoxV2PipelineTest01` — **drives the REAL pipeline**: seeds docs and lets the live poll→Driver path run them to rest. Bare-link ×4 (type+company figured from file bytes) timed · batch-17 (5inv+5ord+5shp+2bs) GT===AI===KW · Driver Switch1 dispatch coverage (8 cases) | Incoming Documents v2 end-to-end |

Main indox is hard-locked twice: the routers pinned in isolation by their suites, the real
pipeline pinned end-to-end by the pipeline suite.

## Known pins (pass-with-note, drift still fails)

`gdx_shp3` / `plx_shp3` (same file): KW OCR reads `00512` vs GT `01512` + doc-date vs
dispatch-date. Declared in each suite Config as `knownPins`; the batch asserts classify a
mismatch on a pinned id as `pinned` (suite stays green) but any NON-pinned doc drifting
fails, and a pinned doc suddenly matching GT is reported as `[pins healed: …]` so silent
changes surface either way. Fixing the pin = remove the id from `knownPins`.

## Suite-authoring rules (learned the hard way)

- **No n8n `Wait` nodes** — headless manual runs (REST `/run`) never resume from Wait;
  use a postgres `SELECT pg_sleep(20);` node to pace watch loops.
- **`alwaysOutputData: true` on executeWorkflow calls that may return 0 items** (the
  Driver returns nothing) — an empty output silently ends the branch.
- **Suites sharing demo files must not coexist in the table** — dedup (company+short-doc)
  correctly DOUBLEs the second copy. Each suite's cleanup deletes ALL test prefixes it can
  collide with (`gdx_%`, `plx_%`, `plb_%`); run suites sequentially.
- **Never seed extra companies** — `figure_company_id` matches against the whole companies
  table; pollution flips its resolution (seen: dbf_ord 511234567→514947746). Seed only what
  the lane asserts on and clean up.
- **n8n v1 execution order runs fan-out branches by node POSITION (topmost first)** —
  serialize lanes via connections when order matters (the summary must run last).
- Suite docs driven by the live poll (`pipeline`) need no isolation; suite docs driven by
  direct router calls tolerate the poll racing them (locks + terminal no-ops make re-touch
  harmless — verified by re-running all suites with the poll live).

## CI — full-fat, no external AI (Phase 1c)

The tests are FULLY LOCAL by design: apitools runs with Tesseract (`OCR_ENGINE=local`, no
Google Vision), and every AI extraction is a deterministic hit on committed fixtures —
`production/n8n/fixtures/ai-extraction-cache.json` (+ `settings.json` / `tag_rules.json`
for pipeline config), seeded idempotently by `indox-test.py` before every run. A CLEAN
environment (fresh clone, CI cold boot) runs the same full-fat suites out of the box;
proven locally by `TRUNCATE ai_extraction_cache` + `bbox indox test all` → green.
The INDOX schema is itself a fixture: `production/n8n/fixtures/01_schema.sql` (dollar-quote-free —
the n8n postgres driver chokes on `$`), applied idempotently by the Test Fixtures workflow AND
mounted into supabase-db initdb for fresh volumes. Proven destructively: DROP a table → any suite
run recreates+reseeds it.

ci-verify runs `bbox indox test all --junit ci-artifacts/indox-e2e.junit.xml` after the
verify step and publishes the per-suite JUnit checks (`indox-e2e`). CI never re-implements
test logic — it calls the same CLI (via traefik: `INDOX_TEST_BASE=http://127.0.0.1
INDOX_TEST_HOST=n8n.localhost`). Requirements in CI:
- **`SUBMODULES_TOKEN` repo secret** (PAT with read access to the private apitools repo) —
  without it apitools stays stripped and the E2E step is skipped (CI still green).
- The supabase Postgres cred is env-driven (`credential_overrides` → `SUPABASE_DB_*`), so
  CI's generated `.env` keeps compose and the n8n cred in sync.
The suites are SELF-PREPARING: each one's first step calls the shared **`INDOX Seed
Fixtures`** workflow (`indoxV2TestFixtures01`) — apply the schema, ensure the storage
bucket, fetch the committed fixtures from `http://indox-demo-docs:8088/fixtures/*.json`,
upsert them through the indox api (TABLE_UPSERT). The CLI only triggers/waits/parses/
reports and AUTODETECTS the n8n endpoint (localhost:5678 → traefik n8n.localhost) — no
presteps or special env anywhere, CI included.

**The same workflow is the canonical ONBOARDING seeder**: `INDOX Reset + Setup`'s setup
branch calls it too (its embedded schema/config copies — already drifted: 44 vs 45
settings, no drive_files — were removed). ONE seeding implementation everywhere; the
orphaned `INDOX Supabase Setup` is deactivated. Proven destructively twice: DROP TABLE
ai_extraction_cache → suite run self-heals; DELETE q_* settings → `bbox indox reset`
re-seeds 45/23.

## Integration-API backends — ONE mechanism for all 3 routers (2026-07-08)

Every integration API picks its backend in exactly ONE place — its router's `Pick Backend`
node, holding `const BACKEND='<value>'`. `n8n-push` resolves the value at import time as
**`.env` var → settings-table row → router default** and substitutes it into the staged
copy (repo files keep the defaults). The substituted constant IS the config: no runtime
toggle, no silent fallback; a flip is a deploy action (edit `.env` or the settings row,
then `bbox n8n push`). A misconfig fails loudly at the Backend Switch.

| API | router | .env var | settings row | default | backends |
|---|---|---|---|---|---|
| DATA | indoxApiRouter01 | `INDOX_DATA_BACKEND` | `backend_data` | supabase | supabase, sheets (legacy) |
| DRIVE | driveApi01 | `DRIVE_BACKEND` | `backend_drive` | google | google, local |
| GMAIL | gmailApiRouter01 | `GMAIL_BACKEND` | `backend_gmail` | imap | imap, oauth |

The DATA router's old redis key (`n8n.indox.data_backend`) is retired from the router;
5 legacy workflows still read it privately (tier-2 cleanup deletes those branches — see
`ai/context/release-endgame-backlog.md` WS1.5). Adding a backend = add the impl sub-WF,
add a Backend Switch branch, extend this table.

### drive api — google | local details

- **google** (default, prod parity): the original 7 Google Drive nodes, topology untouched.
- **local** (`drive api - local`, driveApiLocal01): bytes in the public supabase-storage
  `drive` bucket, metadata in the `drive_files` table, responses Google-SHAPED
  (kind/id/name/webViewLink/md5Checksum/parents), links minted as
  `http://drive.localhost/file/d/<id>/view` — the SAME path shape as Google links, so every
  id-extracting consumer works verbatim (traefik routes that path to the storage public
  object; no authentik, like anyone-with-link). The invoice extractor's one native Drive
  node was routed through `drive api` (the BS extractors already were).

Switching with EXISTING doc rows is inconsistent by design (links point at the other
backend) — flip on a clean/test dataset; the suites find-or-upload their own files so they
are self-consistent. CI's generated `.env` sets `DRIVE_BACKEND=local` → **zero Google
anywhere in CI**. Verified 2026-07-07: google mode all-green post-gate (baseline identical)
· local mode doc_base 3/3 + pipeline 3/3 (21/21 COMPLETED, GT parity, faster: batch ~122s
vs ~163s) · env-substitution path proven end-to-end (.env flip → push → green → flip back).

The supabase API gateway (kong) is also routed locally at `supabase-api.localhost`
(`SUPABASE_BASE_URL`/`SUPABASE_PROTOCOL` in .env; studio's `SUPABASE_PUBLIC_URL` now points
at kong, fixing Studio manual uploads).

Known follow-up: the BS + GDoc suites hardcode two real Drive links for their fixture docs
(lifecycle/extract lanes) — google-only until they find-or-upload like doc_base/pipeline do
(see issues/indox-suites-hardcoded-drive-links.yaml). doc_base + pipeline are fully
backend-agnostic.

## Related tools (NOT part of `bbox indox test`)

- `scripts/indox-v2-actions-test.mjs` — stack-free v1==v2 node-equivalence check (byte
  parity of carried-over router nodes vs 0.1.7). Run: `node scripts/indox-v2-actions-test.mjs`.
- `scripts/indox-v2-decide-test.mjs` — decide-function parity fuzz.
- `scripts/indox-doc-trace.py` — per-doc runtime trace (a diagnosis tool, not a test).
- `development/feature-validation/` — deployment-level observability suite (separate
  concern; `bbox fv run` may absorb it later).
