# QA — 01: REST API

Base URL: `https://any-concurrency.hacohen.bina-solutions.co.il`

---

## TC-API-01 — /healthz returns ok=true

**Pre-condition:** Container is running.

**Steps:**
1. GET `/healthz`
2. Parse JSON response.

**Expected:**
- HTTP 200
- `ok` = `true`
- `sources.n8n`, `sources.traefik`, `sources.docker` = `true`
- `sources.webhook` = `true`
- No field is `null` except `last_ok` for webhook (no spans ingested yet)

---

## TC-API-02 — /api/sources returns per-source config

**Pre-condition:** TC-API-01 passed.

**Steps:**
1. GET `/api/sources`

**Expected:**
- HTTP 200
- Keys present: `n8n`, `traefik`, `docker`, `logspan`, `custom`, `webhook`
- Each entry has `enabled`, `ok`, `last_ok`, `error`, `config`
- `traefik.config.container` is a non-empty string (auto-discovered container name)

---

## TC-API-03 — /api/spans returns data

**Pre-condition:** At least one source is active.

**Steps:**
1. GET `/api/spans?hours=1`

**Expected:**
- HTTP 200
- JSON array (may be empty if no spans in last hour, but must not error)
- Each item has `id`, `src`, `s`, `status`

---

## TC-API-04 — Webhook ingest single span

**Pre-condition:** `ENABLE_WEBHOOK=1` (default).

**Steps:**
1. POST `/ingest/span` with body:
   ```json
   {"id":"qa-single-001","src":"qa","svc":"test","label":"QA single span","s":NOW_MS,"status":"running"}
   ```

**Expected:**
- HTTP 202
- Body: `{"ingested":1,"new":1}`

---

## TC-API-05 — Webhook ingest batch

**Steps:**
1. POST `/ingest/spans` with a JSON array of 3 spans (ids: `qa-batch-001`, `qa-batch-002`, `qa-batch-003`)

**Expected:**
- HTTP 202
- `ingested` = 3, `new` = 3

---

## TC-API-06 — Webhook ingest duplicate is idempotent

**Steps:**
1. POST `/ingest/span` with `id=qa-single-001` (same as TC-API-04)

**Expected:**
- HTTP 202
- `new` = 0 (span already existed)
- `ingested` = 1

---

## TC-API-07 — Close an open span

**Steps:**
1. POST `/ingest/span/qa-single-001/close` with body `{"status":"success"}`

**Expected:**
- HTTP 200
- Response contains `"status":"success"` and `"e"` is a non-null integer

---

## TC-API-08 — /api/span/{id} lookup

**Steps:**
1. GET `/api/span/qa-single-001`

**Expected:**
- HTTP 200
- `id` = `"qa-single-001"`
- `status` = `"success"`
- `src` = `"qa"`
