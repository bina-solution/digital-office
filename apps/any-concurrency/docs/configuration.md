# Configuration Reference

All configuration is via environment variables. None are required — the defaults give you Docker events + Traefik auto-discovery out of the box.

## General

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | Host port binding (standalone compose only) |

## n8n source

| Variable | Default | Description |
|---|---|---|
| `PG_HOST` | _(empty)_ | Postgres host. **Setting this enables the n8n source.** |
| `PG_PORT` | `5432` | Postgres port |
| `PG_USER` | `n8n` | Postgres user |
| `PG_PASS` | _(empty)_ | Postgres password |
| `PG_DB` | `n8n` | Database name |
| `ENABLE_N8N` | auto | Derived from `PG_HOST`; override with `0` to disable |
| `N8N_URL` | _(empty)_ | n8n base URL for deep-link generation in the UI |

## Traefik source

| Variable | Default | Description |
|---|---|---|
| `TRAEFIK_CONTAINER` | _(empty = auto)_ | Container name; empty = auto-discover by image |
| `ENABLE_TRAEFIK` | `1` | Set to `0` to disable |
| `TRAEFIK_BUFFER` | `20000` | Ring-buffer size (max spans in memory) |

Auto-discovery scans running containers for one with `traefik` in its image name, falling back to a container named `traefik`. Set `TRAEFIK_CONTAINER` to skip the scan.

## Docker events source

| Variable | Default | Description |
|---|---|---|
| `ENABLE_DOCKER` | `1` | Set to `0` to disable |
| `DOCKER_BUFFER` | `5000` | Ring-buffer size |

Requires `/var/run/docker.sock` to be mounted read-only.

## LogSpan source

| Variable | Default | Description |
|---|---|---|
| `LOGSPAN_CONTAINER` | _(empty)_ | Container name to tail for `WA_SPAN` log markers |
| `ENABLE_LOGSPAN` | `0` (auto) | Derived from `LOGSPAN_CONTAINER`; set `1` to force enable |
| `WA_BUFFER` | `10000` | Ring-buffer size |

See [`docs/custom-sources.md`](custom-sources.md) for the log-marker format.

## Custom source

| Variable | Default | Description |
|---|---|---|
| `CUSTOM_CONTAINER` | _(empty)_ | Container name to tail for JSON access logs |
| `ENABLE_CUSTOM` | `0` (auto) | Derived from `CUSTOM_CONTAINER`; set `1` to force enable |
| `APITOOLS_BUFFER` | `20000` | Ring-buffer size |

### More than one container

`CUSTOM_CONTAINER` is a single slot. Every further container that emits the same gunicorn JSON
access line gets a lane of its own — its own `src`, ring buffer, tail task and health entry — so a
container that is down or rebuilding fails alone.

| Variable | Default | Description |
|---|---|---|
| `CUSTOM_SOURCE_<ANY>` | _(empty)_ | **One lane**, as `container[=lane]`. One variable per declaring app, so two apps never overwrite each other's declaration. |
| `CUSTOM_SOURCES` | _(empty)_ | Comma/whitespace list of `container[=lane]` — the operator escape hatch for a container no app declares |
| `CUSTOM_BUFFER_<LANE>` | `CUSTOM_BUFFER_DEFAULT` | Ring size for one lane, e.g. `CUSTOM_BUFFER_MAILAPI` |
| `CUSTOM_BUFFER_DEFAULT` | `CUSTOM_BUFFER` | Ring size for lanes that name none. Lower than `CUSTOM_BUFFER` on purpose: there is now one ring per lane in one memory-capped container |
| `ENABLE_CUSTOM_SOURCES` | `1` | Set `0` to ignore every extra lane and keep only the single slot |
| `CUSTOM_HEALTH_PATHS` | `/healthz,/readyz,/health,/livez,/ping,/metrics` | Probe paths dropped from these lanes **when they succeed**; a failing probe is always kept. Set empty to keep everything |

Omit the lane name and it is derived from the container with the deployment suffix stripped
(`mailapi-bina-deployment` → `mailapi`).

**Inside this platform, do not set these on `any-concurrency` directly.** Gate G9 forbids a
layer-2 base app naming a layer-3 app: the consuming app declares its own lane in its `app.json`
`contributes.env`, and `reconcile.py` merges it onto this service. Uninstall the app and its lane
goes with it.

```json
"contributes": { "env": { "any-concurrency": {
  "CUSTOM_SOURCE_MAILAPI": "mailapi-${DEPLOYMENT_NAME:-bina-deployment}=mailapi",
  "CUSTOM_BUFFER_MAILAPI": "8000"
} } }
```

The tailed service must emit gunicorn's access log in the JSON form that carries `duration_us`
(`--access-logformat`, see `apps/apitools/gunicorn.conf.py`). Gunicorn's **default** CLF format has
no duration field, so a span cannot be built from it and the lane stays empty.

## Webhook source

| Variable | Default | Description |
|---|---|---|
| `ENABLE_WEBHOOK` | `1` | Set to `0` to disable `POST /ingest/span` |
| `WEBHOOK_BUFFER` | `10000` | Ring-buffer size |

## Redis / Bull queue

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | _(empty)_ | Redis URL; enables queue panel when set |

## Feature flags

Any `ENABLE_*` variable accepts `0`, `false`, or `False` to disable and anything else (including `1`) to enable.

## Legacy variable aliases

The following variables from earlier versions are still accepted as aliases:

| Old variable | New variable |
|---|---|
| `WA_CONTAINER` | `LOGSPAN_CONTAINER` |
| `APITOOLS_CONTAINER` | `CUSTOM_CONTAINER` |
| `ENABLE_WA` | `ENABLE_LOGSPAN` |
| `ENABLE_APITOOLS` | `ENABLE_CUSTOM` |
