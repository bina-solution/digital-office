# QA Run Results

**Date:** 2026-05-13  
**URL:** https://any-concurrency.hacohen.bina-solutions.co.il/  
**Executed by:** GitHub Copilot via Playwright MCP  
**Result:** ✅ 35/35 PASS

---

## Summary

| Group | Cases | Pass | Fail |
|---|---|---|---|
| API | 8 | 8 | 0 |
| UI – Header | 4 | 4 | 0 |
| UI – Filters | 6 | 6 | 0 |
| UI – Controls | 8 | 8 | 0 |
| UI – Gantt | 5 | 5 | 0 |
| Live / Webhook | 4 | 4 | 0 |
| **Total** | **35** | **35** | **0** |

---

## API (01-api.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-API-01 | /healthz returns ok=true | ✅ PASS | HTTP 200, ok=true, all 6 sources present |
| TC-API-02 | /api/sources config | ✅ PASS | 6 keys, traefik_container=traefik-bina-deployment |
| TC-API-03 | /api/spans returns data | ✅ PASS | HTTP 200, 4740 spans |
| TC-API-04 | Single ingest | ✅ PASS | 202 {"ingested":1,"new":1} |
| TC-API-05 | Batch ingest (3 spans) | ✅ PASS | 202 {"ingested":3,"new":3} |
| TC-API-06 | Duplicate is idempotent | ✅ PASS | 202 {"ingested":1,"new":0} |
| TC-API-07 | Close open span | ✅ PASS | 200, status=success, e=timestamp |
| TC-API-08 | /api/span/{id} lookup | ✅ PASS | 200, id+status confirmed |

---

## UI – Header (02-ui-header.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-UI-H01 | Page loads without errors | ✅ PASS | title=any-concurrency, h1 visible, all 3 canvas elements present |
| TC-UI-H02 | Health badge shows sources online | ✅ PASS | All 6 sources show "on" (n8n·traefik·docker·logspan·custom·webhook) |
| TC-UI-H03 | Live badge goes green | ✅ PASS | class=badge live, text=● live |
| TC-UI-H04 | Stats row shows span counts | ✅ PASS | total 4312, n8n 1578, traefik 2712, docker 22, p50 39ms |

---

## UI – Filters (03-ui-filters.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-UI-F01 | Source pill toggles visible | ✅ PASS | 5 src pills present (n8n/traefik/docker/wa/apitools) |
| TC-UI-F02 | Window selector options | ✅ PASS | Options 5m–7d present (value=0.08333333 for 5m) |
| TC-UI-F03 | Service filter dropdown | ✅ PASS | 63 service options loaded |
| TC-UI-F04 | Status filter includes error | ✅ PASS | Options: (all)/canceled/error/running/success |
| TC-UI-F05 | Search box present | ✅ PASS | type=text, placeholder "id / svc / path…" |
| TC-UI-F06 | Reset view button present | ✅ PASS | #btnReset found |

---

## UI – Controls (04-ui-controls.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-UI-C01 | Reload button | ✅ PASS | #btnReload text "↻ reload" |
| TC-UI-C02 | Expand button | ✅ PASS | #btnExpand found |
| TC-UI-C03 | Collapse button | ✅ PASS | #btnCollapse found |
| TC-UI-C04 | Log Y checkbox | ✅ PASS | type=checkbox, default unchecked |
| TC-UI-C05 | Incident markers toggle | ✅ PASS | type=checkbox, default checked |
| TC-UI-C06 | Group by source toggle | ✅ PASS | type=checkbox, default checked |
| TC-UI-C07 | Hide <50ms toggle | ✅ PASS | type=checkbox, default unchecked |
| TC-UI-C08 | Zoom buttons | ✅ PASS | #zIn, #zOut, #zFit all found |

---

## UI – Gantt (05-ui-gantt.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-UI-G01 | Gantt canvas renders spans | ✅ PASS | 1920×2540px canvas, non-blank |
| TC-UI-G02 | Click span opens detail panel | ✅ PASS | aria-hidden=false, class=open; shows id/status/duration |
| TC-UI-G03 | Detail panel closes on × | ✅ PASS | aria-hidden=true after #dClose click |
| TC-UI-G04 | n8n span shows deep link | ✅ PASS | "→ open in n8n" link visible in detail panel |
| TC-UI-G05 | Follow badge pauses on interaction | ✅ PASS | click→⏸ paused, click again→↪ follow |

---

## Live / Webhook (06-live-webhook.md)

| TC | Name | Result | Notes |
|---|---|---|---|
| TC-LIVE-01 | WebSocket connection established | ✅ PASS | badge=live, WS is connected (module-scoped var, not global) |
| TC-LIVE-02 | Webhook span appears live in Gantt | ✅ PASS | DATA 4870→4874 after ingest; span found in client DATA array within 2.5s |
| TC-LIVE-03 | Open span closes live via WS push | ✅ PASS | status running→success, e=null→timestamp after /close |
| TC-LIVE-04 | URL state persists across reload | ✅ PASS | st=error in hash; restored on reload |

---

## Test Data Used

| Span ID | Purpose | Final Status |
|---|---|---|
| qa-single-001 | single ingest + idempotent + close | success |
| qa-batch-001/002/003 | batch ingest | success/success/error |
| qa-live-{ts} | live round-trip | success |
| qa-open-{ts} | open→close via WS | success |

---

## Environment

| Item | Value |
|---|---|
| Live URL | https://any-concurrency.hacohen.bina-solutions.co.il/ |
| Container | any-concurrency-bina-deployment |
| Traefik container | traefik-bina-deployment (auto-discovered) |
| Spans in ring | ~4800 at test time |
| Sources healthy | n8n, traefik, docker, logspan, custom, webhook |
