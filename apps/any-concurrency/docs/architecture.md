# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            any-concurrency                                  │
│                        (single Docker container)                            │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Source loops (async tasks)                                          │  │
│  │                                                                      │  │
│  │  n8n Postgres ──── live LISTEN/NOTIFY + poll ──────┐                │  │
│  │  Traefik container ──── log tail (CLF) ────────────┤                │  │
│  │  Docker daemon ──── /var/run/docker.sock events ───┤                │  │
│  │  LogSpan container ──── log tail (WA_SPAN JSON) ───┤                │  │
│  │  Custom container ──── log tail (JSON access log) ─┤                │  │
│  │  HTTP POST /ingest/span ───────────────────────────┘                │  │
│  └─────────────────────────────────┬────────────────────────────────────┘  │
│                                    │ upsert_many(spans)                     │
│  ┌─────────────────────────────────▼────────────────────────────────────┐  │
│  │  In-memory RingStore (per source)                                    │  │
│  │  • Ordered by start-time                                             │  │
│  │  • by_id dict for O(1) lookup                                        │  │
│  │  • Configurable ring-buffer eviction                                 │  │
│  │  • upsert semantics: existing spans are updated in-place             │  │
│  └─────────────────────────────────┬────────────────────────────────────┘  │
│                                    │ broadcast delta rows                   │
│  ┌─────────────────────────────────▼────────────────────────────────────┐  │
│  │  Hub (WebSocket fan-out)                                             │  │
│  │  • Registered WebSocket connections                                  │  │
│  │  • JSON push: {"type":"delta","rows":[...]}                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  REST API (FastAPI)                                                         │
│  • GET  /healthz          — per-source liveness                            │
│  • GET  /api/sources      — per-source config + health                     │
│  • GET  /api/spans        — bulk fetch (filter by hours + sources)         │
│  • GET  /api/span/{id}    — single span lookup across all stores           │
│  • POST /ingest/span      — webhook ingest (single or batch)               │
│  • POST /ingest/span/{id}/close — close an open span                       │
│  • WS   /ws               — live delta stream                              │
│  • GET  /                 — serves static/index.html                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Frontend

The UI is a single HTML file with no build step and no JavaScript framework.

Three overlapping HTML canvas elements are used:

| Canvas | Height | Purpose |
|---|---|---|
| `cConc` | 120px | Concurrency bar chart — total active spans per moment |
| `cBrush` | 44px | Time-range brush — drag to zoom, click to jump |
| `cGantt` | dynamic | Gantt lanes — one row per span, grouped by source + service |

State is serialised into the URL hash for sharing/bookmarking.

## Data flow

```
Container log line
      │
      ▼
  _parse_traefik_line()  /  _process()  /  etc.
      │
      ▼
  Span dict: {id, src, svc, svcid, label, status, s, e, d, meta}
      │
      ▼
  RingStore.upsert_many([span])
      │
      ├──▶  broadcast({"type":"delta","rows":[span]})  ──▶  WebSocket clients
      │
      └──▶  GET /api/spans returns all ring-store data on next poll
```

## Source health tracking

Each source has a `_source_health` dict: `{ok: bool, last_ok: int|null, error: str|null}`.

`_mark_source(health, ok, error)` is called on every state change. The `/healthz` and `/api/sources` endpoints expose these dicts directly.

## Span lifecycle

```
status transitions:
  running ──── close() or log event ────▶ success | error | canceled | crashed
  waiting ──── start event ────────────▶ running
```

Spans with `e = null` are "open" and rendered with a pulsing right-edge in the UI.
