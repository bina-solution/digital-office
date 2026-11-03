# any-concurrency QA Suite

Human-readable test plan for the any-concurrency observability dashboard.
Tests are designed to be run manually in a browser **and** to be automated
using the Playwright MCP browser tools.

---

## Quick Run

Open the live dashboard:
```
https://any-concurrency.hacohen.bina-solutions.co.il/
```

Each test case file describes:
- **Pre-condition** — what must be true before the test
- **Steps** — exact actions to perform
- **Expected result** — what "pass" looks like
- **Automated** — the playwright selector / action used when running via MCP

---

## Test Files

| File | Area | Cases |
|---|---|---|
| [01-api.md](cases/01-api.md) | REST API | 8 |
| [02-ui-header.md](cases/02-ui-header.md) | Page load, header, live badge | 4 |
| [03-ui-filters.md](cases/03-ui-filters.md) | Source pills, window, service/status/search | 6 |
| [04-ui-controls.md](cases/04-ui-controls.md) | Buttons, toggles, zoom | 8 |
| [05-ui-gantt.md](cases/05-ui-gantt.md) | Gantt canvas, detail panel, pin | 5 |
| [06-live-webhook.md](cases/06-live-webhook.md) | WebSocket live push, webhook ingest round-trip | 4 |

**Total: 35 test cases**

---

## Results

Execution results are written to [results/run-latest.md](results/run-latest.md)
after each automated run.

---

## Environment

| Variable | Value |
|---|---|
| Base URL | `https://any-concurrency.hacohen.bina-solutions.co.il` |
| Ingest URL | `https://any-concurrency.hacohen.bina-solutions.co.il/ingest/span` |
| Health URL | `https://any-concurrency.hacohen.bina-solutions.co.il/healthz` |

---

## Pass Criteria

All 35 cases must return PASS. Any FAIL blocks release.
A SKIP is acceptable only for environment-specific cases (e.g., n8n deep-link)
marked with `[OPTIONAL]`.
