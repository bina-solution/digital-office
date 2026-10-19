# any-concurrency

**Zero-config concurrency observability for n8n, Traefik, Docker, and any custom app.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)](docker-compose.standalone.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

---

![any-concurrency timeline screenshot](docs/screenshot.png)

A lightweight, single-container timeline visualizer that aggregates concurrent execution spans from multiple sources into one live Gantt/brush canvas. See exactly what your stack is doing — right now and historically — without any agents, sidecars, or infrastructure changes.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOUR_ORG/any-concurrency.git
cd any-concurrency

# 2. Start (Docker socket mounted read-only — auto-discovers Traefik)
docker compose -f docker-compose.standalone.yml up -d

# 3. Open
open http://localhost:8080
```

That's it. Docker events and Traefik access logs are collected automatically.

### With n8n (optional profile)

```bash
docker compose -f docker-compose.standalone.yml --profile n8n up -d
# n8n at http://localhost:5678  ·  dashboard at http://localhost:8080
```

### Send a span via webhook

```bash
curl -s -X POST http://localhost:8080/ingest/span \
  -H "Content-Type: application/json" \
  -d '{"id":"job-1","src":"my-app","svc":"import","label":"nightly import","s":'$(date +%s000)',"status":"running"}'
```

Close it when done:

```bash
curl -s -X POST http://localhost:8080/ingest/span/job-1/close \
  -H "Content-Type: application/json" \
  -d '{"status":"success"}'
```

---

## Features

| Feature | Description |
|---|---|
| **n8n timeline** | Live workflow execution spans pulled from n8n's PostgreSQL database |
| **Traefik access log** | Auto-discovers Traefik container; parses CLF access logs into HTTP spans |
| **Docker events** | Container start/stop/die events as instant spans |
| **LogSpan source** | Any container can emit structured `WA_SPAN` JSON log markers |
| **Custom source** | Tails gunicorn/uvicorn JSON access logs from any container |
| **Webhook ingest** | `POST /ingest/span` — push spans from any language, any runtime |
| **Live WebSocket** | Sub-second push of new spans to all connected browsers |
| **URL state** | Full timeline state encoded in URL hash — shareable, bookmarkable |
| **Zero dependencies** | Single Python container, no DB, no agent, no sidecar |

---

## Sources Reference

| Source | Trigger | Config |
|---|---|---|
| `n8n` | n8n Postgres `execution_entity` table (live tail) | `PG_HOST`, `PG_USER`, `PG_PASS`, `PG_DB` |
| `traefik` | Traefik container access log (CLF format) | `TRAEFIK_CONTAINER` (auto-discovered if empty) |
| `docker` | Docker daemon events via `/var/run/docker.sock` | `ENABLE_DOCKER=1` |
| `logspan` | Container log lines containing `WA_SPAN {...}` JSON | `LOGSPAN_CONTAINER=<name>` |
| `custom` | Container JSON access log (gunicorn format) | `CUSTOM_CONTAINER=<name>` |
| _(one per lane)_ | The same access log from **further** containers, one lane each | `CUSTOM_SOURCE_<APP>=<container>[=<lane>]` |
| `<lane>` | An **app-served span endpoint** — spans the app already holds (a table with start/end columns), pulled over HTTP so the window is its history rather than a ring buffer | `SPAN_SOURCE_<APP>=<url>[=<lane>]` |
| `webhook` | `POST /ingest/span` HTTP API | `ENABLE_WEBHOOK=1` (default) |

---

## Configuration

All configuration is via environment variables. See [`.env.example`](.env.example) for a full annotated reference.

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | Host port (standalone compose only) |
| `PG_HOST` | _(empty)_ | n8n Postgres host; empty disables n8n source |
| `PG_PASS` | _(empty)_ | Postgres password |
| `PG_DB` | `n8n` | Database name |
| `TRAEFIK_CONTAINER` | _(empty = auto)_ | Pin exact container name or leave empty for auto-discovery |
| `ENABLE_DOCKER` | `1` | Docker events source on/off |
| `LOGSPAN_CONTAINER` | _(empty)_ | Container to tail for `WA_SPAN` log markers |
| `ENABLE_LOGSPAN` | `0` | LogSpan source on/off |
| `CUSTOM_CONTAINER` | _(empty)_ | Container to tail for JSON access logs |
| `ENABLE_CUSTOM` | `0` | Custom source on/off |
| `CUSTOM_SOURCE_<APP>` | _(empty)_ | One extra lane, `container[=lane]` — see [docs/configuration.md](docs/configuration.md#more-than-one-container) |
| `SPAN_SOURCE_<APP>` | _(empty)_ | One app-served span lane, `url[=lane]`. The lane name comes from the variable name (`SPAN_SOURCE_INDOX` → `indox`) — see [docs/custom-sources.md](docs/custom-sources.md#span-source--an-endpoint-the-app-serves) |
| `SPAN_SOURCE_POLL_S` | `5` | Delta-poll interval for span sources |
| `SPAN_SOURCE_SEED_H` | `24` | Window fetched once when a span source attaches |
| `SPANS_SHARE_S` | `2` | Seconds one `/api/spans` answer serves every viewer of the same window and sources; `0` = an answer each, one at a time |
| `CUSTOM_BUFFER_<LANE>` | `CUSTOM_BUFFER_DEFAULT` | Ring size for one extra lane |
| `CUSTOM_HEALTH_PATHS` | `/healthz,/readyz,…` | Successful probes on these paths are dropped from custom lanes |
| `ENABLE_WEBHOOK` | `1` | Webhook ingest on/off |
| `WEBHOOK_BUFFER` | `10000` | Max webhook spans kept in memory |
| `TRAEFIK_BUFFER` | `20000` | Max traefik spans in memory |
| `DOCKER_BUFFER` | `5000` | Max docker event spans in memory |
| `REDIS_URL` | _(empty)_ | Redis URL for Bull queue visibility panel |
| `N8N_URL` | _(empty)_ | n8n base URL for deep-link generation |

---

## Webhook API

### Ingest a span

```
POST /ingest/span
POST /ingest/spans   (array alias)
```

**Single span:**
```json
{
  "id":     "job-abc-123",
  "src":    "my-app",
  "svc":    "nightly-import",
  "svcid":  "customer-42",
  "label":  "Import customer 42",
  "status": "running",
  "s":      1700000000000,
  "e":      null,
  "meta":   {"rows": 5200}
}
```

**Batch (array):**
```json
[
  {"id": "span-1", "src": "batch", "svc": "step-1", "s": 1700000000000, "e": 1700000001500, "status": "success"},
  {"id": "span-2", "src": "batch", "svc": "step-2", "s": 1700000001500, "e": 1700000003200, "status": "error"}
]
```

**Response:**
```json
{"ingested": 2, "new": 2}
```

### Close an open span

```
POST /ingest/span/{span_id}/close
```
Body (all optional): `{"e": <ms>, "status": "success", "meta": {...}}`

### Span schema

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✓ | Unique span identifier |
| `src` | string | | Source label shown in UI (default: `"webhook"`) |
| `svc` | string | | Service / workflow name |
| `svcid` | string | | Service instance id |
| `label` | string | | Human-readable label |
| `status` | string | | `running` · `success` · `error` · `canceled` · `waiting` · `crashed` |
| `s` | int (ms) | ✓ | Start timestamp in Unix milliseconds |
| `e` | int (ms) | | End timestamp; `null` = span still open |
| `d` | int (ms) | | Duration; computed from `s`/`e` if omitted |
| `meta` | object | | Arbitrary key-value metadata |

---

## REST API

| Endpoint | Method | Description |
|---|---|---|
| `/healthz` | GET | Overall health + per-source status |
| `/api/sources` | GET | Per-source config, health, and last-ok timestamp |
| `/api/spans` | GET | All spans (`?hours=24&sources=n8n,traefik,...`) |
| `/api/span/{id}` | GET | Single span lookup across all stores |
| `/api/n8n/exec/{id}` | GET | Full n8n execution detail + workflow nodes |
| `/api/queue` | GET | Bull queue counts (requires `REDIS_URL`) |
| `/ws` | WebSocket | Live delta stream |
| `/ingest/span` | POST | Webhook ingest (single or array) |
| `/ingest/span/{id}/close` | POST | Close an open span |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        any-concurrency                          │
│                                                                 │
│  Sources                     Core              API / UI         │
│  ─────────────────           ────────────────  ──────────────── │
│  n8n Postgres  ──── live ──▶ RingStore[n8n]  ──▶ /api/spans    │
│                   tail       RingStore[traefik] ▶ /ws (WS)      │
│  Traefik logs  ──── tail ──▶ RingStore[docker] ▶ /healthz       │
│                              RingStore[logspan] ▶ /api/sources  │
│  Docker events ──── sock ──▶ RingStore[custom] ▶ /ingest/span  │
│                              RingStore[webhook]                  │
│  LogSpan logs  ──── tail ──▶         │                          │
│                                      ▼                          │
│  Custom logs   ──── tail ──▶    Hub (fan-out) ──▶ WebSockets   │
│                                                                 │
│  Webhook POST  ──── HTTP ──▶ (above stores)                    │
│                                                                 │
│  Frontend: pure canvas — Gantt + brush + concurrency bars       │
└─────────────────────────────────────────────────────────────────┘
```

Data never leaves your host. No external services, no telemetry, no cloud.

---

## Adding a Custom Source

The fastest integration is the webhook API — one `curl` or a few lines of code:

**Python:**
```python
import httpx, time

def span(id, svc, label):
    httpx.post("http://localhost:8080/ingest/span", json={
        "id": id, "src": "my-service", "svc": svc,
        "label": label, "status": "running",
        "s": int(time.time() * 1000),
    })

def close(id, status="success"):
    httpx.post(f"http://localhost:8080/ingest/span/{id}/close",
               json={"status": status})
```

**Node.js:**
```js
const ingest = (id, svc, label) =>
  fetch('http://localhost:8080/ingest/span', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ id, src: 'my-service', svc, label,
                           status: 'running', s: Date.now() }),
  });
```

See [`docs/custom-sources.md`](docs/custom-sources.md) for the full log-marker format and advanced patterns.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE) © 2024 — built with ❤️ for visibility into concurrent systems.
