# Incoming Documents — Phase 2: Testing Strategy

> Companion to [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md). Read that first.
>
> Goal: prove the new Python API is **behaviourally identical** to the n8n `Batch Upsert` + `Get Incoming Document` workflows, on real production-shaped data, under load, and across both backends (GSheet + Supabase). All new code must be covered before phase 4 starts re-pointing n8n at the new API.

---

## 1. Pyramid

| Tier | Count target | Tooling | Runs in CI? | Runs locally? |
|---|---|---|---|---|
| Unit | ~80% of statements | `pytest`, `pytest-cov`, `hypothesis` | yes | yes |
| Integration — GSheet | ≥ 25 scenarios | `pytest`, `responses` (mock) + 1 live-sheet smoke | mock yes / live nightly | both |
| Integration — Supabase | ≥ 25 scenarios | `pytest` + `testcontainers[postgres]` running PostgREST | yes | yes |
| Kafka | ≥ 10 scenarios | `pytest` + `testcontainers[kafka]` (Redpanda image) | yes | yes |
| Webapp — unit | ~70% lines on `webapp/src` | `vitest` + `@testing-library/react` | yes | yes |
| Webapp — e2e | ≥ 12 flows | `@playwright/test` against compose | nightly | on demand |
| Contract / parity | ~20 cases | golden JSON: replay n8n responses vs Python responses | yes | yes |
| E2E (curl) | ≥ 15 flows | `bash + curl` script against `compose --profile incoming-docs` | nightly | on demand |
| Load | 2 scenarios (steady, spike) | `locust` against compose | nightly | on demand |

Coverage gate: `pytest --cov=src/incoming_documents --cov-fail-under=85`.

---

## 2. Unit tests (`tests/unit/`)

Pure-python, no I/O. Fast (< 5 s total).

### 2.1 `test_diff.py` — the heart of the system
- Empty incoming → empty diff.
- Incoming with new IDs only → all routed to `create`.
- Incoming with existing IDs, no field changes → all routed to `noop`.
- Mixed update/create/noop → correct buckets.
- `null` and `undefined` values are stripped before comparison.
- `priority_sync` rule: any of `priority_sync_columns` set → `priority_sync=true` is added.
- Hebrew-named columns (`סימון כרטסת עדכנית`) round-trip correctly.
- Hypothesis property: `apply(diff(current, incoming)) == merge(current, incoming)`.

### 2.2 `test_registry.py`
- Load empty registry file → empty list.
- Create / update / delete → file mutated atomically (no partial writes on crash — verified by writing then `kill -9` simulation via `os._exit` in subprocess).
- mtime-based hot-reload picks up external edits.
- Pydantic validation rejects: missing `name`, `backend` not in {gsheet,supabase}, gsheet config missing `spreadsheet_id`, etc.

### 2.3 `test_schemas.py`
- Each request/response model round-trips with golden JSONs from `tests/fixtures/`.
- Reject malformed payloads with structured 422.

### 2.4 `test_query_translation.py`
- Each `op` translates to the expected GSheet filter call args **and** the expected PostgREST query string.
- `in` with > 50 values still produces a single PostgREST request (no chunking off-by-one).

### 2.5 `test_priority_sync.py`
- Mirrors the n8n `Check Priority Sync` Code node behaviour exactly using fixtures captured from the workflow JSON.

---

## 3. Integration tests — Google Sheets (`tests/integration/gsheet/`)

### 3.1 Mocked transport (CI default)
- `responses` / `httpx` mock that imitates the Sheets v4 REST API for: `values.get`, `values.batchUpdate`, `values.append`, `spreadsheets.get` (header/columns).
- Verify: correct ranges, correct `valueInputOption`, header-row cache invalidation on schema mismatch, retry on 429.

### 3.2 Live-sheet smoke (`@pytest.mark.live_gsheet`, nightly only)
- Uses a dedicated test spreadsheet (env `INCOMING_DOCS_TEST_GSHEET_ID`).
- Each test gets a fresh sheet tab via `setup_module` → `spreadsheets.batchUpdate.addSheet`, deleted in teardown.
- Scenarios: create 100 rows, update 50 of them, query by IDs, query by filter, append with Hebrew column.
- **Provisioning end-to-end:** `provision_repo` for a brand-new GSheet repo creates a fresh spreadsheet, adds the tab, writes the Hebrew header row, shares with the test editor, and tears down cleanly. Re-run is a no-op.
- **Introspect adopt:** point a config at the existing prod-shaped test sheet (52 cols, Hebrew) and assert `POST /schema/introspect?adopt=true` produces a `RepoConfig.columns` matching the live header byte-for-byte.

---

## 4. Integration tests — Supabase (`tests/integration/supabase/`)

Spin up a real Postgres + PostgREST via `testcontainers`:

```python
@pytest.fixture(scope="session")
def postgrest_url():
    pg = PostgresContainer("postgres:15")
    pg.start()
    pgrst = DockerContainer("postgrest/postgrest:v12")
        .with_env("PGRST_DB_URI", pg.get_connection_url(driver=None))
        .with_env("PGRST_DB_ANON_ROLE", "postgres")
        .with_exposed_ports(3000)
    pgrst.start()
    yield f"http://{pgrst.get_container_host_ip()}:{pgrst.get_exposed_port(3000)}"
```

### 4.1 Scenarios
- **Provisioning (`provision_repo` / `POST /repos`):**
  - Empty DB + new RepoConfig → schema created, table created, PK unique index created, grants applied, Kafka topic created. Single transaction; on injected failure at any step the rollback removes only what was just created.
  - Re-run with identical config → 200 no-op (idempotent).
  - Re-run with drifted column types → 409 `schema_drift`.
  - `DELETE /repos/<r>?drop_storage=true` removes the table; default `DELETE` keeps it.
  - `POST /schema/introspect?adopt=true` against a pre-existing table populates `RepoConfig.columns` correctly (incl. types).
- `ensure_schema` on empty DB → table created with PK + unique index.
- `ensure_schema` re-run → idempotent (no errors, no DDL applied).
- `ensure_schema` with new column in `RepoConfig.columns` → `ALTER TABLE ADD COLUMN` issued; existing data intact.
- `ensure_schema` with **removed** column in config → reports mismatch but does NOT drop (matches Supabase reference workflow's `Report Schema Mismatch` branch).
- Batch upsert 1, 100, 1k, 10k rows; verify single PostgREST call for each batch (chunked at `INCOMING_DOCS_MAX_BATCH_SIZE`).
- Batch upsert with Kafka broker down → row is persisted but response is 503 `kafka_unavailable` with `written:true`.
- Concurrent upserts of the same `ID` from two threads → no lost updates (PostgREST `on_conflict` semantics).
- Query: every `op` × Hebrew column.
- Query pagination: `mode:"all"` against 5k seeded rows returns `truncated:true` + `next_offset`; following the cursor yields exactly 5k unique rows with no overlap.

---

## 5. Kafka tests (`tests/integration/kafka/`)

Use the Redpanda testcontainer (`docker.redpanda.com/redpandadata/redpanda:latest`).

### 5.1 Producer
- `ensure_topic` creates topic with declared partitions/retention; idempotent on re-run.
- `publish` → events appear on the topic, key is `row.ID`, ordering preserved per key.
- Idempotence: replaying the same `event_id` does not double-publish (producer config + dedupe header).
- Synchronous flush before HTTP 200 — if broker is killed mid-batch, the route returns 503 `kafka_unavailable` with `written:true`.

### 5.2 Native n8n Kafka Trigger consumption (smoke, not unit)
- Bring up Redpanda + n8n with `Incoming Documents 0.1.6` deployed, native Kafka Trigger node configured against `${prefix}.<test_repo>`.
- Producer publishes 10 events; assert n8n executions count = 10 (via n8n's REST `/executions` API) within 30 s.
- No Python consumer worker exists — nothing else to test on the consumer side.

---

## 6. Contract / parity tests (`tests/parity/`)

The riskiest part of the migration is **behavioural drift** vs n8n. Build a golden-replay harness:

1. Capture inputs/outputs from n8n today by adding a temporary "tee" Code node in `Batch Upsert` and `Get Incoming Document` (one-day capture window) that POSTs `{request, response}` JSON pairs to a local collector. Result: ~500 captured pairs stored in `tests/parity/fixtures/`.
2. Parity test loops over each fixture:
   - Replays the request against the new Python API (against an isolated test sheet seeded with the captured pre-state).
   - Asserts the response matches the captured n8n response (with a documented allowlist of acceptable diffs: timestamps, row indices for appends).
3. Failures produce a side-by-side diff in the test report.

This is the **single most important** test file: it directly proves "exactly like the current n8n implementation" (per `plan.txt`).

---

## 7. E2E tests (`tests/e2e/`)

Bash + `curl` driven; runs against `docker compose --profile incoming-docs up -d`.

`tests/e2e/run.sh` flows:

1. Bring up stack with seeded `repos.json` containing a `test_gsheet` and `test_supabase`.
2. `POST /repos/test_supabase/schema/ensure` → 200, table exists.
3. `PUT /repos/test_gsheet/documents` with 50 mixed updates+creates → 200, expected counts.
4. `POST /repos/test_gsheet/documents/query` filter mode → returns the rows just created.
5. Same two flows against `test_supabase`.
6. `POST /repos/test_gsheet/kafka/ensure` then `POST .../kafka/publish` with 10 events → consume topic via `rpk topic consume` and assert all 10 events.
7. Negative cases: malformed body → 422; unknown repo → 404; oversize batch → 413.

Each step asserts HTTP status + JSON shape via `jq`.

---

## 8. Load tests (`tests/load/`)

`locustfile.py` with two scenarios:

### 8.1 `steady_state`
- 50 concurrent users.
- Each user loops: 1 batch upsert (10 rows) → 1 query → sleep(2s).
- Run for 30 min.
- Pass criteria: p50 < 500 ms, p99 < 3 s, 0 5xx, no GSheet 429s leaking out (retry layer must absorb).

### 8.2 `migration_burst`
- Simulates the daily catch-up: single client posts 39,582 rows in batches of 500 (= the production CSV size).
- Pass criteria: completes < 10 min, all rows present in the backend, no duplicates.

Both scenarios must pass for **both** backends.

---

## 8a. Webapp tests (`apitools/src/incoming_documents/webapp/`)

### 8a.1 Unit (`webapp/src/**/*.test.ts(x)`) — `vitest` + `@testing-library/react`
- Each page renders against MSW-mocked API responses; loading + error + empty states all covered.
- `RepoCreate` wizard: schema validation per step; submitting fires `POST /repos` with the exact JSON shown in the review step; `provisioning_failed` 503 surfaces the rollback details.
- `DocumentBrowser`: filter builder produces the documented `Query` JSON; pagination follows `next_offset`; sort/visibility toggles persist in `localStorage`.
- `DocumentDetail`: typed inputs validate per `ColumnDef.type` (date picker for `date`, JSON editor for `json`, etc.); save fires `PATCH` with only changed fields; Hebrew labels render RTL.
- `KafkaTail`: SSE messages render in order, pause stops appending without dropping the stream, filter narrows the rendered list only (not the upstream).
- `SchemaEditor`: drift view diff matches snapshot; "Adopt from backend" calls `?adopt=true`; "Add column" calls `/schema/ensure` with the typed payload.
- `useAuth`: hides admin-only buttons for `viewer`/`editor`.
- OpenAPI drift: a vitest test re-runs `openapi-typescript` and asserts no diff against the checked-in `types.gen.ts`.

### 8a.2 E2E (`webapp/e2e/*.spec.ts`) — Playwright against `docker compose --profile incoming-docs up -d`
1. Login through Authentik mock provider as `admin`.
2. Repo list shows the seeded `test_gsheet` and `test_supabase`.
3. Create a new GSheet repo via the wizard end-to-end (provisions a real test spreadsheet); assert success toast + appears in the list.
4. Open the new repo → Documents tab → create a row → reopen the row → edit one field → save → reload and verify persistence.
5. Documents grid: apply a filter, paginate to page 2, export CSV.
6. Schema tab: add a column → table reloads with the new column.
7. Kafka tab: trigger a write in another tab; SSE shows the event within 5 s.
8. Document detail history sidebar shows that same event.
9. Settings: rename `priority_sync_columns`; change persists via `PUT /repos/<r>`.
10. Danger zone: delete the test repo with `drop_storage=true` after typed confirmation; verify spreadsheet is gone.
11. Repeat the create→edit→delete cycle for a `supabase` repo.
12. Permissions: re-login as `viewer`; assert all write controls (create, edit, delete, schema) are disabled or hidden.

Both Playwright runs (chromium + firefox) must pass on the same fixtures.

---

## 9. CI wiring

GitHub Actions `apitools-incoming-documents.yml`:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services: { docker: {} }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r apitools/requirements.txt -r apitools/requirements-dev.txt
      - run: pytest apitools/src/incoming_documents/tests
              --cov=apitools/src/incoming_documents
              --cov-fail-under=85
              -m "not live_gsheet and not load"
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd apitools/src/incoming_documents/webapp && npm ci && npm run lint && npm run typecheck && npm run test:unit -- --coverage
      - run: cd apitools/src/incoming_documents/webapp && npm run openapi:check    # fails if types.gen.ts drifts
  nightly:
    if: github.event_name == 'schedule'
    needs: test
    steps:
      - run: pytest apitools/src/incoming_documents/tests -m "live_gsheet"
        env: { INCOMING_DOCS_TEST_GSHEET_ID: ${{ secrets.TEST_GSHEET_ID }} }
      - run: cd apitools/src/incoming_documents/webapp && npx playwright install --with-deps && npm run test:e2e
      - run: locust -f tests/load/locustfile.py --headless -u 50 -r 5 -t 30m
```

---

## 10. Pre-cutover checklist (gate to phase 6)

Before swapping production traffic to the Python API:

- [ ] All unit + integration + parity + e2e tests green for ≥ 7 consecutive nightly runs.
- [ ] Load test `migration_burst` green on both backends.
- [ ] Parity diff allowlist reviewed and signed off.
- [ ] Backup of production sheet taken (`./scripts/n8n-pull` + GSheet export).
- [ ] Rollback procedure documented: flip `INCOMING_DOCS_ENABLED=false`, restore old `Batch Upsert` workflow ID in 0.1.6's `executeWorkflow` nodes.
- [ ] Sentry alerts wired for: Python 5xx > 1%/5min, Kafka consumer lag > 10k, GSheet 429 rate > 5%/min.
- [ ] On-call runbook published (where to find logs, how to drain Kafka, how to re-introspect Supabase schema).
