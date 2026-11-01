"""any-concurrency — deployment-wide concurrency observability.

Real-time Gantt timeline across multiple span sources:
  - docker   : container lifecycle + health events (auto, requires Docker socket)
  - traefik  : HTTP request spans from Traefik access logs (auto-discovered)
  - n8n      : workflow execution spans from n8n Postgres (configure PG_HOST etc.)
  - webhook  : HTTP ingest — POST /ingest/span from any app (always enabled)
  - logspan  : WA_SPAN structured log markers from any container (LOGSPAN_CONTAINER)
  - custom   : gunicorn-style JSON access log tail (CUSTOM_CONTAINER — one container)
  - <alias>  : the same tail against MANY containers (CUSTOM_SOURCES), one lane each
  - <lane>   : spans an APP serves over HTTP (SPAN_SOURCE_<APP>) — for work already recorded as
               a table with start/end columns, where the useful window is history not the tail
  - n8n-bg   : n8n's workers and task runners — the container set is DISCOVERED from Docker and
               rescanned, so a worker added later gets a lane later (N8N_LANES_*), all in one
               section with one lane per container

Mount /var/run/docker.sock (read-only) for Docker + log-tail sources.
See .env.example for the full configuration reference.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import aiodocker
import asyncpg
from pydantic import BaseModel
from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# ── Sentry/GlitchTip error reporting (platform standard) ──────────────────────────
# Wired declaratively: glitchtip-push mints this service's project + deterministic DSN into
# ANY_CONCURRENCY_SENTRY_DSN in .env; compose maps it to SENTRY_DSN. No-op if unset. sentry-sdk
# auto-enables the FastAPI/Starlette integration.
_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
            release=os.getenv("SENTRY_RELEASE"),
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:  # never let telemetry break the app
        pass

# -- config -------------------------------------------------------------------

PG_HOST = os.getenv("PG_HOST", "n8n-postgres")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "root")
PG_PASS = os.getenv("PG_PASSWORD", "password")
PG_DB = os.getenv("PG_DB", "n8n")

REDIS_URL = os.getenv("REDIS_URL", "")

# Public n8n base URL — used to build deep links from the UI to executions.
#
# THE HOST DECIDES THE SCHEME, not a hardcoded default. The platform's edge convention
# (platform/manager/reconcile.py `routing_labels`) publishes every app twice: a `-local` router for
# `<host>.localhost` on the plain **web** entrypoint, and a `-https` router for `${APP}_BASE_URL` on
# **websecure** with the ACME resolver. ACME cannot issue a certificate for a `.localhost` name, so
# there is no TLS listener behind `https://n8n.localhost` and a deep link built with that scheme is
# dead by construction — which is exactly what the board's "open in n8n" button produced locally.
# Every compose default in this repo spells the scheme `${N8N_PROTOCOL:-https}`, so a deployment
# whose DEPLOYMENT_DOMAIN is `localhost` inherits `https` unless someone remembers to override
# N8N_PROTOCOL in .env — a fix that lives only in an untracked file is not a fix.
#
# So: an explicit scheme is honoured for any real domain (a TLS deployment keeps https, and an
# operator can still point N8N_URL at http://127.0.0.1:5678), and is corrected to http only for the
# host family the platform provably serves over plain HTTP.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _is_local_host(netloc: str) -> bool:
    host = netloc.split("@")[-1].rsplit(":", 1)[0].strip("[]").lower()
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def _public_n8n_url() -> str:
    """Normalise whatever the environment supplies into a working `<scheme>://<host>[/path]`."""
    raw = (os.getenv("N8N_URL") or os.getenv("N8N_BASE_URL") or os.getenv("WEBHOOK_URL") or "")
    raw = raw.strip().rstrip("/")
    if not raw:
        return ""
    # `//host` makes urlsplit treat a bare `n8n.example.com` as a host rather than a path.
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    netloc = parts.netloc
    if not netloc:
        return ""
    if _is_local_host(netloc):
        scheme = "http"
    else:
        scheme = parts.scheme or (os.getenv("N8N_PROTOCOL") or "https").strip().lower()
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


N8N_URL = _public_n8n_url()

POLL_INTERVAL_S = float(os.getenv("POLL_INTERVAL_S", "2"))

# Traefik: empty string = auto-discover (scans docker containers by image name).
# Set TRAEFIK_CONTAINER to a specific container name to skip auto-discovery.
TRAEFIK_CONTAINER = os.getenv("TRAEFIK_CONTAINER", "")
TRAEFIK_BUFFER = int(os.getenv("TRAEFIK_BUFFER", "20000"))

# LOGSPAN source: tail a container for WA_SPAN structured log markers.
# Any container that emits lines like: WA_SPAN {"evt":"msg_start","id":"..."}
LOGSPAN_CONTAINER = os.getenv("LOGSPAN_CONTAINER", os.getenv("WA_CONTAINER", ""))
LOGSPAN_BUFFER = int(os.getenv("LOGSPAN_BUFFER", os.getenv("WA_BUFFER", "5000")))

# CUSTOM source: tail a container for gunicorn-style JSON access log lines.
# Lines must contain a "duration_us" field (standard gunicorn JSON access log).
CUSTOM_CONTAINER = os.getenv("CUSTOM_CONTAINER", os.getenv("APITOOLS_CONTAINER", ""))
CUSTOM_BUFFER = int(os.getenv("CUSTOM_BUFFER", os.getenv("APITOOLS_BUFFER", "20000")))

DOCKER_BUFFER = int(os.getenv("DOCKER_BUFFER", "5000"))

# WEBHOOK source: always-on HTTP ingest endpoint (POST /ingest/span).
# Any app can push spans without container log access.
WEBHOOK_BUFFER = int(os.getenv("WEBHOOK_BUFFER", "10000"))
# Legacy buffer aliases
WA_BUFFER = LOGSPAN_BUFFER
APITOOLS_BUFFER = CUSTOM_BUFFER

# Feature flags — all default on; set to 0/false to disable.
_OFF = ("0", "false", "False")
ENABLE_N8N     = os.getenv("ENABLE_N8N",     "1") not in _OFF
ENABLE_TRAEFIK = os.getenv("ENABLE_TRAEFIK", "1") not in _OFF
ENABLE_DOCKER  = os.getenv("ENABLE_DOCKER",  "1") not in _OFF
ENABLE_WEBHOOK = os.getenv("ENABLE_WEBHOOK", "1") not in _OFF
ENABLE_LOGSPAN = os.getenv("ENABLE_LOGSPAN", os.getenv("ENABLE_WA",      "1")) not in _OFF and bool(LOGSPAN_CONTAINER)
ENABLE_CUSTOM  = os.getenv("ENABLE_CUSTOM",  os.getenv("ENABLE_APITOOLS", "1")) not in _OFF and bool(CUSTOM_CONTAINER)
# Public alias for the "custom" source, contributed by the app that feeds it (see its app.json
# `contributes.env`). Empty when no such app is installed, and then no alias is published at all.
CUSTOM_ALIAS   = os.getenv("CUSTOM_SOURCE_ALIAS", "").strip()
# Legacy aliases kept for backwards-compatibility
ENABLE_WA       = ENABLE_LOGSPAN
ENABLE_APITOOLS = ENABLE_CUSTOM
WA_CONTAINER        = LOGSPAN_CONTAINER
APITOOLS_CONTAINER  = CUSTOM_CONTAINER

# ── the custom source, generalised from ONE container to MANY ────────────────────────────────
# Everything above is untouched: a deployment that sets CUSTOM_CONTAINER / APITOOLS_CONTAINER /
# CUSTOM_SOURCE_ALIAS / ENABLE_APITOOLS keeps exactly the behaviour it has today, including the
# `custom` health key, the published alias, and the `at:` span-id prefix. CUSTOM_SOURCES adds
# FURTHER containers alongside that slot; each becomes its own `src` on the timeline with its own
# lane, ring buffer, tail task and health entry, so one dead container cannot stop the others.
#
#   CUSTOM_SOURCES=svc-a=lane-a,svc-b=lane-b
#
# A bare `container` is accepted too; the alias then derives from the container name with the
# deployment suffix stripped (some-svc-bina-deployment -> some-svc) — this platform's container
# naming convention (see any compose file's `container_name:`).
#
# ONE LANE PER DECLARING APP: `CUSTOM_SOURCE_<ANYTHING>=container[=alias]` declares a single lane.
# This is the form the platform itself uses, and the reason it exists is gate G9 — a layer-2 base
# app may not name a layer-3 app, so this service cannot list those containers in its own compose.
# The consuming app declares its own lane in ITS app.json (`contributes.env`) and reconcile.py
# merges it onto this service, exactly as apitools already contributes APITOOLS_CONTAINER. One var
# per app rather than one shared list, because two apps writing the same key would overwrite each
# other; uninstall the app and its lane disappears with it.
_CUSTOM_SOURCE_ENV_RE = re.compile(r"^CUSTOM_SOURCE_[A-Z0-9_]+$")
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME", "").strip()
CUSTOM_SOURCES_RAW = os.getenv("CUSTOM_SOURCES", "")
ENABLE_CUSTOM_SOURCES = os.getenv("ENABLE_CUSTOM_SOURCES", "1") not in _OFF

# Health/readiness probes are polled by docker, traefik and n8n on a fixed interval, so on a quiet
# service they are *most* of the lane and they crowd out the requests that represent real work.
# They are dropped only when they SUCCEEDED — a probe that starts failing is exactly the thing an
# operator needs to see on the timeline, so it is kept. Set CUSTOM_HEALTH_PATHS= (empty) to keep
# every probe.
CUSTOM_HEALTH_PATHS = frozenset(
    p.strip().rstrip("/") or "/"
    for p in os.getenv("CUSTOM_HEALTH_PATHS", "/healthz,/readyz,/health,/livez,/ping,/metrics").split(",")
    if p.strip()
)


class CustomSource(NamedTuple):
    """One tailed container and the timeline source it feeds."""
    container: str
    src: str          # the `src` published on every span from this container
    key: str          # key in source_health ("custom" for the legacy slot, else == src)
    idp: str          # span-id prefix ("at" for the legacy slot — ids stay byte-identical)
    buffer: int


def _sanitise_src(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", name.strip()).strip("-")


def _default_alias(container: str) -> str:
    """`mailapi-bina-deployment` -> `mailapi` when DEPLOYMENT_NAME is known."""
    c = container.strip()
    if DEPLOYMENT_NAME and c.endswith(f"-{DEPLOYMENT_NAME}"):
        c = c[: -(len(DEPLOYMENT_NAME) + 1)]
    return _sanitise_src(c) or c


def _custom_buffer_default() -> int:
    """Ring size for a lane that names none of its own.

    NOT `CUSTOM_BUFFER` (20000): that number sized ONE ring in a 384M container, and there is now
    one ring per lane. A chatty service fills a ring in minutes, so the extra lanes get a smaller
    default and any lane that wants more says so by name.
    """
    try:
        return max(100, int(os.getenv("CUSTOM_BUFFER_DEFAULT", "") or CUSTOM_BUFFER))
    except ValueError:
        return CUSTOM_BUFFER


def _source_buffer(src: str) -> int:
    """Per-source ring size, same `*_BUFFER` idiom as every other source.

    CUSTOM_BUFFER_MAILAPI=5000 sizes the `mailapi` lane; CUSTOM_BUFFER_DEFAULT is the fallback.
    """
    env = "CUSTOM_BUFFER_" + re.sub(r"[^A-Z0-9]", "_", src.upper())
    fallback = _custom_buffer_default()
    try:
        return max(100, int(os.getenv(env, "") or fallback))
    except ValueError:
        return fallback


def _build_custom_sources() -> list[CustomSource]:
    out: list[CustomSource] = []
    seen: set[str] = set()
    # The legacy single slot always comes first so it keeps ownership of the "custom" health key.
    if ENABLE_CUSTOM and CUSTOM_CONTAINER:
        legacy_src = CUSTOM_ALIAS or "custom"
        out.append(CustomSource(CUSTOM_CONTAINER, legacy_src, "custom", "at", CUSTOM_BUFFER))
        seen.add(CUSTOM_CONTAINER)
    if ENABLE_CUSTOM_SOURCES:
        # CUSTOM_SOURCES (one list) first, then one CUSTOM_SOURCE_<APP> per declaring app, sorted
        # so the lane order is deterministic rather than dependent on environ ordering.
        specs = list(re.split(r"[,\s]+", CUSTOM_SOURCES_RAW.strip()))
        specs += [
            v for _, v in sorted(
                (k, v) for k, v in os.environ.items()
                # CUSTOM_SOURCE_ALIAS is the LEGACY single-slot alias, not a lane declaration.
                if k != "CUSTOM_SOURCE_ALIAS" and _CUSTOM_SOURCE_ENV_RE.match(k) and v.strip()
            )
        ]
        for item in specs:
            item = item.strip()
            if not item:
                continue
            container, _, alias = item.partition("=")
            container = container.strip()
            if not container or container in seen:
                continue
            src = _sanitise_src(alias) or _default_alias(container)
            if not src or src in {s.src for s in out}:
                continue
            out.append(CustomSource(container, src, src, src, _source_buffer(src)))
            seen.add(container)
    return out


CUSTOM_SOURCE_LIST = _build_custom_sources()
# Extra sources beyond the legacy slot — the ones that need their own health entry and store.
EXTRA_CUSTOM_SOURCES = [s for s in CUSTOM_SOURCE_LIST if s.key != "custom"]

# ── span sources: a lane an app SERVES, rather than one this service reads out of a log ───────
# Same inversion as CUSTOM_SOURCE_<APP> above (the app declares its own lane in its app.json
# `contributes.env`; this base app names no app), for work whose spans are not in a log line.
#
#   SPAN_SOURCE_<APP>=<url>[=<lane>]
#
# Why a third mechanism rather than reusing one of the two that exist:
#   · A LOG TAIL can only see what a container printed, and only as far back as the ring holds.
#     Some apps already HOLD their spans as a table — INDOX's action-dispatch brackets are
#     literally (started_at, ended_at) rows going back days — and the useful window for those is
#     the history, not the tail.
#   · READING THAT DATABASE FROM HERE would put a layer-3 schema inside a layer-2 base app (gate
#     G9), and would need a network this container is deliberately not on.
#   · PUSHING to /ingest/span would work, but the ring is memory: the history would end at the
#     next restart, and every producer would have to double-write on its hot path.
# So the app serves the projection and this service pulls it. The app owns the meaning; this
# service only stores and draws. That is exactly the `n8n` source's contract, one hop further out:
# the DB is the store of record, the ring is only the live tail.
#
# The endpoint answers two questions, both returning this service's own span schema:
#   GET <url>?hours=<h>   the whole window (served straight through by /api/spans)
#   GET <url>?since=<ms>  anything that STARTED OR ENDED after <ms> (the delta poll)
# `since` is start-or-end and not start-alone on purpose: a span that opened an hour ago and
# closes now must reach the timeline when it closes, or it renders as running forever.
_SPAN_SOURCE_ENV_RE = re.compile(r"^SPAN_SOURCE_[A-Z0-9_]+$")
SPAN_SOURCES_RAW = os.getenv("SPAN_SOURCES", "")
ENABLE_SPAN_SOURCES = os.getenv("ENABLE_SPAN_SOURCES", "1") not in _OFF
SPAN_SOURCE_POLL_S = max(2.0, float(os.getenv("SPAN_SOURCE_POLL_S", "5") or 5))
SPAN_SOURCE_TIMEOUT_S = max(2.0, float(os.getenv("SPAN_SOURCE_TIMEOUT_S", "25") or 25))
# Seed window on attach, and the overlap re-asked for on every delta poll. The overlap is what
# absorbs clock skew and an endpoint that stamps `since` off its own DB rather than ours; upserts
# are idempotent (RingStore returns only what actually changed), so re-asking costs nothing.
SPAN_SOURCE_SEED_H = max(0.1, float(os.getenv("SPAN_SOURCE_SEED_H", "24") or 24))
SPAN_SOURCE_OVERLAP_S = max(5.0, float(os.getenv("SPAN_SOURCE_OVERLAP_S", "60") or 60))


class SpanSource(NamedTuple):
    """One app-served span endpoint and the timeline source it feeds."""
    url: str
    src: str          # the `src` published on every span from this endpoint
    key: str          # key in source_health (== src)
    buffer: int


def _span_buffer(src: str) -> int:
    """Per-source ring size — `SPAN_BUFFER_<SRC>`, else `SPAN_BUFFER_DEFAULT`.

    Separate from CUSTOM_BUFFER_* rather than shared: these lanes are sized by how much HISTORY
    is worth holding in front of the endpoint, not by how chatty a container's log is.
    """
    try:
        fallback = max(100, int(os.getenv("SPAN_BUFFER_DEFAULT", "") or 20000))
    except ValueError:
        fallback = 20000
    env = "SPAN_BUFFER_" + re.sub(r"[^A-Z0-9]", "_", src.upper())
    try:
        return max(100, int(os.getenv(env, "") or fallback))
    except ValueError:
        return fallback


def _split_span_spec(item: str) -> tuple[str, str]:
    """`<url>[=<lane>]` -> (url, lane). A query string in the URL does NOT become a lane.

    An inline `=lane` is only recognised when the last `=` sits before any `?`, because
    `…/spans?rows=doc` and `…/spans` + lane `doc` are otherwise the same eight characters.
    A URL that carries a query therefore names its lane by env-var name (or by hostname),
    never inline — which is what `SPAN_SOURCE_<APP>` does anyway.
    """
    q, eq = item.find("?"), item.rfind("=")
    if eq <= 0 or (q != -1 and eq > q):
        return item.strip(), ""
    url, lane = item[:eq].strip(), item[eq + 1:].strip()
    if re.search(r"[/:?&]", lane):          # a lane name is a bare token
        return item.strip(), ""
    return url, lane


def _build_span_sources() -> list[SpanSource]:
    """`SPAN_SOURCES` (operator escape hatch) plus one `SPAN_SOURCE_<APP>` per declaring app.

    The lane name comes from the env var NAME first (`SPAN_SOURCE_INDOX` -> `indox`, the same
    reading `CUSTOM_SOURCE_MAILAPI` already gets), then from an inline `=lane`, then from the
    URL's hostname. Naming it in the key is what keeps a URL with a query string unambiguous.

    Sorted by env key so lane order is deterministic rather than dependent on environ ordering —
    same reason `_build_custom_sources` sorts.
    """
    if not ENABLE_SPAN_SOURCES:
        return []
    #: (value, lane-from-key or "") pairs, escape hatch first so a declaring app cannot be
    #: displaced by an operator list entry that names the same lane.
    specs: list[tuple[str, str]] = [
        (v, "") for v in re.split(r"[,\s]+", SPAN_SOURCES_RAW.strip())
    ]
    specs += [(v, k[len("SPAN_SOURCE_"):]) for k, v in sorted(os.environ.items())
              if _SPAN_SOURCE_ENV_RE.match(k) and v.strip()]
    out: list[SpanSource] = []
    seen_url: set[str] = set()
    for item, from_key in specs:
        item = item.strip()
        if not item:
            continue
        url, inline = _split_span_spec(item)
        if not url.startswith(("http://", "https://")) or url in seen_url:
            continue
        src = (_sanitise_src(from_key.lower()) or _sanitise_src(inline)
               or _sanitise_src(urlsplit(url).hostname or ""))
        if not src or src in {s.src for s in out}:
            continue
        out.append(SpanSource(url, src, src, _span_buffer(src)))
        seen_url.add(url)
    return out


SPAN_SOURCE_LIST = _build_span_sources()

# ── n8n background lanes: the workers and task runners, DISCOVERED not declared ───────────────
# The n8n containers are the one set that a CUSTOM_SOURCE_* declaration cannot describe. Every
# other lane is one app -> one container, fixed at install time; n8n is one app -> a container SET
# that changes without an install: `n8n-worker-3` appears when the worker count is raised, each
# worker brings its own task-runner sidecar, and a declaration written today names the containers
# that existed today. So this source takes the container list from Docker instead of from the
# environment, and re-reads it on a timer (N8N_LANES_SCAN_S) so a container that appears at 03:00
# gets its lane at 03:00.
#
# ONE `src` for the whole set. The timeline draws a section per `src` and a row per `svc`, so
# sharing one src is what makes "workers + runners" a single section with a row per container
# rather than six sections. The per-container identity is the `svc` (`worker-1/executions`,
# `runner-2/runner`) and the health key (`n8n-bg:worker-1`), so nothing is lost by sharing it.
ENABLE_N8N_LANES = os.getenv("ENABLE_N8N_LANES", "1") not in _OFF
N8N_LANES_SRC = os.getenv("N8N_LANES_SRC", "n8n-bg").strip() or "n8n-bg"
N8N_LANES_SCAN_S = max(5.0, float(os.getenv("N8N_LANES_SCAN_S", "45") or 45))
# One ring for the whole section (it is one `src`). Sized for the whole worker set, not per lane.
N8N_LANES_BUFFER = max(1000, int(os.getenv("N8N_LANES_BUFFER", "24000") or 24000))
N8N_LANES_TAIL = max(0, int(os.getenv("N8N_LANES_TAIL", "5000") or 5000))

# ── per-TASK spans, from n8n's own event bus ─────────────────────────────────────────────────
# The lanes above draw the launcher's state and the broker's complaints, which answers "is the
# runner wedged" but not "what ran". No log answers that: the shipped task-broker logs ONLY
# rejections, deferrals, ack timeouts and errors, and the JS runner logs nothing per task — so
# every task that SUCCEEDS is invisible in every log on the box, which is precisely why a busy
# runner reads as a dead one.
#
# n8n does record it, just not to stdout. Its internal event bus brackets every task with
#   n8n.runner.task.requested  {taskId, nodeId, executionId, workflowId}
#   n8n.runner.response.received {taskId, ...}
# and the event-bus log WRITER runs unlicensed (the log-streaming *destinations* are the paid
# part), so those pairs are already being written to `<n8n user folder>/n8nEventLog*.log` on this
# deployment — 5,720 of them in the current files, at millisecond resolution. Pair them on taskId
# and you have the real start and end of every task, with no n8n change and no restart.
#
# The timestamps are requester-side: they span broker queueing + runner execution + result
# transport. For a contention timeline that is the more honest number — the wait IS the problem.
ENABLE_N8N_TASKS = os.getenv("ENABLE_N8N_TASKS", "1") not in _OFF
# The n8n user folder, mounted read-only (docker-compose.yml). All n8n processes share it.
N8N_EVENTLOG_DIR = os.getenv("N8N_EVENTLOG_DIR", "/n8n-data").strip()
# The LIVE files only; `-1/-2/-3` are this writer's rotations, i.e. history we do not re-read.
# `file[=lane]`: the optional lane PINS every task in that file to one runner lane, which is what
# makes attribution exact once each n8n process is given its own event log (see `_n8n_task_lane`).
N8N_EVENTLOG_FILES: list[tuple[str, str]] = []
for _spec in os.getenv("N8N_EVENTLOG_FILES", "n8nEventLog.log,n8nEventLog-worker.log").split(","):
    _spec = _spec.strip()
    if _spec:
        _f, _, _lane = _spec.partition("=")
        N8N_EVENTLOG_FILES.append((_f.strip(), _lane.strip()))
N8N_TASKS_POLL_S = max(0.25, float(os.getenv("N8N_TASKS_POLL_S", "1.5") or 1.5))
# How much of an existing file to replay on attach, so the lane is not empty until the next task.
N8N_TASKS_BACKFILL = max(0, int(os.getenv("N8N_TASKS_BACKFILL_BYTES", "3000000") or 3000000))
# A request with no response after this long stops being tracked; its span stays open on the
# timeline, which is the correct picture — that task never came back.
N8N_TASKS_TTL_S = max(60.0, float(os.getenv("N8N_TASKS_TTL_S", "1800") or 1800))
# How often to reconcile still-open task spans against execution_entity (the DB is truth).
N8N_TASKS_RECONCILE_S = max(5.0, float(os.getenv("N8N_TASKS_RECONCILE_S", "20") or 20))
_N8N_TASKS_KEY = f"{N8N_LANES_SRC}:tasks"

# `sources=` default: the historical list verbatim, plus every configured custom source, so a new
# lane shows up without the caller having to know it exists. Callers that pass an explicit
# `sources=` are unaffected.
_BASE_SOURCES = ["n8n", "traefik", "docker", "logspan", "custom", "webhook", "wa", "apitools"]
if ENABLE_N8N_LANES:
    _BASE_SOURCES.append(N8N_LANES_SRC)
DEFAULT_SOURCES = ",".join(dict.fromkeys(
    _BASE_SOURCES + [s.src for s in CUSTOM_SOURCE_LIST] + [s.src for s in SPAN_SOURCE_LIST]))

STATIC_DIR = Path(__file__).parent / "static"

# -- n8n source ---------------------------------------------------------------

# Aggregate highlight metadata into a JSON blob per execution. Workflows may
# write either `highlight.outline` or the shorter legacy `outline`; both surface
# as `meta.highlight.outline` on the timeline.
_HL_JOIN = """
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(
        CASE WHEN m.key = 'outline' THEN 'highlight.outline' ELSE m.key END,
        m.value
    ) AS hl
  FROM execution_metadata m
    WHERE m."executionId" = e.id AND (m.key LIKE 'highlight.%' OR m.key = 'outline')
) hl ON true
"""

# The datetime params are cast `$N::timestamptz` explicitly. The execution_entity timestamps are
# timestamptz and the params are tz-aware UTC, so this changes no VALUE — it pins the param type.
# Without the cast, asyncpg occasionally described the param as naive `timestamp` and then failed to
# encode the aware value ("can't subtract offset-naive and offset-aware datetimes"), an intermittent
# codec hiccup that surfaced as a P6 baseline warn ("[n8n] tail query failed"). The cast removes the
# ambiguity so the aware codec is always chosen.
EXEC_SELECT = f"""
SELECT
    e.id,
    e."workflowId" AS wfid,
    COALESCE(w.name, '(unknown)') AS wf,
    e.mode,
    e.status,
    e.finished,
    e."startedAt",
    e."stoppedAt",
    e."deletedAt" IS NOT NULL AS del,
    hl.hl AS highlight
FROM execution_entity e
LEFT JOIN workflow_entity w ON w.id = e."workflowId"
{_HL_JOIN}
WHERE e."startedAt" >= $1::timestamptz
ORDER BY e."startedAt"
"""

EXEC_DELTA = f"""
SELECT
    e.id,
    e."workflowId" AS wfid,
    COALESCE(w.name, '(unknown)') AS wf,
    e.mode,
    e.status,
    e.finished,
    e."startedAt",
    e."stoppedAt",
    e."deletedAt" IS NOT NULL AS del,
    hl.hl AS highlight
FROM execution_entity e
LEFT JOIN workflow_entity w ON w.id = e."workflowId"
{_HL_JOIN}
WHERE e."startedAt" >= $1::timestamptz
  AND (
       e."startedAt" > $2::timestamptz
    OR (e."stoppedAt" IS NOT NULL AND e."stoppedAt" > $2::timestamptz)
  )
ORDER BY e."startedAt"
"""


# A bar is ~6px per glyph wide, so the label has to say the most useful thing FIRST.
# `#<id> <mode>` said only what every other n8n bar already said ("#457571 webhook"); the
# workflow's own `outline` says what that execution actually DID. The id stays as a short
# prefix because it is how an execution is identified everywhere else in this UI (drawer
# subtitle, deep link, `/api/n8n/exec/<id>`), and `mode` survives in `meta` either way.
_LABEL_MAX = 120


def _hl_label(hl: dict[str, Any] | None) -> str | None:
    """Pick the bar summary out of an execution's highlight metadata.

    `outline` is the canonical one and wins outright; any other declared `highlight.*`
    key is accepted in declaration order, which is what the ordered strip in `_n8n_row`
    is preserved for. Returns None when nothing usable was written.
    """
    if not isinstance(hl, dict):
        return None
    for k in ("outline", *hl.keys()):
        v = hl.get(k)
        if v is None:
            continue
        s = v.strip() if isinstance(v, str) else str(v)
        if not s or s in ("null", "undefined"):
            continue
        return s if len(s) <= _LABEL_MAX else s[: _LABEL_MAX - 1] + "…"
    return None


def _n8n_row(r: asyncpg.Record) -> dict[str, Any]:
    started: datetime | None = r["startedAt"]
    stopped: datetime | None = r["stoppedAt"]
    s_ms = int(started.timestamp() * 1000) if started else None
    e_ms = int(stopped.timestamp() * 1000) if stopped else None
    d_ms = (e_ms - s_ms) if (s_ms is not None and e_ms is not None) else None
    meta: dict[str, Any] = {"id": r["id"], "mode": r["mode"], "fin": bool(r["finished"]), "del": bool(r["del"])}
    raw_hl = r["highlight"] if "highlight" in r.keys() else None
    if raw_hl:
        if isinstance(raw_hl, str):
            try:
                raw_hl = json.loads(raw_hl)
            except Exception:
                raw_hl = None
        if isinstance(raw_hl, dict):
            # Strip the redundant "highlight." prefix; keep insertion order
            # so the first declared highlight wins for the bar label.
            stripped = {
                (k[10:] if k.startswith("highlight.") else k): (v.strip().strip('"') if isinstance(v, str) else v)
                for k, v in raw_hl.items()
            }
            meta["highlight"] = stripped
    outline = _hl_label(meta.get("highlight"))
    return {
        "id": f"n8n:{r['id']}",
        "src": "n8n",
        "svc": r["wf"],
        "svcid": r["wfid"] or "_",
        "label": f"#{r['id']} {outline}" if outline else f"#{r['id']} {r['mode']}",
        "status": r["status"] or "unknown",
        "s": s_ms,
        "e": e_ms,
        "d": d_ms,
        "meta": meta,
    }


# -- traefik CLF parser -------------------------------------------------------

# Traefik default access log format:
# <remoteaddr> - <user> [<date>] "<method> <uri> <proto>" <status> <bytes>
#   "<referrer>" "<ua>" <reqcount> "<routername>" "<serviceurl>" <duration>ms
_CLF_RE = re.compile(
    r'^(?P<ip>\S+)\s+-\s+(?P<user>\S+)\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>[^"]*?)\s+(?P<proto>[^"]+)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\d+|-)\s+'
    r'"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)"\s+'
    r'(?P<rcount>\d+)\s+"(?P<router>[^"]*)"\s+"(?P<svcurl>[^"]*)"\s+'
    r'(?P<dur>\d+)ms\s*$'
)


def _parse_traefik_line(line: str) -> dict[str, Any] | None:
    m = _CLF_RE.match(line)
    if not m:
        return None
    try:
        # Traefik date: 02/Jan/2006:15:04:05 +0000
        ts = datetime.strptime(m.group("ts"), "%d/%b/%Y:%H:%M:%S %z")
    except Exception:
        return None
    dur_ms = int(m.group("dur"))
    end_ms = int(ts.timestamp() * 1000) + dur_ms  # log written at request end
    start_ms = end_ms - dur_ms
    status_code = int(m.group("status"))
    if 200 <= status_code < 400:
        st = "success"
    elif 400 <= status_code < 500:
        st = "canceled"  # client error -> grey-ish
    else:
        st = "error"
    router = m.group("router") or "(none)"
    # router name like "n8n-https@docker" -> service key
    svc = router.split("@", 1)[0] if router else "(none)"
    path = m.group("path")
    return {
        "id": f"tr:{end_ms}:{m.group('rcount')}",
        "src": "traefik",
        "svc": svc,
        "svcid": svc,
        "label": f"{m.group('method')} {path[:80]}",
        "status": st,
        "s": start_ms,
        "e": end_ms,
        "d": dur_ms,
        "meta": {
            "code": status_code,
            "method": m.group("method"),
            "path": path,
            "router": router,
            "ip": m.group("ip"),
            "ua": m.group("ua")[:120],
        },
    }


# -- in-memory ring buffers for traefik + docker ------------------------------

class RingStore:
    def __init__(self, maxlen: int) -> None:
        self.items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.by_id: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    async def upsert_many(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async with self.lock:
            new_or_changed: list[dict[str, Any]] = []
            for r in rows:
                prev = self.by_id.get(r["id"])
                if prev is None:
                    if len(self.items) == self.items.maxlen and self.items:
                        evicted = self.items[0]
                        self.by_id.pop(evicted["id"], None)
                    self.items.append(r)
                    self.by_id[r["id"]] = r
                    new_or_changed.append(r)
                else:
                    if prev != r:
                        prev.update(r)
                        new_or_changed.append(prev)
            return new_or_changed

    async def open_spans(self, svc_suffix: str) -> list[dict[str, Any]]:
        """Every span still open for a service whose id ends with svc_suffix."""
        async with self.lock:
            return [it for it in self.items
                    if it.get("e") is None and str(it.get("svcid") or "").endswith(svc_suffix)]

    async def close_by_id(self, ends: dict[str, tuple[int, str]]) -> list[dict[str, Any]]:
        """Close specific spans: {span_id: (end_ms, status)}. Returns the rows that changed."""
        out: list[dict[str, Any]] = []
        async with self.lock:
            for sid, (end_ms, status) in ends.items():
                it = self.by_id.get(sid)
                if it is None or it.get("e") is not None:
                    continue
                st = it.get("s")
                end = max(int(float(st)), int(end_ms)) if st is not None else int(end_ms)
                it["e"] = end
                it["d"] = end - int(float(st)) if st is not None else 0
                it["status"] = status
                out.append(it)
        return out

    async def close_stale_open(self, svc_suffix: str, ttl_ms: float,
                               status: str = "unknown") -> list[dict[str, Any]]:
        """Close spans still open past their TTL, working from the STORE rather than from the
        tailer's `pending` map.

        Why this exists: `pending` lives in the tailer's memory, the published span lives here. Any
        restart of the tracer resets `pending` to empty while leaving already-published OPEN spans
        in the ring -- and nothing could ever close those again. They render as a task running
        forever, which is precisely the stall this timeline exists to disprove.

        Measured 2026-08-19: four `shape:get` spans on runner-2/tasks shown running for 17,265s
        (execs 3421929/31/32/33) while all four executions were gmailApiImap01 runs that SUCCEEDED
        in 8 seconds, 4.6 hours earlier. An earlier instance: exec 3414455, shown at 1,954s, had
        succeeded in under a second. Both survived the 1,800s `_trim` because they were no longer
        in `pending` to be trimmed.

        Closes as `unknown`, not `error`: we genuinely do not know how the task ended, and marking
        a succeeded execution's span `error` would trade one false alarm for another.
        """
        now = time.time() * 1000
        out: list[dict[str, Any]] = []
        async with self.lock:
            for it in self.items:
                if it.get("e") is not None:
                    continue
                if not str(it.get("svcid") or "").endswith(svc_suffix):
                    continue
                st = it.get("s")
                if st is None or (now - float(st)) < ttl_ms:
                    continue
                end = int(float(st) + ttl_ms)
                it["e"] = end
                it["d"] = end - int(float(st))
                it["status"] = status
                out.append(it)
        return out

    def since(self, t_ms: int) -> list[dict[str, Any]]:
        # include open spans (e is None) regardless of start, plus any closed span whose end is in window
        return [it for it in self.items if it.get("e") is None or it["e"] >= t_ms]


def _source_health(enabled: bool) -> dict[str, Any]:
    return {"enabled": enabled, "ok": False, "last_ok": None, "last_error": None, "last_event": None}


def _mark_source(health: dict[str, Any], ok: bool, error: str | None = None, event: bool = False) -> None:
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    health["ok"] = ok
    if ok:
        health["last_ok"] = now
        health["last_error"] = None
    elif error:
        health["last_error"] = error[:300]
    if event:
        health["last_event"] = now


# -- docker source ------------------------------------------------------------

def _docker_status(state: str | None, exit_code: int | None) -> str:
    if state == "running":
        return "running"
    if state in ("exited", "dead"):
        if exit_code is None or exit_code == 0:
            return "success"
        return "error"
    if state == "restarting":
        return "waiting"
    if state == "created":
        return "new"
    return state or "unknown"


async def docker_seed(docker: aiodocker.Docker, store: RingStore) -> None:
    """Initial snapshot of currently-running containers as open spans."""
    try:
        containers = await docker.containers.list(all=True)
    except Exception as exc:
        print(f"[docker] seed failed: {exc}")
        return
    rows = []
    for c in containers:
        try:
            info = await c.show()
        except Exception:
            continue
        state = info.get("State", {}) or {}
        started_at = state.get("StartedAt") or info.get("Created")
        finished_at = state.get("FinishedAt")
        if not started_at:
            continue
        s_ms = _parse_iso_ms(started_at)
        e_ms = _parse_iso_ms(finished_at) if finished_at and not finished_at.startswith("0001") else None
        if s_ms is None:
            continue
        name = (info.get("Name") or "").lstrip("/")
        cid = info.get("Id", "")[:12]
        st = _docker_status(state.get("Status"), state.get("ExitCode"))
        rows.append({
            "id": f"dk:{cid}:{s_ms}",
            "src": "docker",
            "svc": name or cid,
            "svcid": name or cid,
            "label": f"{name} ({state.get('Status','?')})",
            "status": st,
            "s": s_ms,
            "e": e_ms,
            "d": (e_ms - s_ms) if e_ms is not None else None,
            "meta": {"id": cid, "image": info.get("Config", {}).get("Image"), "exit": state.get("ExitCode")},
        })
    await store.upsert_many(rows)


def _parse_iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        # Strip trailing Z and fractional seconds beyond microseconds
        s2 = s.rstrip("Z")
        if "." in s2:
            head, frac = s2.split(".", 1)
            frac = frac[:6]
            s2 = f"{head}.{frac}"
        dt = datetime.fromisoformat(s2).replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


async def docker_events_loop(docker: aiodocker.Docker, store: RingStore, broadcast, health: dict[str, Any]) -> None:
    """Watch container lifecycle events and emit start/stop spans."""
    open_spans: dict[str, dict[str, Any]] = {}
    # Pre-populate from current state
    for it in list(store.items):
        if it["src"] == "docker" and it.get("e") is None:
            open_spans[it["meta"]["id"]] = it

    while True:
        try:
            subscriber = docker.events.subscribe()
            _mark_source(health, True)
            while True:
                ev = await subscriber.get()
                if ev is None:
                    break
                if ev.get("Type") != "container":
                    continue
                action = ev.get("Action", "")
                attrs = ev.get("Actor", {}).get("Attributes", {}) or {}
                cid = ev.get("Actor", {}).get("ID", "")[:12]
                name = attrs.get("name") or cid
                # aiodocker may pass `time` as int seconds OR a datetime (newer versions)
                t_raw = ev.get("time", 0)
                if isinstance(t_raw, datetime):
                    t_ms = int(t_raw.timestamp() * 1000)
                else:
                    try:
                        t_ms = int(float(t_raw) * 1000)
                    except Exception:
                        t_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                if action == "start":
                    span = {
                        "id": f"dk:{cid}:{t_ms}",
                        "src": "docker",
                        "svc": name,
                        "svcid": name,
                        "label": f"{name} (running)",
                        "status": "running",
                        "s": t_ms,
                        "e": None,
                        "d": None,
                        "meta": {"id": cid, "image": attrs.get("image"), "exit": None},
                    }
                    open_spans[cid] = span
                    new = await store.upsert_many([span])
                    _mark_source(health, True, event=True)
                    if new:
                        await broadcast({"type": "delta", "rows": new})
                elif action.startswith("health_status"):
                    # docker emits "health_status: healthy" / "health_status: unhealthy"
                    healthy = action.endswith("healthy") and not action.endswith("unhealthy")
                    unhealthy = action.endswith("unhealthy")
                    if not (healthy or unhealthy):
                        continue
                    marker = {
                        "id": f"dk-h:{cid}:{t_ms}",
                        "src": "docker",
                        "svc": name,
                        "svcid": name,
                        "label": f"{name} health: {'healthy' if healthy else 'unhealthy'}",
                        "status": "success" if healthy else "crashed",
                        "s": t_ms,
                        "e": t_ms + 1,
                        "d": 1,
                        "meta": {"id": cid, "image": attrs.get("image"), "event": action, "marker": "health"},
                    }
                    new = await store.upsert_many([marker])
                    _mark_source(health, True, event=True)
                    if new:
                        await broadcast({"type": "delta", "rows": new})
                    continue
                elif action == "restart":
                    marker = {
                        "id": f"dk-r:{cid}:{t_ms}",
                        "src": "docker",
                        "svc": name,
                        "svcid": name,
                        "label": f"{name} restart",
                        "status": "crashed",
                        "s": t_ms,
                        "e": t_ms + 1,
                        "d": 1,
                        "meta": {"id": cid, "image": attrs.get("image"), "event": action, "marker": "restart"},
                    }
                    new = await store.upsert_many([marker])
                    _mark_source(health, True, event=True)
                    if new:
                        await broadcast({"type": "delta", "rows": new})
                    continue
                elif action in ("die", "kill", "stop", "oom"):
                    span = open_spans.pop(cid, None)
                    exit_code = None
                    try:
                        exit_code = int(attrs.get("exitCode", "0"))
                    except Exception:
                        pass
                    if action == "oom":
                        st = "crashed"
                    elif exit_code == 0:
                        st = "success"
                    else:
                        st = "error"
                    if span is None:
                        # synthesize without start
                        span = {
                            "id": f"dk:{cid}:{t_ms}",
                            "src": "docker",
                            "svc": name,
                            "svcid": name,
                            "label": f"{name} ({action})",
                            "status": st,
                            "s": t_ms - 1000,
                            "e": t_ms,
                            "d": 1000,
                            "meta": {"id": cid, "image": attrs.get("image"), "exit": exit_code},
                        }
                    else:
                        span = dict(span)
                        span["e"] = t_ms
                        span["d"] = t_ms - span["s"]
                        span["status"] = st
                        span["label"] = f"{name} ({action})"
                        span["meta"]["exit"] = exit_code
                    new = await store.upsert_many([span])
                    _mark_source(health, True, event=True)
                    if new:
                        await broadcast({"type": "delta", "rows": new})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            print(f"[docker] events loop error: {exc}; retry in 5s")
            await asyncio.sleep(5)


# -- traefik log tail loop ----------------------------------------------------

_TRAEFIK_IMAGE_HINTS = ("traefik",)


async def _discover_traefik_container(docker: aiodocker.Docker) -> str | None:
    """Return the name of a running Traefik container, or None.

    Discovery order:
    1. TRAEFIK_CONTAINER env var (if non-empty) — pinned by operator.
    2. Container named exactly 'traefik'.
    3. Any running container whose image name contains 'traefik'.
    """
    if TRAEFIK_CONTAINER:
        return TRAEFIK_CONTAINER
    try:
        await docker.containers.get("traefik")
        return "traefik"
    except Exception:
        pass
    try:
        containers = await docker.containers.list(all=False)
        for c in containers:
            try:
                info = await c.show()
            except Exception:
                continue
            image = ((info.get("Config") or {}).get("Image") or "").lower()
            name = (info.get("Name") or "").lstrip("/")
            if any(h in image for h in _TRAEFIK_IMAGE_HINTS) or "traefik" in name.lower():
                return name
    except Exception:
        pass
    return None


async def traefik_log_loop(docker: aiodocker.Docker, store: RingStore, broadcast, health: dict[str, Any]) -> None:
    """Tail traefik container logs and parse CLF access lines into spans."""
    while True:
        try:
            cname = await _discover_traefik_container(docker)
            if not cname:
                _mark_source(health, False, "no traefik container found; set TRAEFIK_CONTAINER env var")
                print("[traefik] no container found; retry in 30s. Tip: set TRAEFIK_CONTAINER env var.")
                await asyncio.sleep(30)
                continue
            try:
                container = await docker.containers.get(cname)
                _mark_source(health, True)
                print(f"[traefik] following container: {cname}")
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[traefik] container '{cname}' not found: {type(exc).__name__}: {exc!r}")
                await asyncio.sleep(15)
                continue
            # First, pull recent logs as a snapshot (tail=2000 lines)
            try:
                snap = await container.log(stdout=True, stderr=False, tail=2000, follow=False)
                rows = []
                for line in snap:
                    span = _parse_traefik_line(line.rstrip("\n"))
                    if span:
                        rows.append(span)
                if rows:
                    await store.upsert_many(rows)
                    _mark_source(health, True, event=True)
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[traefik] snapshot failed: {type(exc).__name__}: {exc!r}")

            # Now follow
            async for line in container.log(stdout=True, stderr=False, follow=True, tail=0):
                span = _parse_traefik_line(line.rstrip("\n"))
                if not span:
                    continue
                new = await store.upsert_many([span])
                _mark_source(health, True, event=True)
                if new:
                    await broadcast({"type": "delta", "rows": new})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            print(f"[traefik] tail error: {type(exc).__name__}: {exc!r}; retry in 5s")
            await asyncio.sleep(5)


# -- logspan: structured span markers in container logs -----------------------
# Any container can emit WA_SPAN JSON markers; this loop tails that container.
# Format: a log line containing: WA_SPAN {"evt":"msg_start","id":"<id>",...}
#                           or:  WA_SPAN {"evt":"msg_end","id":"<id>","dur":<ms>,"ok":true}
# Set LOGSPAN_CONTAINER to the container name. When empty this source is skipped.

_WA_RE = re.compile(r"WA_SPAN\s+(\{.*\})\s*$")


async def logspan_log_loop(docker: aiodocker.Docker, store: RingStore, broadcast, health: dict[str, Any]) -> None:
    """Tail LOGSPAN_CONTAINER for WA_SPAN log markers and convert to spans."""
    open_spans: dict[str, dict[str, Any]] = {}

    def _process(line: str) -> dict[str, Any] | None:
        m = _WA_RE.search(line)
        if not m:
            return None
        try:
            j = json.loads(m.group(1))
        except Exception:
            return None
        evt = j.get("evt")
        sid = j.get("id")
        if not sid:
            return None
        if evt == "msg_start":
            span = {
                "id": f"ls:{sid}",
                "src": "logspan",
                "svc": (j.get("type") or "message"),
                "svcid": j.get("from") or "unknown",
                "label": (("→ " if j.get("fromMe") else "← ") + (j.get("from") or "unknown")),
                "status": "running",
                "s": int(j.get("ts") or 0),
                "e": None,
                "d": None,
                "meta": {"from": j.get("from"), "fromMe": j.get("fromMe"), "type": j.get("type")},
            }
            open_spans[sid] = span
            return span
        if evt == "msg_end":
            base = open_spans.pop(sid, None)
            end_ts = int(j.get("ts") or 0)
            dur = j.get("dur")
            if base is None:
                start_ts = end_ts - int(dur or 0)
                base = {
                    "id": f"ls:{sid}", "src": "logspan", "svc": "message",
                    "svcid": "unknown", "label": "(unmatched)", "status": "running",
                    "s": start_ts, "e": None, "d": None, "meta": {},
                }
            base["e"] = end_ts
            base["d"] = int(dur) if dur is not None else max(0, end_ts - base["s"])
            base["status"] = "success" if j.get("ok") else "error"
            if j.get("err"):
                base["meta"] = {**(base.get("meta") or {}), "err": j["err"]}
            return base
        return None

    while True:
        try:
            try:
                container = await docker.containers.get(LOGSPAN_CONTAINER)
                _mark_source(health, True)
                print(f"[logspan] following container: {LOGSPAN_CONTAINER}")
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[logspan] container not found ({LOGSPAN_CONTAINER}): {type(exc).__name__}: {exc!r}")
                await asyncio.sleep(15)
                continue
            try:
                snap = await container.log(stdout=True, stderr=True, tail=5000, follow=False, timestamps=True)
                rows = []
                for line in snap:
                    span = _process(line.rstrip("\n"))
                    if span:
                        rows.append(span)
                if rows:
                    await store.upsert_many(rows)
                    _mark_source(health, True, event=True)
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[logspan] snapshot failed: {type(exc).__name__}: {exc!r}")

            async for line in container.log(stdout=True, stderr=True, follow=True, tail=0, timestamps=True):
                span = _process(line.rstrip("\n"))
                if not span:
                    continue
                new = await store.upsert_many([span])
                _mark_source(health, True, event=True)
                if new:
                    await broadcast({"type": "delta", "rows": new})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            print(f"[logspan] tail error: {type(exc).__name__}: {exc!r}; retry in 5s")
            await asyncio.sleep(5)


# -- custom: gunicorn JSON access log tail --------------------------------------

# gunicorn json access lines like:
# {"timestamp":"[11/May/2026:17:53:52 +0000]","client_ip":"...","method":"POST",
#  "path":"/documentJsonQuery","query":"","status":200,"response_bytes":2206,
#  "user_agent":"axios/1.12.0","duration_us":8666176}
# We detect access lines by presence of `"duration_us"` (app json logs use `duration_ms`).
_APITOOLS_RE = re.compile(r'(\{[^\n]*?"duration_us"[^\n]*?\})\s*$')



# ── n8n worker / task-runner lanes ────────────────────────────────────────────────────────────
# n8n does not log access lines; it logs lifecycle sentences, and a unit of work is TWO lines:
#   Worker started execution 3401082 (job 339887)
#   Worker finished execution 3401082 (job 339887)
# so a span only closes when the second arrives. `_N8N_OPEN` holds the starts we have seen but
# not yet closed, keyed by (lane, execution id) — one dict per process, bounded below.
#
# The warnings are the whole point of these lanes. A saturated task runner does NOT raise: the
# broker logs offer expiry at INFO and an ack timeout at WARN, then silently waits for
# N8N_RUNNERS_TASK_REQUEST_TIMEOUT. Measured 2026-08-18: 16 driver lanes sat wedged for 15
# minutes with zero errors anywhere. Rendering those lines as point events is what makes that
# failure visible while it is happening instead of half an hour later.
#
# The task-runner sidecars are a different log entirely: a Go launcher, ANSI-coloured, carrying
# its own clock and level token, which at the configured level (N8N_RUNNERS_LAUNCHER_LOG_LEVEL,
# `info` here) says almost nothing after boot — seven lines and then silence for hours. Reading it
# the same way as a worker is why those three lanes were empty. So a launcher is read as a STATE
# MACHINE instead: each phase line OPENS a span that stays open until the next phase line closes
# it, which means the lane always draws the phase the launcher is in right now — and "js: offer
# pending" stretching across the whole window is exactly the picture of a runner that never got
# its offer accepted. Unrecognised WARN/ERROR lines are kept as point events too, so a message
# this table never anticipated is still visible rather than dropped.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The Go launcher stamps its own LOCAL clock on every line, on top of the docker timestamp we
# already read (`…Z 2026/08/18 16:50:36 INFO …`). Two clocks in one label, one of them in the
# wrong timezone, is worse than none — so its copy is dropped from the text.
_N8N_GOCLOCK_RE = re.compile(r"^\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s+")

_N8N_OPEN: dict[tuple[str, str], int] = {}
_N8N_OPEN_MAX = 4000
# executionId -> the worker lane that ran it, learned from `Worker started execution N`. The event
# bus names the HOST for queue events but not for task events, so this is the second of two ways a
# task gets attributed to the runner that served it (see `_n8n_task_lane`).
_N8N_EXEC_LANE: dict[str, str] = {}
_N8N_EXEC_LANE_MAX = 20000
# (lane, runtime) -> the phase span currently open on that launcher lane.
_N8N_PHASE: dict[tuple[str, str], dict[str, Any]] = {}
_N8N_PHASE_MAX = 200

_N8N_TS_RE      = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s+(.*)$")
_N8N_START_RE   = re.compile(r"Worker started execution (\d+)(?:\s+\(job (\d+)\))?")
_N8N_FINISH_RE  = re.compile(r"Worker finished execution (\d+)(?:\s+\(job (\d+)\))?")
# `[launcher:js]` / `[runner:py]` — which of the launcher's runtimes a line is about.
_N8N_KIND_RE    = re.compile(r"\[(?:launcher|runner):([a-z0-9]+)\]")
# The Go launcher's level token (`INFO  `/`WARN  `/`ERROR `) and winston's `[warn]` form. n8n's own
# worker lines carry NO level (verified on this deployment), so this catch-all cannot flood.
_N8N_LEVEL_RE   = re.compile(r"(?:^|\s)(?:\[(warn|error|fatal)\]|(WARN|ERROR|FATAL))(?:\s|$)")

# The launcher's state machine. First match wins, so order matters.
_N8N_PHASE_RES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"Starting launcher goroutine"),                       "launcher starting",  "unknown"),
    (re.compile(r"Waiting for task broker to be ready"),               "waiting for broker", "unknown"),
    (re.compile(r"Task broker is ready|[Cc]onnected to (?:the )?task broker"), "broker ready", "unknown"),
    (re.compile(r"Waiting for launcher's task offer to be accepted"),  "offer pending",      "unknown"),
    (re.compile(r"(?:Launching|Starting) runner"),                     "runner launching",   "running"),
    (re.compile(r"Runner (?:process )?(?:is )?(?:started|ready|launched|registered)"), "runner up", "running"),
]
# Instants, not intervals. The idle-timeout exit is tested before the generic "Runner process
# exited" in _N8N_WARN_RES below, or a clean idle shutdown would be drawn as a crash.
# Idle is NOT work. "Waiting for launcher's task offer to be accepted" is the launcher's RESTING
# state: it holds for as long as an attached runtime has nothing to do, which on this estate is
# essentially always for `py` and most of the time for `js`. Drawn as an open phase span it
# painted every runner lane with one full-width bar per runtime and buried the millisecond task
# ticks underneath. Matching it now CLOSES whatever phase was open and opens nothing, so a quiet
# lane reads as "attached, waiting for work" -- which is what it means.
_N8N_IDLE_PHASES = {"offer pending"}

_N8N_EVENT_RES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"Starting launcher's health check server(?: at port (\d+))?"), "launcher up",   "success"),
    (re.compile(r"Runner process exited on idle timeout"),        "runner idle-shutdown", "canceled"),
    (re.compile(r"Sending shutdown signal to runner"),            "runner shutdown",      "canceled"),
]
_N8N_WARN_RES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"took too long to acknowledge acceptance of task \((\S+?)\)"), "runner ack timeout", "error"),
    (re.compile(r'rejected by Runner with reason "([^"]+)"'),                     "offer rejected",     "error"),
    (re.compile(r"Task request timed out"),                                       "task request timeout", "error"),
    (re.compile(r"job stalled more than maxStalledCount \(execution (\d+)\)"),   "bull stall",         "error"),
    (re.compile(r"Found runner unresponsive \((\d+/\d+)\)"),                     "runner unresponsive","error"),
    (re.compile(r"Task broker is down"),                                          "broker down",        "error"),
    (re.compile(r"Runner process exited(?: with error: (.+))?"),                  "runner exited",      "error"),
    (re.compile(r"(JavaScript heap out of memory|possible out-of-memory)"),        "out of memory",      "error"),
]
# Lines that end a launcher's current phase rather than merely annotating it.
_N8N_PHASE_ENDERS = {"runner idle-shutdown", "runner shutdown", "runner exited", "broker down"}


def _n8n_ts_ms(raw: str | None) -> int:
    if raw:
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            pass
    return int(time.time() * 1000)


def _n8n_point(src: str, lane: str, svc: str, label: str, status: str, ts_ms: int,
               detail: str = "", body: str = "", **meta: Any) -> dict[str, Any]:
    """A zero-duration span: something that happened at an instant, not over an interval."""
    return {
        "id": f"{src}:{lane}:{svc[:1]}:{ts_ms}:{abs(hash((label, detail, body))) & 0xffffffff}",
        "src": src, "svc": f"{lane}/{svc}", "svcid": f"{lane}/{svc}",
        "label": (f"{label}: {detail}" if detail else label)[:90],
        "status": status,
        "s": ts_ms, "e": ts_ms, "d": 0,
        "meta": {"lane": lane, "kind": label, "detail": detail[:160], "line": body[:200], **meta},
    }


def _n8n_phase_close(lane: str, kind: str, ts_ms: int, status: str = "success") -> dict[str, Any] | None:
    """Close the phase open on (lane, runtime); the returned copy re-upserts over the open one."""
    prev = _N8N_PHASE.pop((lane, kind), None)
    if prev is None:
        return None
    end = max(int(prev["s"]), ts_ms)
    return {**prev, "e": end, "d": end - int(prev["s"]), "status": status}


def _n8n_spans(line: str, lane: str, src: str) -> list[dict[str, Any]]:
    """One log line from one n8n container -> the spans it produces on that container's lane.

    Returns a LIST because closing a phase and opening the next one is a single line's work.
    """
    raw = line.rstrip("\n").strip()
    m = _N8N_TS_RE.match(raw)
    ts_ms = _n8n_ts_ms(m.group(1) if m else None)
    body = _N8N_GOCLOCK_RE.sub("", _ANSI_RE.sub("", m.group(2) if m else raw).strip())
    if not body:
        return []

    m2 = _N8N_START_RE.search(body)
    if m2:
        if len(_N8N_OPEN) > _N8N_OPEN_MAX:
            _N8N_OPEN.clear()
        _N8N_OPEN[(lane, m2.group(1))] = ts_ms
        if len(_N8N_EXEC_LANE) > _N8N_EXEC_LANE_MAX:
            _N8N_EXEC_LANE.clear()
        _N8N_EXEC_LANE[m2.group(1)] = lane   # which machine ran it -> which runner served it
        return []                        # nothing to draw until it closes

    m2 = _N8N_FINISH_RE.search(body)
    if m2:
        ex = m2.group(1)
        start = _N8N_OPEN.pop((lane, ex), None)
        s_ms = start if start is not None else ts_ms
        return [{
            "id": f"{src}:{lane}:x:{ex}",
            "src": src, "svc": f"{lane}/executions", "svcid": f"{lane}/executions",
            "label": f"execution #{ex}" + (f" (job {m2.group(2)})" if m2.group(2) else ""),
            "status": "success",
            "s": s_ms, "e": ts_ms, "d": max(0, ts_ms - s_ms),
            "meta": {"lane": lane, "execution": ex, "job": m2.group(2), "truncated": start is None},
        }]

    km = _N8N_KIND_RE.search(body)
    kind = km.group(1) if km else "launcher"
    # `js:`/`py:` says WHICH runtime; the untagged launcher lines need no prefix at all.
    tag = f"{kind}: " if km else ""

    for rx, label, status in _N8N_EVENT_RES:
        w = rx.search(body)
        if w:
            detail = (w.group(1) if w.groups() else "") or ""
            out: list[dict[str, Any]] = []
            if label in _N8N_PHASE_ENDERS:
                closed = _n8n_phase_close(lane, kind, ts_ms, status)
                if closed:
                    out.append(closed)
            out.append(_n8n_point(src, lane, "runner", f"{tag}{label}", status, ts_ms,
                                  detail, body, runtime=kind))
            return out

    for rx, label, status in _N8N_PHASE_RES:
        if not rx.search(body):
            continue
        cur = _N8N_PHASE.get((lane, kind))
        if cur is not None and (cur.get("meta") or {}).get("phase") == label:
            return []                    # the same phase restated; the open span already says it
        out = []
        closed = _n8n_phase_close(lane, kind, ts_ms)
        if closed:
            out.append(closed)
        if label in _N8N_IDLE_PHASES:
            return out                   # idle: close what was open, draw nothing
        span = {
            "id": f"{src}:{lane}:p:{kind}:{ts_ms}",
            "src": src, "svc": f"{lane}/runner", "svcid": f"{lane}/runner",
            "label": f"{tag}{label}",
            "status": status,
            "s": ts_ms, "e": None, "d": None,
            "meta": {"lane": lane, "phase": label, "runtime": kind, "line": body[:200]},
        }
        if len(_N8N_PHASE) > _N8N_PHASE_MAX:
            _N8N_PHASE.clear()
        _N8N_PHASE[(lane, kind)] = span
        out.append(span)
        return out

    for rx, label, status in _N8N_WARN_RES:
        w = rx.search(body)
        if w:
            detail = (w.group(1) if w.groups() else "") or ""
            out = []
            if label in _N8N_PHASE_ENDERS:
                closed = _n8n_phase_close(lane, kind, ts_ms, "error")
                if closed:
                    out.append(closed)
            out.append(_n8n_point(src, lane, "warnings", label, status, ts_ms, detail, body,
                                  runtime=kind))
            return out

    lvl = _N8N_LEVEL_RE.search(body)
    if lvl:
        level = (lvl.group(1) or lvl.group(2) or "").lower()
        msg = _N8N_LEVEL_RE.sub(" ", body, count=1).strip()
        return [_n8n_point(src, lane, "warnings", level, "error", ts_ms, msg[:80], body,
                           runtime=kind)]
    return []


def _parse_n8n_line(line: str, src: str, idp: str) -> dict[str, Any] | None:
    """Back-compat single-span shim for a hand-declared `CUSTOM_SOURCE_*=<n8n container>` lane.

    The discovered lanes (`n8n_lanes_loop`) call `_n8n_spans` directly, because a phase change
    produces two spans and this shape can only carry one.
    """
    spans = _n8n_spans(line, idp or src, src)
    return spans[-1] if spans else None


# ── which containers are n8n's, and what to call their lanes ─────────────────────────────────
# Named by structure, not by a list: `n8n-worker-<N>[-runners]`, `n8n-task-runners`,
# `n8n-webhook[-<N>]`, `n8n` — each optionally suffixed with the deployment name. Matching the
# STRUCTURE is what makes a worker that does not exist yet already have a lane.
_N8N_ROLE_RES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^n8n-worker-(\d+)-runners$"), "runner-{0}"),
    (re.compile(r"^n8n-task-runners$"),         "runner-main"),
    (re.compile(r"^n8n-worker-(\d+)$"),         "worker-{0}"),
    (re.compile(r"^n8n-webhook(?:-(\d+))?$"),   "webhook-{0}"),
    (re.compile(r"^n8n$"),                      "main"),
)
# The unambiguous roles, used to LEARN the deployment suffix when DEPLOYMENT_NAME is not set.
# Without it `n8n-postgres-<dep>` would strip down to `n8n` and masquerade as the main lane.
_N8N_SUFFIX_RES: tuple[re.Pattern, ...] = (
    re.compile(r"^n8n-worker-\d+-runners-(.+)$"),
    re.compile(r"^n8n-task-runners-(.+)$"),
    re.compile(r"^n8n-worker-\d+-(?!runners(?:-|$))(.+)$"),
)


def _n8n_role(stem: str) -> str | None:
    for rx, tpl in _N8N_ROLE_RES:
        m = rx.fullmatch(stem)
        if not m:
            continue
        n = (m.group(1) if m.groups() else None) or ""
        return tpl.format(n) if "{0}" in tpl else tpl
    return None


def _n8n_deployment_suffixes(names: list[str]) -> frozenset[str]:
    if DEPLOYMENT_NAME:
        return frozenset({DEPLOYMENT_NAME})
    out: set[str] = set()
    for raw in names:
        n = raw.lstrip("/")
        for rx in _N8N_SUFFIX_RES:
            m = rx.match(n)
            if m:
                out.add(m.group(1))
    return frozenset(out)


def _n8n_lane_name(container: str, suffixes: frozenset[str] = frozenset()) -> str | None:
    """`n8n-worker-1-runners-shlomo-laptop` -> `runner-1`; a non-n8n container -> None."""
    n = (container or "").strip().lstrip("/")
    stems = [n]
    for suf in suffixes:
        if suf and n.endswith(f"-{suf}"):
            stems.append(n[: -(len(suf) + 1)])
    for stem in stems:
        role = _n8n_role(stem)
        if role:
            return role.rstrip("-") or None
    return None


def _parse_custom_line(line: str, src: str = "", idp: str = "at") -> dict[str, Any] | None:
    """Parse one gunicorn JSON access line into a span for source `src`.

    `src`/`idp` are what make this one parser serve many containers: apitools, mailapi and drive
    all emit the identical format (see each service's gunicorn access-logformat), so the only
    per-source facts are the lane name and the span-id prefix.
    """
    src = src or CUSTOM_ALIAS or "custom"
    # n8n lanes speak lifecycle sentences, not gunicorn JSON — route them to their own reader.
    if src.startswith("n8n-"):
        return _parse_n8n_line(line, src, idp)
    m = _APITOOLS_RE.search(line)
    if not m:
        return None
    try:
        j = json.loads(m.group(1))
    except Exception:
        return None
    if "duration_us" not in j:
        return None
    ts_raw = (j.get("timestamp") or "").strip("[]")
    try:
        ts = datetime.strptime(ts_raw, "%d/%b/%Y:%H:%M:%S %z")
    except Exception:
        return None
    try:
        dur_us = int(j.get("duration_us") or 0)
    except Exception:
        dur_us = 0
    dur_ms = max(0, dur_us // 1000)
    end_ms = int(ts.timestamp() * 1000) + dur_ms  # gunicorn writes line at request end
    start_ms = end_ms - dur_ms
    try:
        code = int(j.get("status") or 0)
    except Exception:
        code = 0
    if 200 <= code < 400:
        st = "success"
    elif 400 <= code < 500:
        st = "canceled"
    elif code >= 500:
        st = "error"
    else:
        st = "unknown"
    method = (j.get("method") or "?").upper()
    path = j.get("path") or "/"
    # A SUCCEEDING health/readiness probe is infrastructure polling, not work: docker, traefik and
    # n8n hit these on a fixed interval, and on a quiet service they would otherwise be most of the
    # lane. A FAILING one is kept — that is the case an operator has to see.
    if code < 400 and (path.rstrip("/") or "/") in CUSTOM_HEALTH_PATHS:
        return None
    # group by first two path segments so the lane stays compact (e.g. /incomingDocuments/repos)
    parts = [p for p in path.split("/") if p][:2]
    svc = ("/" + "/".join(parts)) if parts else "/"
    return {
        "id": f"{idp}:{end_ms}:{code}:{abs(hash((method, path, j.get('client_ip'), dur_us))) & 0xffffffff}",
        "src": src,
        "svc": svc,
        "svcid": svc,
        "label": f"{method} {path[:80]}",
        "status": st,
        "s": start_ms,
        "e": end_ms,
        "d": dur_ms,
        "meta": {
            "code": code,
            "method": method,
            "path": path,
            "query": j.get("query"),
            "ip": j.get("client_ip"),
            "ua": (j.get("user_agent") or "")[:120],
            "bytes": j.get("response_bytes"),
        },
    }


# Legacy name — kept so anything calling the old single-source parser still works unchanged.
_parse_apitools_line = _parse_custom_line


async def custom_log_loop(
    docker: aiodocker.Docker,
    store: RingStore,
    broadcast,
    health: dict[str, Any],
    source: CustomSource | None = None,
    parse: Callable[[str], list[dict[str, Any]]] | None = None,
    tail: int = 5000,
) -> None:
    """Tail ONE container's logs and turn its lines into spans.

    One task per container: each retries its own container independently, so a source whose
    container is stopped or rebuilding cannot stall the others' tails.

    `parse` overrides the line reader for callers whose log is not a gunicorn access log — it
    returns a LIST because one line can be two spans (an n8n launcher phase line both closes the
    phase that was open and opens the next one). The default keeps the single-span behaviour.
    """
    if source is None:  # legacy call shape — the single CUSTOM_CONTAINER slot
        source = CustomSource(APITOOLS_CONTAINER, CUSTOM_ALIAS or "custom", "custom", "at", CUSTOM_BUFFER)
    src, idp = source.src, source.idp

    def _default_parse(ln: str) -> list[dict[str, Any]]:
        span = _parse_custom_line(ln, src, idp)
        return [span] if span else []

    _parse = parse or _default_parse
    tag = source.src
    while True:
        try:
            try:
                container = await docker.containers.get(source.container)
                _mark_source(health, True)
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[{tag}] container not found ({source.container}): {type(exc).__name__}: {exc!r}")
                await asyncio.sleep(15)
                continue
            try:
                snap = await container.log(stdout=True, stderr=True, tail=tail, follow=False, timestamps=True)
                rows = []
                for line in snap:
                    rows.extend(_parse(line.rstrip("\n")))
                if rows:
                    await store.upsert_many(rows)
                    _mark_source(health, True, event=True)
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[{tag}] snapshot failed: {type(exc).__name__}: {exc!r}")

            async for line in container.log(stdout=True, stderr=True, follow=True, tail=0, timestamps=True):
                spans = _parse(line.rstrip("\n"))
                if not spans:
                    continue
                new = await store.upsert_many(spans)
                _mark_source(health, True, event=True)
                if new:
                    await broadcast({"type": "delta", "rows": new})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            print(f"[{tag}] tail error: {type(exc).__name__}: {exc!r}; retry in 5s")
            await asyncio.sleep(5)


_SPAN_STATUSES = frozenset(("running", "success", "error", "canceled", "waiting", "crashed", "unknown"))


def _coerce_spans(payload: Any, src: str) -> list[dict[str, Any]]:
    """Validate an app's span payload into this service's schema.

    Defensive on purpose: the producer is another app's endpoint, not this codebase, so a single
    malformed row must cost that row and nothing else. `src` is FORCED to the configured lane —
    an endpoint declared as lane X cannot publish into lane Y, however it labels its rows.
    """
    rows = payload if isinstance(payload, list) else (payload or {}).get("spans")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("id") or "").strip()
        try:
            s_ms = int(float(r["s"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not sid:
            continue
        e_ms: int | None
        try:
            e_ms = int(float(r["e"])) if r.get("e") is not None else None
        except (TypeError, ValueError):
            e_ms = None
        # An end before the start is not renderable — clamp rather than drop, so the event is
        # still visible (as an instant) instead of silently vanishing from the timeline.
        if e_ms is not None and e_ms < s_ms:
            e_ms = s_ms
        st = str(r.get("status") or "unknown")
        meta = r.get("meta")
        out.append({
            "id": f"{src}:{sid}",
            "src": src,
            "svc": str(r.get("svc") or src),
            "svcid": str(r.get("svcid") or ""),
            "label": str(r.get("label") or sid)[:_LABEL_MAX],
            "status": st if st in _SPAN_STATUSES else "unknown",
            "s": s_ms,
            "e": e_ms,
            "d": (e_ms - s_ms) if e_ms is not None else None,
            "meta": meta if isinstance(meta, dict) else {},
        })
    return out


async def _fetch_span_source(source: SpanSource, session: aiohttp.ClientSession | None = None,
                             *, hours: float | None = None,
                             since_ms: int | None = None) -> list[dict[str, Any]]:
    """One GET against an app's span endpoint. `hours` = window, `since_ms` = delta."""
    params = ({"hours": f"{hours:g}"} if hours is not None
              else {"since": str(int(since_ms or 0))})
    timeout = aiohttp.ClientTimeout(total=SPAN_SOURCE_TIMEOUT_S)
    if session is not None:
        async with session.get(source.url, params=params, timeout=timeout) as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)
    else:
        async with aiohttp.ClientSession(timeout=timeout) as own:
            async with own.get(source.url, params=params) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
    return _coerce_spans(payload, source.src)


async def span_pull_loop(store: RingStore, broadcast, health: dict[str, Any],
                         source: SpanSource) -> None:
    """Seed one app-served lane over `SPAN_SOURCE_SEED_H`, then poll it for deltas.

    One task per source — a slow or dead endpoint stalls its own lane and no other. The cursor
    advances only after a SUCCESSFUL fetch and never past the instant that fetch began, so a
    span written while the request was in flight is re-asked for on the next poll rather than
    skipped; the overlap on top of that absorbs clock skew between this container and the app's.
    """
    seeded = False
    cursor_ms = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                asked_at_ms = int(time.time() * 1000)
                rows = await (_fetch_span_source(source, session, since_ms=cursor_ms) if seeded
                              else _fetch_span_source(source, session, hours=SPAN_SOURCE_SEED_H))
                new = await store.upsert_many(rows) if rows else []
                cursor_ms = max(0, asked_at_ms - int(SPAN_SOURCE_OVERLAP_S * 1000))
                if not seeded:
                    seeded = True
                    print(f"[{source.src}] seeded {len(rows)} span(s) over {SPAN_SOURCE_SEED_H:g}h "
                          f"from {source.url}")
                _mark_source(health, True, event=bool(new))
                if new:
                    await broadcast({"type": "delta", "rows": new})
                await asyncio.sleep(SPAN_SOURCE_POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _mark_source(health, False, repr(exc))
                print(f"[{source.src}] span pull failed ({source.url}): "
                      f"{type(exc).__name__}: {exc!r}; retry in 15s")
                await asyncio.sleep(15)


async def _running_container_names(docker: aiodocker.Docker) -> list[str]:
    """Names of the running containers, from the list endpoint (one call, no per-container show)."""
    out: list[str] = []
    for c in await docker.containers.list(all=False):
        try:
            names = c["Names"] or []
        except Exception:
            names = []
        for n in names:
            n = (n or "").lstrip("/")
            if n:
                out.append(n)
                break
    return out


async def n8n_lanes_loop(
    docker: aiodocker.Docker,
    store: RingStore,
    broadcast,
    health: dict[str, Any],
    lanes: dict[str, dict[str, Any]],
) -> None:
    """Keep one tail task per n8n container, re-deciding the container set on every scan.

    This is the difference between a lane you configure and a lane that exists: a worker added
    (or removed) while this process runs gets (or loses) its lane at the next scan, with no
    config edit and no restart. A container that disappears has its tail cancelled and its health
    entry dropped, so `/healthz` describes the containers that are there NOW rather than the ones
    that were there at boot.
    """
    tails: dict[str, asyncio.Task] = {}
    prefix = f"{N8N_LANES_SRC}:"
    try:
        while True:
            try:
                names = await _running_container_names(docker)
                suffixes = _n8n_deployment_suffixes(names)
                want: dict[str, str] = {}
                claimed: set[str] = set()
                for name in sorted(names):
                    lane = _n8n_lane_name(name, suffixes)
                    if lane and lane not in claimed:   # first container wins a lane name
                        want[name] = lane
                        claimed.add(lane)

                for cname, lane in sorted(want.items()):
                    running = tails.get(cname)
                    if running is not None and not running.done():
                        continue
                    key = f"{prefix}{lane}"
                    health.setdefault(key, _source_health(True))
                    lanes[key] = {"container": cname, "lane": lane}
                    cs = CustomSource(cname, N8N_LANES_SRC, key, lane, N8N_LANES_BUFFER)
                    tails[cname] = asyncio.create_task(custom_log_loop(
                        docker, store, broadcast, health[key], cs,
                        parse=(lambda ln, _l=lane: _n8n_spans(ln, _l, N8N_LANES_SRC)),
                        tail=N8N_LANES_TAIL,
                    ))
                    print(f"[{N8N_LANES_SRC}] + lane {lane} <- {cname}")

                for cname in [c for c in tails if c not in want]:
                    tails.pop(cname).cancel()
                    for key, meta in list(lanes.items()):
                        if meta.get("container") == cname:
                            lanes.pop(key, None)
                            health.pop(key, None)
                    print(f"[{N8N_LANES_SRC}] - lane <- {cname} (container gone)")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[{N8N_LANES_SRC}] scan failed: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(N8N_LANES_SCAN_S)
    finally:
        for t in tails.values():
            t.cancel()


# ── per-task spans: tail n8n's event-bus log ──────────────────────────────────────────────────

_N8N_HOST_WORKER_RE = re.compile(r"n8n-worker-(\d+)")
_N8N_WORKER_LANE_RE = re.compile(r"worker-(\d+)")


def _n8n_task_lane(host: str | None, execution: str | None, is_main: bool) -> str:
    """Which RUNNER lane a task belongs to.

    A task is served by the runner sidecar attached to the process that requested it — the
    sidecar's own `N8N_RUNNERS_TASK_BROKER_URI` points at exactly one worker's broker, so
    worker-1 -> runner-1 is not a guess. Two independent sources say which process that was:
    the event bus names the host on its queue events, and the worker's own log says which
    executions it started.

    Neither covers a SUB-workflow execution. It never enters the bull queue (it runs inside its
    parent's process) so no `n8n.queue.job.*` event ever carries its host, and the worker only
    logs the top-level execution it picked up. Roughly half the tasks on this deployment are
    from sub-workflows, and both workers append to the SAME event-log file, so there is no honest
    way to split those between runner-1 and runner-2 — guessing would put real tasks on the wrong
    runner, which is worse than not placing them. They go to their own visible lane instead.

    The fix is one env var per worker, and it needs an n8n restart:
    `N8N_EVENTBUS_LOGWRITER_LOGBASENAME=n8nEventLog-worker-1` (…-2, …) gives each worker its own
    file, and then the file itself names the runner and attribution is exact for every task.
    """
    if host:
        m = _N8N_HOST_WORKER_RE.search(host)
        if m:
            return f"runner-{m.group(1)}"
        if host.startswith("main"):
            return "runner-main"
    lane = _N8N_EXEC_LANE.get(execution or "")
    if lane:
        m = _N8N_WORKER_LANE_RE.fullmatch(lane)
        if m:
            return f"runner-{m.group(1)}"
        if lane == "main":
            return "runner-main"
    return "runner-main" if is_main else "runner-unattributed"


def _read_new_bytes(path: str, offset: int, backfill: int) -> tuple[bytes, int]:
    """Read what was appended since `offset`. Returns (bytes, new offset).

    offset < 0 means "first sight": start `backfill` bytes from the end. A file that SHRANK was
    rotated out from under us (n8n renames the base file and opens a new one), so we start over.
    """
    size = os.path.getsize(path)
    if offset < 0:
        offset = max(0, size - backfill)
    elif size < offset:
        offset = 0
    if size <= offset:
        return b"", offset
    with open(path, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read(size - offset)
    return chunk, offset + len(chunk)


async def n8n_task_log_loop(store: RingStore, broadcast, health: dict[str, Any],
                            state: dict[str, Any]) -> None:
    """Turn n8n's event-bus log into ONE span per task runner task, with real start and end."""
    offsets: dict[str, int] = {}
    partials: dict[str, bytes] = {}
    pending: dict[str, dict[str, Any]] = {}    # taskId -> the open span we already published
    exec_host: dict[str, str] = {}             # executionId -> hostId (from queue events)
    node_names: dict[str, tuple[str, str]] = {}  # nodeId -> (name, type)
    first_pass = True

    def _trim() -> list[dict[str, Any]]:
        """Expire stale pending tasks -- and CLOSE them, because a silent pop leaves the
        already-emitted span open FOREVER.

        The span was published to the ring the moment its task was requested. Dropping the pending
        entry without emitting a terminal update means the ring keeps the open one and the UI draws
        it as still running for the rest of the process's life. Measured 2026-08-18: four
        `Map ID Match Line Data` bars sat "running" past the 1,800s TTL -- 1,899s and counting --
        for executions that had errored half an hour earlier, because this function popped them
        quietly. Terminal workflow events close these properly now; this is the backstop for a task
        whose execution produced no terminal event at all (killed worker, lost log), and it must
        close, not forget.
        """
        for d, cap in ((exec_host, 20000), (node_names, 20000)):
            if len(d) > cap:
                d.clear()
        cutoff = time.time() * 1000 - N8N_TASKS_TTL_S * 1000
        out: list[dict[str, Any]] = []
        for tid in [t for t, sp in pending.items() if sp["s"] < cutoff]:
            prev = pending.pop(tid, None)
            if not prev:
                continue
            end = int(prev["s"]) + int(N8N_TASKS_TTL_S * 1000)
            out.append({**prev, "e": end, "d": end - int(prev["s"]), "status": "error"})
        return out

    def _handle(line: bytes, is_main: bool, pin: str,
                first_pass: bool = False) -> list[dict[str, Any]]:
        try:
            d = json.loads(line)
        except Exception:
            return []
        ev = d.get("eventName")
        if not ev:
            return []
        p = d.get("payload") or {}
        if ev.startswith("n8n.queue.job."):
            ex, hid = p.get("executionId"), p.get("hostId")
            if ex and hid:
                exec_host[str(ex)] = str(hid)
            return []
        if ev == "n8n.node.started":
            nid = p.get("nodeId")
            if nid:
                node_names[str(nid)] = (str(p.get("nodeName") or ""), str(p.get("nodeType") or ""))
            return []
        if ev in ("n8n.workflow.failed", "n8n.workflow.success", "n8n.workflow.crashed"):
            # A terminal workflow event is the authoritative close for a task whose execution died
            # mid-node. n8n emits `n8n.runner.response.received` only when the runner ANSWERS; an
            # execution that throws inside the Code node never produces one, so the span stayed
            # open until N8N_TASKS_TTL_S (30 min) and rendered as a task still running.
            # Measured 2026-08-18: eight `Map ID Match Line Data` spans displayed as running for up
            # to 1,735s while all eight of their executions had ERRORED 23-30 minutes earlier. The
            # timeline was manufacturing the exact stall it exists to disprove, which is worse than
            # showing nothing. A task with no response when its execution ended did not succeed:
            # failed/crashed closes as `error`, and a success-with-pending-task closes as
            # `canceled` (the answer never came back, whatever the workflow's own verdict was).
            ex_done = str(p.get("executionId") or "")
            if not ex_done:
                return []
            ts_ms = _n8n_ts_ms(d.get("ts"))
            orphans = [k for k, v in pending.items()
                       if (v.get("meta") or {}).get("execution") == ex_done]
            out = []
            for tid_o in orphans:
                prev = pending.pop(tid_o)
                end = max(int(prev["s"]), ts_ms)
                out.append({**prev, "e": end, "d": end - int(prev["s"]),
                            "status": "canceled" if ev == "n8n.workflow.success" else "error"})
            return out
        if ev not in ("n8n.runner.task.requested", "n8n.runner.response.received"):
            return []

        tid = str(p.get("taskId") or "")
        if not tid:
            return []
        ts_ms = _n8n_ts_ms(d.get("ts"))
        ex = str(p.get("executionId") or "")
        if ev == "n8n.runner.task.requested":
            lane = pin or _n8n_task_lane(exec_host.get(ex), ex, is_main)
            name, ntype = node_names.get(str(p.get("nodeId") or ""), ("", ""))
            label = name or (ntype.rsplit(".", 1)[-1] if ntype else "") or f"task {tid}"
            span = {
                "id": f"{N8N_LANES_SRC}:t:{ex or 'x'}:{tid}",
                "src": N8N_LANES_SRC, "svc": f"{lane}/tasks", "svcid": f"{lane}/tasks",
                "label": f"{label} · #{ex}"[:90] if ex else label[:90],
                "status": "running",
                "s": ts_ms, "e": None, "d": None,
                "meta": {"lane": lane, "task": tid, "execution": ex,
                         "workflow": p.get("workflowId"), "node": name or p.get("nodeId"),
                         "nodeType": ntype, "host": exec_host.get(ex)},
            }
            pending[tid] = span
            # During the backfill replay, publish nothing yet. A fixed-size replay window can
            # contain a request whose close falls outside it, and an open span published from
            # history can never be closed by anything -- it renders as a task running forever.
            # Measured 2026-08-18: four `Map ID Match Line Data` bars were RESURRECTED by every
            # restart, showing 2,091s of "running" for executions that had errored 35 minutes
            # earlier, because the replay re-emitted the request while the terminal event sat
            # before the window start. Live traffic still publishes immediately, so an in-flight
            # task is visible the moment it starts.
            return [] if first_pass else [span]

        prev = pending.pop(tid, None)
        if prev is None:
            return []      # response whose request predates our backfill window — nothing to draw
        end = max(int(prev["s"]), ts_ms)
        return [{**prev, "e": end, "d": end - int(prev["s"]), "status": "success"}]

    while True:
        try:
            rows: list[dict[str, Any]] = []
            seen_any = False
            for name, pin in N8N_EVENTLOG_FILES:
                path = os.path.join(N8N_EVENTLOG_DIR, name)
                try:
                    chunk, offsets[path] = await asyncio.to_thread(
                        _read_new_bytes, path, offsets.get(path, -1),
                        N8N_TASKS_BACKFILL if first_pass else 0)
                except FileNotFoundError:
                    continue
                seen_any = True
                if not chunk:
                    continue
                buf = partials.pop(path, b"") + chunk
                lines = buf.split(b"\n")
                partials[path] = lines.pop()          # last element is an incomplete line
                is_main = "worker" not in name
                for ln in lines:
                    ln = ln.strip()
                    if ln.startswith(b"{"):
                        rows.extend(_handle(ln, is_main, pin, first_pass))
            # NOTE: `first_pass` used to be cleared HERE, before the `if first_pass and pending`
            # block below -- so that block never ran once. Kept the flag alive until after it.
            state["pending"] = len(pending)
            state["files"] = {p: o for p, o in offsets.items()}
            if not seen_any:
                _mark_source(health, False,
                             f"no event log under {N8N_EVENTLOG_DIR} (is the n8n volume mounted?)")
            else:
                _mark_source(health, True, event=bool(rows))
            if rows:
                new = await store.upsert_many(rows)
                if new:
                    await broadcast({"type": "delta", "rows": new})
            if first_pass and pending:
                # Requests replayed from history whose close was outside the window. They were
                # never published (see above), so dropping them is silent and correct.
                pending.clear()
            first_pass = False
            rows.extend(_trim())
            # Backstop that survives a tracer restart -- `_trim` can only close what is still in
            # `pending`, and a restart empties it while the published open spans remain in the ring.
            stale = await store.close_stale_open("/tasks", N8N_TASKS_TTL_S * 1000.0)
            if stale:
                await broadcast({"type": "delta", "rows": stale})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _mark_source(health, False, repr(exc))
            print(f"[{N8N_LANES_SRC}] task log error: {type(exc).__name__}: {exc!r}")
        await asyncio.sleep(N8N_TASKS_POLL_S)


# -- webhook: HTTP ingest endpoint for any app --------------------------------
# POST /ingest/span  (single span or list of spans)
# POST /ingest/spans (array of spans, alias)
# Span schema (all fields except id and s are optional):
#   id      : str   — unique span identifier (required)
#   src     : str   — source name shown on timeline (default: "webhook")
#   svc     : str   — service/workflow name
#   svcid   : str   — service identifier
#   label   : str   — human-readable label
#   status  : str   — running | success | error | canceled | waiting | crashed
#   s       : int   — start unix milliseconds (required)
#   e       : int   — end unix milliseconds (null = span still open)
#   d       : int   — duration ms (computed from s/e if omitted)
#   meta    : dict  — arbitrary key-value metadata


# -- WebSocket fan-out --------------------------------------------------------

class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.discard(ws)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        data = json.dumps(msg, default=str)
        async with self.lock:
            clients = list(self.clients)
        dead = []
        for ws in clients:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=2)
            except Exception:
                dead.append(ws)
        if not dead:
            return
        async with self.lock:
            for d in dead:
                self.clients.discard(d)


async def reconcile_open_against_db(app, store: RingStore, broadcast) -> None:
    """Close runner-task spans whose EXECUTION has already finished, using the n8n DB as truth.

    Why this exists at all: a task span is opened on `n8n.runner.task.requested` and closed on
    `n8n.runner.response.received`. When the execution dies before the runner answers -- a thrown
    node, a killed worker -- no response event is ever written, so the span stays open and the
    timeline draws a task that has been "running" for hours. Terminal `n8n.workflow.*` events cover
    the common case, but not every one reaches this tailer (worker log rotation, a tracer restart
    that empties `pending`, an execution whose events landed in a file we started reading after the
    fact). Every one of those leaves a permanent phantom bar, which is the exact stall this timeline
    exists to disprove -- measured repeatedly: execs 3414455, 3421929/31/32/33, and a run of
    `Raise Double Blocked` / `Group By ACTION` / `Build Deliver` bars on 2026-08-20.

    Rather than add another event-ordering heuristic, ask the database: `execution_entity` knows
    exactly which executions are finished and when. Anything still open here whose execution is no
    longer running gets closed at that execution's real `stoppedAt`, with its real outcome. Spans
    whose execution row no longer exists (pruned) fall through to the TTL sweeper.
    """
    MAP = {"success": "success", "error": "error", "crashed": "error",
           "canceled": "canceled", "waiting": "waiting"}
    while True:
        try:
            pool = getattr(app.state, "pool", None)
            if pool is not None:
                opened = await store.open_spans("/tasks")
                by_exec: dict[str, list[dict[str, Any]]] = {}
                for sp in opened:
                    ex = str(((sp.get("meta") or {}).get("execution")) or "")
                    if ex.isdigit():
                        by_exec.setdefault(ex, []).append(sp)
                if by_exec:
                    ids = [int(x) for x in by_exec]
                    async with pool.acquire() as conn:
                        rows = await conn.fetch(
                            'SELECT id, status, "stoppedAt" FROM execution_entity '
                            'WHERE id = ANY($1::int[]) AND status NOT IN (\'running\', \'new\')',
                            ids)
                    ends: dict[str, tuple[int, str]] = {}
                    for r in rows:
                        stopped = r["stoppedAt"]
                        end_ms = int(stopped.timestamp() * 1000) if stopped else int(time.time() * 1000)
                        status = MAP.get(str(r["status"]), "unknown")
                        for sp in by_exec.get(str(r["id"]), []):
                            ends[sp["id"]] = (end_ms, status)
                    if ends:
                        changed = await store.close_by_id(ends)
                        if changed:
                            await broadcast({"type": "delta", "rows": changed})
                            print(f"[{N8N_LANES_SRC}] reconciled {len(changed)} orphaned task span(s)"
                                  f" against execution_entity")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[{N8N_LANES_SRC}] reconcile error: {type(exc).__name__}: {exc!r}")
        await asyncio.sleep(N8N_TASKS_RECONCILE_S)


# -- lifespan -----------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.hub = Hub()
    app.state.traefik_store = RingStore(TRAEFIK_BUFFER)
    app.state.docker_store = RingStore(DOCKER_BUFFER)
    app.state.logspan_store = RingStore(LOGSPAN_BUFFER)
    app.state.custom_store = RingStore(CUSTOM_BUFFER)
    app.state.webhook_store = RingStore(WEBHOOK_BUFFER)
    # ONE ring and ONE `src` for the whole n8n worker/runner set — the lanes inside it are `svc`s.
    app.state.n8n_lane_store = RingStore(N8N_LANES_BUFFER)
    app.state.n8n_lanes: dict[str, dict[str, Any]] = {}   # health key -> {container, lane}
    app.state.n8n_tasks: dict[str, Any] = {}              # per-task source diagnostics
    # One ring per custom source, keyed by its `src`. The legacy slot REUSES app.state.custom_store
    # so `custom_store`/`apitools_store` keep pointing at the same buffer they always have.
    app.state.custom_stores = {}
    for _cs in CUSTOM_SOURCE_LIST:
        app.state.custom_stores[_cs.src] = (
            app.state.custom_store if _cs.key == "custom" else RingStore(_cs.buffer)
        )
    # One ring per app-served span lane. Unlike the custom lanes this ring is only the live tail —
    # /api/spans serves the requested window from the endpoint itself, so history is not capped by
    # this buffer (same division of labour as the n8n source and its DB).
    app.state.span_stores = {_ss.src: RingStore(_ss.buffer) for _ss in SPAN_SOURCE_LIST}
    # Legacy aliases for backward-compat with downstream code that still uses old names
    app.state.wa_store = app.state.logspan_store
    app.state.apitools_store = app.state.custom_store
    app.state.source_health = {
        "n8n": _source_health(ENABLE_N8N),
        "traefik": _source_health(ENABLE_TRAEFIK),
        "docker": _source_health(ENABLE_DOCKER),
        "logspan": _source_health(ENABLE_LOGSPAN),
        "custom": _source_health(ENABLE_CUSTOM),
        "webhook": _source_health(ENABLE_WEBHOOK),
        # Legacy keys (same dict objects, so updates are reflected in both names)
        "wa": None,       # overwritten below
        "apitools": None, # overwritten below
    }
    app.state.source_health["wa"] = app.state.source_health["logspan"]
    # The custom source has a public ALIAS so API consumers can ask for it by the app that feeds
    # it. The alias is contributed by that app (CUSTOM_SOURCE_ALIAS); hardcoding "apitools" here
    # put a layer-3 app name in a layer-2 API surface, and published it even when uninstalled.
    if CUSTOM_ALIAS:
        app.state.source_health[CUSTOM_ALIAS] = app.state.source_health["custom"]
    # Every EXTRA custom source gets a health entry of its own (not an alias of "custom"), so one
    # container going down is visible as that lane failing and does not mark the others degraded.
    for _cs in EXTRA_CUSTOM_SOURCES:
        app.state.source_health[_cs.key] = _source_health(True)
    for _ss in SPAN_SOURCE_LIST:
        app.state.source_health[_ss.key] = _source_health(True)

    # Postgres pool (n8n) — created lazily by _n8n_pool_supervisor with retries
    app.state.pool = None

    # Redis (optional)
    app.state.redis = None
    if REDIS_URL:
        try:
            import redis.asyncio as aioredis  # type: ignore
            app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            await app.state.redis.ping()
        except Exception as exc:
            print(f"[redis] disabled: {exc}")
            app.state.redis = None

    # Docker client + tasks
    app.state.docker = None
    tasks: list[asyncio.Task] = []
    if ENABLE_DOCKER or ENABLE_TRAEFIK or ENABLE_LOGSPAN or CUSTOM_SOURCE_LIST or ENABLE_N8N_LANES:
        try:
            app.state.docker = aiodocker.Docker()
            # Fix: default aiohttp total=300s timeout disconnects log-follow streams
            # after 5min. aiodocker events pass timeout=0 explicitly; log() does not.
            _old_docker_s = app.state.docker.session
            app.state.docker.session = aiohttp.ClientSession(
                connector=app.state.docker.connector,
                connector_owner=True,
                timeout=aiohttp.ClientTimeout(
                    total=None, sock_read=None, connect=30, sock_connect=30
                ),
            )
            _old_docker_s._connector_owner = False  # orphan old; connector owned by new session
            if ENABLE_DOCKER:
                await docker_seed(app.state.docker, app.state.docker_store)
                _mark_source(app.state.source_health["docker"], True)
                tasks.append(asyncio.create_task(
                    docker_events_loop(app.state.docker, app.state.docker_store, app.state.hub.broadcast, app.state.source_health["docker"])
                ))
            if ENABLE_TRAEFIK:
                tasks.append(asyncio.create_task(
                    traefik_log_loop(app.state.docker, app.state.traefik_store, app.state.hub.broadcast, app.state.source_health["traefik"])
                ))
            if ENABLE_LOGSPAN:
                tasks.append(asyncio.create_task(
                    logspan_log_loop(app.state.docker, app.state.logspan_store, app.state.hub.broadcast, app.state.source_health["logspan"])
                ))
            # One tail task per container — independent retry, independent health.
            for cs in CUSTOM_SOURCE_LIST:
                tasks.append(asyncio.create_task(
                    custom_log_loop(
                        app.state.docker, app.state.custom_stores[cs.src],
                        app.state.hub.broadcast, app.state.source_health[cs.key], cs,
                    )
                ))
            if CUSTOM_SOURCE_LIST:
                print("[custom] sources: " + ", ".join(
                    f"{cs.src}<-{cs.container}(buf={cs.buffer})" for cs in CUSTOM_SOURCE_LIST))
            # The n8n lanes take their container list from Docker, not from the environment.
            if ENABLE_N8N_LANES:
                tasks.append(asyncio.create_task(
                    n8n_lanes_loop(app.state.docker, app.state.n8n_lane_store,
                                   app.state.hub.broadcast, app.state.source_health,
                                   app.state.n8n_lanes)
                ))
                print(f"[{N8N_LANES_SRC}] discovery every {N8N_LANES_SCAN_S:g}s "
                      f"(buf={N8N_LANES_BUFFER}, deployment={DEPLOYMENT_NAME or '(inferred)'})")
        except Exception as exc:
            for name in ("docker", "traefik", "logspan", "custom", *(c.key for c in EXTRA_CUSTOM_SOURCES)):
                _mark_source(app.state.source_health[name], False, str(exc))
            print(f"[docker] init failed: {exc}")

    # App-served span lanes need neither the docker socket nor the n8n pool — they are plain HTTP
    # against another container, so they start whether or not either of those came up.
    for _ss in SPAN_SOURCE_LIST:
        tasks.append(asyncio.create_task(
            span_pull_loop(app.state.span_stores[_ss.src], app.state.hub.broadcast,
                           app.state.source_health[_ss.key], _ss)
        ))
    if SPAN_SOURCE_LIST:
        print("[span] sources: " + ", ".join(
            f"{s.src}<-{s.url}(buf={s.buffer})" for s in SPAN_SOURCE_LIST)
            + f" every {SPAN_SOURCE_POLL_S:g}s")

    # Per-task spans read n8n's event-bus log off the shared n8n volume — no docker socket, no
    # n8n process involved, so it starts whether or not the docker client came up.
    if ENABLE_N8N_TASKS:
        app.state.source_health[_N8N_TASKS_KEY] = _source_health(True)
        tasks.append(asyncio.create_task(
            n8n_task_log_loop(app.state.n8n_lane_store, app.state.hub.broadcast,
                              app.state.source_health[_N8N_TASKS_KEY], app.state.n8n_tasks)
        ))
        print(f"[{N8N_LANES_SRC}] per-task spans from {N8N_EVENTLOG_DIR}/{{"
              + ",".join(f + (f"={lane}" if lane else "") for f, lane in N8N_EVENTLOG_FILES)
              + f"}} every {N8N_TASKS_POLL_S:g}s")

    # n8n live tail — supervisor builds pool with backoff and (re)starts the tail
    if ENABLE_N8N:
        tasks.append(asyncio.create_task(_n8n_pool_supervisor(app)))

    # Orphaned task spans are closed from the DB, not from event ordering. Needs both the task
    # spans source (to have spans) and the n8n pool (to have truth), so it is started with both.
    if ENABLE_N8N_TASKS and ENABLE_N8N:
        tasks.append(asyncio.create_task(
            reconcile_open_against_db(app, app.state.n8n_lane_store, app.state.hub.broadcast)
        ))
        print(f"[{N8N_LANES_SRC}] open-span reconciler every {N8N_TASKS_RECONCILE_S:g}s"
              " (closes spans whose execution already finished)")

    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if app.state.pool is not None:
            await app.state.pool.close()
        if app.state.docker is not None:
            try:
                await app.state.docker.close()
            except Exception:
                pass
        if app.state.redis is not None:
            try:
                await app.state.redis.close()
            except Exception:
                pass


async def _n8n_pool_supervisor(app: FastAPI) -> None:
    """Keep an asyncpg pool alive for the n8n source; (re)start the live tail when up."""
    backoff = 2.0
    while True:
        try:
            pool = await asyncpg.create_pool(
                host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS,
                database=PG_DB, min_size=1, max_size=4, command_timeout=15,
            )
            # Sanity ping
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            app.state.pool = pool
            _mark_source(app.state.source_health["n8n"], True)
            print(f"[n8n] pool ready (host={PG_HOST} db={PG_DB})")
            backoff = 2.0
            try:
                await _n8n_live_tail(app)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _mark_source(app.state.source_health["n8n"], False, str(exc))
                print(f"[n8n] live tail crashed: {exc}")
            finally:
                app.state.pool = None
                try:
                    await pool.close()
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        except Exception as exc:
            _mark_source(app.state.source_health["n8n"], False, str(exc))
            print(f"[n8n] pool init failed: {exc}; retry in {backoff:.0f}s")
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            return
        backoff = min(backoff * 2, 30.0)


async def _n8n_live_tail(app: FastAPI) -> None:
    pool: asyncpg.Pool = app.state.pool
    cursor = datetime.now(timezone.utc)
    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL_S)
            now = datetime.now(timezone.utc)
            since_dt = datetime.fromtimestamp(now.timestamp() - 24 * 3600, tz=timezone.utc)
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(EXEC_DELTA, since_dt, cursor)
            except Exception as exc:
                _mark_source(app.state.source_health["n8n"], False, str(exc))
                # On a fresh volume this container is up before n8n has finished its ~100 schema
                # migrations, so the first few polls hit a half-built execution_entity and fail
                # with `column e."deletedAt" does not exist`. It resolves itself within a minute.
                # Printing it as a failure made the baseline's P6 log review flag a healthy boot,
                # which is the same "retry quietly vs raise" distinction the app conditions draw:
                # a transient is shown, not alarmed about.
                msg = str(exc)
                transient = ("does not exist" in msg and ("column" in msg or "relation" in msg))
                if not transient:
                    print(f"[n8n] tail query failed: {exc}")
                elif not getattr(app.state, "_n8n_migrating_logged", False):
                    app.state._n8n_migrating_logged = True
                    print("[n8n] execution_entity not migrated yet — retrying quietly "
                          "(normal on a fresh volume; logged once)")
                continue
            cursor = now
            _mark_source(app.state.source_health["n8n"], True, event=bool(rows))
            if rows:
                payload = [_n8n_row(r) for r in rows]
                await app.state.hub.broadcast({"type": "delta", "rows": payload})
    except asyncio.CancelledError:
        return


# -- API ----------------------------------------------------------------------

app = FastAPI(title="any-concurrency", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    pg_ok = False
    if app.state.pool is not None:
        try:
            async with app.state.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            pg_ok = True
        except Exception:
            pg_ok = False
    return {
        "ok": True,
        "sources": {
            "n8n": pg_ok,
            "traefik": bool(app.state.source_health["traefik"]["ok"]),
            "docker": bool(app.state.source_health["docker"]["ok"]),
            "logspan": bool(app.state.source_health["logspan"]["ok"]),
            "custom": bool(app.state.source_health["custom"]["ok"]),
            "webhook": ENABLE_WEBHOOK,
            # one entry per extra custom source — each has its own `source_details` entry too, so
            # hooks/verify can tell "not configured" from "broke" without special-casing a name.
            **{cs.key: bool(app.state.source_health[cs.key]["ok"]) for cs in EXTRA_CUSTOM_SOURCES},
            # one entry per app-served span lane, same contract as the custom lanes above
            **{ss.key: bool(app.state.source_health[ss.key]["ok"]) for ss in SPAN_SOURCE_LIST},
            # one entry per DISCOVERED n8n container (`n8n-bg:worker-1`, …) — the set changes
            # with the worker set, so this is read from the live registry, not from config.
            **{k: bool((app.state.source_health.get(k) or {}).get("ok"))
               for k in sorted(app.state.n8n_lanes)},
            **({_N8N_TASKS_KEY: bool((app.state.source_health.get(_N8N_TASKS_KEY) or {}).get("ok"))}
               if ENABLE_N8N_TASKS else {}),
            # legacy aliases
            "wa": bool(app.state.source_health["logspan"]["ok"]),
            **({CUSTOM_ALIAS: bool(app.state.source_health["custom"]["ok"])} if CUSTOM_ALIAS else {}),
        },
        "source_details": {k: v for k, v in app.state.source_health.items()
                           if k not in ("wa", CUSTOM_ALIAS)},
        "redis": app.state.redis is not None,
        "n8n_url": N8N_URL,
    }


async def _fetch_n8n_spans(hours: float) -> list[dict[str, Any]]:
    if app.state.pool is None:
        return []
    since = datetime.now(timezone.utc).timestamp() - hours * 3600
    since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(EXEC_SELECT, since_dt)
    return [_n8n_row(r) for r in rows]


# One answer for the viewers of the same moment. A page asks every 3.5 s and each viewer was answered
# alone: eight at once took 0.79-2.29 s where one takes 0.06 (measured 2026-10-09) - each computing the
# same list and asking the same apps for it again. Whoever asks for the same window and sources within
# SPANS_SHARE_S is handed the answer already made; the first to ask makes it and the others wait for
# that one. A write through /ingest is part of what is asked for (`_spans_written`), so an answer made
# before it is never handed out after it - a writer reads what it wrote. With 0 every asker gets an
# answer of its own, still one at a time.
SPANS_SHARE_S = max(0.0, float(os.getenv("SPANS_SHARE_S", "2") or 0))
_spans_written = [0]
_spans_shared: dict[tuple, tuple[float, bytes]] = {}
_spans_making: dict[tuple, asyncio.Lock] = {}


@app.get("/api/spans")
async def get_spans(
    hours: float = Query(24, ge=0.01, le=24 * 14),
    sources: str = Query(DEFAULT_SOURCES),
) -> Response:
    src_set = {s.strip() for s in sources.split(",") if s.strip()}
    key = (f"{hours:g}", ",".join(sorted(src_set)), _spans_written[0])
    async with _spans_making.setdefault(key, asyncio.Lock()):
        now = time.monotonic()
        for old in [k for k, (at, _) in _spans_shared.items() if now - at >= SPANS_SHARE_S]:
            del _spans_shared[old]                      # only this moment's answers are kept…
        for idle in [k for k, lk in _spans_making.items()
                     if k != key and k not in _spans_shared and not lk.locked()]:
            del _spans_making[idle]                     # …and only the locks somebody is behind
        if key not in _spans_shared:
            _spans_shared[key] = (now, JSONResponse(await _spans_now(hours, src_set)).body)
        return Response(_spans_shared[key][1], media_type="application/json")


async def _spans_now(hours: float, src_set: set[str]) -> list[dict[str, Any]]:
    since_ms = int((datetime.now(timezone.utc).timestamp() - hours * 3600) * 1000)
    out: list[dict[str, Any]] = []
    if "n8n" in src_set:
        try:
            n8n_rows = await _fetch_n8n_spans(hours)
            out.extend(n8n_rows)
        except Exception as exc:
            print(f"[api/spans] n8n fetch failed: {exc}")
    if "traefik" in src_set:
        out.extend(app.state.traefik_store.since(since_ms))
    if "docker" in src_set:
        out.extend(app.state.docker_store.since(since_ms))
    if "logspan" in src_set or "wa" in src_set:
        out.extend(app.state.logspan_store.since(since_ms))
    # `custom` selects the legacy slot (by that key or by its published alias); every other custom
    # source is selected by its own name. Asking for a source that is not configured is not an
    # error — it simply contributes nothing, exactly as `custom` behaves today.
    seen_stores: set[int] = set()
    for cs in CUSTOM_SOURCE_LIST:
        want = cs.src in src_set or (cs.key == "custom" and "custom" in src_set)
        if not want:
            continue
        store = app.state.custom_stores.get(cs.src)
        if store is None or id(store) in seen_stores:
            continue
        seen_stores.add(id(store))
        out.extend(store.since(since_ms))
    # App-served lanes answer the WINDOW from the app, not from the ring — that is the whole point
    # of this source type (the app's table holds days; the ring holds the tail). The ring is the
    # fallback, so a slow or restarting endpoint degrades to "what we already have" instead of an
    # empty section, which would read as "nothing happened".
    for ss in SPAN_SOURCE_LIST:
        if ss.src not in src_set:
            continue
        store = app.state.span_stores.get(ss.src)
        try:
            out.extend(await _fetch_span_source(ss, hours=hours))
        except Exception as exc:
            print(f"[api/spans] {ss.src} fetch failed, serving ring: {exc!r}")
            if store is not None:
                out.extend(store.since(since_ms))
    # The whole n8n worker/runner section is one src backed by one ring.
    if N8N_LANES_SRC in src_set:
        out.extend(app.state.n8n_lane_store.since(since_ms))
    if "webhook" in src_set:
        out.extend(app.state.webhook_store.since(since_ms))
    return out


# Backwards-compat shim used by older clients
@app.get("/api/executions")
async def get_executions(hours: float = Query(24, ge=0.01, le=24 * 14)) -> JSONResponse:
    rows = await _fetch_n8n_spans(hours)
    return JSONResponse(rows)


@app.get("/api/queue")
async def get_queue() -> dict[str, Any]:
    if app.state.redis is None:
        return {"available": False}
    r = app.state.redis
    out: dict[str, Any] = {"available": True, "queues": {}}
    try:
        meta_keys: list[str] = []
        async for k in r.scan_iter(match="bull:*:meta", count=100):
            meta_keys.append(k)
        names = sorted({k.split(":", 2)[1] for k in meta_keys})
        for name in names:
            base = f"bull:{name}"
            wait, active, delayed, failed, completed = await asyncio.gather(
                r.llen(f"{base}:wait"),
                r.llen(f"{base}:active"),
                r.zcard(f"{base}:delayed"),
                r.zcard(f"{base}:failed"),
                r.zcard(f"{base}:completed"),
                return_exceptions=True,
            )

            def _v(x: Any) -> int:
                return x if isinstance(x, int) else 0

            out["queues"][name] = {
                "wait": _v(wait), "active": _v(active),
                "delayed": _v(delayed), "failed": _v(failed),
                "completed": _v(completed),
            }
    except Exception as exc:
        out["error"] = str(exc)
    return out


@app.websocket("/ws")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    await app.state.hub.add(ws)
    try:
        # initial seed: send a hello
        await ws.send_text(json.dumps({"type": "hello", "t": int(datetime.now(timezone.utc).timestamp() * 1000)}))
        while True:
            # keep socket alive; receive any message client sends
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await ws.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await app.state.hub.remove(ws)


def _find_in_store(store: RingStore, span_id: str) -> dict[str, Any] | None:
    return store.by_id.get(span_id)


@app.get("/api/span/{span_id}")
async def get_span(span_id: str) -> JSONResponse:
    """Look up a single span across all stores. n8n spans are fetched from PG."""
    if span_id.startswith("n8n:"):
        if app.state.pool is None:
            return JSONResponse({"error": "n8n pool not ready"}, status_code=503)
        try:
            exec_id = int(span_id.split(":", 1)[1])
        except Exception:
            return JSONResponse({"error": "bad id"}, status_code=400)
        async with app.state.pool.acquire() as conn:
            # Same highlight join as the list query — without it a single-span lookup came
            # back with the generic `#<id> <mode>` label while the timeline showed the
            # outline, i.e. the same span rendered two different ways.
            row = await conn.fetchrow(
                'SELECT e.id, e."workflowId" AS wfid, COALESCE(w.name, \'(unknown)\') AS wf, '
                'e.mode, e.status, e.finished, e."startedAt", e."stoppedAt", '
                'e."deletedAt" IS NOT NULL AS del, hl.hl AS highlight '
                'FROM execution_entity e LEFT JOIN workflow_entity w ON w.id = e."workflowId" '
                f'{_HL_JOIN} '
                'WHERE e.id = $1', exec_id,
            )
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(_n8n_row(row))
    for store in (
        app.state.traefik_store,
        app.state.docker_store,
        app.state.logspan_store,
        app.state.custom_store,
        *app.state.custom_stores.values(),
        *app.state.span_stores.values(),
        app.state.webhook_store,
    ):
        hit = _find_in_store(store, span_id)
        if hit is not None:
            return JSONResponse(hit)
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/n8n/exec/{exec_id}")
async def get_n8n_exec(exec_id: int) -> JSONResponse:
    """Full execution detail: row + metadata + workflow node summary + deep link."""
    if app.state.pool is None:
        return JSONResponse({"error": "n8n pool not ready"}, status_code=503)
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT e.id, e."workflowId" AS wfid, COALESCE(w.name, \'(unknown)\') AS wf, '
            'e.mode, e.status, e.finished, e."startedAt", e."stoppedAt", '
            'e."deletedAt" IS NOT NULL AS del, e."retryOf", e."retrySuccessId" '
            'FROM execution_entity e LEFT JOIN workflow_entity w ON w.id = e."workflowId" '
            'WHERE e.id = $1', exec_id,
        )
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        meta_rows = await conn.fetch(
            'SELECT key, value FROM execution_metadata WHERE "executionId" = $1 ORDER BY key', exec_id,
        )
        wf_data = await conn.fetchval(
            'SELECT "workflowData" FROM execution_data WHERE "executionId" = $1', exec_id,
        )
    nodes: list[dict[str, Any]] = []
    if wf_data:
        try:
            wf_obj = wf_data if isinstance(wf_data, dict) else json.loads(wf_data)
            for n in (wf_obj.get("nodes") or [])[:200]:
                nodes.append({
                    "name": n.get("name"),
                    "type": (n.get("type") or "").split(".")[-1],
                    "disabled": bool(n.get("disabled")),
                })
        except Exception:
            pass
    started = row["startedAt"]
    stopped = row["stoppedAt"]
    s_ms = int(started.timestamp() * 1000) if started else None
    e_ms = int(stopped.timestamp() * 1000) if stopped else None
    deep = f"{N8N_URL}/workflow/{row['wfid']}/executions/{row['id']}" if (N8N_URL and row["wfid"]) else None
    return JSONResponse({
        "id": row["id"],
        "workflowId": row["wfid"],
        "workflow": row["wf"],
        "mode": row["mode"],
        "status": row["status"] or "unknown",
        "finished": bool(row["finished"]),
        "deleted": bool(row["del"]),
        "retryOf": row["retryOf"],
        "retrySuccessId": row["retrySuccessId"],
        "startedAt": s_ms,
        "stoppedAt": e_ms,
        "durationMs": (e_ms - s_ms) if (s_ms is not None and e_ms is not None) else None,
        "metadata": [{"key": r["key"], "value": r["value"]} for r in meta_rows],
        "nodes": nodes,
        "deepLink": deep,
        "n8nUrl": N8N_URL,
    })




# -- Webhook ingest endpoints -------------------------------------------------

class _IngestSpan(BaseModel):
    id: str
    src: str = "webhook"
    svc: str = ""
    svcid: str = ""
    label: str = ""
    status: str = "running"
    s: int                          # start ms — required
    e: int | None = None            # end ms — null means span still open
    d: int | None = None            # duration ms (computed if omitted)
    meta: dict[str, Any] | None = None

    def to_span(self) -> dict[str, Any]:
        d = self.d
        if d is None and self.e is not None:
            d = max(0, self.e - self.s)
        return {
            "id": self.id,
            "src": self.src,
            "svc": self.svc,
            "svcid": self.svcid,
            "label": self.label or self.svc or self.id,
            "status": self.status,
            "s": self.s,
            "e": self.e,
            "d": d,
            "meta": self.meta or {},
        }


@app.post("/ingest/span", status_code=202)
@app.post("/ingest/spans", status_code=202)
async def ingest_spans(body: list[_IngestSpan] | _IngestSpan) -> dict[str, Any]:
    """Ingest one or more spans via HTTP POST.

    Accepts either a single span object or a JSON array of spans.
    Returns {"ingested": <count>, "new": <count of never-seen ids>}.
    """
    if not ENABLE_WEBHOOK:
        raise HTTPException(status_code=503, detail="webhook source disabled; set ENABLE_WEBHOOK=1")
    items = body if isinstance(body, list) else [body]
    if len(items) > 1000:
        raise HTTPException(status_code=413, detail="batch too large; max 1000 spans per request")
    spans = [i.to_span() for i in items]
    new = await app.state.webhook_store.upsert_many(spans)
    _spans_written[0] += 1
    _mark_source(app.state.source_health["webhook"], True, event=bool(new))
    if new:
        await app.state.hub.broadcast({"type": "delta", "rows": new})
    return {"ingested": len(spans), "new": len(new)}


@app.post("/ingest/span/{span_id}/close", status_code=200)
async def close_span(
    span_id: str,
    e: int | None = Body(None, description="End timestamp ms; defaults to now"),
    status: str = Body("success", description="Final status"),
    meta: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Close an open span by id — sets e, d, and status.

    Useful for spans with unknown duration that were submitted with status=running.
    """
    if not ENABLE_WEBHOOK:
        raise HTTPException(status_code=503, detail="webhook source disabled")
    existing = app.state.webhook_store.by_id.get(span_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="span not found")
    end_ms = e if e is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    updated = {
        **existing,
        "e": end_ms,
        "d": max(0, end_ms - existing["s"]),
        "status": status,
        "meta": {**(existing.get("meta") or {}), **(meta or {})},
    }
    new = await app.state.webhook_store.upsert_many([updated])
    _spans_written[0] += 1
    _mark_source(app.state.source_health["webhook"], True, event=True)
    if new:
        await app.state.hub.broadcast({"type": "delta", "rows": new})
    return updated


@app.get("/api/sources")
async def get_sources() -> dict[str, Any]:
    """Return config and health state for every source.

    Useful for dashboards and diagnostics. Example response::

        {
          "n8n":      {"enabled": true,  "ok": true,  "last_ok": 1700000000000, "error": null,  "config": {"pg_host": "...", ...}},
          "traefik":  {"enabled": true,  "ok": true,  "last_ok": ...,            "error": null,  "config": {"container": "traefik"}},
          "docker":   {"enabled": true,  "ok": true,  "last_ok": ...,            "error": null,  "config": {}},
          "logspan":  {"enabled": false, "ok": false, "last_ok": null,           "error": "...", "config": {"container": ""}},
          "custom":   {"enabled": false, "ok": false, "last_ok": null,           "error": null,  "config": {"container": ""}},
          "webhook":  {"enabled": true,  "ok": true,  "last_ok": ...,            "error": null,  "config": {"buffer": 10000}},
        }
    """
    def _detail(key: str, enabled: bool, conf: dict[str, Any]) -> dict[str, Any]:
        h = app.state.source_health.get(key) or {}
        return {
            "enabled": enabled,
            "ok": bool(h.get("ok")),
            "last_ok": h.get("last_ok"),
            "error": h.get("error"),
            "config": conf,
        }

    return {
        "n8n": _detail("n8n", ENABLE_N8N, {"pg_host": PG_HOST, "pg_db": PG_DB, "n8n_url": N8N_URL}),
        "traefik": _detail("traefik", ENABLE_TRAEFIK, {"container": TRAEFIK_CONTAINER or "(auto-discover)"}),
        "docker": _detail("docker", ENABLE_DOCKER, {}),
        "logspan": _detail("logspan", ENABLE_LOGSPAN, {"container": LOGSPAN_CONTAINER}),
        "custom": _detail("custom", ENABLE_CUSTOM, {
            "container": CUSTOM_CONTAINER, "alias": CUSTOM_ALIAS or None, "buffer": CUSTOM_BUFFER,
        }),
        "webhook": _detail("webhook", ENABLE_WEBHOOK, {"buffer": WEBHOOK_BUFFER}),
        **{
            cs.key: _detail(cs.key, True, {"container": cs.container, "buffer": cs.buffer})
            for cs in EXTRA_CUSTOM_SOURCES
        },
        # Discovered n8n lanes: one entry per container currently tailed, plus the section itself
        # so a dashboard can see the src, its scan interval and which lanes it resolved to. The
        # section has no health record of its own — a discovered source is up when it has a lane
        # that is up, so it is aggregated rather than left permanently false.
        N8N_LANES_SRC: {
            "enabled": ENABLE_N8N_LANES,
            "ok": any(bool((app.state.source_health.get(k) or {}).get("ok"))
                      for k in app.state.n8n_lanes),
            "last_ok": max((int((app.state.source_health.get(k) or {}).get("last_ok") or 0)
                            for k in app.state.n8n_lanes), default=0) or None,
            "error": None,
            "config": {
                "discovery": "docker container names",
                "scan_seconds": N8N_LANES_SCAN_S,
                "buffer": N8N_LANES_BUFFER,
                "deployment": DEPLOYMENT_NAME or None,
                "lanes": {v["lane"]: v["container"] for v in app.state.n8n_lanes.values()},
            },
        },
        **{
            k: _detail(k, True, {"container": v["container"], "lane": v["lane"]})
            for k, v in sorted(app.state.n8n_lanes.items())
        },
        _N8N_TASKS_KEY: _detail(_N8N_TASKS_KEY, ENABLE_N8N_TASKS, {
            "source": "n8n event bus (n8n.runner.task.requested / .response.received)",
            "dir": N8N_EVENTLOG_DIR,
            "files": {f: (lane or "(attributed per event)") for f, lane in N8N_EVENTLOG_FILES},
            "poll_seconds": N8N_TASKS_POLL_S,
            **app.state.n8n_tasks,
        }),
    }

# Serve UI
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
