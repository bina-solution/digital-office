"""Flask blueprint factory for ``/incomingDocuments``.

Mounts:
* ``GET /health`` — shallow probe
* ``GET/POST/DELETE /repos[/...]`` — registry CRUD (full provisioner: step 8)
* ``PUT /repos/<r>/documents`` — batch upsert via diff engine + repo
* ``POST /repos/<r>/documents/query`` — batch get with pagination
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from typing import Any, NamedTuple

from flask import (
    Blueprint, Response, g, has_request_context, jsonify, request, stream_with_context,
)
from pydantic import ValidationError as PydanticValidationError

from ..core import (
    BatchTooLarge,
    IncomingDocumentsError,
    Query,
    RepoConfig,
    RepoRegistry,
    ValidationError,
    compute_diff,
    get_default_registry,
)
from ..core.errors import RepoNotFound
from ..poller import start_polling, sync_repo_once as _sync_repo_once
from ..core.models import EventEnvelope
from ..core.month_key import month_key_of
from ..core.provisioning import provision_repo
from ..kafka.admin import KafkaAdmin, NullKafkaAdmin
from ..kafka.consumer import KafkaConsumer, NullKafkaConsumer
from ..kafka.producer import KafkaProducer, NullKafkaProducer, topic_for
from ..repo_factory import RepoFactory, default_repo_factory

_log = logging.getLogger(__name__)


def _max_batch_size() -> int:
    try:
        return int(os.getenv("INCOMING_DOCS_MAX_BATCH_SIZE", "500"))
    except ValueError:
        return 500


def _max_query_limit() -> int:
    try:
        # [table timeouts 2026-09-02] 500, down from 2000: a grid page never needs more, and a
        # 2000-row page of 150-column rows was the request that outlived the console proxy.
        return int(os.getenv("INCOMING_DOCS_QUERY_MAX_LIMIT", "500"))
    except ValueError:
        return 2000


# ---------------------------------------------------------------------------
# Test-suite runner (בדיקות) — drive the INDOX **n8n E2E test workflows**.
#
# The tab runs the SYSTEM's own end-to-end suites — sync-v3 and the indox-v2
# state machine — NOT the Python feature-validation extraction benchmarks.
# Each n8n suite exposes a webhook that runs ONE lane per call and returns that
# lane's Assert-node verdicts (items carrying a ``result:"PASS…"`` string) via a
# Respond node — the exact mechanism ``scripts/indox-test.py --lanes`` uses.
#
# We model each n8n suite as a UI "suite" and each of its lanes as a UI "case",
# so ``cases_done`` increments as lanes complete → genuine LIVE progress (the old
# feature-validation path had no intra-run signal). Lanes fire concurrently in a
# background thread; NO n8n credentials are needed (webhooks are unauthenticated),
# preserving this service's no-n8n-coupling design.
# ---------------------------------------------------------------------------
_TEST_RUNS: dict[str, dict] = {}
_TEST_RUNS_LOCK = threading.Lock()

# Last-run summary per suite (in-memory) so the suite list shows a pass/fail
# meter + timestamp after a run without persisting anything.
_TEST_LAST: dict[str, dict] = {}

# suite key -> config. Mirrors apps/indox/hooks/test.py (SUITES / LANES /
# LANE_PATHS). Only the five WEBHOOK-enabled suites are here; the manual-only
# ones (bs / doc_base / decide) have no lane webhook, so they aren't UI-runnable.
_N8N_TEST_SUITES: dict[str, dict] = {
    # [ui-lane 2026-08-31] The three CLI-only suites join the console's בדיקות tab. Each is a
    # single 'all' lane: the SAME graph `bbox indox test` runs, entered through a Lane Webhook
    # instead of the manual trigger, answering the BFF contract (items whose `result` contains
    # PASS) via a Lane Verdict shim off the 🏁 Test Summary node.
    "decide": {
        "label": "מכונת מצבים — החלטות",
        "group": "statemachine",
        "webhook": "decide-e2e-lane",
        "lanes": ["all"],
        "budget_s": 240,
        "conc": 1,
        "description": "סולם ההחלטות המלא (57 מקרים): שערי בחירה, חברה, סוג, כפולים, ניתוב — decide טהור.",
    },
    "doc_base": {
        "label": "מכונת מצבים — בסיס",
        "group": "statemachine",
        "webhook": "doc-base-e2e-lane",
        "lanes": ["all"],
        "budget_s": 360,
        "conc": 1,
        "description": "כיסוי ענפי docBase (21), כל 9 ההנדלרים, ומחזור חיים על קבצים אמיתיים לכל סוג.",
    },
    "bs": {
        "label": "מכונת מצבים — מאזן",
        "group": "statemachine",
        "webhook": "bs-e2e-lane",
        "lanes": ["all"],
        "budget_s": 480,
        "conc": 1,
        "description": "מאזן: מחזור חיים עד COMPLETED, ענפי קישור, כיסוי הנדלרים, ונתיב כשל חילוץ.",
    },
    "sync_kernel": {
        "label": "סנכרון — ליבה",
        "group": "sync",
        "webhook": "sync-kernel-e2e-lane",
        "lanes": ["diff", "record", "deliver", "attempts", "order", "cursor"],
        "budget_s": 360,
        "conc": 4,  # light pure-Postgres lanes — safe to run 4-wide
        "description": "סמנטיקת ליבת הסנכרון (Postgres טהור): diff, רישום, מסירה, ניסיונות, סדר, סמן.",
    },
    "sync_sources": {
        "label": "סנכרון — מקורות",
        "group": "sync",
        "webhook": "sync-sources-e2e-lane",
        # [thin-only 2026-08-31, owner order] the five proc-* lanes are gone with the retired
        # v1 processor path; the battery separately asserts ZERO legacy executions.
        "lanes": ["drive-gdoc", "drive-bs", "gmail-doc", "gmail-bs", "gmail-link"],
        "budget_s": 900,
        "conc": 4,
        "description": "E2E רזה לכל מקור (drive+gmail): מסירה דקה לשורה, מכונת המצבים משלימה.",
    },
    "sync_full": {
        "label": "סנכרון — מלא",
        "group": "sync",
        "webhook": "sync-full-e2e-lane",
        "lanes": ["registry", "history", "mixed", "races", "chaos"],
        "budget_s": 780,
        "conc": 4,
        "description": "מערך מלא: רישום, היסטוריה, מעורב, מרוצי־תהליכים, כאוס.",
    },
    "mail_organizer": {
        "label": "מסדר הדואר — תיוג",
        "group": "mail",
        "webhook": "mail-organizer-e2e-lane",
        "lanes": ["label-engine", "system-labels"],
        "budget_s": 360,
        "conc": 2,
        "description": "הדואר הנכנס מגיע ללא תוויות: המסדר מתייג DOC_TO_SYNC + PROCESSED, "
                       "יוצר את התוויות החסרות, והסנכרון מוצא את ההודעה לפי התווית.",
    },
    "sealed_inv": {
        "label": "אקשנים חתומים — חשבונית",
        "group": "statemachine",
        "webhook": "sealed-inv-e2e-lane",
        "lanes": ["all"],
        "budget_s": 1600,
        "conc": 1,
        "description": "כל אקשן של חשבונית בליין חתום משלו: זריעה במצב המדויק שלפני האקשן, "
                       "דרייבר דרך הוובהוק היצרני, באצווה של 1 וגם 100 — יומן פעולות סגור + "
                       "אפקט על השורות.",
    },
    "sealed_ship": {
        "label": "אקשנים חתומים — תעודת משלוח",
        "group": "statemachine",
        "webhook": "sealed-ship-e2e-lane",
        "lanes": ["all"],
        "budget_s": 1600,
        "conc": 1,
        "description": "כל אקשן של תעודת משלוח בליין חתום, באצווה של 1 וגם 100.",
    },
    "sealed_bs": {
        "label": "אקשנים חתומים — דוח גיול",
        "group": "statemachine",
        "webhook": "sealed-bs-e2e-lane",
        "lanes": ["all"],
        "budget_s": 1600,
        "conc": 1,
        "description": "כל אקשן של דוח גיול בליין חתום, באצווה של 1 וגם 100.",
    },
    "sealed_ord": {
        "label": "אקשנים חתומים — הזמנה",
        "group": "statemachine",
        "webhook": "sealed-ord-e2e-lane",
        "lanes": ["all"],
        "budget_s": 1600,
        "conc": 1,
        "description": "הזמנה היא סוג חונה: decide + mark_completed, באצווה של 1 וגם 100.",
    },
    "sealed_rcp": {
        "label": "אקשנים חתומים — קבלה",
        "group": "statemachine",
        "webhook": "sealed-rcp-e2e-lane",
        "lanes": ["all"],
        "budget_s": 1600,
        "conc": 1,
        "description": "קבלה היא סוג חונה: decide + mark_completed, באצווה של 1 וגם 100.",
    },
    "gdoc": {
        "label": "מכונת מצבים — GDoc",
        "group": "statemachine",
        "webhook": "gdoc-e2e-lane",
        "lanes": ["batch:inv", "batch:ord", "batch:shp", "lc", "extract", "cov", "perr"],
        "budget_s": 900,
        "conc": 2,  # heavy OCR/extraction lanes — 2-wide avoids starving a doc past its assertion
        "description": "מחזור חיים מלא עד COMPLETED, חילוץ מקבילי, כיסוי מנתבי־פעולות, בידוד שגיאות.",
    },
    "pipeline": {
        "label": "מכונת מצבים — צינור מלא",
        "group": "statemachine",
        "webhook": "pipeline-e2e-lane",
        "lanes": ["bare", "batch", "cov"],
        "budget_s": 1080,
        "conc": 2,  # heavy extraction lanes
        "description": "צינור מקצה־לקצה דרך מכונת המצבים והמנתבים: bare, batch, cov.",
    },
}

# UI grouping labels (the user's three subsystems; action-routers are exercised
# INSIDE the sync + state-machine suites — no standalone router webhook exists).
_TEST_GROUPS: dict[str, str] = {"sync": "סנכרון", "statemachine": "מכונת מצבים",
                                "mail": "דואר"}


def _n8n_webhook_base() -> str:
    """Base URL for n8n webhooks (the test-suite lanes live here). Derived from
    N8N_WEBHOOK_BASE, else from the manage-webhook URL, else the in-cluster default."""
    base = os.getenv("N8N_WEBHOOK_BASE")
    if base:
        return base.rstrip("/")
    mgr = os.getenv("INDOX_MANAGE_WEBHOOK_URL", "http://n8n-webhook:5678/webhook/indox-manage")
    if "/webhook/" in mgr:
        return mgr.rsplit("/", 1)[0]
    return "http://n8n-webhook:5678/webhook"


def _invalidate_settings_cache() -> None:
    """Bust `indoxSettings01`'s 20-minute settings KV cache right after a write.

    That workflow caches `companies_settings` / `key_val_settings` / `key_val_queries` for 1200s
    (n8n-nodes-kv-storage, in-process, no delete op — see `Invalidate Cache Webhook` in the
    blueprint, which writes each key empty + ttl:1 so the next read falls through to a fresh
    compute instead of serving up to 20 minutes of stale data). Best-effort: a settings write must
    never fail, or appear to fail, because n8n or this one webhook happened to be unreachable —
    the cache still self-expires on its own TTL either way, this just removes the WAIT.
    """
    import httpx  # lazy

    user = os.getenv("SETTINGS_AUTH_USER", "settings")
    pw = os.getenv("SETTINGS_AUTH_PASS", "")
    try:
        with httpx.Client(timeout=5.0) as c:
            c.post(f"{_n8n_webhook_base()}/settings/invalidate-cache",
                   auth=(user, pw) if pw else None)
    except Exception:
        pass  # best-effort — see docstring

    # This process's OWN short-TTL settings reads (`_old_document_months_back` and anything else
    # cached via `_sync_cached`) — a second, independent cache from n8n's KV store above, so
    # busting only the n8n side would still leave this BFF answering /sync/inventory with a stale
    # `OldDocumentMonthsBack` for up to `_TTL_INVENTORY` seconds after a PUT. Referenced by name
    # (both are defined further down this module) rather than imported, since this runs long after
    # module load; best-effort, same as the webhook above — a write must never fail on this.
    try:
        with _SYNC_SRC_LOCK:
            for k in [k for k in _SYNC_SRC_CACHE if ":setting:" in k]:
                _SYNC_SRC_CACHE.pop(k, None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Settings editor allowlist (Phase 3 — הגדרות).
#
# The `settings` table holds ~45 key/value rows, most of them STRUCTURAL:
# the big `q_*` apitools query JSONs, keyword lists, `fixture_*` doc-type
# specs, folder-routing URLs, and `sync_registry` (which drives live sync
# routing). None of those may be blind-overwritten from this basic editor.
#
# Only these small, well-understood scalar/toggle keys are writable via
# `PUT /config/settings/<key>`; everything else is shown read-only in the UI
# and 400s on write.
# ---------------------------------------------------------------------------
_EDITABLE_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        "activePrioritySync",     # toggle "true"/"false" (default OFF)
        "indox.statemachine.drain.tick_minutes",   # cadence of the incremental (mode=changed)
                                   # drain pass, minutes; the schedule trigger fires every 2m and
                                   # Normalize Request paces itself by this value (default "2")
        "indox.statemachine.drain.full_minutes",   # cadence of the FULL-TABLE (mode=all) pass,
                                   # minutes (default "120" = every 2h); runs with the same
                                   # parallel/batch settings as any other drain
        "indoxDrainOn",                # toggle "true"/"false" — master drainer kill switch;
        "indoxOn",                     # THE master toggle "true"/"false": off = no sync AND no scheduled
                                   # drain, read by both lanes beside their own switch (2026-09-02)
        "DriveSearchConnection",       # which Drive find_link / check_from_office search: a catalog
                                   # connection id, or "profile:<id>" for the local engine; empty =
                                   # the first enabled drive pipe's own identity (2026-09-02)
        "indoxSyncOn",                 # toggle "true"/"false" — per-tenant sync gate (syncV3Main0001)
                                   # missing row reads as ON (drainer COALESCEs to 'true')
        "indoxSourceFeedbackOn",  # toggle "true"/"false" — source feedback kill switch.
                                   # When on, a finished document's VERDICT is reported back to
                                   # every source it came from: the Drive file moves into the
                                   # pipe's synced/failed folder, the mail gets the pipe's
                                   # labels.synced/labels.failed tag. Missing row reads as OFF
                                   # (the driver COALESCEs to false) — deliberately the opposite
                                   # default from indoxDrainOn, because this one touches a
                                   # client's Drive and mailbox.
        "indox_execution_mode",   # e.g. "parallel-actions"
        "max_actions_per_doc",    # small int, "50"
        "OldDocumentMonthsBack",  # small int, "1200"
        "default-upload-folder",  # drive folder id — manual/API document-upload
                                   # destination (owner decision 2026-08-05); lazily
                                   # provisioned to local drive engine (admin profile),
                                   # `automations/uploads` — see _ensure_default_upload_folder
        # --- Extraction refactor (ai/context/archive/indox-pre-2026-09/EXTRACTION-REFACTOR-PLAN.md §2.5) ---
        # LIVE, not groundwork. These were added ahead of their wiring and the note here still
        # said "read by NO workflow yet"; the wiring landed and the note did not move. Each of
        # BaseDocEx01 / InvoiceDocEx01 / ShipmentDocEx01 now opens with a settings read on these
        # two and records 'skipped: extraction_<engine>_enabled=false' on the row when off, so
        # turning one off here stops that engine on the next document. Fail-open: a missing row
        # or a garbage value reads as ON.
        "extraction_ai_enabled",      # toggle "true"/"false" — AI extraction kill switch
        "extraction_local_enabled",   # toggle "true"/"false" — local extraction kill switch
        # Which READER leads when both engines return a REAL but different type — "LOCAL"
        # (default, historical) or "AI". Read by SelectBase01's type vote, where it is worth one
        # point: it decides a straight 3-2 disagreement and nothing else, so a lone answer still
        # wins alone and the sync pipe's own declaration can still outvote it. Editable because it
        # is exactly the knob an operator reaches for after seeing one bad classification, and it
        # was the one setting on that screen they could see and not change.
        # Value vocabulary is CLOSED and normalized in config_settings_put — see there for why.
        "indox.extraction.type_priority",
        "extraction_model",           # free text, e.g. "models/gemini-3.1-pro-preview"
        "extraction_selection_confidence_threshold",  # numeric text, e.g. "50"
        # --- Drain pool (apps/indox/issues/drain-pool-consolidation-plan.md) ---
        # P lanes of B documents, backpressured. B is the memory lever: n8n retains every
        # node's output for the whole execution, so heap grows with lane WIDTH — a 9,790-doc
        # lane cost ~1,060 MB and two on one worker tripped V8's 2,600 MB ceiling.
        "indox.statemachine.drain.parallel",  # small int, "4"  — concurrent driver lanes
        "indox.statemachine.driver.batch",    # small int, "2000" — documents per lane
        "indox.statemachine.driver.max",      # small int, "2000" — driver entry circuit-breaker
    }
)


# ---------------------------------------------------------------------------
# Per-action router caps — an OPEN key family, allowlisted by PATTERN.
#
# `indox.statemachine.action_router.max` is how many rows the driver's router
# takes in one batch of a given action, and `…action_router.<ACTION>.max`
# overrides it for that action alone (indoxV2Driver01, "Group By ACTION").
# The action names are DATA — new actions arrive without a code change — so no
# frozenset can enumerate these keys, and they were therefore rendered
# read-only in the settings UI despite being exactly the small int an operator
# reaches for during an incident (extract_base_doc is capped at 5 because its
# p95 is 183 s/row against a 3,600 s router timeout).
#
# The RANGE is enforced here rather than only on the client, because unlike the
# closed list above this family accepts keys nobody wrote by hand: a cap of 0
# or "" would make the router emit no chunks at all and the action would
# silently stop dispatching.
# ---------------------------------------------------------------------------
_ROUTER_CAP_RE = re.compile(
    r"^indox\.statemachine\.action_router\.(?:[A-Za-z0-9_]+\.)?max$"
)
_ROUTER_CAP_MIN = 1
_ROUTER_CAP_MAX = 20000


def _is_editable_setting_key(key: str) -> bool:
    """The closed allowlist above, plus the open per-action router-cap family."""
    return key in _EDITABLE_SETTINGS_KEYS or bool(_ROUTER_CAP_RE.match(key or ""))


def _coerce_settings_value(value) -> str:
    """The `settings.value` column is TEXT — normalize the incoming JSON value
    to the string form the pipeline expects (bools as "true"/"false")."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    # dict/list/None — serialize so we never store a Python repr
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# THE COLUMN CATALOG — the database says WHAT EXISTS, the catalog says WHAT IT MEANS.
#
# Before this, `repos.json` hand-declared the column list and drifted to 46 of the table's 126
# columns: `created_at` (which the documents grid SORTS BY), `ERROR`, `THUMBNAIL`, `DOC_ID`,
# `MERGED_INTO` and the whole AI_*/LOCAL_*/SELECTED_* family were real, load-bearing and
# invisible to the layer meant to describe them. Code that needed them reached around the
# registry, which is how a column ends up undeclared and still queried.
#
# THE SPLIT, and why it is not arbitrary:
#   * EXISTENCE + SQL TYPE are FACTS. Postgres already knows them; any second copy can only go
#     stale, and this one did. So they are introspected from the instance schema, every request
#     (behind a short TTL), and nothing can drift.
#   * LABEL, LOGICAL TYPE, ENUM, DEFAULT VISIBILITY are EDITORIAL. Postgres cannot know them.
#     `blueprint/schema/display.json` is where a human writes them, ONCE, globally — an instance
#     is a instance of the same product, not a different product, so there is no per-instance fork.
#
# The logical type is the half that matters most and is the least obvious: 15 of the 16 columns
# this app treats as booleans are physically TEXT (`DOC_DATE_COMPLETED`, `EX_IS_BS`, every
# `*_COMPLETED`). Introspection returns `text` for all of them, and a UI built on that renders a
# text cell, filters by substring, and answers "is it done?" with string truthiness — which is a
# live defect class here. That knowledge is authored, so it lives in the catalog.
#
# An UNLISTED column still comes back — as its raw name, hidden by default. A column must be
# visible and usable the day it appears, never blank and never absent.
# ---------------------------------------------------------------------------
#: A SQL string literal, for the few places a value must be inlined because the RPC takes one
#: statement and no bind parameters. Doubling the quote is the escape postgres defines; the
#: identifier allowlist above each call site is the belt — an instance id is [A-Za-z0-9_-] and
#: anything else is refused rather than escaped, because a instance id that needs escaping is not a
#: instance id.
def _sql_lit(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


#: instance IDS as the registry defines them; anything else never reaches SQL.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

#: SCHEMA NAMES get their own, stricter gate. Every other identifier this code emits is checked
#: against information_schema — it exists or the query is refused — but the schema name is the one
#: identifier there is nothing to check it against, so it carries its own rule instead: a postgres
#: unquoted identifier, lowercase, letter-first. It is resolved from `public.indox_instances` and
#: NEVER taken from the request; `?instance=` selects a ROW, it does not supply a name.
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")


_CATALOG_TTL = 30.0
_catalog_cache: dict[str, Any] = {"at": 0.0, "stamp": None, "data": None}
_columns_cache: dict[str, tuple[float, list[dict]]] = {}


def _display_catalog_path() -> str:
    return os.getenv(
        "INCOMING_DOCS_DISPLAY_CATALOG", "/app/blueprint/schema/display.json"
    )


def _display_catalog() -> dict:
    """display.json, reloaded when the file's mtime/size moves — the same hot-reload
    discipline the repo registry uses, so adding a label needs no restart."""
    path = _display_catalog_path()
    try:
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
    except OSError:
        return {}
    if _catalog_cache["stamp"] != stamp:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _catalog_cache["data"] = json.load(fh)
            _catalog_cache["stamp"] = stamp
        except Exception:
            _log.warning("display catalog unreadable at %s — serving raw column names", path)
            _catalog_cache["data"] = {}
            _catalog_cache["stamp"] = stamp
    return _catalog_cache["data"] or {}


_views_cache: dict[str, Any] = {"stamp": None, "data": None}


def _views_catalog() -> dict:
    """views.json — LAYER 2: where a column appears, never what it means.

    Same hot-reload discipline as the display catalog, and the same global scope: a view is
    authored once and every instance gets it. What ships here are DEFAULTS; the operator's own
    deviation lives in the URL, which is this console's existing contract."""
    path = os.getenv("INCOMING_DOCS_VIEWS_CATALOG", "/app/blueprint/schema/views.json")
    try:
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
    except OSError:
        return {}
    if _views_cache["stamp"] != stamp:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _views_cache["data"] = json.load(fh)
            _views_cache["stamp"] = stamp
        except Exception:
            _log.warning("views catalog unreadable at %s — serving no views", path)
            _views_cache["data"] = {}
            _views_cache["stamp"] = stamp
    return _views_cache["data"] or {}


def _views_for(table: str) -> dict:
    entry = ((_views_catalog().get("tables") or {}).get(table)) or {}
    return {
        "default_view": entry.get("default_view"),
        "views": entry.get("views") or {},
    }


#: physical SQL type -> the registry's LogicalType, used ONLY when the catalog is silent.
#: Deliberately conservative: this schema is TEXT-first, so anything unrecognised is a string,
#: which is also the safest default for a column nobody has classified yet.
_SQL_TO_LOGICAL = {
    "text": "string", "character varying": "string", "character": "string",
    "integer": "int", "bigint": "int", "smallint": "int",
    "numeric": "numeric", "double precision": "numeric", "real": "numeric",
    "boolean": "bool", "json": "json", "jsonb": "json", "date": "date",
    "timestamp with time zone": "timestamp", "timestamp without time zone": "timestamp",
}


def _resolved_columns(cfg, repo_obj) -> list[dict] | None:
    """The live column list for `cfg`, merged with the display catalog.

    Returns None when introspection is not available (a gsheet repo, or the RPC failing), so
    every caller can fall back to the registry's declared columns rather than serve nothing."""
    if cfg.backend != "supabase":
        return None
    key = f"{getattr(repo_obj, 'schema', '')}.{getattr(repo_obj, 'table', '')}"
    hit = _columns_cache.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _CATALOG_TTL:
        return hit[1]
    transport = getattr(repo_obj, "transport", None)
    if transport is None or not hasattr(transport, "_exec_sql"):
        return None
    try:
        rows = transport._exec_sql(
            "select column_name, data_type from information_schema.columns "
            f"where table_schema = '{repo_obj.schema}' and table_name = '{repo_obj.table}' "
            "order by ordinal_position"
        ) or []
    except Exception as e:  # a catalog read must never take the screen down
        _log.warning("column introspection failed for %s: %s", key, e)
        return None
    if not rows:
        return None

    cat = _display_catalog()
    meta = (((cat.get("tables") or {}).get(repo_obj.table) or {}).get("columns")) or {}
    enums = cat.get("enums") or {}
    prev = {c.name: c for c in cfg.columns}  # keeps nullable/unique/default the app enforces

    out: list[dict] = []
    for r in rows:
        name = r.get("column_name")
        if not name:
            continue
        m = meta.get(name) or {}
        old = prev.get(name)
        col: dict[str, Any] = {
            "name": name,
            "type": m.get("type")
            or _SQL_TO_LOGICAL.get(str(r.get("data_type") or "").lower(), "string"),
            "nullable": getattr(old, "nullable", True) if old else True,
            "unique": getattr(old, "unique", False) if old else False,
            "default": getattr(old, "default", None) if old else None,
        }
        for k in ("label", "enum", "visible", "searchable", "align", "deprecated",
                  "description", "ui_type"):
            if m.get(k) is not None:
                col[k] = m[k]
        if col.get("enum") and col["enum"] in enums:
            col["enum_values"] = enums[col["enum"]]
        out.append(col)

    _columns_cache[key] = (now, out)
    return out


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Active INDOX instance.
#
# An *instance* is a registered repo seen from the product side: its own target
# table, its own columns, its own row count. The multi-repo model already exists
# end to end, so "instances" is a SELECTION concern over it, not a new data
# model — see digital-office/sim/INDOX-INSTANCES.md §2.
#
# The selection is persisted next to the repo registry (same directory, same
# atomic temp-file + os.replace discipline) rather than held in memory: Gunicorn
# runs several workers, and an in-process variable would make the active
# instance depend on which worker answered the request.
#
# SCOPE, STATED HONESTLY: selecting an instance scopes the TABLE (which repo the
# documents routes address). It does NOT yet scope `/config/settings`,
# `/sync/registry` or `/sync/status` — those read single global supabase tables
# with no instance column. Making them per-instance is a tenancy change in the
# database, not a routing change here.
# ---------------------------------------------------------------------------
_ACTIVE_INSTANCE_LOCK = threading.Lock()


def _active_instance_path():
    from pathlib import Path

    explicit = os.getenv("INCOMING_DOCS_ACTIVE_INSTANCE")
    if explicit:
        return Path(explicit)
    registry_path = Path(
        os.getenv(
            "INCOMING_DOCS_REPO_REGISTRY",
            ".storage/incoming_documents/repos.json",
        )
    )
    return registry_path.parent / "active_instance.json"


def _read_active_instance() -> str | None:
    path = _active_instance_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return None
    value = data.get("active") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _write_active_instance(name: str) -> None:
    import tempfile
    from pathlib import Path

    path = Path(_active_instance_path())
    with _ACTIVE_INSTANCE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".active_instance.", suffix=".json.tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"active": name, "updated_at": _now_iso()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _instance_target(cfg: RepoConfig) -> str:
    """The instance's actual target table — the thing that makes two instances
    visibly different in the switcher."""
    if cfg.backend == "gsheet":
        return (cfg.gsheet.sheet_name if cfg.gsheet else "") or "gsheet"
    return (cfg.supabase.table if cfg.supabase else "") or "supabase"


# ---------------------------------------------------------------------------
# _scope() — the ONE answer to "which instance is this request about?".
#
# WHY THIS EXISTS. Selecting an instance has to change what the endpoints that
# carry no ``<repo>`` in their URL actually READ, and for a long time it did
# not: ``GET /dashboard/stats``, the sync board's document join and
# ``apply-fallback-type`` each named ``incoming_documents`` as a string literal.
# With one instance registered that is invisible — the literal happens to be the
# right table. With two it is a dashboard that counts the wrong company's
# documents and, worse, an UPDATE that writes ``TYPE`` into the wrong company's
# table. A silent cross-instance write is the most damaging thing this service can
# do, and it was three string literals away.
#
# There is exactly ONE resolver on purpose (indox-final-plan §6.3). A second way
# to decide "the active table" is precisely how the two drift apart, so every
# repo-less site that addresses documents takes a ``_Scope`` and takes it as a
# REQUIRED argument: a site that forgets to ask fails loudly at the call, rather
# than quietly defaulting to somebody else's rows.
#
# ``instance`` rides along because it is also the sync caches' missing key —
# see ``_sync_cached`` below.
# ---------------------------------------------------------------------------
class _Scope(NamedTuple):
    """(instance, doc_table) for the currently ACTIVE INDOX instance."""

    #: the active instance's name — the discriminator every sync cache key needs
    instance: str
    #: its supabase document table, or None when the instance is not
    #: supabase-backed. None is deliberate: a gsheet instance has no postgres
    #: table, so the supabase-side reads below must degrade to "no rows" rather
    #: than fall back to a literal and read a table that belongs to someone else.
    doc_table: str | None


def _resolve_active(configs: list[RepoConfig]) -> str:
    """The active instance, self-healing. A pointer at a deleted repo (or no
    pointer at all) resolves to the first registered one rather than leaving
    the UI with an `active` id that isn't in its own list — the failure mode
    that makes a switcher render an empty chip."""
    names = [c.name for c in configs]
    stored = _read_active_instance()
    if stored and stored in names:
        return stored
    return names[0] if names else ""


#: The instance every instance-scoped row belongs to when nothing says otherwise.
#: MUST match the `default` on settings/companies/tag_rules in
#: apps/indox/blueprint/fixtures/schema.sql — the DDL default is what carried the
#: existing rows over without a backfill, and this is the reader half of that
#: same decision. Changing one without the other splits the config in half.
_DEFAULT_INSTANCE = "incoming-documents-main"


def _instance() -> str:
    """The COMPONENT this config row belongs to — the `instance` COLUMN on
    settings/companies/tag_rules. **Not the instance.**

    The instance is the SCHEMA (`indox_<id>`), resolved per request by
    `_request_schema()`. These are two different facts that unfortunately share
    one word: the column separates components within one instance's config, the
    schema separates instances from each other.

    [2026-08-28] This used to return `_resolve_active(registry.list())` — the
    active REPO name — and it worked only by coincidence: the active repo
    happened to be named the same string as the column's only value. Point the
    console at any other repo (the archive, say) and every config read filtered
    on a name no row carries, so settings, companies and tag_rules all came back
    EMPTY and the console rendered as though the configuration had been wiped.
    Worse, it made a instance-scoped read depend on `active_instance.json`, a
    single global pointer on the host — which is the legacy multi-instance model
    being removed, reaching into the new one.

    So it returns the constant. That is exactly what it resolved to in practice,
    with the coincidence and the dependency both gone.
    """
    return _DEFAULT_INSTANCE


def _tenant(extra: dict | None = None) -> dict:
    """Filter for a instance-scoped read: `{'instance': ...}` plus whatever else."""
    f = {"instance": _instance()}
    if extra:
        f.update(extra)
    return f


def _scope(reg: RepoRegistry) -> _Scope:
    """Resolve the active instance to (name, document table). Never raises: an
    unreadable registry is a reason to answer for nothing, not to 500."""
    try:
        configs = reg.list()
    except Exception:
        configs = []
    active = _resolve_active(configs)
    cfg = next((c for c in configs if c.name == active), None)
    if cfg is None:
        return _Scope("", None)
    return _Scope(cfg.name, _instance_target(cfg) if cfg.backend == "supabase" else None)


# Stable per-instance chip colour. Instances have no colour of their own in the
# live model (the sim seeds one per company), so derive a deterministic one from
# the name: the same instance is the same colour on every machine and every
# reload, which is the only property the chip actually needs.
#
# The colour is a NAME from the office's palette (the screen's stylesheet carries the block — its
# text steps, which turn with a dark ground), in the order the other screens give their avatars
# (drive's owners, mail's senders, chat's contacts): neighbours in the list differ in hue.
_INSTANCE_COLORS = tuple(f"var(--{step})" for step in ("sky-d", "olive-d", "plum-d", "lime-d", "violet", "muted"))


def _instance_color(name: str) -> str:
    return _INSTANCE_COLORS[sum(name.encode("utf-8")) % len(_INSTANCE_COLORS)]


def _request_schema(default: str = "public") -> str:
    """The schema THIS REQUEST reads from — the instance's when `?instance=` named one.

    Bound once per request by the blueprint's before_request hook, so the dozen read helpers
    that never took a schema argument (the dashboard's aggregates, the action log, the sync
    board) follow the operator's instance without each of them growing a parameter and each
    caller remembering to pass it. Absent an instance, `public` — exactly as before.

    Outside a request, `_schema_context()` can pin the answer for the current thread — that is
    how the background refreshers serve every instance instead of only `public` (which is all
    this function could ever answer in a plain thread, however many instances existed)."""
    try:
        if has_request_context():
            return getattr(g, "indox_schema", None) or default
    except Exception:
        pass
    override = getattr(_SCHEMA_CONTEXT, "schema", None)
    if override:
        return override
    return default


def _request_instance() -> str | None:
    """The tenant ID this request (or schema-context) acts for — the schema minus its `indox_`
    prefix, an exact inversion under the registry's schema law (schema_name = 'indox_' || id).
    None when tenantless (schema `public`), so callers can refuse or omit explicitly."""
    sch = _request_schema()
    return sch[len("indox_"):] if sch.startswith("indox_") else None


_SCHEMA_CONTEXT = threading.local()


@contextmanager
def _schema_context(schema: str):
    """Pin `_request_schema()` for THIS THREAD while a background pass works one instance.

    A context rather than a parameter, deliberately: one refresher pass calls a dozen helpers
    (`_read_sync_registry`, `_compute_dashboard_stats_payload`, their
    callees) that each consult `_request_schema()` internally — threading a schema argument
    through every signature is exactly the churn the per-request g-binding exists to avoid.
    Never nests across instances: each pass sets, works one instance, restores."""
    prev = getattr(_SCHEMA_CONTEXT, "schema", None)
    _SCHEMA_CONTEXT.schema = schema
    try:
        yield
    finally:
        _SCHEMA_CONTEXT.schema = prev


def _stats_target_schemas(transport) -> list[tuple[str, str]]:
    """[(instance_id, schema)] the background refreshers must serve — every ENABLED instance in
    `public.indox_instances`, or [("", "public")] on a deployment that has no registry (fresh
    machine before provisioning, or pre-tenancy). Errors fall back to `public` LOUDLY: a
    refresher that silently serves nobody is the bug this helper replaces."""
    try:
        if hasattr(transport, "_exec_sql"):
            rows = transport._exec_sql(
                "select id, schema_name from public.indox_instances "
                "where enabled order by id"
            ) or []
            out = [
                (str(r.get("id") or ""), str(r.get("schema_name") or ""))
                for r in rows
            ]
            out = [(i, s) for i, s in out if i and s and _SAFE_SCHEMA.match(s)]
            if out:
                return out
    except Exception as exc:
        _log.warning(
            "stats refresher: instance registry unreadable (%s) — refreshing public only", exc)
    return [("", "public")]


def _paged_select(transport, *, table: str, select=None, max_rows: int = 200_000,
                  order_col: str = "id", filter: dict | None = None,
                  schema: str | None = None) -> list[dict]:
    """Read up to ``max_rows`` rows through PostgREST, which silently caps any
    single request at its `max-rows` (1000 on this stack). Pages by offset with
    a stable order so ERP-scale tables (10k-100k rows) come back complete —
    without this, reads LOOKED fine but silently truncated at 1000.

    The stop condition compares the returned chunk size against the FIXED page
    size this function itself requested (1000) — never against a caller-supplied
    limit. `POST /documents/query`'s `truncated` flag learned this the hard way:
    it compared `len(rows) >= q.limit` (the CLIENT's limit, e.g. 2000) against
    rows PostgREST had already silently clamped to 1000, so `1000 >= 2000` read
    as "no more data" one page early, every time — see the month-index endpoint
    below and its `INDOX-MONTH-INDEX` note for the bug this caused."""
    schema = schema or _request_schema()
    page = 1000
    out: list[dict] = []
    offset = 0
    while offset < max_rows:
        chunk = transport.select(
            schema=schema, table=table, select=select, filter=filter,
            order=[(order_col, "asc")], limit=page, offset=offset,
        ) or []
        out.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return out[:max_rows]


# ---------------------------------------------------------------------------
# indox_dashboard_stats — the dashboard's read model, maintained on write.
#
# GET /dashboard/stats used to be `_paged_select` over the WHOLE document table, on every
# request, followed by an in-process aggregate — flat-ish at 6,250 rows, unbounded past it
# (INDOX-UNIFIED-N8N-SPEC.md §5: "at 180,000 rows the UI lives or dies here"). The schema in
# scripts/ops/dashboard-stats-schema.sql adds a statement-level trigger on every
# incoming_documents* table that does ONE thing on write: flips `indox_dashboard_stats.dirty`
# — an indexed upsert, not a recompute, so a 500-row n8n batch write costs the trigger ONE
# firing, not 500. `_compute_dashboard_stats_payload` below is the exact aggregate this
# replaced (unchanged logic — same status/type/company/extraction/recent shape); what moved is
# WHO calls it and WHEN: `_dashboard_stats_loop`, a background daemon thread started once from
# `create_blueprint`, is the only steady-state caller. `GET /dashboard/stats` becomes one
# primary-key SELECT (see the endpoint below) — O(1) regardless of table size.
#
# Cold start / drift: a doc_table with no row yet (fresh DB, or the trigger not yet applied)
# is computed synchronously ONCE by the endpoint itself as a fallback, and that result is
# written back so every request after the first is the fast path. `_DASH_STATS_RECONCILE_S`
# forces a from-scratch recompute periodically even when NOT dirty — repairs against a trigger
# that silently failed to fire (a corrupt/legacy row edited outside this path, a migration that
# ran before this schema existed) without anyone having to notice and ask for it by hand.

_DASH_STATUS_GROUP = {
    "COMPLETED": "done",
    # recoverable / needs a human or a retry
    "MISSING_COMPANY_ID": "attention", "UNKNOWN_COMPANY": "attention",
    "MISSING_TYPE": "attention",
    "MISSING_SHIPMENT": "attention", "ACTION_REQUIRED": "attention",
    "ACTION_RESTART": "attention",
    "PAUSE": "attention", "FROM_OFFICE": "attention", "NEEDS_REVIEW": "attention",
    # hard failures
    "EXTRACTION_FAILED": "failed", "MAX_ITERATIONS": "failed",
    # terminal no-ops / in-flight (not actionable)
    "DOUBLE": "other", "OLD": "other", "TRASH": "other", "IN_PROGRESS": "other",
    # delivered by sync, not yet picked up for extraction (A2, 2026-08-06). `other`, NOT
    # `attention`: it is the normal resting state of a thin-pipe document between delivery and
    # extraction, and painting a healthy backlog as "needs a human" is the false-clean in reverse.
    "TO_EXTRACT": "other",
    # terminal RESOLVED outcomes, not failures and not work items (2026-08-06):
    #   MERGED  — the losing row of an adjudicated merge; a tombstone carrying MERGED_INTO.
    #   GARBAGE — BaseDocEx01's <3-word verdict: a blank page / unreadable fragment.
    # Both are `other` for the same reason TO_EXTRACT is: the dashboard's default for an
    # unlisted status is `attention`, so a status missing from this map does not merely lose
    # its label — it actively summons a human to a document nothing is wrong with.
    "MERGED": "other", "GARBAGE": "other",
    # [missing-link 2026-08-13] MOVED OUT OF `attention`, deliberately. Owner: "make missing link
    # stop showing up inside דורשים טיפול in the top number ... it just means we only have the BS
    # line data."
    # MISSING_LINK is a balance-sheet LINE parsed out of a parent invoice list whose own source
    # document INDOX never received. The row legitimately carries COMPANY_ID, TYPE and
    # COMPANY_DOC_ID from its parent; what it lacks is the individual PDF, and nothing in the
    # pipeline can conjure one — measured, of 3,203 BS-line children that reached COMPLETED,
    # 3,202 had a file and exactly 1 did not. So it is not a work item awaiting a human decision,
    # it is a resting state awaiting a document that may never arrive.
    # This is the SAME argument that already put TO_EXTRACT, MERGED and GARBAGE here: the default
    # for an unlisted status is `attention`, so leaving it out would re-summon a human. At 6,013
    # rows it was the single largest contributor to the דורשים טיפול headline (7,934), i.e. ~76%
    # of that number was a backlog nobody can act on — the false-clean in reverse.
    # NOTE: the STATUS LABEL is unchanged and stays 'חסר קישור' (vocab.ts). Only the dashboard
    # ROLL-UP changes; per-status counts and the status bar still show it under its own name.
    "MISSING_LINK": "other",
}


def _dash_group(status: str) -> str:
    return _DASH_STATUS_GROUP.get((status or "").upper(), "attention")


# ── the dashboard time window ────────────────────────────────────────────────
#
# Same control, same semantics, same reasoning as the mail inbox's window
# (apps/mail/mailview/app.py `_since_ts` — the reference implementation this
# mirrors so the platform feels like one product): `all` (default, unchanged
# behaviour), `15m`, `30m`, `1h`, `today`, `month`. The window cuts on **created_at**
# — when the row entered INDOX — because "what came in during the last hour"
# is the operational question while syncs pour documents in; DOC_DATE is the
# document's own (business) date and answers a different question.
#
# ⚠ THE TIMEZONE IS THE USER'S, NEVER THE SERVER'S. This container runs UTC;
# the client watching this dashboard is in Asia/Jerusalem (UTC+3 in summer).
# A "today" computed from server time would begin three hours late — every
# document that arrived between 00:00 and 03:00 local would be missing from
# "today", silently, every day. So the browser sends its own
# `new Date().getTimezoneOffset()` and the day/month boundaries are cut in
# THAT frame. The sub-day windows (15m/30m/1h) are the same span in every timezone
# and ignore the offset entirely — only CALENDAR windows need it.
#
# ADDING A SUB-DAY WINDOW IS THESE TWO LINES AND NOTHING ELSE. Everything that has to
# know "is this narrower than a day" reads _DASH_WINDOW_SECONDS rather than listing the
# ids again: `_dash_win_since` converts it to an instant, `_dash_win_effective` collapses
# it to `today` on a day-granularity basis, and `_dash_since_for_basis` floors it there.
# The one list that is NOT derived is the UI's SUBDAY_WINDOWS (DashboardPage.tsx), which
# greys the button out before the click — keep the two in step.
_DASH_WINDOWS = ("all", "15m", "30m", "1h", "today", "month")
_DASH_WINDOW_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600}


def _dash_win_since(win: str | None, tz_off_min, now: float | None = None) -> str | None:
    """UTC ISO-8601 instant the window starts, or None for "all" (and for
    anything unrecognised — an unknown window must widen to everything, never
    silently hide documents).

    `tz_off_min` is the browser's `Date.prototype.getTimezoneOffset()`: minutes
    to ADD to local time to reach UTC, so it is NEGATIVE east of Greenwich
    (Israel in summer sends -180). Clamped to the real range of earth's offsets
    (-14h..+14h) so a malformed or hostile value cannot move the day boundary
    by years; an unparseable one means UTC, which is only ever wrong by hours
    and never wrong by a whole window."""
    win = (win or "all").strip().lower()
    if win not in _DASH_WINDOWS or win == "all":
        return None
    now = time.time() if now is None else now
    if win in _DASH_WINDOW_SECONDS:
        return datetime.fromtimestamp(now - _DASH_WINDOW_SECONDS[win], tz=timezone.utc).isoformat()
    try:
        shift = max(-14 * 60, min(14 * 60, int(tz_off_min))) * 60
    except (TypeError, ValueError):
        shift = 0
    # Shift the instant into the user's frame, cut the boundary there, shift the
    # boundary back — the exact arithmetic mailview validated in production.
    loc = datetime.fromtimestamp(now - shift, tz=timezone.utc)
    loc = loc.replace(hour=0, minute=0, second=0, microsecond=0)
    if win == "month":
        loc = loc.replace(day=1)
    return datetime.fromtimestamp(loc.timestamp() + shift, tz=timezone.utc).isoformat()


# ── the window's DRIVING COLUMN (?basis=) ────────────────────────────────────
#
# The window above cuts on ONE column. Until now that column was hard-coded to
# `created_at`, which answers "what ARRIVED in the last 30 minutes". That is the
# right default and stays the default — but it is not the only question, and
# when sync halts it is actively misleading: `created_at` in the last 30m was
# **1** while `updated_at` in the same 30m was **123**. Nothing was arriving,
# the state machine was working flat out, and the dashboard showed zeros
# everywhere. `basis` makes the driving column switchable so "every line that
# had an action executed in the last 30m" (`updated_at`) is askable too.
#
# ⚠ ABSENT `basis` MUST BE BYTE-IDENTICAL TO BEFORE. The default resolves to
# `created_at`, the filter it builds is the same single-key `gte` dict, and an
# unrecognised basis falls back to the default rather than erroring — the same
# rule `win` follows (an unknown value must never silently hide documents). The
# basis the server ACTUALLY applied is echoed in the response so the UI can
# prove it rather than trusting what it asked for.
#
# WHICH COLUMNS ARE OFFERED, AND WHY THE OTHERS ARE NOT.
# Every date-ish column in the table was measured against the live 16,237-row
# table (2026-08-10). Two things disqualify a column: mixed value formats, and
# day-granularity.
#
#   OFFERED
#     created_at  timestamptz, indexed. Arrival into INDOX. The default.
#     updated_at  timestamptz, indexed, maintained by `trg_incdoc_touch`. The
#                 last time anything on the row changed — the "had an action
#                 executed" question the owner is actually asking.
#     TIMESTAMP   TEXT, but measured STRICTLY uniform: all 15,032 filled values
#                 are exactly `YYYY-MM-DDTHH:MM:SS.mmmZ`, 24 chars, zero
#                 non-conforming. For a fixed-width ISO-8601 format,
#                 lexicographic `>=` IS chronological `>=`, so a plain btree on
#                 the text column answers the window exactly and by index scan
#                 (measured: 0.32 ms / 160 buffers). The comparison value is
#                 rendered into that same 24-char shape by
#                 `_dash_since_for_basis` — comparing like against like is what
#                 makes this exact rather than lucky.
#
#     doc_date_norm
#                 timestamptz, indexed, trigger-maintained. The DOCUMENT'S OWN
#                 (business) date — "what did we receive DATED last month",
#                 which is a different and equally operational question from
#                 "what arrived last month". This is the normalised form of
#                 `DOC_DATE`; the raw TEXT column is not offered and cannot be
#                 (see below). Added 2026-08-10 together with the n8n workflow
#                 edit G39 requires — see schema.sql for the column, the parse
#                 rules and the trigger.
#
#   NOT OFFERED — these are advertised to the UI with `available: false` and a
#   reason, NOT hidden. A control that silently lacks an option looks broken;
#   one that explains itself is a finding.
#     RECEIVED_DATE     9,239 filled, ZERO ISO, and 477 rows whose value is the
#                       literal string `true`.
#     AI_DOC_DATE       4,606 filled, mixed (4,539 DMY4 / 42 DMY2 / 25 ISO).
#     LOCAL_DOC_DATE    3,106 filled, mixed DMY4/DMY2.
#     SELECTED_DOC_DATE 6,242 filled, DD/MM/YYYY only — no ISO to sort by.
#     BS_LINE_DATE      2,112 filled, mixed (1,910 ISO / 202 DMY4).
#   Each of them is the SAME defect `doc_date_norm` fixes for `DOC_DATE`, and
#   each is fixable the same way: another normalised column, another trigger,
#   another index, another field on the batch-upsert trigger's schema. They are
#   left disabled rather than done speculatively — `DOC_DATE` is the one the UI
#   already navigates by, so it is the one worth a column.
#
# WHY `DOC_DATE` ITSELF STILL CANNOT BE A BASIS, AND WHY THE FIX IS A COLUMN.
# `DOC_DATE` is TEXT in three live shapes (measured 2026-08-10 on 16,264 rows:
# 8,360 filled = 5,114 ISO + 2,806 DD/MM/YYYY + 440 DD/MM/YY). Lexicographic
# `>=` across those is not merely imprecise, it is BACKWARDS for the 39% in
# slash form: '25/06/2026' > '2026-08-10' (they differ at index 1, '5' > '0'),
# so every slash-format row would report as inside every window, forever. No
# amount of index or comparison-value shaping fixes that; only normalising the
# VALUE does, which is what `doc_date_norm` is.
#
# WHY A TRIGGER-MAINTAINED PLAIN COLUMN AND NOT A STORED GENERATED ONE.
# `indoxApiSupabase01`'s `Build Merge Write` node does `select *` on the rows it
# merges and re-emits `update … set "<col>" = <param>` for every column outside
# a hardcoded 24-name skip list. A STORED GENERATED column reached by that loop
# is a runtime SQLSTATE 428C9 on a live merge path — an outage. A plain column
# stays writable so that statement succeeds, and the BEFORE INSERT OR UPDATE
# trigger recomputes the value unconditionally, so the write is immediately
# replaced by the value derived from that row's own `DOC_DATE`. Derived in
# effect, writable in fact. (Proved live in a rolled-back transaction: a direct
# `set "doc_date_norm" = '1999-01-01'` comes back out as the DOC_DATE-derived
# value.)
#
# THREE LIMITS OF THIS BASIS, ALL REPORTED RATHER THAN HIDDEN.
#  1. HISTORICAL ROWS. A trigger fires on write, so every row that existed
#     before the migration carries NULL until something touches it. This basis
#     therefore under-reports the back catalogue on day one and converges as the
#     pipeline works. `_dash_basis_excluded` counts exactly those rows and the
#     UI prints the number, which is the same honest degradation `TIMESTAMP`
#     already gets — it is NOT a silent zero. Filling them would be a one-off
#     bulk UPDATE over every document row; that is an owner decision.
#  2. DAY GRANULARITY. A business date has no time of day, so the sub-day windows
#     cannot mean anything narrower than "today" on it. Rather than return a
#     confidently empty board, `_dash_since_for_basis` FLOORS the window's start
#     to the beginning of the viewer's local calendar day for this basis, and
#     the response says so in `win_effective` (the UI reads the basis's
#     `granularity` and disables the sub-day buttons outright). Silently
#     answering a 30-minute question with a whole day would be the cache-key bug
#     in reverse: the right numbers, mislabelled.
#  3. THE WINDOW'S RIGHT EDGE IS OPEN, and on THIS basis that is visible for the
#     first time. Every window here is `col >= since` with no upper bound —
#     which has always been harmless because an ARRIVAL instant cannot be in the
#     future (measured: 0 of 16,264 rows have `created_at` or `updated_at` ahead
#     of now()). A BUSINESS date can, and does: 97 of the 8,353 parseable
#     `DOC_DATE` values are future-dated extraction errors (10/07/2094,
#     31/12/2050, …). So "היום" on this basis means "dated today OR LATER", and
#     those 97 sit inside every window forever — the same shape of defect the
#     raw TEXT column had, at 1.2% instead of 39%.
#     NOT FIXED HERE, deliberately. A bounded window needs TWO clauses on one
#     column, and the transport's filter is `{col: {op, value}}` — one clause per
#     column, one entry per dict key. Expressing `>= X and < Y` means changing
#     the shape every read in this app passes through (`_runtime_params`), which
#     is a larger and riskier change than the whole of this feature. It is
#     stated in the basis `hint` (the UI renders it as the option's tooltip) so
#     the number is explainable at the point of use, and left as an explicit
#     follow-up rather than smuggled in beside a schema migration.
_DASH_BASIS_DEFAULT = "created_at"

#: id -> spec. `col` is the physical column; `kind` selects how the window's
#: start instant is rendered for comparison; `eligible` is the filter counting
#: rows the basis can actually place on a timeline (see `_dash_basis_excluded`).
_DASH_BASES: dict[str, dict] = {
    "created_at": {
        "label": "נוצר", "kind": "ts", "col": "created_at",
        "hint": "מתי המסמך נכנס ל-INDOX",
        "eligible": {"op": "not_null"},
    },
    "updated_at": {
        "label": "עודכן", "kind": "ts", "col": "updated_at",
        "hint": "מתי בוצעה פעולה אחרונה על השורה",
        "eligible": {"op": "not_null"},
    },
    "TIMESTAMP": {
        "label": "חותמת זמן", "kind": "iso_text", "col": "TIMESTAMP",
        "hint": "חותמת הזמן שנכתבה על השורה בצינור העיבוד",
        # non-null AND non-empty AND digit-leading: '' and NULL both fall below
        # this bound, so `total - eligible` is the true un-placeable count.
        "eligible": {"op": "gte", "value": "0000-01-01T00:00:00.000Z"},
    },
    "doc_date_norm": {
        "label": "תאריך מסמך", "kind": "business_day", "col": "doc_date_norm",
        "hint": "התאריך המודפס על המסמך עצמו (מנורמל מ-DOC_DATE); "
                "רזולוציית יום — טווחים קצרים מיום נמדדים כ\"היום\"; "
                "הטווח פתוח קדימה, ולכן כולל גם מסמכים שתאריכם עתידי "
                "(97 מסמכים בטבלה, שגיאות חילוץ כמו 10/07/2094)",
        # DAY granularity: the two sub-day windows cannot mean anything narrower
        # than "today" here. Declared rather than assumed, so the UI disables
        # them instead of quietly showing a day's numbers under a 30m label.
        "granularity": "day",
        "min_win": "today",
        # NULL is the only un-placeable state: an unparseable DOC_DATE and a
        # never-written historical row both land there, and both are genuinely
        # un-placeable, so this count is exact rather than approximate.
        "eligible": {"op": "not_null"},
    },
}

#: offered in the UI as disabled options, with the measured reason. Keeping them
#: visible is the point: "why can't I window by RECEIVED_DATE" is answerable
#: from the dashboard itself instead of being a silent omission.
_DASH_BASES_UNAVAILABLE: dict[str, dict] = {
    "RECEIVED_DATE": {"label": "תאריך קבלה",
                      "reason": "אין ערכי ISO; 477 שורות מכילות את הערך true"},
    "AI_DOC_DATE": {"label": "תאריך AI",
                    "reason": "פורמטים מעורבים — מיון לא אמין"},
    "LOCAL_DOC_DATE": {"label": "תאריך מקומי",
                       "reason": "פורמטים מעורבים — מיון לא אמין"},
    "BS_LINE_DATE": {"label": "תאריך שורת גיול",
                     "reason": "פורמטים מעורבים — מיון לא אמין"},
}

#: lower-cased id -> canonical id, so `?basis=timestamp` finds "TIMESTAMP".
#: `doc_date` is spelled out because that is the name the column had in the UI
#: while it was a DISABLED option, and a stale `?basis=DOC_DATE` (a bookmark, a
#: dashboard link, a saved localStorage value from before the migration) must
#: reach the working column rather than silently falling back to `created_at`
#: and labelling arrival dates as document dates.
_DASH_BASIS_ALIASES = {k.lower(): k for k in _DASH_BASES}
_DASH_BASIS_ALIASES["doc_date"] = "doc_date_norm"


def _dash_basis(raw: object) -> str:
    """Canonical basis id for a request value. Unknown/absent -> the default,
    never an error and never a widened window: an unrecognised basis must
    behave exactly like today's hard-coded `created_at`."""
    return _DASH_BASIS_ALIASES.get(str(raw or "").strip().lower(),
                                   _DASH_BASIS_DEFAULT)


def _dash_since_for_basis(since_iso: str | None, basis: str,
                          tz_off_min: object = None) -> str | None:
    """`since_iso` rendered in the BASIS COLUMN'S OWN format.

    For the timestamptz bases this returns the input unchanged — which is what
    keeps the `created_at` default byte-identical. For the fixed-width ISO TEXT
    basis it re-renders the same instant as `YYYY-MM-DDTHH:MM:SS.mmmZ`, because
    a lexicographic comparison is only exact between two strings of the SAME
    shape; handing PostgREST Python's `+00:00`-suffixed, microsecond-precision
    isoformat to compare against a `…mmmZ` column would be comparing two
    different alphabets and getting away with it by coincidence.

    For a BUSINESS-DAY basis (`doc_date_norm`) it floors the instant to the
    start of the calendar day that instant falls in **in the viewer's frame**,
    and renders that day at 00:00 UTC — the same anchor the column stores.

    Why the flooring is not optional, and why it needs the offset. A business
    date has no time of day; the column stores `<day> 00:00:00+00`. Comparing
    that against a raw instant is off by up to a whole day in either direction:
      * an Israel viewer (getTimezoneOffset() = -180) asking for "today" sends a
        window starting at 21:00 UTC on the PREVIOUS day, which a naive `>=`
        would satisfy with yesterday's documents too;
      * a New York viewer (+300) sends 05:00 UTC on the SAME day, which a naive
        `>=` would fail for every document actually dated today — an empty board
        that looks like "nothing happened".
    Flooring in the viewer's frame gives the same right answer in both. The
    offset is clamped exactly as `_dash_win_since` clamps it (±14h, unparseable
    means UTC) so a malformed or hostile `tz` cannot move a day boundary.

    This also absorbs the sub-day windows: `15m`/`30m`/`1h` floor to the same
    "start of today", which is the honest answer for a day-granularity column
    and is reported as `win_effective` rather than pretended away."""
    if since_iso is None:
        return None
    kind = _DASH_BASES.get(basis, {}).get("kind")
    if kind == "iso_text":
        dt = datetime.fromisoformat(since_iso).astimezone(timezone.utc)
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"
    if kind == "business_day":
        dt = datetime.fromisoformat(since_iso).astimezone(timezone.utc)
        try:
            shift = max(-14 * 60, min(14 * 60, int(tz_off_min))) * 60
        except (TypeError, ValueError):
            shift = 0
        day = datetime.fromtimestamp(dt.timestamp() - shift, tz=timezone.utc).date()
        return f"{day.isoformat()}T00:00:00+00:00"
    return since_iso


def _dash_win_effective(win: str, basis: str) -> str:
    """The window the chosen basis can ACTUALLY express.

    A day-granularity basis cannot answer a 15-minute question, so every window in
    `_DASH_WINDOW_SECONDS` becomes `today` there. Echoed to the client
    (`win_effective`) so a board showing a day's numbers is never labelled as a
    quarter of an hour's — the UI's own fix is to disable those buttons for such a
    basis, and this is the server-side truth behind that."""
    if (win in _DASH_WINDOW_SECONDS
            and _DASH_BASES.get(basis, {}).get("granularity") == "day"):
        return "today"
    return win


def _dash_bases_catalogue() -> list[dict]:
    """What the UI renders: every candidate column, offered or not, with the
    reason it is not. Order is fixed (offered first) so the control does not
    reshuffle between polls.

    `granularity`/`min_win` travel with the offered entries so the WINDOW
    control can react to the BASIS control without hard-coding which columns are
    day-shaped — the same reason the option list itself comes from the server:
    it is a property of the data, not of the page."""
    out = []
    for k, v in _DASH_BASES.items():
        item = {"id": k, "label": v["label"], "hint": v["hint"],
                "available": True,
                "granularity": v.get("granularity", "instant")}
        if v.get("min_win"):
            item["min_win"] = v["min_win"]
        out.append(item)
    out += [{"id": k, "label": v["label"], "reason": v["reason"],
             "available": False}
            for k, v in _DASH_BASES_UNAVAILABLE.items()]
    return out


def _dash_basis_excluded(transport, doc_table: str, basis: str) -> dict | None:
    """How many rows the chosen basis CANNOT place on the timeline.

    A `gte` filter drops NULLs silently — SQL three-valued logic, not a bug, but
    it means an empty window is ambiguous: nothing happened, or this basis has
    no data? This answers that directly, as two `count=exact` HEAD-shaped reads
    (PostgREST `Content-Range`, no rows transferred) rather than by dragging the
    table into Python. Returns None if the transport cannot count — a missing
    diagnostic must never take the dashboard down with it."""
    spec = _DASH_BASES.get(basis)
    if spec is None or not hasattr(transport, "count"):
        return None
    try:
        total = transport.count(schema=_request_schema(), table=doc_table, filter=None)
        eligible = transport.count(schema=_request_schema(), table=doc_table,
                                   filter={spec["col"]: spec["eligible"]})
    except Exception as exc:  # diagnostics are best-effort, never fatal
        _log.debug("dashboard basis-exclusion count failed (%s): %s", basis, exc)
        return None
    return {"rows": total, "eligible": eligible,
            "excluded": max(0, int(total) - int(eligible))}


def _dash_truthy(v: object) -> bool:
    return str(v).strip().lower() in ("true", "t", "1", "yes")


# ── the per-field extraction score ────────────────────────────────────────────
#
# TWO RULES, both of which this table used to get wrong, and both of which showed
# up on the board as the same symptom — a number nobody could act on.
#
# (1) THE POPULATION IS THE DOCUMENTS THAT FINISHED, NOT EVERY ROW IN THE WINDOW.
#     The denominator was `total`, so every row the pipe had merely DELIVERED counted
#     against the score. Measured on the live table (30m/updated_at window, 2026-08-12):
#     534 rows in the window, 497 of them carrying a TYPE, but only 81 actually FINISHED —
#     the rest sit in TO_EXTRACT/IN_PROGRESS, where no field has been resolved yet.
#     Scoring extraction over documents still being extracted makes the number a function
#     of the sync backlog: a big Drive delivery drops the score without a single extraction
#     getting worse. The same five fields over the three candidate populations read
#     58/33/52/30/36 (every row), 63/35/56/33/38 (has a TYPE) and 95/60/86/62/64
#     (finished) — only the last one answers "how good is our extraction".
#
#     "Finished" is `_dash_group(STATUS) == "done"`, NOT a literal `== "COMPLETED"`, so
#     this panel's denominator is BY CONSTRUCTION the same row set as the "הושלמו" KPI
#     beside it. COMPLETED is the group's only member today; if a second terminal-success
#     status is ever added to _DASH_STATUS_GROUP, the KPI and this score move together
#     instead of silently disagreeing. Excluded rows stay fully visible everywhere else on
#     the board (by_status / by_type / the KPI strip all count them); they are out of THIS
#     panel only, and `scored` / `skipped` state exactly how many.
#
# (2) THE DOCUMENT NUMBER IS READ AS A VALUE, NOT AS `INVOICE_ID_COMPLETED`.
#     That flag is the reason "מס׳ מסמך" read 0%. It is an INVOICE-only legacy stamp,
#     and since the two-point rearchitecture (2026-08-11) the modern path deliberately
#     stops writing it — indoxV2ActionsGDoc01/'Select Per Type Values' says so in as
#     many words: "INVOICE_ID is deliberately NOT stamped … the query stays available as
#     a genuine fallback". The extractor writes DOC_ID (COMPANY_DOC_ID retired 2026-08-17); the only
#     remaining writer of the flag is the legacy `query_invoice_id` action, whose own
#     gate (`!doc.INVOICE_ID`) is now closed by that very mapping. Measured over the same
#     window: 5 rows of 692 carry the flag, while 385 carry an actual document number.
#     So the bar was reporting the death of a fallback, not the extraction of a field.
#     DOC_ID first (the consolidated id every TYPE now writes), then INVOICE_ID (what
#     the per-type router resolves), then INVOICE_ID (pre-consolidation rows) — the same
#     precedence scripts/ops/migrations/2026-08-06_doc_id_consolidation.sql backfilled by.
#
# `kind` is what keeps the two readings honest about being different measurements:
# "flag" asks whether the STAGE recorded an answer, "value" asks whether the ROW has one.
#
# [2026-09-03, owner order "ציון חילוץ should be 90+ for completed documents"] Four of the five
# bars used to read STAGE STAMPS (COMPANY_NAME_COMPLETED, DOC_DATE_COMPLETED,
# DOC_TOTAL_AMOUNT_COMPLETED, AI_EXTRACTION_COMPLETED) that only the invoice and shipment lanes
# ever wrote, that every ACTION_RESTART wiped, that a COMPLETED document never re-acquired, and one
# of which was a picture of the extraction_ai_enabled toggle — 5 / 4 / 4 / 3 on the live dashboard
# while the one honest bar (DOC_ID, a VALUE) read 94. Every bar is now a VALUE of the FINAL
# columns the selectors declare (fixture_<TYPE>.json select.outputs), and a field counts only on
# the document types it applies to: a delivery note structurally has no total.
_DASH_EXT_FIELDS = [
    {"key": "COMPANY_ID", "label": "חברה", "kind": "value",
     "cols": ("COMPANY_ID", "COMPANY_NAME"), "types": None,
     "hint": "COMPANY_ID — הערך הסופי של החברה"},
    {"key": "DOC_DATE", "label": "תאריך", "kind": "value",
     "cols": ("DOC_DATE",), "types": None,
     "hint": "DOC_DATE — תאריך המסמך הסופי"},
    {"key": "DOC_ID", "label": "מס׳ מסמך", "kind": "value",
     "cols": ("DOC_ID", "INVOICE_ID"), "types": None,
     "hint": "DOC_ID / INVOICE_ID — ערך שחולץ בפועל"},
    {"key": "DOC_TOTAL_AMOUNT", "label": "סכום", "kind": "value",
     "cols": ("DOC_TOTAL_AMOUNT", "BS_LINE_AMOUNT"), "types": ("INVOICE", "BALANCE_SHEET"),
     "hint": "DOC_TOTAL_AMOUNT / BS_LINE_AMOUNT — נספר רק על חשבוניות וכרטסות"},
    {"key": "TYPE", "label": "סוג", "kind": "value",
     "cols": ("TYPE",), "types": None,
     "hint": "TYPE — סוג המסמך הסופי"},
]


def _dash_certainty(row: dict) -> int | None:
    """`SELECTION_CERTAINTY` is TEXT on incoming_documents (0 / 50 / 100, or a per-company floor);
    parse the leading integer the way indox_priority_signature does, None when absent."""
    s = str(row.get("SELECTION_CERTAINTY") or "").strip()
    m = re.match(r"^[+-]?\d+", s)
    return int(m.group(0)) if m else None


#: Values that occupy a date column without being a date. `RECEIVED_DATE` carries the literal
#: string 'true' on 477 live rows (an upstream writer putting a boolean in a date field — the
#: same TEXT-boolean class of bug the pipeline has hit before), and 'true' is TRUTHY, so the
#: `RECEIVED_DATE or DOC_DATE` fallback never reached the perfectly good DOC_DATE those rows
#: all carry. The dashboard's "מסמכים אחרונים" therefore printed `true` in its date column —
#: and, worse, SORTED on it: `'true'` sorts above every real date string, so the eight rows
#: shown as "the most recent documents" were just the eight most corrupted ones.
_DASH_NON_DATES = {"true", "false", "none", "null", "nan", "-", "—"}


def _dash_row_date(row: dict) -> str | None:
    """The first value on this row that can honestly be shown as its date.

    Presence is not enough — the value has to look like a date. Anything else is treated as
    absent so the next candidate gets its turn, which is exactly what the old `or` chain
    could not do."""
    for col in ("RECEIVED_DATE", "DOC_DATE", "TIMESTAMP"):
        v = str(row.get(col) or "").strip()
        if not v or v.lower() in _DASH_NON_DATES:
            continue
        if _month_key_of(v) is not None:   # the one shared "is this a date" rule
            return v
    return None


def _dash_ext_present(row: dict, field: dict) -> bool:
    """Did this document answer `field`? A "flag" field is answered when its stamp is
    truthy; a "value" field when ANY of its columns holds a non-blank value (first
    listed wins in meaning, but presence is what is being counted)."""
    if field["kind"] == "flag":
        return _dash_truthy(row.get(field["cols"][0]))
    return any(str(row.get(c) or "").strip() for c in field["cols"])


def _compute_dashboard_stats_payload(transport, doc_table: str,
                                     since_iso: str | None = None,
                                     basis: str = _DASH_BASIS_DEFAULT,
                                     tz_off_min: object = None) -> dict:
    """The full aggregate for one document table: totals, status/type/company
    distribution, per-field extraction scoring, and the 8 most recent rows.
    Pure (no jsonify, no request/Flask access) so it serves both the background
    refresher and the cold-start synchronous fallback identically.

    `since_iso` (the dashboard time window) is pushed into the SQL as a
    `<basis> >= …` WHERE clause — PostgREST `gte` — so a narrow window
    means the server never materialises the rest of the table. Filtering the
    full read in-process would look identical and save nothing; at 8,500+ rows
    and growing that is the wrong layer (same argument as mailview's window,
    which ANDs an IMAP SINCE for the same reason).

    `basis` picks WHICH column that clause cuts on (see `_DASH_BASES`). The
    default reproduces the previous hard-coded `created_at` filter exactly —
    same single-key dict, same value — so an absent `basis` changes nothing.
    Every offered basis is btree-indexed, which is what keeps this an index
    scan instead of the sequential scan it used to be (measured on the live
    16,237-row table: 40.4 ms / 2,211 buffers before, 2.4 ms / 171 after).

    `tz_off_min` is the viewer's `getTimezoneOffset()`, needed ONLY by the
    business-day basis (see `_dash_since_for_basis`), which has to know which
    calendar day the window's start instant belongs to. Every other basis
    ignores it, so passing it changes nothing for them — the `created_at`
    default still builds the identical single-key filter it always did."""
    cols = ["ID", "NAME", "STATUS", "TYPE", "COMPANY_NAME", "COMPANY_ID",
            "SOURCE_TYPE",
            # created_at orders "מסמכים אחרונים"; the three date columns feed _dash_row_date
            "created_at", "TIMESTAMP",
            "RECEIVED_DATE", "DOC_DATE",
            # the extraction score reads FINAL VALUES only — see _DASH_EXT_FIELDS
            "DOC_ID", "INVOICE_ID", "DOC_TOTAL_AMOUNT", "BS_LINE_AMOUNT",
            "SELECTION_CERTAINTY"]
    basis = basis if basis in _DASH_BASES else _DASH_BASIS_DEFAULT
    since_val = _dash_since_for_basis(since_iso, basis, tz_off_min)
    flt = ({_DASH_BASES[basis]["col"]: {"op": "gte", "value": since_val}}
           if since_val else None)
    rows = _paged_select(transport, table=doc_table, select=cols, order_col="ID",
                         filter=flt) or []

    total = len(rows)
    by_status: dict = {}
    groups = {"done": 0, "attention": 0, "failed": 0, "other": 0}
    by_type: dict = {}
    # WHERE the documents came from — SOURCE_TYPE, the column literally named "source".
    # SYNC_NAME (the specific pipe) was the other candidate and is the wrong one for a
    # distribution: measured live, 10,680 of 22,968 rows carry no SYNC_NAME at all, so
    # nearly half the board would be one "(ללא)" bar. SOURCE_TYPE is populated on all but
    # 159 rows. Same `(ריק)`-style bucket for those, for the same reason by_status has one:
    # a missing value is a fact about the pipe, not a row to drop.
    by_source: dict = {}
    by_company: dict = {}
    companies: set = set()
    ext_counts = {f["key"]: 0 for f in _DASH_EXT_FIELDS}
    ext_applicable = {f["key"]: 0 for f in _DASH_EXT_FIELDS}
    ext_scored = 0
    cert_sum = 0
    cert_rows = 0
    for r in rows:
        st = (r.get("STATUS") or "").upper() or "(ריק)"
        by_status[st] = by_status.get(st, 0) + 1
        grp = _dash_group(st)
        groups[grp] += 1
        tp = (r.get("TYPE") or "").upper() or "(ללא סוג)"
        by_type[tp] = by_type.get(tp, 0) + 1
        # RAW value, empty string for blank — NOT a Hebrew placeholder like by_type's
        # "(ללא סוג)". The bars are drillable, so whatever goes in here ends up in a
        # `?source=` URL and then in a SOURCE_TYPE filter: a display string put here
        # would produce a link that matches zero rows (measured: 159 blank rows, all
        # true NULL, none empty-string). The UI owns the label AND the is-null sentinel.
        sc = (r.get("SOURCE_TYPE") or "").strip().upper()
        by_source[sc] = by_source.get(sc, 0) + 1
        cn = (r.get("COMPANY_NAME") or "").strip()
        if cn and cn.lower() not in ("unknown", "(none)"):
            by_company[cn] = by_company.get(cn, 0) + 1
            companies.add(cn.lower())
        cid = (r.get("COMPANY_ID") or "").strip()
        if cid:
            companies.add(cid.lower())
        # THE SCORE'S POPULATION IS THE DOCUMENTS THAT FINISHED — the same set the
        # "הושלמו" KPI counts, by construction. See _DASH_EXT_FIELDS rule (1).
        if grp != "done":
            continue
        ext_scored += 1
        for f in _DASH_EXT_FIELDS:
            if f.get("types") and tp not in f["types"]:
                continue                      # the field does not apply to this document type
            ext_applicable[f["key"]] += 1
            if _dash_ext_present(r, f):
                ext_counts[f["key"]] += 1
        cert = _dash_certainty(r)
        if cert is not None:
            cert_sum += cert
            cert_rows += 1

    ext = [{"key": f["key"], "label": f["label"], "hint": f["hint"], "unit": "%",
            "applicable": ext_applicable[f["key"]],
            "pct": (round(100 * ext_counts[f["key"]] / ext_applicable[f["key"]])
                    if ext_applicable[f["key"]] else 0)}
           for f in _DASH_EXT_FIELDS]
    scored_fields = [e for e in ext if e["applicable"]]
    ext_overall = (round(sum(e["pct"] for e in scored_fields) / len(scored_fields))
                   if scored_fields else 0)
    ext_certainty = {"mean": round(cert_sum / cert_rows) if cert_rows else None, "rows": cert_rows}
    top_companies = sorted(
        ({"name": n, "count": c} for n, c in by_company.items()),
        key=lambda x: -x["count"])[:6]
    status_list = sorted(
        ({"status": s, "count": c, "group": _dash_group(s)} for s, c in by_status.items()),
        key=lambda x: -x["count"])
    type_list = sorted(
        ({"type": t, "count": c} for t, c in by_type.items()),
        key=lambda x: -x["count"])
    # Same shape and same contract as `by_type` — the FULL distribution, not a top-N.
    # Every bar is drillable (the UI links each to /documents?source=…), and truncating
    # would produce bars whose sum silently disagrees with `total`.
    source_list = sorted(
        ({"source": s, "count": c} for s, c in by_source.items()),
        key=lambda x: -x["count"])
    # "Recent" means recent, so it sorts on a real instant — `created_at` (when the row entered
    # INDOX), not on a date STRING. The old key sorted `str(RECEIVED_DATE or DOC_DATE)`
    # lexically, which ranks '31/01/2020' above '01/12/2026' because it compares the DAY first,
    # and ranks the literal 'true' above both. Neither the order nor the printed date survived
    # contact with the real table. `_dash_row_date` supplies the displayed value.
    recent = sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)[:8]
    recent_out = [{"id": r.get("ID"), "name": r.get("NAME"),
                   "status": r.get("STATUS"), "type": r.get("TYPE"),
                   "company": r.get("COMPANY_NAME"),
                   "date": _dash_row_date(r)}
                  for r in recent]

    out = {
        "total": total,
        "completed": groups["done"],
        "attention": groups["attention"],
        "failed": groups["failed"],
        "companies": len(companies),
        "groups": groups,
        "by_status": status_list,
        "by_type": type_list,
        "by_source": source_list,
        "top_companies": top_companies,
        # `scored` is the panel's denominator, and it is part of the payload rather
        # than something the UI re-derives: without it a 73% is unreadable — 73% of
        # what? — and the difference between `scored` and `total` is exactly the
        # in-flight backlog this panel deliberately does not judge. `scored` equals
        # groups["done"] by construction; it is stated separately anyway so the panel
        # never has to reach into another section's number to explain its own.
        "extraction": {"fields": ext, "overall": ext_overall, "certainty": ext_certainty,
                       "scored": ext_scored, "skipped": total - ext_scored},
        "recent": recent_out,
    }
    # Only when a window is actually applied. Without one nothing is excluded,
    # and the all-time payload is the one PERSISTED into `indox_dashboard_stats`
    # — bolting a basis-shaped diagnostic onto the stored read model would put a
    # number there that no longer describes it.
    if since_val is not None:
        excl = _dash_basis_excluded(transport, doc_table, basis)
        if excl is not None:
            out["basis_excluded"] = excl["excluded"]
            out["basis_eligible"] = excl["eligible"]
            out["basis_rows"] = excl["rows"]
    return out


def _dashboard_stats_read(transport, doc_table: str) -> dict | None:
    rows = transport.select(
        schema=_request_schema(), table="indox_dashboard_stats",
        select=["doc_table", "payload", "dirty", "updated_at", "error"],
        filter={"doc_table": doc_table}, limit=1,
    ) or []
    return rows[0] if rows else None


def _dashboard_stats_write(transport, doc_table: str, payload: dict | None,
                           error: str | None, dirty: bool = False) -> None:
    # `payload` is a JSONB column — pass the dict AS-IS. transport.upsert JSON-serializes the
    # whole row itself; pre-serializing here would store a JSON STRING inside the column instead
    # of a JSON OBJECT (`payload->>'total'` would then read null, not 6250 — a scalar string has
    # no keys to extract), which is exactly what the first deploy of this did.
    transport.upsert(
        schema=_request_schema(), table="indox_dashboard_stats", on_conflict="doc_table",
        rows=[{
            "doc_table": doc_table,
            "payload": payload if payload is not None else {},
            "dirty": dirty,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }],
    )


def _dashboard_stats_write_error(transport, doc_table: str, error: str) -> None:
    """A failed recompute records the failure WITHOUT touching `payload` — the row already there
    (the last successful compute) keeps serving reads. Overwriting `payload` on a transient error
    would turn one bad poll into a blank dashboard; leaving `dirty` true means the next tick tries
    again rather than waiting out the full reconcile interval."""
    try:
        transport.update(
            schema=_request_schema(), table="indox_dashboard_stats",
            match={"doc_table": doc_table}, values={"error": error},
        )
    except Exception:
        # the row may not exist yet (very first compute ever failed) — an upsert WOULD wipe
        # nothing in that case since there is nothing to wipe, so it is the correct fallback here
        try:
            transport.upsert(
                schema=_request_schema(), table="indox_dashboard_stats", on_conflict="doc_table",
                rows=[{"doc_table": doc_table, "payload": {}, "dirty": True,
                       "updated_at": datetime.now(timezone.utc).isoformat(), "error": error}],
            )
        except Exception:
            pass


_DASH_STATS_MIN_INTERVAL = 3.0    # never recompute more often than this, however fast writes land
#: Forced from-scratch refresh even when NOT dirty — pure drift repair, since the trigger already
#: keeps `dirty` accurate on every real write (a DB trigger cannot silently miss a write the way a
#: polling loop can). 30 minutes, not 5: measured at 180,000 rows this recompute alone takes
#: several minutes of serial paged reads, so a short reconcile interval means the "drift repair"
#: pass is running back-to-back with itself in practice at that scale, which is pure waste when
#: nothing has actually drifted.
_DASH_STATS_RECONCILE_S = 1800.0
#: Backoff for a pass that FAILED (DGO-63). The loop below is a 1s tick — correct while the database
#: answers, because a dirty row is then picked up within a second. It is wrong when the database is
#: not there at all: every tick pays two failed connections (a DNS lookup that cannot resolve
#: `kong`, then PostgREST) plus two WARNING lines, forever. Measured 2026-10-01 with supabase off:
#: ~2 warning pairs per second, `docker stats` 5-10% of a core on a container nobody is using, and
#: 42-53% before that. A failed pass now waits `_DASH_STATS_BACKOFF_S` doubling up to
#: `_DASH_STATS_BACKOFF_MAX_S`, so an absent dependency costs one attempt a minute instead of one
#: a second — and the first successful pass resets it to the 1s tick, so nothing is slower when the
#: database is up.
_DASH_STATS_BACKOFF_S = 2.0
_DASH_STATS_BACKOFF_MAX_S = 180.0
_dash_stats_thread: threading.Thread | None = None
_dash_stats_stop: threading.Event | None = None


def _dashboard_stats_known_tables() -> list[str]:
    """Every supabase-backed instance's document table — the background loop refreshes ALL of
    them, not only the currently-active one, so switching instances never lands on cold data."""
    try:
        configs = get_default_registry().list()
    except Exception:
        return []
    return sorted({_instance_target(c) for c in configs
                   if c.backend == "supabase" and _instance_target(c)})


#: This background refresher (the sync-stats one retired with sync_item_counts, 2026-09-02) does
#: its real work in the SAME single-process BFF (one gunicorn worker, gthread — see gunicorn.conf.py) as the requests
#: they exist to keep off the request path. At small tables neither pass takes long enough to
#: matter; measured at 180,000 seeded rows, EACH pass alone took several minutes (serial
#: OFFSET-paged reads — the exact cost the spec's "never OFFSET" line warns about, now paid in
#: the background instead of a request, but still real cost) and running BOTH heavy passes at
#: once measurably starved foreground reads (0.5-0.6s ballooned to 1-18s while both churned
#: concurrently). This lock makes the two passes take turns rather than compete — it does not
#: make either pass faster, but it halves the worst-case concurrent load on the shared httpx
#: pool/GIL, which is the lever available without touching gunicorn's worker/thread tuning or
#: the pipeline's own tuned settings. See the module docstring section below for what a real fix
#: (keyset paging + concurrent pages, already the pattern `_collect_items` uses) would take.
_STATS_COMPUTE_LOCK = threading.Lock()


def _dashboard_stats_loop(stop_event: threading.Event) -> None:
    # last_run is keyed (schema, table): the same doc table exists in EVERY instance schema, and
    # a single-table key would let instance one's fresh compute silence instance two's stale one.
    last_run: dict[tuple[str, str], float] = {}
    paid_wait = 0.0
    while not stop_event.is_set():
        try:
            transport = _sync_transport()
            tables = _dashboard_stats_known_tables()
            # One pass per ENABLED instance. This loop runs in a plain thread, where
            # _request_schema() can only ever answer `public` — which is why, before the schema
            # context, "refreshes ALL of them" was true of tables and false of instances: no
            # instance but the first ever got a background refresh.
            for _iid, schema in _stats_target_schemas(transport):
                with _schema_context(schema):
                    dirty_rows = transport.select(
                        schema=_request_schema(), table="indox_dashboard_stats",
                        select=["doc_table", "dirty"],
                    ) or []
                    dirty_by_table = {r["doc_table"]: bool(r.get("dirty")) for r in dirty_rows}
                    now = time.monotonic()
                    for table in tables:
                        last = last_run.get((schema, table), 0.0)
                        if now - last < _DASH_STATS_MIN_INTERVAL:
                            continue
                        dirty = dirty_by_table.get(table, True)  # never-seen table needs its first compute
                        if not dirty and (now - last) < _DASH_STATS_RECONCILE_S:
                            continue
                        try:
                            with _STATS_COMPUTE_LOCK:
                                payload = _compute_dashboard_stats_payload(transport, table)
                                _dashboard_stats_write(transport, table, payload, None)
                        except Exception as exc:  # one bad table must not stop the others, or the loop
                            _log.warning("dashboard-stats refresher: %s.%s failed: %s",
                                         schema, table, exc)
                            try:
                                _dashboard_stats_write_error(transport, table, str(exc))
                            except Exception:
                                pass
                        last_run[(schema, table)] = now
            paid_wait = 0.0            # a completed pass means the database is answering again
        except Exception as exc:
            paid_wait = min(_DASH_STATS_BACKOFF_MAX_S,
                            paid_wait * 2 if paid_wait else _DASH_STATS_BACKOFF_S)
            _log.warning("dashboard-stats refresher: %s (retrying in %.0fs)", exc, paid_wait)
        stop_event.wait(timeout=paid_wait or 1.0)


def start_dashboard_stats_refresher() -> None:
    """Idempotent — mirrors poller.start_polling's one-thread-per-process guard."""
    global _dash_stats_thread, _dash_stats_stop
    if _dash_stats_thread is not None and _dash_stats_thread.is_alive():
        return
    _dash_stats_stop = threading.Event()
    _dash_stats_thread = threading.Thread(
        target=_dashboard_stats_loop, args=(_dash_stats_stop,),
        name="indox-dashboard-stats", daemon=True,
    )
    _dash_stats_thread.start()

#: THE THREE CLASSES. Measured over the last 24h (151,426 stamps):
#:   progress   100,077 (66.1%, 60 labels) — work that moved the document forward
#:   blocked     32,877 (21.7%, 22 labels) — a lane that could not run: another holds the lock
#:   no_action   18,472 (12.2%, 11 labels) — the machine looked and deliberately did nothing
#: Prefix matching on `BLOCKED`/`NO ACTION` rather than an enumerated list, because the label
#: vocabulary grows with the workflows (93 distinct labels in one day) and a new
#: `BLOCKED BY LOCK <new_lane>` must classify correctly the day it first fires, not the day
#: someone remembers to add it here. Anything unrecognised counts as progress — the same
#: default the workflows use, and the honest reading of "a node ran and stamped its name".
_ACTION_CLASSES = ("progress", "blocked", "no_action")


def _action_class(label: str) -> str:
    up = label.upper()
    if up.startswith("BLOCKED"):
        return "blocked"
    if up.startswith("NO ACTION"):
        return "no_action"
    return "progress"


def _csv_arg(raw: object) -> list[str]:
    """`?cls=blocked,no_action` -> ['blocked','no_action']. One value is a one-item list, so a
    caller that sends a scalar (everything before the grid's multi-select existed) is
    unchanged."""
    return [p.strip() for p in str(raw or "").split(",") if p.strip()]


#: Sortable columns -> the key read off one stamp tuple `(ms, seq, label, doc_id, exec)`.
#: `docs` carries the joined document, so NAME/STATUS sort on what the row actually shows
#: rather than on the id behind it. Anything not in here falls back to `ts` — an unknown sort
#: must order the timeline the way it always did, never error and never scramble it.
_ACTION_SORT_KEYS = {
    "ts": lambda s, d: s[0],
    "label": lambda s, d: s[2],
    "cls": lambda s, d: _action_class(s[2]),
    "id": lambda s, d: s[3],
    "name": lambda s, d: (d.get(s[3], {}).get("name") or ""),
    "status": lambda s, d: (d.get(s[3], {}).get("status") or ""),
    # numeric-looking but a TEXT id; sorted as a number when it is one so 999 < 1000, with
    # the missing ones (41% of stamps) sinking to one end instead of interleaving
    "exec": lambda s, d: (int(s[4]) if s[4].isdigit() else -1),
}


#: Rows the coarse pre-filter may pull. 32,506 rows carry a log today, so `all` fits whole;
#: the cap is what stops an ERP-scale table from turning one request into an unbounded read.
_ACTIONS_SCAN_ROWS = int(os.getenv("INDOX_ACTIONS_SCAN_ROWS", "60000"))
#: Stamps RETAINED (the newest N). 24h is ~151k, so a day fits; `month`/`all` (~427k) do not,
#: and say so via `truncated` rather than pretending. Bounds the process's memory at roughly
#: 100 bytes/stamp — labels and document rows are shared references, not copies.
_ACTIONS_MAX = int(os.getenv("INDOX_ACTIONS_MAX", "200000"))
#: Page sizes. Bounded so one request can never be asked to serialise the whole window.
_ACTIONS_LIMIT_DEFAULT = 100
_ACTIONS_LIMIT_MAX = 1000              # raised 2026-08-16: the log page offers 500/1000-row pages
#: Narrow windows re-scan cheaply (≤1,348 rows), so they track the dashboard's 15s poll. The
#: wide ones cost a 13-19 MB read + parse, so one scan a minute is the honest ceiling; paging
#: and filtering are served from the same scan and cost nothing.
_TTL_DASH_ACTIONS = 10.0
_TTL_DASH_ACTIONS_WIDE = 60.0

#: ONE SLOT, deliberately. The panel shows exactly one window at a time, and a retained scan is
#: the largest object this process holds (~20 MB at the cap) — keyed into `_SYNC_SRC_CACHE`,
#: which never evicts, six visited windows would pin six of them for the life of the process.
#: A single slot cannot: switching window (or instance) replaces it. The key still carries the
#: instance AND the table, so a stale scan can never be served under another instance's name —
#: the exact bug `_sync_cached`'s doc comment records.
_ACTIONS_MEMO: dict[str, object] = {"key": None, "expires": 0.0, "value": None}
_ACTIONS_MEMO_LOCK = threading.Lock()


def _actions_cached(key: str, ttl: float, build):
    now = time.monotonic()
    with _ACTIONS_MEMO_LOCK:
        if _ACTIONS_MEMO["key"] == key and float(_ACTIONS_MEMO["expires"] or 0) > now:
            return _ACTIONS_MEMO["value"]
    value = build()  # built outside the lock: it does network I/O
    with _ACTIONS_MEMO_LOCK:
        _ACTIONS_MEMO.update(key=key, expires=now + ttl, value=value)
    return value


# [2026-08-21] _actions_scan REMOVED with the ACTION_LOG column it parsed. It walked every
# document's cumulative log string, pulled ', <label>, <ts>, <exec>' stamps out of it, and merged
# them into one timeline -- 108 lines of parser, a 6,000-char middle-trim to apologise for, and an
# `unparsed` counter for the timestamp-shaped tokens it could not attribute to an action. The
# router's dispatch-bracket table answers the same question in rows: see _actions_scan_pg, which
# has been the default source since 2026-08-16 and is now the only one.

# ── LIVE ACTION LOG — the dispatch-bracket table (owner order 2026-08-16, pg since ~12:xx) ──
#
# The Action Router's `Log Action Start` / `Log Action End` postgres nodes bracket every real
# dispatch with ONE ROW per (document, action, execution) in
# public.indox_action_execution_log: Start INSERTs (ON CONFLICT DO NOTHING), End UPSERTs
# `ENDED_AT`. A row without `ENDED_AT` is a dispatch in flight or one whose execution died
# between the brackets. Only REAL dispatches appear (no no_action verdicts, no BLOCKED stamps
# — those never reach the dispatcher). The execution id is in the PRIMARY KEY on purpose:
# a second completed row for the same (doc, action) is a real double-run, surfaced loudly.
_ACTIONS_PG_TABLE = "indox_action_execution_log"
_ACTIONS_PG_MAX_ROWS = 250_000                  # a full day at ~6,300 dispatches/h is ~151k rows
_ACTIONS_LIVE_CACHE_S = 10                      # one read serves every poll in a 10s window
_actions_redis_cli = None


# ── TIMELINE PROJECTION — INDOX as concurrency spans (GET /timeline/spans) ──────────────────
#
# Read by any-concurrency's `SPAN_SOURCE_INDOX` lane. Three row families, one `svcid` vocabulary:
# EVERY span carries the document id, so one search box entry on the timeline collapses all
# three families to a single document. That is the whole point of the section.

_TIMELINE_ROWS = ("doc", "action", "sync")
_TIMELINE_LIMIT_DEFAULT = 20_000
_TIMELINE_LIMIT_MAX = 60_000
_TIMELINE_MAX_HOURS = 24 * 14
#: How far behind `?since` a delta poll still re-reads, so a bracket that OPENED before the
#: cursor and CLOSES now is still reported. See the endpoint for why this is safe to bound.
_TIMELINE_DELTA_LOOKBACK_S = float(os.getenv("INDOX_TIMELINE_DELTA_LOOKBACK_S", "3600") or 3600)

#: An open dispatch bracket older than this never closed — the execution died between
#: `Log Action Start` and `Log Action End`. Sized off the doc-step lock TTL (10 min), doubled,
#: so a merely slow action is not libelled as dead.
_TIMELINE_DEAD_BRACKET_S = float(os.getenv("INDOX_TIMELINE_DEAD_BRACKET_S", "1200") or 1200)

#: Document STATUS -> (timeline status, is the document still moving?).
#:
#: DELIBERATELY NOT `_dash_group`. The dashboard asks "does a human need to act on this?"; a
#: timeline asks "is this document still moving?" — and the two disagree on exactly the rows that
#: matter here. `IN_PROGRESS` is `other` to the dashboard (not actionable) but is the definition
#: of moving; `ACTION_RESTART` is `attention` there but is the state the driver re-dispatches
#: from, i.e. moving too. Anything unlisted is treated as parked: closed, grey, no claim made.
_TIMELINE_DOC_STATUS = {
    "COMPLETED":        ("success", False),
    "EXTRACTION_FAILED": ("error",  False),
    "MAX_ITERATIONS":   ("error",   False),
    # still moving — the span stays OPEN and the timeline draws its live right edge
    "IN_PROGRESS":      ("running", True),
    "TO_EXTRACT":       ("running", True),
    "ACTION_RESTART":   ("running", True),
    # at rest for good: resolved, superseded or unusable. Grey, closed, not a failure.
    "OLD":              ("unknown", False),
    "MERGED":           ("unknown", False),
    "GARBAGE":          ("unknown", False),
    "DOUBLE":           ("unknown", False),
    "MISSING_LINK":     ("unknown", False),
}


def _timeline_ms(raw: object) -> int | None:
    """One PostgREST timestamptz -> epoch ms. None on anything unparseable."""
    if not raw:
        return None
    try:
        return int(datetime.fromisoformat(str(raw)).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _timeline_doc_spans(transport, doc_table: str, since_iso: str, limit: int,
                        delta: bool, truncated: list[str]) -> list[dict]:
    """One span per DOCUMENT — the `מסמך` row: created_at -> the moment it stopped moving.

    The window cuts on `created_at` (when the document entered INDOX) but a delta poll cuts on
    `updated_at`, because a delta's job is "what CHANGED since the cursor" and a document that
    arrived yesterday and completed a second ago changed a second ago.
    """
    col = "updated_at" if delta else "created_at"
    rows = _paged_select(
        transport, table=doc_table,
        select=["ID", "NAME", "STATUS", "TYPE", "SOURCE_TYPE", "created_at", "updated_at"],
        order_col=col, max_rows=limit,
        filter={col: {"op": "gte", "value": since_iso}},
    ) or []
    if len(rows) >= limit:
        truncated.append("doc")
    out = []
    for r in rows:
        s_ms = _timeline_ms(r.get("created_at"))
        if s_ms is None:
            continue
        status = str(r.get("STATUS") or "")
        st, moving = _TIMELINE_DOC_STATUS.get(status.upper(), ("unknown", False))
        doc_id = str(r.get("ID") or "")
        name = str(r.get("NAME") or "") or doc_id
        out.append({
            "id": f"doc:{doc_id}", "svc": "מסמך", "svcid": doc_id,
            "label": name, "status": st,
            "s": s_ms, "e": None if moving else (_timeline_ms(r.get("updated_at")) or s_ms),
            "meta": {"doc": doc_id, "name": name, "docStatus": status,
                     "type": r.get("TYPE") or "", "source": r.get("SOURCE_TYPE") or ""},
        })
    return out


def _timeline_action_spans(transport, since_iso: str, limit: int,
                           truncated: list[str]) -> list[dict]:
    """One span per DISPATCH — the `פעולה · <ACTION>` rows, straight off the bracket table.

    ⚠ A closed bracket proves the dispatch RAN TO COMPLETION, not that it SUCCEEDED: this table
    has no result column (`DOC_STATUS` is the document's status at dispatch time). So `success`
    here means "the router closed the bracket" and nothing stronger. An unclosed bracket older
    than the doc-step lock TTL is the one case that IS a failure — the execution died between
    Log Action Start and Log Action End — and is reported as such.
    """
    rows = _paged_select(
        transport, table=_ACTIONS_PG_TABLE,
        select=["ID", "ACTION", "EXECUTION_ID", "NAME", "DOC_STATUS", "TRIGGER",
                "ORIGIN_EXECUTION", "STARTED_AT", "ENDED_AT"],
        order_col="STARTED_AT", max_rows=limit,
        filter={"STARTED_AT": {"op": "gte", "value": since_iso}},
    ) or []
    if len(rows) >= limit:
        truncated.append("action")
    dead_ms = int(time.time() * 1000) - int(_TIMELINE_DEAD_BRACKET_S * 1000)
    out = []
    for r in rows:
        s_ms = _timeline_ms(r.get("STARTED_AT"))
        if s_ms is None:
            continue
        e_ms = _timeline_ms(r.get("ENDED_AT"))
        doc_id = str(r.get("ID") or "")
        action = str(r.get("ACTION") or "?")
        name = str(r.get("NAME") or "") or doc_id
        if e_ms is not None:
            st = "success"
        elif s_ms < dead_ms:
            st = "error"           # never closed, and too old to still be in flight
        else:
            st = "running"
        out.append({
            "id": f"act:{doc_id}:{action}:{r.get('EXECUTION_ID') or ''}",
            "svc": f"פעולה · {action}", "svcid": doc_id,
            "label": f"{action} · {name}", "status": st,
            "s": s_ms, "e": e_ms,
            "meta": {"doc": doc_id, "name": name, "action": action,
                     "execution": r.get("EXECUTION_ID") or "",
                     "docStatus": r.get("DOC_STATUS") or "",
                     "trigger": r.get("TRIGGER") or "",
                     "origin": r.get("ORIGIN_EXECUTION") or ""},
        })
    return out


def _timeline_sync_spans(transport, since_iso: str, limit: int,
                         truncated: list[str]) -> list[dict]:
    """One span per SYNCED ITEM — the `סנכרון · <pipe>` rows, from the ledger's claim bracket.

    Two reads, not one: a claim that has not yet delivered has `delivered_at IS NULL`, so a single
    filter on `delivered_at` would show only the successes — the deliveries in flight, and any
    claim whose worker died, would be invisible. That is precisely the population this row exists
    to make visible, so `claimed_at` is read as well and the two are merged on the ledger key.
    """
    by_key: dict[tuple, dict] = {}
    for col in ("delivered_at", "claimed_at"):
        rows = _paged_select(
            transport, table="sync_ledger",
            select=["source", "platform_id", "status", "doc_id", "claimed_at", "delivered_at"],
            order_col=col, max_rows=limit,
            filter={col: {"op": "gte", "value": since_iso}},
        ) or []
        if len(rows) >= limit:
            truncated.append(f"sync:{col}")
        for r in rows:
            by_key[(r.get("source"), r.get("platform_id"))] = r
    out = []
    for (source, platform_id), r in by_key.items():
        claimed = _timeline_ms(r.get("claimed_at"))
        delivered = _timeline_ms(r.get("delivered_at"))
        s_ms = claimed if claimed is not None else delivered
        if s_ms is None:
            continue
        led = str(r.get("status") or "")
        doc_id = str(r.get("doc_id") or "")
        if led == "delivered" or delivered is not None:
            st = "success"
        elif led in ("needs_review", "quarantined"):
            st = "error"
        else:
            st = "running"
        out.append({
            "id": f"sync:{source}:{platform_id}",
            "svc": f"סנכרון · {source or '?'}", "svcid": doc_id or str(platform_id or ""),
            "label": f"{source or '?'} · {doc_id or platform_id}", "status": st,
            "s": s_ms, "e": delivered,
            "meta": {"doc": doc_id, "pipe": source or "", "platformId": platform_id or "",
                     "ledgerStatus": led},
        })
    return out


def _actions_redis():
    """Lazy singleton client for the stack's one redis (the n8n queue redis). Import stays
    inside so a missing lib degrades this endpoint alone, never the app's import."""
    global _actions_redis_cli
    if _actions_redis_cli is None:
        import redis  # lazy
        _actions_redis_cli = redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            db=int(os.environ.get("REDIS_DB", "0")),
            decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _actions_redis_cli


def _actions_scan_pg(since_iso: str | None) -> dict:
    """public.indox_action_execution_log rendered in `_actions_scan`'s contract — stamps
    newest-first plus the counting fields — with two extras appended to each tuple:
    `dur_s` (STARTED_AT→ENDED_AT seconds, None while running) and `done`. ONE ROW PER
    (doc, action, execution) straight off the primary key, no collapsing (owner decision):
    a second completed row for the same (doc, action) is a real double-run, and surfacing
    it is this log's job. The window cut happens server-side on STARTED_AT."""
    transport = _sync_transport()
    rows = _paged_select(
        transport, table=_ACTIONS_PG_TABLE,
        select=["ID", "ACTION", "EXECUTION_ID", "NAME", "DOC_STATUS",
                "STARTED_AT", "ENDED_AT"],
        order_col="STARTED_AT", max_rows=_ACTIONS_PG_MAX_ROWS,
        filter=({"STARTED_AT": {"op": "gte", "value": since_iso}}
                if since_iso is not None else None),
    ) or []

    heap: list[tuple] = []
    docs: dict[str, dict] = {}
    seq = 0
    malformed = 0
    for r in rows:
        if not isinstance(r, dict):
            malformed += 1
            continue
        doc_id = str(r.get("ID") or "")
        action = str(r.get("ACTION") or "")
        try:
            st = datetime.fromisoformat(str(r.get("STARTED_AT")))
            ms = int(st.timestamp() * 1000)
        except (TypeError, ValueError):
            malformed += 1
            continue
        if not doc_id or not action:
            malformed += 1
            continue
        ended = r.get("ENDED_AT")
        dur_s = None
        if ended:
            try:
                dur_s = round((datetime.fromisoformat(str(ended)) - st).total_seconds(), 1)
            except (TypeError, ValueError):
                dur_s = None
        done = bool(ended)
        if doc_id not in docs:
            docs[doc_id] = {"id": doc_id, "name": str(r.get("NAME") or ""),
                            "status": str(r.get("DOC_STATUS") or "")}
        # label = the CLEAN action name, always (owner ruling): started-vs-finished lives in
        # the dur_s/done fields (the משך column), never glued onto the action.
        seq += 1
        heap.append((ms, seq, action, doc_id,
                     str(r.get("EXECUTION_ID") or ""), dur_s, done))

    stamps = sorted(heap, reverse=True)
    labels: dict[str, int] = {}
    classes = {c: 0 for c in _ACTION_CLASSES}
    for s in stamps:
        labels[s[2]] = labels.get(s[2], 0) + 1
        classes[_action_class(s[2])] += 1
    label_list = sorted(
        ({"label": k, "cls": _action_class(k), "count": v} for k, v in labels.items()),
        key=lambda x: (-x["count"], x["label"]),
    )
    return {
        "stamps": stamps,
        "docs": docs,
        "window_total": len(stamps),
        "retained": len(stamps),
        "truncated": False,                      # everything in the window is retained
        "labels": label_list,
        "classes": classes,
        "scanned_rows": len(rows),               # here: table rows read, not documents
        "rows_capped": len(rows) >= _ACTIONS_PG_MAX_ROWS,
        "ts_tokens": len(rows),
        "stamps_parsed": len(rows) - malformed,
        "unparsed": malformed,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


# The month-navigation bucketing rule now has ONE owner, `core.month_key`, because the
# INDEX (this module) and the FILTER (a `documents/query` clause the DATABASE evaluates)
# have to agree and did not. `_month_key_of` accepted both live DOC_DATE shapes — ISO and
# `D/M/YY(YY)` — while clicking a chip sent `{op:'startswith', value:'YYYY-MM'}`, a raw
# string prefix only the ISO shape can match. Measured 2026-08-11 on the live corpus: chip
# `אוקטובר 2026` advertised 38 documents, the grid rendered 3. `core.month_key` renders the
# same rule as Python (here) or as a POSIX regex (the supabase backend's `month` operator),
# so the two halves cannot drift again. See final-indox.md B21/B22/B23 for the trail.
_month_key_of = month_key_of


def _run_one_lane(base_url: str, suite_key: str, lane: str, budget_s: int) -> dict:
    """Fire ONE suite-lane webhook and parse its Assert-node verdicts into a
    TestCaseResult-shaped dict. Mirrors apps/indox/hooks/test.py :func:`run_lane`:
    the webhook response IS the lane verdict — a JSON array of items, each with a
    ``result:"PASS…"``/``"FAIL…"`` string; the lane passes iff every result says PASS."""
    import time as _time
    import httpx  # lazy

    cfg = _N8N_TEST_SUITES[suite_key]
    url = f"{base_url}/{cfg['webhook']}"
    t0 = _time.time()
    try:
        with httpx.Client(timeout=float(budget_s) + 30.0) as c:
            resp = c.post(url, json={"lane": lane})
            resp.raise_for_status()
            items = resp.json()
        if isinstance(items, dict):
            items = [items]
        results = [
            str((i.get("json", i) or {}).get("result", ""))
            for i in items
            if isinstance(i, dict) and (i.get("json", i) or {}).get("result") is not None
        ]
        ok = bool(results) and all("PASS" in r for r in results)
        if not results:
            failed_assertions = [
                {"name": lane, "expected": "PASS", "actual": "no assert output", "operator": "contains"}
            ]
        else:
            failed_assertions = [
                {"name": lane, "expected": "PASS", "actual": r[:200], "operator": "contains"}
                for r in results
                if "PASS" not in r
            ]
        return {
            "suite": suite_key,
            "name": lane,
            "status": "passed" if ok else "failed",
            "passed": ok,
            "assertions_passed": sum(1 for r in results if "PASS" in r),
            "assertions_total": len(results),
            "duration_s": round(_time.time() - t0, 1),
            "failed_assertions": failed_assertions,
        }
    except Exception as e:  # transport / timeout / non-2xx — surface as a failed case
        return {
            "suite": suite_key,
            "name": lane,
            "status": "error",
            "passed": False,
            "assertions_passed": 0,
            "assertions_total": 0,
            "duration_s": round(_time.time() - t0, 1),
            "failed_assertions": [
                {"name": lane, "expected": "PASS", "actual": f"transport: {e}"[:200], "operator": "contains"}
            ],
        }


def _append_case(run_id: str, case: dict) -> None:
    """Thread-safe: record one completed lane and bump live progress counters."""
    with _TEST_RUNS_LOCK:
        run = _TEST_RUNS.get(run_id)
        if run is None:
            return
        run["per_case"].append(case)
        run["cases_done"] = len(run["per_case"])
        if case.get("passed"):
            run["passed"] = run.get("passed", 0) + 1
        else:
            run["failed"] = run.get("failed", 0) + 1


def _run_tests_bg(run_id: str, suite_keys: list[str]):
    """Background worker: fire every lane of every requested suite CONCURRENTLY,
    updating per-case progress as each lane returns. Never raises."""
    import concurrent.futures

    base = _n8n_webhook_base()
    work = [
        (k, lane, _N8N_TEST_SUITES[k]["budget_s"])
        for k in suite_keys
        for lane in _N8N_TEST_SUITES[k]["lanes"]
    ]
    try:
        # Cap concurrency: each lane is a heavy E2E n8n execution (real OCR/processing),
        # and on a constrained host too many at once starves them → a doc doesn't finish
        # processing before its assertion runs (contention-flaky: proc-gmail-link "rows 0 != 1",
        # pipeline "bare" empty webhook response). Use the MIN per-suite `conc` across the run
        # (extraction suites cap at 2, light sync suites at 4); env can override globally.
        suite_conc = min((_N8N_TEST_SUITES[k].get("conc", 4) for k in suite_keys), default=4)
        env_cap = os.getenv("INDOX_TEST_LANE_CONCURRENCY")
        try:
            cap = int(env_cap) if env_cap else suite_conc
        except ValueError:
            cap = suite_conc
        cap = max(1, cap)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(cap, len(work) or 1)
        ) as ex:
            futs = [ex.submit(_run_one_lane, base, k, lane, b) for (k, lane, b) in work]
            for f in concurrent.futures.as_completed(futs):
                _append_case(run_id, f.result())
    except Exception as e:  # pool/setup failure — never crash the thread
        with _TEST_RUNS_LOCK:
            run = _TEST_RUNS.get(run_id)
            if run is not None:
                run.update({"status": "error", "finished": _now_iso(), "error": str(e)})
        return
    with _TEST_RUNS_LOCK:
        run = _TEST_RUNS.get(run_id)
        if run is None:
            return
        run["status"] = "done"
        run["finished"] = _now_iso()
        # per-suite last-run summary → drives the suite-list meters
        by_suite: dict[str, list] = {}
        for c in run["per_case"]:
            by_suite.setdefault(c["suite"], []).append(c)
        for k, cases in by_suite.items():
            _TEST_LAST[k] = {
                "case_count": len(cases),
                "cases_passed": sum(1 for c in cases if c.get("passed")),
                "all_passed": all(c.get("passed") for c in cases),
                "last_run": run["finished"],
            }


def _build_openapi(prefix: str) -> dict:
    """Hand-rolled, dependency-free OpenAPI 3.0 spec for the webapp client.

    We deliberately don't pull in `apispec` — the surface is small and
    stable enough that a hand-written spec is easier to keep accurate.
    """
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Incoming Documents API",
            "version": "1.0.0",
            "description": "Repository registry + batch upsert + SSE event tail.",
        },
        "servers": [{"url": prefix}],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Liveness probe",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/auth/me": {
                "get": {
                    "summary": "Authentik ForwardAuth identity",
                    "responses": {"200": {"description": "identity"}},
                }
            },
            "/repos": {
                "get": {
                    "summary": "List all repos",
                    "responses": {"200": {"description": "list"}},
                },
                "post": {
                    "summary": "Provision a new repo",
                    "requestBody": {"required": True},
                    "responses": {
                        "201": {"description": "created"},
                        "409": {"description": "duplicate"},
                    },
                },
            },
            "/repos/{repo}": {
                "get": {
                    "summary": "Get a repo config",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "ok"}, "404": {"description": "not found"}},
                },
                "delete": {
                    "summary": "Delete a repo from the registry",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
            },
            "/repos/{repo}/stats": {
                "get": {
                    "summary": "Repo stats (row count, columns, kafka flag)",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/repos/{repo}/documents": {
                "put": {
                    "summary": "Batch upsert documents",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/repos/{repo}/documents/query": {
                "post": {
                    "summary": "Paginated document query",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/repos/{repo}/documents/month-index": {
                "post": {
                    "summary": "Real server-side aggregate: row count per YYYY-MM of a date column",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/repos/{repo}/documents/{id}": {
                "get": {
                    "summary": "Get a single document",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "ok"}, "404": {"description": "not found"}},
                },
                "patch": {
                    "summary": "Patch a single document",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "ok"}},
                },
            },
            "/repos/{repo}/documents/{id}/history": {
                "get": {
                    "summary": "Kafka event history for a single document",
                    "parameters": [
                        {"name": "repo", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            # Instances — the Drive/Mail/Chat "connected accounts" contract over
            # the existing multi-repo model. Selecting an instance scopes the
            # TABLE; it does not yet scope /config/* or /sync/registry (single
            # global tables on this stack).
            "/accounts": {
                "get": {
                    "summary": "List INDOX instances (one per registered repo) + the active one",
                    "responses": {"200": {"description": "{accounts:[…], active}"}},
                }
            },
            "/account/select": {
                "post": {
                    "summary": "Make an instance active (persisted beside the repo registry)",
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "{active, account}"},
                                  "404": {"description": "unknown instance"}},
                }
            },
            "/account/add": {
                "post": {
                    "summary": "Provision a new instance (same provisioner as POST /repos)",
                    "requestBody": {"required": True},
                    "responses": {"201": {"description": "{account, accounts, active}"},
                                  "400": {"description": "bad spec"}},
                }
            },
            "/account/remove": {
                "post": {
                    "summary": "De-register an instance (the backing table is NOT dropped)",
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "{accounts, active}"},
                                  "400": {"description": "last remaining instance"},
                                  "404": {"description": "unknown instance"}},
                }
            },
            "/account/detail": {
                "get": {
                    "summary": "Everything the active instance owns (switcher details panel)",
                    "responses": {"200": {"description": "{account, repo, target, columns, registry, settings, counts}"},
                                  "404": {"description": "no instance registered"}},
                }
            },
            "/sync/status": {
                "get": {
                    "summary": "Proxy n8n INDOX manage webhook STATUS (live per-sync counts)",
                    "parameters": [
                        {"name": "sync", "in": "query",
                         "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "status or {reachable:false}"}},
                }
            },
            "/sync/registry": {
                "get": {
                    "summary": "settings.sync_registry parsed to JSON",
                    "responses": {"200": {"description": "{registry:[…], reachable}"}},
                }
            },
            "/config/settings": {
                "get": {
                    "summary": "All settings key/value rows",
                    "responses": {"200": {"description": "{settings:[…], editable_keys, reachable}"}},
                }
            },
            "/config/settings/{key}": {
                "put": {
                    "summary": "Upsert a single allowlisted settings row",
                    "parameters": [
                        {"name": "key", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "requestBody": {"required": True},
                    "responses": {"200": {"description": "updated row"},
                                  "400": {"description": "key not editable / bad body"}},
                }
            },
            "/config/companies": {
                "get": {
                    "summary": "All companies rows (SELECT *)",
                    "responses": {"200": {"description": "{companies:[…], reachable}"}},
                }
            },
            "/tests/suites": {
                "get": {
                    "summary": "List INDOX n8n E2E test suites (sync + state machine) + last-run summary",
                    "responses": {"200": {"description": "{suites:[…], groups, reachable}"}},
                }
            },
            "/tests/run": {
                "post": {
                    "summary": "Start a suite run (or all suites); returns {run_id}",
                    "requestBody": {"required": False},
                    "responses": {"200": {"description": "{run_id}"}},
                }
            },
            "/tests/run/{run_id}": {
                "get": {
                    "summary": "Live progress of a test run",
                    "parameters": [
                        {"name": "run_id", "in": "path", "required": True,
                         "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "progress object"},
                                  "404": {"description": "unknown run"}},
                }
            },
        },
    }


# ===========================================================================
# INDOX sync control plane (סנכרון) — the server half of the sync page.
#
# The full design is apps/indox/indox solution.md (§ Sync). Three rules run
# through everything below:
#
#   1. STATE LIVES IN OUR DB. One row per external item in `sync_ledger` (the
#      "sync item": discovered → claimed → delivered | failed | needs_review),
#      written only by the Sync Item API workflow (syncLedgerApi01). Folders and
#      labels in the source are user-visible MARKS that delivery may leave
#      behind; nothing here reads them to decide state.
#
#   2. THE REGISTRY IS `settings.sync_registry`. Every registry mutation is a
#      read-modify-write of that one row. No parallel store.
#
#   3. THIS BFF TALKS TO NO OTHER APP. Counts come from the `sync_item_counts`
#      view; run / retry go to n8n's manage door (SyncApi0000000001). Pickers
#      for folders, labels and connections are the browser's business, against
#      the sibling apps under the console shell.
# ===========================================================================

#: windowed /dashboard/stats aggregates (win != all) — computed live per
#: request rather than by the read-model loop, so a short cache absorbs the
#: dashboard's 15s poll (and several viewers) without hiding fresh arrivals
#: for longer than one poll interval.
_TTL_DASH_WIN = 10.0
#: This process's OWN short-TTL memo (dashboard window aggregates, settings reads). In-process,
#: and every builder reads OUR database — never another app (owner rule 2026-09-02).
_SYNC_SRC_CACHE: dict[str, tuple[float, object]] = {}
_SYNC_SRC_LOCK = threading.Lock()


def _sync_cached(key: str, ttl: float, build):
    """Memoize `build()` under `key` for `ttl` seconds (monotonic clock). The build runs OUTSIDE
    the lock so a slow aggregate never serialises unrelated readers."""
    now = time.monotonic()
    with _SYNC_SRC_LOCK:
        hit = _SYNC_SRC_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _SYNC_SRC_LOCK:
        _SYNC_SRC_CACHE[key] = (now + ttl, value)
    return value


def _sync_cache_clear(prefix: str = "") -> None:
    """Drop this process's memo for the CURRENT schema after a write. Since 2026-09-02 the sync
    board itself reads the sync_item_counts view directly, so this only ever clears the small
    dashboard/settings memo — a mutation in one tenant never cold-starts another's."""
    full = f"{_request_schema()}\x00{prefix}"
    with _SYNC_SRC_LOCK:
        for k in [k for k in _SYNC_SRC_CACHE if k.startswith(full) or k.startswith(prefix or "\x01")]:
            _SYNC_SRC_CACHE.pop(k, None)


def _sync_transport():
    from ..backends.supabase_transport import HttpxSupabaseTransport

    return HttpxSupabaseTransport()


# ----- the one source-of-truth row ----------------------------------------


def _read_sync_registry(transport) -> list[dict]:
    """`settings.sync_registry` parsed to a list. Raises on an unreachable
    supabase — every caller turns that into its own degraded envelope."""
    rows = transport.select(
        schema=_request_schema(), table="settings", select=["key", "value"],
        filter=_tenant({"key": "sync_registry"}), limit=1,
    )
    value = rows[0].get("value") if rows else None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = []
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def _write_sync_registry(transport, entries: list[dict]) -> None:
    """Write the row back. TEXT column, so the list is serialized exactly the way
    `_coerce_settings_value` already serializes structured settings values."""
    # Normalise on the way out, not on the way in: EVERY write goes through here,
    # so this is the one gate that cannot be bypassed by a new endpoint. It also
    # means the five live rows — which predate `enabled`, `fallback_type` and the
    # sim's pair names — are repaired by the first save that touches the registry,
    # without a migration step anyone has to remember to run.
    for e in entries:
        _normalise_entry(e)
    transport.upsert(
        schema=_request_schema(), table="settings", on_conflict="instance,key",
        rows=[{"instance": _instance(), "key": "sync_registry",
               "value": json.dumps(entries, ensure_ascii=False)}],
    )
    _sync_cache_clear()


def _find_entry(registry: list[dict], name: str) -> dict | None:
    return next((e for e in registry if str(e.get("name") or "") == name), None)


# ---------------------------------------------------------------------------
# _normalise_entry() — the registry has TWO vocabularies for the same pipe, and
# this is the only place that is allowed to know both.
#
# A drive pipe names its folders twice over:
#
#   sim / webapp editor : pairs[] = {from, to}     (+ dest_folder, failed_folder)
#   sync-v3 engine      : pairs[] = {to_sync, in_progress, synced, failed}
#
# `syncV3Main0001`'s Build Units reads `p.to_sync` and `p.synced`; the editor
# writes `p.from` and `p.to`; `LocationLine` renders `p.from`/`p.to`. So the two
# halves have been talking past each other in BOTH directions: the five live rows
# carry only the engine names, so the UI drew every drive pipe as
# "תיקייה — → —", and a pipe authored through the editor carries only the sim
# names, so the engine resolved `folderId: undefined` and listed nothing. A pipe
# you configured and a pipe you could see were disjoint sets.
#
# The fix belongs HERE rather than in the editor or the engine. The BFF is the
# only component both of them go through, so normalising on write is what makes
# "the registry is the whole contract" true: the row that lands in
# `settings.sync_registry` always carries both spellings, and neither side has to
# learn the other's. Do NOT push this into the webapp (the sim is read-only
# reference and must keep its own names) or into n8n (a second normaliser is how
# the two drift apart — the same argument as `_scope`).
#
# It also fills the fields the live rows predate, so that "absent" stops being a
# silently-defaulted behaviour:
#   enabled       absent means enabled — the engine already assumes it, so say it
#   fallback_type what to write when extraction cannot classify. NOT type_hint:
#                 type_hint is a guess about the source, fallback_type is a
#                 decision about the output (sim ALIGNMENT-CHANGELOG §379). They
#                 were being written from a single editor field, which made the
#                 more consequential of the two unreachable.
# ---------------------------------------------------------------------------
#: pairs[]: sim/editor name -> engine name. Both are written; neither is dropped.
_PAIR_ALIASES = (("from", "to_sync"), ("to", "synced"), ("failed_to", "failed"))


def _normalise_entry(entry: dict) -> dict:
    """Fill an entry's second vocabulary in place, and return it.

    Idempotent, and never overwrites a value that is already set — a row that
    already carries both names comes back untouched, so re-normalising an
    existing registry cannot change what the engine reads.
    """
    if not isinstance(entry, dict):
        return entry

    pairs = entry.get("pairs")
    if isinstance(pairs, list):
        for p in pairs:
            if not isinstance(p, dict):
                continue
            for sim_key, engine_key in _PAIR_ALIASES:
                a, b = p.get(sim_key), p.get(engine_key)
                if a and not b:
                    p[engine_key] = a
                elif b and not a:
                    p[sim_key] = b

    # `enabled` is load-bearing: syncV3Main0001 and SyncScanner00001 both skip on
    # `enabled === false` and both treat absent as enabled. Writing it explicitly
    # means the pause control's state is readable from the row itself.
    if entry.get("enabled") is None:
        entry["enabled"] = True

    # ── ONE DECLARED TYPE, ONE STRENGTH ────────────────────────────────────────────────────
    # `type_hint`, `fallback_type` and `type_authority` were three fields answering one
    # question — what does this location say its documents are, and how much is that worth —
    # and the operator had to know which of the three to reach for. They collapse to a VALUE
    # (`type_hint`) and a STRENGTH (`type_authority`), lowest first:
    #   'fallback'  used only when neither engine classified the document (scores 0 in the
    #               base selector's vote, so it can never outrank a real reading). This is
    #               exactly what a lone `fallback_type` has always meant.
    #   'hint'      votes beside the two engines and can break their disagreement.
    #   'decisive'  the location settles it and outranks both.
    # `fallback_type` stays in storage as a MIRROR — the sync board's one-click reclassify and
    # /sync/<name>/reclassify still read it — and is no longer separately editable.
    #
    # Idempotent and non-destructive, like everything else here. A legacy entry whose two
    # values genuinely DIFFER (hint INVOICE, fallback RECEIPT) is the one case the unified
    # model cannot spell, so it is left exactly as it was rather than silently collapsed; no
    # live pipe has ever carried such a pair.
    hint = str(entry.get("type_hint") or "").strip()
    fallback = str(entry.get("fallback_type") or "").strip()
    if not hint and fallback:
        # a fallback with no hint IS the 'fallback' strength — that is what it always meant
        entry["type_hint"] = fallback
        entry.setdefault("type_authority", "fallback")
        hint = fallback
    if hint and not str(entry.get("type_authority") or "").strip():
        # a hint written before the strength existed means what it meant then: a hint
        entry["type_authority"] = "hint"
    if "fallback_type" not in entry:
        entry["fallback_type"] = entry.get("type_hint")

    return entry


# _default_processor was deleted 2026-08-31 with the proc retirement: it minted the v1
# processor names for Console-authored pipes ("thin mode is test-only" — inverted since).
# Every sync is thin; processor_wf is refused by _validate_sync_entry, not defaulted.


def _validate_sync_entry(entry: dict, *, require_complete: bool) -> None:
    """Reject ambiguous or incomplete registry rows before they reach sync-v3."""
    source = str(entry.get("source") or "drive").lower()
    if source not in {"drive", "gmail"}:
        raise ValidationError(f"unsupported sync source '{source}'")

    # `type_authority` says how much `type_hint` is worth to SelectBase01's type vote:
    # 'fallback' only when nothing classified the document, 'hint' beside the two extraction
    # engines, 'decisive' above both. Absent reads as 'hint', which is what every entry written
    # before 2026-08-31 means — so this validates the SPELLING and refuses nothing that already
    # exists. It is checked rather than shrugged off because the selector compares the string
    # literally: a typo'd 'decisiv' would silently degrade to a hint and look like the feature
    # simply not working.
    authority = str(entry.get("type_authority") or "").strip().lower()
    if authority and authority not in {"fallback", "hint", "decisive"}:
        raise ValidationError(
            "type_authority must be 'fallback', 'hint' or 'decisive' "
            f"(got '{entry.get('type_authority')}')")
    if authority and not str(entry.get("type_hint") or "").strip():
        raise ValidationError(
            f"type_authority '{authority}' needs a type_hint — {authority} about what?")
    if require_complete and not str(entry.get("connection") or "").strip():
        raise ValidationError("a production sync entry needs a connection")
    if str(entry.get("engine") or "") == "v3" and require_complete:
        # THIN IS THE ONLY MODE (proc RETIRED 2026-08-31: the v1 processors and Deliver's proc
        # branch are gone). The engine still derives mode from these fields --
        #     mode = s.v3_mode || (s.processor_wf ? 'proc' : 'thin')   [syncV3Main0001]
        # -- and Deliver answers proc with a recorded refusal, so an entry that names either
        # would be born broken: every delivery refused, loudly, forever. The config plane
        # refuses the REGISTRATION instead, at write time, where the operator can act on it.
        _mode = str(entry.get("v3_mode") or "").strip().lower()
        if _mode == "proc" or str(entry.get("processor_wf") or "").strip():
            raise ValidationError(
                "the processor path is retired (2026-08-31): every sync is thin — remove "
                "processor_wf / v3_mode 'proc' from this entry")
        # PROJECTION STAYS REQUIRED: with one mode there is exactly one meaning
        # (`projection==='on'`), but an unset value still hides the operator's intent, and the
        # historical proc reading was the OPPOSITE default — keep the question explicit.
        if entry.get("projection") not in {"on", "off"}:
            raise ValidationError(
                "a production v3 sync entry needs projection 'on' or 'off' — say which you mean")

    if source == "gmail":
        # OWNER RULE (2026-09-02): a pipe needs its SOURCE tag and nothing else. `synced` /
        # `failed` are user-visible marks the state machine's feedback writes — optional.
        labels = entry.get("labels")
        if require_complete and (not isinstance(labels, dict)
                                 or not str(labels.get("to_sync") or "").strip()):
            raise ValidationError("a gmail sync entry needs a to_sync label (the tag it watches)")
        return

    pairs = entry.get("pairs")
    if require_complete and (not isinstance(pairs, list) or not pairs):
        raise ValidationError("a drive sync entry needs at least one folder pair")
    for pair in pairs or []:
        if not isinstance(pair, dict):
            raise ValidationError("drive sync pairs must be objects")
        for sim_key, engine_key in _PAIR_ALIASES:
            sim_value = str(pair.get(sim_key) or "").strip()
            engine_value = str(pair.get(engine_key) or "").strip()
            if sim_value and engine_value and sim_value != engine_value:
                raise ValidationError(
                    f"drive pair conflict: {sim_key} and {engine_key} name different folders"
                )
        # OWNER RULE (2026-09-02): the SOURCE folder is required; synced / failed folders are
        # optional marks (a pair without them simply leaves files where they are).
        if require_complete and not str(pair.get("to_sync") or pair.get("from") or "").strip():
            raise ValidationError("each drive pair needs a to_sync folder (the folder it watches)")


# ----- cross-service reads (drive / mail / connections) --------------------
#
# INDOX consumes the platform's services rather than re-declaring accounts
# (INDOX-SYNC.md §8). Each service owns its own connection catalog and its own
# synthetic local adapter, so we ask THEM, not the vault directly — otherwise the
# built-in local drive/mailbox (which is what the live pipes actually pull from)
# would be missing from the list.

_SVC_TIMEOUT = float(os.getenv("INDOX_SERVICE_TIMEOUT_S", "8"))

def _apitools_base() -> str:
    """apitools (OCR/rendering backend) internal base URL. `APITOOLS_BASE` is already
    set in apps/indox/docker-compose.yml for this service, defaulting to the in-cluster
    address so this also works unconfigured."""
    return os.getenv("APITOOLS_BASE", "http://apitools:8080").rstrip("/")


# ---------------------------------------------------------------------------
# DEFAULT UPLOAD FOLDER — owner decision (2026-08-05): the chat app's
# document-upload destination (what used to be the "מסמכים מהבוט בווצאפ"
# Google folder) is a first-class INDOX setting, `default-upload-folder`,
# resolving to the LOCAL drive engine (admin profile), folder
# `automations/uploads`. The old Google folder is legacy — a past
# destination, never a sync source.
#
# The setting is provisioned lazily (get-or-create, same discipline as
# `_ensure_folder`/`_ensure_sync_dest_folder`) and persisted into
# `public.settings` on first resolution so it shows up — and is overridable —
# in the settings UI (`_EDITABLE_SETTINGS_KEYS`) instead of living only in an
# env var. A value already present in `settings` (typed in by an operator, or
# left over from a previous resolution) always wins over provisioning.
# ---------------------------------------------------------------------------
_DEFAULT_UPLOAD_FOLDER_SETTING_KEY = "default-upload-folder"


# Optional shrink of the stored preview. apitools' page image is a 300-DPI render
# (`APITOOLS_PDF_DPI`) — measured 2026-08-10 over the 40 most recent documents: mean
# 722 KB, max 1.3 MB — so downscaling is tempting. It is nevertheless DEFAULT OFF.
#
# MEASURED, 2026-08-10, and the reason for the default: enabling it put a JPEG decode on
# the request path of THIS container, which is the tightest one in the stack (512 MiB cap,
# 1.0 CPU, gunicorn 1 worker x 8 gthreads, plus a constant full-table Supabase sync scan).
# Within 25 minutes `memory.events` went from `max 0` — the ceiling had never once been
# reached — to `max 378` with 118 MB swapped and pgmajfault 6072, i.e. sustained reclaim
# thrash. The duplicate-render fix (see `_thumbnail_from_apitools`) is worth real money;
# shaving a cosmetic asset from 722 KB to ~80 KB is not worth pushing a container that sits
# on the document path into its ceiling. Set INDOX_THUMBNAIL_MAX_WIDTH to a positive width
# to turn it back on — ideally only once this service has memory headroom, or once the
# resize is done by apitools, which already owns the raster and has 6 GiB.
_THUMBNAIL_MAX_WIDTH = int(os.getenv("INDOX_THUMBNAIL_MAX_WIDTH", "0") or 0)


def _downscale_jpeg(jpg_bytes: bytes, max_width: int = 0) -> bytes:
    """Shrink an already-encoded JPEG to thumbnail width.

    Uses PIL's `draft()`, which lets libjpeg do the downscale DURING the DCT decode, so a
    3300x4700 page never exists at full size in memory (this process has a 512 MiB cap and
    8 gthread workers sharing it — a naive full decode is ~47 MB of RGB per concurrent
    call). Never raises: on any failure the caller still gets a usable image back, because
    a slightly-too-large thumbnail beats no thumbnail.
    """
    max_width = max_width or _THUMBNAIL_MAX_WIDTH
    if max_width <= 0:
        return jpg_bytes          # disabled by default — see _THUMBNAIL_MAX_WIDTH above
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(jpg_bytes))
        if img.width and img.width <= max_width:
            return jpg_bytes
        target_h = max(1, int(img.height * max_width / max(1, img.width)))
        img.draft("RGB", (max_width, target_h))       # cheap DCT-scaled decode
        img = img.convert("RGB")
        if img.width > max_width:                      # draft only hits 1/2,1/4,1/8 steps
            target_h = max(1, int(img.height * max_width / max(1, img.width)))
            img = img.resize((max_width, target_h), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80, optimize=True)
        return out.getvalue() or jpg_bytes
    except Exception:
        return jpg_bytes


def _thumbnail_from_apitools(file_id: str, timeout: float = 30.0) -> bytes | None:
    """Return the page raster apitools ALREADY rendered for `file_id`, or None.

    THE POINT OF THIS FUNCTION (owner, 2026-08-10): "apitools already generates image from
    all documents ... it should not be a separated call that does pdf rendering. its
    duplicacy cause we already always do pdf to jpeg in apitools."

    Every document on this path is rasterised by apitools during `/documentOcr` (poppler at
    `APITOOLS_PDF_DPI`=300, see apps/apitools/src/pdf_core/pdf_to_jpg.py), and apitools keeps
    that raster keyed by the md5 it returns as `file_hash` — the same value INDOX stores as
    `API_TOOLS_ID`. `/documentImage?file_id=<hash>` serves it: read-only, side-effect free,
    and NOT behind apitools' `_expensive_request_slot` bulkhead, so it never queues.

    The thumbnail step used to POST the whole file back to `/pdfToJpeg`, re-rendering every
    page of the same PDF at 300 DPI a second time, deskewing each and vconcat-ing them into
    one canvas — purely to make a preview. Measured on the live stack 2026-08-10:
    `/pdfToJpeg` n=12, p50 8.45s, p90 18.29s, max 26.04s, admitted 8-at-a-time against a
    4-CPU budget shared with the OCR that actually matters, and waited on for up to
    `APITOOLS_SLOT_WAIT_TIMEOUT`=600s. The lookup below: n=40, 97.5% hit, mean 1.28s.
    """
    import httpx

    with httpx.Client(timeout=timeout) as c:
        r = c.get(f"{_apitools_base()}/documentImage", params={"file_id": file_id})
    if r.status_code != 200:
        return None
    # apitools answers a cache miss with 404 + JSON {"error": "image_not_found"}; guard the
    # content-type too so a JSON body is never mistaken for image bytes.
    if "json" in (r.headers.get("content-type") or "").lower():
        return None
    return r.content or None


# ---------------------------------------------------------------------------
# ONE CLICK FROM AN ANSWER TO THE RUN THAT PRODUCED IT
#
# Every INDOX-facing n8n reply now carries `execution_id` / `workflow_id` (the
# terminal Code nodes stamp them). This turns that into a URL the operator can
# actually click.
#
# Why it matters more than it sounds: the whole point of phases 0-4 is that the
# UI reports what the engine really did. But "SCAN was refused: pipe runs on the
# v1 engine" is the engine's CONCLUSION — the reasoning is in the execution, and
# without a link the operator has to open n8n, guess which of the last hundred
# executions was theirs, and match it by wall-clock. That gap is where people
# stop believing the screen and start believing their memory.
#
# The base URL is browser-reachable, NOT the in-cluster `http://n8n:5678` the
# BFF itself calls: those are different addresses for the same service, and
# handing the browser the internal one produces a link that silently never
# resolves. Empty when unset — the UI then shows the id as text rather than a
# dead link, because an id you can paste beats a link that goes nowhere.
# ---------------------------------------------------------------------------
def _n8n_public_base() -> str:
    for var in ("N8N_PUBLIC_URL", "N8N_BASE_URL", "N8N_URL"):
        v = (os.getenv(var) or "").strip().rstrip("/")
        if v:
            return v if "://" in v else f"https://{v}"
    return ""


def _exec_ref(data: object) -> dict | None:
    """`{execution_id, workflow_id, url}` from an n8n reply, or None.

    Tolerates the two shapes n8n answers with — `lastNode` returns the node's
    first item, a Respond node set to "all entries" returns an array — for the
    same reason `_scan` does: mis-reading an array as "no fields present" is how
    a present answer looks absent.
    """
    if isinstance(data, list):
        data = data[0] if (data and isinstance(data[0], dict)) else None
    if not isinstance(data, dict):
        return None
    ex = str(data.get("execution_id") or "").strip()
    wf = str(data.get("workflow_id") or "").strip()
    if not ex:
        return None
    base = _n8n_public_base()
    ref = {"execution_id": ex, "workflow_id": wf or None, "url": None}
    if base and wf:
        ref["url"] = f"{base}/workflow/{wf}/executions/{ex}"
    elif base:
        ref["url"] = f"{base}/executions/{ex}"
    return ref


def _svc_call(method: str, url: str, *, params=None, json_body=None,
              timeout: float | None = None) -> tuple[object | None, str | None]:
    """``(payload, None)`` or ``(None, reason)``. Never raises: a service that is
    down is a reason to show less, never a 500 out of this BFF."""
    import httpx  # lazy

    try:
        with httpx.Client(timeout=timeout or _SVC_TIMEOUT) as c:
            r = c.request(method, url, params=params, json=json_body)
            r.raise_for_status()
            return (r.json() if r.content else {}), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ----- LIST(sync, state): the one primitive, per source type ---------------


def _ns(pipe: str) -> str:
    """The pipe's LEDGER identity: `<instance>/<pipe>` (phase 6b).

    A pipe keeps its plain name everywhere a human reads it — the board, the editor, the URL. Only
    its identity in `sync_ledger`/`sync_cursor` is qualified, because those two are
    keyed on `source` and duplicating an INDOX gives the second instance a pipe called `drive-gdoc`
    too. Un-namespaced, both instances share ledger rows and each reads the other's deliveries as
    already done: one client's documents silently never arrive, with both boards showing green.

    Already-qualified names pass through unchanged, so this is safe to apply more than once and safe
    to apply to a name that arrived from the engine rather than from the registry.
    """
    p = str(pipe or "")
    return p if "/" in p else f"{_instance()}/{p}"


def _sync_summary(transport, entries: list[dict]) -> dict:
    """The strip above the cards (owner 2026-09-02, the card view comes back): totals per state
    over every pipe, the last pass and the next one from the scheduler's own state
    (public.app_schedule_state, job 'sync', written by indox01), and the day history starts.
    DB-only; every part degrades to None on its own."""
    tot = {"to_sync": 0, "in_progress": 0, "synced": 0, "failed": 0, "needs_review": 0,
           "sources": len(entries)}
    for e in entries:
        c = e.get("counts") or {}
        tot["to_sync"] += int(c.get("discovered") or 0)
        tot["in_progress"] += int(c.get("claimed") or 0)
        tot["synced"] += int(c.get("delivered") or 0)
        tot["failed"] += int(c.get("failed") or 0)
        tot["needs_review"] += int(c.get("needs_review") or 0)
    last_pass = None
    next_pass_at = None
    every_min = 15
    try:
        for r in transport.select(schema="public", table="app_settings", select=["key", "value"],
                                  filter={"app": {"op": "eq", "value": "indox"},
                                          "key": {"op": "eq", "value": "indox.auto.sync.every"}},
                                  limit=1) or []:
            every_min = max(1, int(str(r.get("value") or "15").strip() or 15))
    except Exception:
        pass
    try:
        flt: dict = {"app": {"op": "eq", "value": "indox"}, "job": {"op": "eq", "value": "sync"}}
        inst = _request_instance()
        if inst:
            flt["instance"] = {"op": "eq", "value": inst}
        rows = transport.select(schema="public", table="app_schedule_state",
                                select=["instance", "job", "last_run_at", "last_exec", "last_note"],
                                filter=flt, order=[("last_run_at", "desc")], limit=1, offset=0) or []
        if rows:
            r = rows[0]
            exec_id = str(r.get("last_exec") or "") or None
            last_pass = {"started_at": r.get("last_run_at"), "execution_id": exec_id,
                         "note": r.get("last_note"),
                         "url": (f"{_n8n_public_base()}/workflow/syncV3Main0001/executions/{exec_id}"
                                 if exec_id and _n8n_public_base() else None)}
            try:
                from datetime import datetime, timedelta
                t = datetime.fromisoformat(str(r.get("last_run_at")).replace("Z", "+00:00"))
                next_pass_at = (t + timedelta(minutes=every_min)).isoformat()
            except Exception:
                next_pass_at = None
    except Exception:
        last_pass = None
    return {"totals": tot, "last_pass": last_pass, "next_pass_at": next_pass_at,
            "cadence_min": every_min, "history_since": "2026-08-28",
            # the server's clock, so the page's freshness and the next-pass ETA never trust the
            # browser's (the PipelineBar's lesson: a skewed laptop clock lied about liveness)
            "as_of": _now_iso()}


def _enrich_registry(transport, registry: list[dict], scope: _Scope,
                     with_items: bool = False) -> list[dict]:
    """Config AND state in one read — the state being the SYNC ITEM COUNTS (view
    `sync_item_counts`, one row per pipe: discovered / claimed / delivered / failed / needs_review,
    when discovery and delivery last touched it, the most recent error). DB-ONLY, by owner rule
    (2026-09-02): no mail call, no drive call, no cached copy of a walk. `with_items` is accepted
    for old callers and ignored — there is nothing live left to walk.

    Never raises. If the view cannot be read (unreachable DB, view not yet migrated) every entry
    reports `counts: None` + `counts_computed: False` — unknown is not zero.
    """
    rows: dict[str, dict] | None = {}
    try:
        for r in transport.select(
                schema=_request_schema(), table="sync_item_counts",
                select=["source", "pipe", "discovered", "claimed", "delivered", "failed",
                        "needs_review", "total", "last_discovered_at", "last_delivered_at",
                        "last_claimed_at", "last_error", "oldest_waiting_at", "waiting"],
                limit=1000) or []:
            rows[str(r.get("source") or "")] = r
    except Exception:
        rows = None
    # THE REASONS (owner 2026-09-03: every red item explains itself): view sync_item_reasons,
    # last_error grouped per source over failed + needs_review — the card shows the top three,
    # the items drawer the rest. Absent view (not yet migrated) → no reasons, never an error.
    reasons_by: dict[str, list] = {}
    try:
        for r in transport.select(
                schema=_request_schema(), table="sync_item_reasons",
                select=["source", "reason", "n", "last_at"], limit=5000) or []:
            reasons_by.setdefault(str(r.get("source") or ""), []).append(
                {"reason": str(r.get("reason") or ""), "count": int(r.get("n") or 0),
                 "last_at": r.get("last_at")})
    except Exception:
        reasons_by = {}

    out: list[dict] = []
    for entry in registry:
        e = dict(entry)
        name = str(e.get("name") or "")
        e["connection_kind"] = str(e.get("source") or "")
        try:
            e["cadence_min"] = int((e.get("batch") or {}).get("schedule_min") or 15)
        except (TypeError, ValueError):
            e["cadence_min"] = 15
        rs = reasons_by.get(_ns(name)) or reasons_by.get(name) or []
        e["reasons"] = sorted(rs, key=lambda x: -x["count"])[:3]
        if rows is None:
            e["counts"] = None
            e["counts_computed"] = False
        else:
            r = rows.get(_ns(name)) or rows.get(name) or {}

            def n(k: str, _r=r) -> int:
                try:
                    return int(_r.get(k) or 0)
                except (TypeError, ValueError):
                    return 0
            e["counts"] = {"discovered": n("discovered"), "claimed": n("claimed"),
                           "delivered": n("delivered"), "failed": n("failed"),
                           "needs_review": n("needs_review"), "total": n("total")}
            # the view is authoritative: a pipe with no row has no items, and that IS a count
            e["counts_computed"] = True
            e["last_discovered_at"] = r.get("last_discovered_at")
            e["last_delivered_at"] = r.get("last_delivered_at")
            e["last_error"] = r.get("last_error")
            # the lag metric (sync best practice): the oldest item still owed, poison items
            # excluded — a pipe whose bar stopped moving shows HOW LONG it has been stuck
            e["oldest_waiting_at"] = r.get("oldest_waiting_at")
            e["waiting"] = n("waiting")
        # "last run" = the latest of: the run button's stamp, the last discovery, the last delivery
        # (ISO strings, same tz — lexical max is chronological max).
        cands = [str(v) for v in (e.get("last_run"), e.get("last_discovered_at"),
                                  e.get("last_delivered_at")) if v]
        e["last_run"] = max(cands) if cands else None
        if e.get("connection"):
            e["connection_label"] = str(e.get("connection"))
        out.append(e)
    return out


# ----- INVENTORY: at-source vs in-INDOX, per registry entry ----------------


# ----- DONE: source-side loop closed (synced OR failed) — see GET /sync/inventory -----
#
# `done` is deliberately a THIRD fact, distinct from the two this endpoint already reports:
#   in_indox   does THIS INDOX instance already hold a row for it (a table match)
#   delivered  (sync_ledger, elsewhere) did OUR pipeline record a delivery
#   done       did the SOURCE get cleaned up — the operator's own signal that the loop closed,
#              made independently of INDOX: a gmail message carrying the synced/failed label, or a
#              drive file sitting in the synced/failed folder. A message can be labelled done by a
#              human, or a file moved by hand, with no INDOX row ever created — `done` catches that;
#              `in_indox`/`delivered` cannot.
#
# Same cost asymmetry as at_source/in_indox (see `_inventory_gmail`'s docstring): gmail's answer is
# one more cheap `limit:1` search per state (reuses `_gmail_state_total`, already built for exactly
# this), so it is computed UNCONDITIONALLY, same as at_source. Drive's answer is a second and third
# full folder listing (`synced` + `failed`, on top of the `to_sync` listing at_source already pays
# for) — the same cost CLASS as at_source, but doubling-to-tripling it, and unlike gmail there is no
# cheap substitute (Drive has no count-only call). Measured cold, /sync/inventory's default path was
# already 5.7s for to_sync alone; forcing synced+failed on every request risks the 40s console proxy
# timeout on a large archive. So drive's `done` is opt-in via `?with_done=1` (the same pattern as
# `?with_items=1` on GET /sync/registry) and `null` + `done_computed:false` otherwise — never a
# fabricated 0.




# ----- CLAIM / ADVANCE: writing the SOURCE, never the table ----------------


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE COMMAND — the server half of "drive the pipeline from the console".
#
# The console could observe the state machine but never drive it: draining and
# restarting in bulk needed SQL plus a basic-auth n8n webhook a browser cannot
# call. Three endpoints close that gap (`GET /pipeline/status`,
# `POST /pipeline/drain`, `POST /repos/<r>/documents/bulk`).
#
# TWO DATABASES, AND THEY ARE NOT THE SAME ONE. INDOX's rows live in the
# supabase postgres; n8n's executions live in its own postgres (container
# `n8n-postgres`, user `hacohen`, db `n8n`). Both are read here over psycopg —
# already a dependency for the n8n credential store — on connections pinned
# `default_transaction_read_only=on`, verified 2026-08-23 to reject a write with
# ReadOnlySqlTransaction. This is the ONLY place in the BFF that reads n8n's
# database, and it only ever reads.
#
# The env var is deliberately NOT `N8N_DB_DSN`: that name is read by
# `repo_factory` and setting it would reroute every repo build through an n8n
# credential lookup (see the compose comment: "N8N_DB_DSN intentionally NOT
# set"). `.env`'s existing `N8N_DB_DSN` is also stale — measured 2026-08-23, its
# embedded password is 28 chars against the 28→48-char one the live n8n
# container actually authenticates with, so reusing that string would have
# failed at runtime and looked like an outage. The parts below come from the
# same `POSTGRES_*` / `SUPABASE_DB_*` values the databases themselves are
# created from. Port is hardcoded 5432 on purpose: `SUPABASE_DB_PORT` (5433) is
# the HOST-published port, not the one on the docker network.
#
# EVERY read degrades on its own. A payload that says "n8n is unreadable" is
# useful; a 500 that takes the whole bar down with it is not.
# ═══════════════════════════════════════════════════════════════════════════

#: The drain workflow. One alive execution of it is the whole single-drainer rule.
_PIPELINE_DRAIN_WF = os.getenv("INDOX_DRAIN_WORKFLOW_ID", "indoxV2BaseDrain01")
#: The driver — the lanes a drain fans out into. `drivers` vs `parallel` is the
#: honest answer to "is the pool full or is it wedged".
_PIPELINE_DRIVER_WF = os.getenv("INDOX_DRIVER_WORKFLOW_ID", "indoxV2Driver01")

#: n8n statuses that mean "this execution still owns resources". `new` is in the
#: list because a queued row has NOT started yet and has a NULL `startedAt` — a
#: guard that filtered on `startedAt` would count the whole queue as zero and let
#: a second drainer through.
_PIPELINE_ALIVE = ("running", "waiting", "new")
#: `crashed` counts as an error: the worker died mid-execution, which is exactly
#: what an operator needs to see. Measured 2026-08-23: 0 in the last hour, 35 in
#: six, 55 in twenty-four — the predicate counts.
_PIPELINE_ERROR_STATUSES = ("error", "crashed")

#: STATUS values that mean the document is finished with the state machine.
#: A NULL STATUS is NOT terminal (it is a row nothing has decided yet), so
#: `non_terminal` is total minus these rather than a NOT IN — under SQL's
#: three-valued logic `NOT IN` silently drops every NULL row.
#:
#: [owner ruling 2026-08-31] The display set matches the STATE MACHINE'S OWN law, not a
#: 4-status shortlist: every parked verdict the pickup excludes (the 2026-08-14 terminal-
#: failure set) IS final — MISSING_LINK and MISSING_COMPANY_ID explicitly included by the
#: owner ("שתיהם נחשבים מצב סופי"). Counting them as non-final made the drain widget read
#: "5,313 לא סופיים" over an estate whose machine owed exactly ~210 rows (IN_PROGRESS +
#: ACTION_RESTART + dead-letters). Non-terminal now means precisely: rows the machine is
#: still expected to move — IN_PROGRESS / TO_EXTRACT / ACTION_RESTART / DOUBLE (awaiting
#: merge adjudication) / ACTION_FAILED (dead-letter with retry backoff) / NULL.
_PIPELINE_TERMINAL = (
    "COMPLETED", "MERGED", "OLD", "GARBAGE", "PAUSE", "MAX_ITERATIONS",
    "MISSING_LINK", "MISSING_COMPANY_ID", "MISSING_TYPE", "UNKNOWN_COMPANY",
    "EXTRACTION_FAILED", "API_TOOLS_FAILED", "PRIORITY_SYNC_FAILED",
    "ACTION_REQUIRED", "NEEDS_REVIEW",
)

#: doc_action locks: `n8n.process_lock.doc_action.<ID>::<ACTION>`, dot-delimited.
#: A colon pattern matches nothing at all and reads as a clean zero.
_PIPELINE_LOCK_MATCH = "n8n.process_lock.doc_action.*"
#: Locks are NOT released when the action completes — they lapse on their TTL —
#: so "held" is normal and only a LOW remaining TTL means one has been held for
#: most of its lease. Default 1800s against a measured ~2810s lease ≈ held longer
#: than ~17 minutes, past any action's intended life.
#:
#: THE THRESHOLD IS ONLY AS GOOD AS THAT LEASE. Shorten the lease below 1800s and
#: every lock reads stale from the instant it is taken, which would turn the leak
#: signal into permanent noise. `_pipeline_locks` therefore also reports the
#: largest remaining TTL it saw (`locks_lease_s`), so the assumption is checkable
#: from the payload rather than only from a redis session.
_PIPELINE_LOCK_STALE_TTL_S = int(os.getenv("INDOX_LOCK_STALE_TTL_S", "1800") or 1800)
#: Bound the SCAN so a runaway key space cannot turn a 5-second poll into a stall.
_PIPELINE_LOCK_SCAN_MAX = 50_000

#: One status read serves every open tab inside this window. The bar polls every
#: 5s while a drain runs and 20s idle; without this, N tabs are N× the DB load
#: for an answer that cannot have changed. `as_of` is stamped by the DB at
#: compute time, so a cached payload dates itself honestly.
_PIPELINE_STATUS_TTL_S = 2.0
# ONE MEMO PER INSTANCE. A single shared entry meant the first instance to poll answered for
# every other one for the whole TTL — the bar showed identical numbers (same `as_of`, to the
# microsecond) under two different instance names. Keyed by schema, exactly like the row-count
# cache, so an instance can only ever be served its own reading.
_PIPELINE_STATUS_MEMO: dict[str, dict[str, object]] = {}
_PIPELINE_STATUS_LOCK = threading.Lock()

#: Serialises check-then-fire in `POST /pipeline/drain`. The BFF runs ONE
#: gunicorn worker by design (gunicorn.conf.py), so this closes the window in
#: which two operators clicking together both pass the single-drainer guard.
_PIPELINE_FIRE_LOCK = threading.Lock()

#: The INDOX mode (all/changed/ids) a drain was fired with. n8n serialises its
#: run data with `flatted`, which interns every string into a shared array, so
#: the request body is NOT recoverable from `execution_data` by any substring
#: read — verified 2026-08-23 against a live drain blob. What this process fired
#: it therefore has to remember; anything else falls back to n8n's own trigger
#: mode, which is a different fact and is labelled as one.
_PIPELINE_DRAIN_MODES: dict[str, str] = {}
_PIPELINE_DRAIN_MODES_MAX = 64

#: [2026-08-24, owner order] the selection has NO size cap — the one-selector body may
#: resolve to the whole table; `_resolve_selection`'s page guard (500k) is runaway
#: protection only. The old `_PIPELINE_BULK_MAX_IDS` (5000) died with the same order.
#: [2026-08-24, owner order] widened from STATUS-only to ANY schema column: the console must
#: support "שינוי סטטוס או כל נתון לקבוצה שלמה". Still ONE writer — every id goes through the
#: same diff-engine upsert path a single-document PATCH uses; the protected trio below can
#: never be patched from here.
_PIPELINE_BULK_PROTECTED_FIELDS = frozenset({"created_at", "updated_at"})

#: CSV export (POST /repos/<r>/documents/export) row cap. Deliberately NOT the
#: bulk cap above: an export acts on nothing, so it may sweep the whole table.
#: Hitting it is not a 413 either — by the time the fetch loop learns the count,
#: the response headers are long gone, so the cap is reported IN-BAND (a final
#: `__TRUNCATED__` row; see the handler).
_EXPORT_MAX_ROWS = 100_000
#: fetch_by_ids chunk for `ids`-mode exports. Fixed, not `_max_batch_size()`:
#: that env knob sizes the WRITE path and an export must not move with it.
_EXPORT_FETCH_CHUNK = 500

#: Direct router dispatch (POST /repos/<r>/documents/dispatch): the console's face of the
#: sanctioned manual dispatch (webhook + full-row lines + ACTION + TRIGGER label). Only verbs
#: the router actually implements; restart stays OUT — ACTION_RESTART via STATUS is its one
#: sanctioned door.
#: select_base / select_type are here for a reason the other verbs do not have: they are the only
#: actions that are MEANT to be re-run, and the decide gate deliberately will not re-run them for
#: a document selected before the hash columns existed (a stored hash is required, and treating
#: "unknown" as "changed" would re-select the whole estate on one sweep). Clearing that backlog is
#: therefore an operator action over a chosen selector — which is exactly what this endpoint is.
#: restart_priority_sync is the ONE door for re-sending a line the ERP already has, and it is here
#: because there is no other correct way to ask for one in bulk. Clearing PRIORITY_SYNC_COMPLETED
#: and PRIORITY_SYNC_SIGNATURE by hand looks equivalent and is not: the dup guard reads
#: ACTION_HISTORY, where the original action_priority_sync still sits unpaired, so decide re-emits
#: the action and the guard (correctly) blocks it — measured 2026-08-25, that is exactly what a
#: bulk SQL clear produced. The restart action writes the same two columns AND leaves a 'restart*'
#: entry in the history, which is what makes the next send legitimate rather than a repeat.
_DISPATCH_ALLOWED_ACTIONS = frozenset({
    "extract_base_doc", "extract_per_type", "link_documents", "find_link",
    "action_priority_sync", "select_base", "select_type", "restart_priority_sync",
})
#: router Switch vocabulary for DOC_TYPE (verified against indoxV2ActionRouter01 2026-08-24;
#: extract_base_doc routes by ACTION before DOC_TYPE is consulted).
#: TYPE -> DOC_TYPE, the value indoxV2ActionRouter01's Switch1 routes on. This is a SECOND copy
#: of resolveDocType (indoxV2ActionsGlobal01 :: _DOC_CLASS) and it must be kept in step with it:
#: a type missing here does not fail, it falls to the default below and is dispatched to the
#: WRONG lane. [five classes 2026-08-27] ORDER and RECEIPT are named explicitly for exactly that
#: reason — they are parked types with their own one-action routers, and defaulting them to the
#: invoice lane would re-open the per-type extraction and ERP sync this change removed.
_DISPATCH_DOC_TYPE = {
    "BALANCE_SHEET": "bs_doc", "SHIPMENT": "shipment",
    "ORDER": "order", "RECEIPT": "receipt",
}
#: heavy columns stripped from dispatch lines — the router does not need them and a 30k-char
#: line is its own failure mode.
_DISPATCH_STRIP = (
    "BS_EXTRACTED_LINES", "DOUBLE_LINE_CONTEXT", "SELECTION_SCORE_DEBUG",
    "SELECTION_DEBUG_BASE", "SELECTION_DEBUG_PERTYPE", "THUMBNAIL",
    "SOURCE_LIST", "ALSO_SEEN_AS",
)
_DISPATCH_BATCH = 5


def _csv_cell(value) -> str:
    """One RFC4180 CSV field.

    Quote only when the value contains a comma, quote, CR or LF; double the
    inner quotes. None → empty string; dict/list → JSON (`ensure_ascii=False`
    so Hebrew stays readable, same as the settings serialiser above);
    everything else → ``str(value)``.
    """
    if value is None:
        s = ""
    elif isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    if any(ch in s for ch in ',"\r\n'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def _pipeline_conninfo(prefix: str, *, host: str, dbname: str, user: str) -> str:
    """libpq conninfo for one of the two databases, or "" when not configured.

    Built with `make_conninfo` from separate parts rather than interpolated into
    a URL: a password containing `@`, `:` or `/` silently corrupts a URL-form DSN
    and produces an authentication failure that looks like a wrong credential.
    A full `<PREFIX>_DSN` still wins when a deployment prefers one string.
    """
    explicit = (os.getenv(f"{prefix}_DSN") or "").strip()
    if explicit:
        return explicit
    password = os.getenv(f"{prefix}_PGPASSWORD") or ""
    if not password:
        return ""
    from psycopg.conninfo import make_conninfo  # lazy: import cost only when used

    return make_conninfo(
        host=os.getenv(f"{prefix}_PGHOST") or host,
        port=os.getenv(f"{prefix}_PGPORT") or "5432",
        dbname=os.getenv(f"{prefix}_PGDATABASE") or dbname,
        user=os.getenv(f"{prefix}_PGUSER") or user,
        password=password,
        connect_timeout=int(os.getenv("INDOX_PG_CONNECT_TIMEOUT_S", "4") or 4),
        application_name="indox-bff-pipeline",
    )


def _pipeline_indox_conninfo() -> str:
    return _pipeline_conninfo(
        "PIPELINE_INDOX", host="supabase-db", dbname="postgres", user="postgres"
    )


def _pipeline_n8n_conninfo() -> str:
    return _pipeline_conninfo(
        "PIPELINE_N8N", host="n8n-postgres", dbname="n8n", user="hacohen"
    )


def _pipeline_query(conninfo: str, statements: list[tuple[str, tuple]]):
    """Run read-only statements on ONE connection; `[rows_per_statement]` or None.

    A fresh connection per call rather than a pooled one: `_PIPELINE_STATUS_TTL_S`
    already bounds this to well under one connect per second, and a cached
    connection would have to survive a postgres restart, a network blip and eight
    gthread workers sharing it — three ways to serve a stale error instead of a
    number. Returns None on ANY failure; the caller decides what to say.
    """
    if not conninfo:
        return None
    try:
        import psycopg  # lazy

        with psycopg.connect(
            conninfo,
            autocommit=True,
            # Belt AND braces: this connection is for reading. The session flag
            # makes an accidental write fail at the database rather than land.
            options="-c default_transaction_read_only=on",
        ) as conn:
            out = []
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, params)
                    out.append(cur.fetchall())
            return out
    except Exception as e:
        _log.warning("pipeline read failed: %s: %s", type(e).__name__, e)
        return None


def _pipeline_safe_table(name: object) -> str | None:
    """A document table name safe to interpolate into SQL, or None.

    The name comes from the repo registry (trusted, operator-written) and cannot
    be bound as a parameter — identifiers never can. This is the guard that keeps
    that "cannot" from becoming an injection point if the registry is ever
    writable by something less trusted.
    """
    text = str(name or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_]{1,63}", text) else None


def _pipeline_indox_numbers(doc_table: str | None, instance: str,
                            schema: str = "public") -> dict | None:
    """The INDOX half of the status payload, in one round trip, or None.

    `as_of` is `now()` FROM THIS DATABASE. The container clock happens to agree
    today (both UTC, measured identical to the second on 2026-08-23) but the
    browser's does not — this host renders ~3h ahead — so a freshness claim built
    anywhere other than here would eventually be a lie told with confidence.
    """
    table = _pipeline_safe_table(doc_table)
    if not table:
        return None
    # THE BAR IS ON EVERY SCREEN, SO IT LIED ON EVERY SCREEN. All three relations below were
    # hardcoded `public.`, which is instance one's data behind the compat views — so the pipeline
    # strip showed הכהן's totals, terminal counts and drain gate while לוי was selected, and would
    # have started failing outright the moment those views are dropped. Same identifier discipline
    # as everywhere else: the schema is validated, never interpolated on trust.
    if not _SAFE_SCHEMA.match(schema or ""):
        return None
    rows = _pipeline_query(
        _pipeline_indox_conninfo(),
        [
            (
                f'''SELECT now()::text,
                       (SELECT count(*) FROM "{schema}"."{table}"),
                       (SELECT count(*) FROM "{schema}"."{table}"
                          WHERE "STATUS" = ANY(%s)),
                       (SELECT count(*) FROM "{schema}"."{table}"
                          WHERE "STATUS" = 'ACTION_RESTART'),
                       (SELECT count(*) FROM "{schema}".indox_action_execution_log
                          WHERE "STARTED_AT" > now() - interval '5 minutes'),
                       -- a MISSING row reads as ON: the drainer COALESCEs the
                       -- gate to 'true', so showing OFF here would contradict
                       -- what the pipeline is actually doing.
                       coalesce((SELECT lower(value) = 'true' FROM "{schema}".settings
                                   WHERE instance = %s AND key = 'indoxDrainOn'), true),
                       (SELECT value FROM "{schema}".settings
                          WHERE instance = %s
                            AND key = 'indox.statemachine.drain.parallel')''',
                (list(_PIPELINE_TERMINAL), instance, instance),
            )
        ],
    )
    if not rows or not rows[0]:
        return None
    as_of, total, terminal, action_restart, dispatch_5m, drain_on, parallel = rows[0][0]
    try:
        parallel_n = int(str(parallel).strip())
    except (TypeError, ValueError):
        parallel_n = 0
    return {
        "as_of": str(as_of),
        # total minus terminal — see _PIPELINE_TERMINAL for why not a NOT IN
        "non_terminal": int(total or 0) - int(terminal or 0),
        "action_restart": int(action_restart or 0),
        "dispatch_5m": int(dispatch_5m or 0),
        "drain_on": bool(drain_on),
        "parallel": parallel_n,
    }


def _pipeline_n8n_numbers() -> dict | None:
    """Live drain + driver + error counts from n8n's own database, or None.

    `deletedAt IS NULL` is load-bearing, not defensive: 3,687 of 23,690 execution
    rows were soft-deleted on 2026-08-23, and counting one as a live drain would
    wedge the drain button behind an execution that no longer exists.
    """
    conninfo = _pipeline_n8n_conninfo()
    alive = list(_PIPELINE_ALIVE)
    rows = _pipeline_query(
        conninfo,
        [
            (
                '''SELECT
                     (SELECT count(*) FROM execution_entity
                        WHERE "workflowId" = %s AND status = ANY(%s)
                          AND "deletedAt" IS NULL),
                     (SELECT count(*) FROM execution_entity
                        WHERE "workflowId" = %s AND status = ANY(%s)
                          AND "deletedAt" IS NULL),
                     (SELECT count(*) FROM execution_entity
                        WHERE status = ANY(%s) AND "deletedAt" IS NULL
                          AND coalesce("startedAt", "createdAt")
                              > now() - interval '1 hour')''',
                (
                    _PIPELINE_DRAIN_WF, alive,
                    _PIPELINE_DRIVER_WF, alive,
                    list(_PIPELINE_ERROR_STATUSES),
                ),
            ),
            (
                # The OLDEST alive drain, which is the one the single-drainer rule
                # is about. `startedAt` is NULL until a queued execution is picked
                # up, so the elapsed clock falls back to when it was created.
                '''SELECT id::text, mode,
                          coalesce("startedAt", "createdAt")::text
                     FROM execution_entity
                    WHERE "workflowId" = %s AND status = ANY(%s)
                      AND "deletedAt" IS NULL
                    ORDER BY id ASC LIMIT 1''',
                (_PIPELINE_DRAIN_WF, alive),
            ),
        ],
    )
    if rows is None or not rows[0]:
        return None
    drains, drivers, errors_1h = rows[0][0]
    live = rows[1][0] if rows[1] else None
    return {
        "drains": int(drains or 0),
        "drivers": int(drivers or 0),
        "errors_1h": int(errors_1h or 0),
        "live": (
            {
                "execution_id": str(live[0]),
                # What THIS process fired, when it fired it. Otherwise n8n's own
                # trigger mode ('trigger' = one of the schedules, 'webhook' =
                # someone else's call) — a different fact, labelled as one.
                "mode": _PIPELINE_DRAIN_MODES.get(str(live[0])) or str(live[1] or ""),
                "started_at": str(live[2] or ""),
                "n8n_url": _pipeline_exec_url(str(live[0])),
            }
            if live
            else None
        ),
    }


def _pipeline_exec_url(execution_id: str) -> str:
    """The BROWSER-reachable link to one drain execution, or "".

    Deep-links to the workflow's execution list when the public base is known —
    the run you most want to open is the one that has not come back yet.
    """
    base = _n8n_public_base()
    if not base or not execution_id:
        return ""
    return f"{base}/workflow/{_PIPELINE_DRAIN_WF}/executions/{execution_id}"


def _pipeline_locks() -> dict:
    """Held doc_action locks and how many are near the end of their lease.

    Redis is already a dependency of this service (the action log, unlock-all and
    stop-all all use the same client), so this adds no new coupling. Unreachable
    redis reports `locks_available: false` rather than a zero — a fabricated zero
    on the ONE number that signals a lock leak is worse than no number.
    """
    try:
        cli = _actions_redis()
        total = 0
        stale = 0
        lease = 0
        cursor = 0
        while True:
            cursor, batch = cli.scan(
                cursor=cursor, match=_PIPELINE_LOCK_MATCH, count=1000
            )
            if batch:
                total += len(batch)
                pipe = cli.pipeline()
                for key in batch:
                    pipe.ttl(key)
                for ttl in pipe.execute():
                    # -1 = no expiry set at all: a lock that can never lapse is
                    # the worst kind of stale. -2 = the key died mid-scan.
                    if ttl == -1 or (0 <= ttl < _PIPELINE_LOCK_STALE_TTL_S):
                        stale += 1
                    if isinstance(ttl, int) and ttl > lease:
                        lease = ttl
            if cursor == 0 or total >= _PIPELINE_LOCK_SCAN_MAX:
                break
        return {"locks": total, "locks_stale": stale, "locks_available": True,
                # the freshest lease seen — the evidence behind the stale rule
                "locks_lease_s": lease}
    except Exception as e:
        _log.warning("pipeline lock scan failed: %s: %s", type(e).__name__, e)
        return {"locks": 0, "locks_stale": 0, "locks_available": False,
                "locks_error": str(e)}


def _pipeline_remember_mode(execution_id: str, mode: str) -> None:
    """Bounded memory of what mode each drain was fired with — see
    `_PIPELINE_DRAIN_MODES`. Bounded because it is keyed by an ever-growing
    execution id and nothing else would ever evict it."""
    if not execution_id:
        return
    _PIPELINE_DRAIN_MODES[str(execution_id)] = mode
    if len(_PIPELINE_DRAIN_MODES) > _PIPELINE_DRAIN_MODES_MAX:
        for old in list(_PIPELINE_DRAIN_MODES)[: -_PIPELINE_DRAIN_MODES_MAX]:
            _PIPELINE_DRAIN_MODES.pop(old, None)


def create_blueprint(
    *,
    registry: RepoRegistry | None = None,
    repo_factory: RepoFactory | None = None,
    kafka_admin: KafkaAdmin | None = None,
    kafka_producer: KafkaProducer | None = None,
    kafka_consumer: KafkaConsumer | None = None,
    url_prefix: str | None = None,
) -> Blueprint:
    """Build and return the ``incoming_documents_bp`` blueprint."""
    prefix = url_prefix or os.getenv(
        "INCOMING_DOCS_API_PREFIX", "/incomingDocuments"
    )
    reg = registry or get_default_registry()
    factory: RepoFactory = repo_factory or default_repo_factory
    admin: KafkaAdmin = kafka_admin or NullKafkaAdmin()
    producer: KafkaProducer = kafka_producer or NullKafkaProducer()
    consumer: KafkaConsumer = kafka_consumer or NullKafkaConsumer()

    bp = Blueprint("incoming_documents_bp", __name__, url_prefix=prefix)

    # ----- error handler: map our exception hierarchy to the canonical envelope
    @bp.errorhandler(IncomingDocumentsError)
    def _handle_known(err: IncomingDocumentsError):
        return jsonify(err.to_envelope()), err.status

    # ----- /health
    @bp.get("/health")
    def health():
        try:
            reg.list()
            return jsonify({"status": "ok", "service": "incoming_documents"}), 200
        except Exception as e:  # pragma: no cover - defensive
            return jsonify({"status": "unhealthy", "error": str(e)}), 503

    # ----- /repos (list + get + create + delete) — full CRUD lands in step 8
    @bp.get("/repos")
    def list_repos():
        return jsonify(
            {
                "success": True,
                "repos": [
                    c.model_dump(mode="json", by_alias=True) for c in reg.list()
                ],
            }
        )

    @bp.get("/repos/<repo>")
    def get_repo(repo: str):
        cfg = reg.get(repo)
        payload = cfg.model_dump(mode="json", by_alias=True)
        # THE COLUMNS THE UI IS TOLD ABOUT ARE THE ONES THE TABLE ACTUALLY HAS. Introspected
        # per request (30s TTL) and merged with the display catalog; the registry's own list is
        # the fallback for a gsheet repo or an unreachable database, never the source of truth.
        scoped = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        live = _resolved_columns(cfg, scoped)
        if live is not None:
            payload["columns"] = live
        # LAYER 2 travels with the schema: the grid gets what exists, what it means, and where
        # it shows, in one payload — so a screen never has to know a column name to lay itself
        # out. The lookup follows the SWITCHED table, not the repo's, or browsing `settings`
        # would be laid out with `incoming_documents`' view.
        table = getattr(scoped, "table", None) or (cfg.supabase.table if cfg.supabase else cfg.name)
        payload["view_catalog"] = _views_for(table)
        payload["table"] = table
        return jsonify({"success": True, "repo": payload})

    @bp.post("/repos")
    def register_repo():
        body = request.get_json(silent=True)
        if body is None:
            raise ValidationError("request body must be JSON")
        try:
            cfg = RepoConfig.model_validate(body)
        except PydanticValidationError as e:
            raise ValidationError(
                "RepoConfig validation failed",
                errors=e.errors(include_url=False, include_context=False, include_input=False),
            ) from e
        # Auto-inject studio_url from env if not provided
        if cfg.backend == "supabase" and cfg.supabase and not cfg.supabase.studio_url:
            studio_url = os.getenv("SUPABASE_STUDIO_URL", "")
            if studio_url:
                cfg = cfg.model_copy(
                    update={"supabase": cfg.supabase.model_copy(update={"studio_url": studio_url})}
                )
        result = provision_repo(
            cfg,
            registry=reg,
            repo_factory=factory,
            kafka_admin=admin,
        )
        return (
            jsonify({"success": True, **result}),
            201,
        )

    @bp.delete("/repos/<repo>")
    def delete_repo(repo: str):
        reg.delete(repo)
        return jsonify({"success": True}), 200

    @bp.patch("/repos/<repo>")
    def patch_repo(repo: str):
        """Partial update of repo config fields (e.g. active, poll_interval_seconds)."""
        cfg = reg.get(repo)
        body = request.get_json(silent=True) or {}
        # Only allow patching safe scalar fields
        allowed = {"active", "poll_interval_seconds", "supabase_studio_url", "upsert_match_rules"}
        unknown = set(body) - allowed
        if unknown:
            raise ValidationError(f"fields not patchable: {sorted(unknown)}")
        update: dict = {}
        if "active" in body:
            update["active"] = body["active"]
        if "poll_interval_seconds" in body:
            update["poll_interval_seconds"] = body["poll_interval_seconds"]
        if "supabase_studio_url" in body and cfg.supabase:
            update["supabase"] = cfg.supabase.model_copy(
                update={"studio_url": body["supabase_studio_url"]}
            )
        if "upsert_match_rules" in body:
            from ..core.models import UpsertMatchRule
            update["upsert_match_rules"] = [
                UpsertMatchRule.model_validate(r) for r in body["upsert_match_rules"]
            ]
        updated = cfg.model_copy(update=update)
        reg.update(updated)
        return jsonify({"success": True, "repo": updated.model_dump(mode="json", by_alias=True)})

    def _perform_batch_upsert(repo: str, body: list[dict]):
        cfg = reg.get(repo)
        if not isinstance(body, list):
            raise ValidationError("request body must be a JSON array of items")
        cap = _max_batch_size()
        if len(body) > cap:
            raise BatchTooLarge(
                f"batch size {len(body)} exceeds max {cap}",
                limit=cap,
                got=len(body),
            )
        # THE WRITE ENGINE ITSELF HAS TO KNOW THE INSTANCE. Every write path funnels here — the
        # grid's inline edit, the batch upsert, the bulk action — so scoping only the CALLERS left
        # a half-fix: the selection resolved in the caller's instance and the write still landed in
        # `public`. It reads the request directly because every caller is inside one.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        pk = cfg.primary_key
        non_pk_cols = [c.name for c in cfg.columns if c.name != pk]
        filtered: list[dict] = []
        for item in body:
            if not isinstance(item, dict):
                continue
            has_value = any(
                item.get(c) not in (None, "") for c in non_pk_cols
            ) or item.get(pk) not in (None, "")
            if has_value:
                if item.get(pk) in (None, ""):
                    item = {**item, pk: str(uuid.uuid4())}
                filtered.append(item)
        body = filtered
        if not body:
            return jsonify({"success": True, "created": [], "updated": [],
                            "skipped": [], "stats": {"incoming": 0, "created": 0,
                            "updated": 0, "noop": 0, "events_published": 0}})
        pks: list[str] = []
        for item in body:
            if isinstance(item, dict) and item.get(pk) is not None:
                pks.append(str(item[pk]))
        current_rows_by_pk = repo_obj.fetch_by_ids(pks) if pks else []

        extra_rows: list[dict] = []
        if cfg.upsert_match_rules:
            extra_rows = repo_obj.fetch_by_match_rules(body, cfg.upsert_match_rules)

        seen_pks: set[str] = {str(r[pk]) for r in current_rows_by_pk if r.get(pk) is not None}
        current_rows: list[dict] = list(current_rows_by_pk)
        for r in extra_rows:
            if r.get(pk) is not None and str(r[pk]) not in seen_pks:
                seen_pks.add(str(r[pk]))
                current_rows.append(r)

        diff = compute_diff(
            current_rows=current_rows, incoming=body, config=cfg
        )
        updated = repo_obj.batch_update(diff.updates) if diff.updates else []
        created = repo_obj.batch_create(diff.creates) if diff.creates else []

        envelopes: list[EventEnvelope] = []
        if cfg.kafka.enabled:
            existing_by_pk = {
                str(r.get(cfg.primary_key, "")): r for r in current_rows
            }
            for u in diff.updates:
                base = existing_by_pk.get(str(u.pk), {})
                full_row = {**base, **u.changes, cfg.primary_key: u.pk}
                envelopes.append(
                    EventEnvelope(
                        repo=cfg.name,
                        event_type="ROW_CHANGED",
                        row=full_row,
                    )
                )
            for c in diff.creates:
                envelopes.append(
                    EventEnvelope(
                        repo=cfg.name,
                        event_type="ROW_CREATED",
                        row=dict(c),
                    )
                )
            if envelopes:
                producer.publish_many(envelopes)
                producer.flush()

        if created:
            with _stats_cache_lock:
                _stats_cache.pop(cfg.name, None)

        return jsonify(
            {
                "success": True,
                "updated": updated,
                "created": created,
                "skipped": diff.skipped,
                "stats": {
                    "incoming": len(body),
                    "updated": len(updated),
                    "created": len(created),
                    "noop": len(diff.noops),
                    "events_published": len(envelopes),
                },
            }
        )

    # ----- /repos/<r>/documents : batch upsert
    @bp.put("/repos/<repo>/documents")
    def batch_upsert(repo: str):
        body = request.get_json(silent=True)
        if not isinstance(body, list):
            raise ValidationError("request body must be a JSON array of items")
        return _perform_batch_upsert(repo, body)

    # ----- /documents : convenience active-repo upsert
    @bp.route("/documents", methods=["POST", "PUT"])
    def active_repo_documents():
        scope = _scope(reg)
        if not scope.instance:
            raise RepoNotFound("No active repository configured")
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            body = [body]
        if not isinstance(body, list):
            raise ValidationError("request body must be a JSON item or array of items")
        return _perform_batch_upsert(scope.instance, body)

    # ----- /repos/<r>/documents/query : batch get
    @bp.post("/repos/<repo>/documents/query")
    def batch_query(repo: str):
        cfg = reg.get(repo)
        body = request.get_json(silent=True) or {}
        try:
            q = Query.model_validate(body)
        except PydanticValidationError as e:
            raise ValidationError(
                "Query validation failed",
                errors=e.errors(include_url=False, include_context=False, include_input=False),
            ) from e
        cap = _max_query_limit()
        if q.limit > cap or q.mode == "all":
            q = q.model_copy(update={"limit": min(q.limit, cap)})
        # `?instance=` scopes the read to that instance's schema; absent, nothing changes.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        # NO ROW-LEVEL INSTANCE FILTER IS IMPOSED HERE, deliberately. An earlier version added
        # `filter={'instance': _instance()}` to satisfy the transport's guard, and it was WRONG:
        # `_instance()` is the one global name ('incoming-documents-main'), while a instance's own
        # rows carry their own ('incoming-documents-levi'). Reading indox_levi.settings with the
        # global name returned 8 rows out of 68 — and the 8 were the leaked ones, not levi's.
        # The SCHEMA is the isolation; see the transport, where a instance-schema read is served
        # before that guard for exactly this reason.
        rows = repo_obj.query(q)
        truncated = len(rows) >= q.limit
        next_offset = (q.offset + q.limit) if truncated else None
        # Optional exact total for "page N of M" pagination. Only computed when
        # the client asks (`with_count`) and the backend supports it; degrades
        # to null so a backend without count support never breaks the query.
        total: int | None = None
        if q.with_count:
            counter = getattr(repo_obj, "count", None)
            if callable(counter):
                try:
                    # [table timeouts 2026-09-02] The exact count is the one part of a grid page
                    # that does not shrink with the page: every keystroke of a search re-counted
                    # the whole table. Memoised for 15s per (schema, table, filter, search) — a
                    # page flip or a re-sort within that window pays nothing, and a count that is
                    # 15s stale on a 26k-row table is indistinguishable from exact to a reader.
                    _ck = ("docs-count\x00" + str(getattr(repo_obj, "schema", "")) + "\x00"
                           + str(getattr(repo_obj, "table", "")) + "\x00"
                           + json.dumps(q.filter if q.mode == "filter" else None, sort_keys=True,
                                        ensure_ascii=False, default=str)
                           + "\x00" + str(q.search or "") + "\x00"
                           + ",".join(q.search_columns or []))
                    total = _sync_cached(_ck, 15.0, lambda: counter(q))
                except Exception:  # count is best-effort — never fail the query
                    total = None
        return jsonify(
            {
                "success": True,
                "rows": rows,
                "count": len(rows),
                "total": total,
                "truncated": truncated,
                "next_offset": next_offset,
            }
        )

    # ----- /repos/<r>/documents/month-index : real server-side month aggregate ---
    # DocumentBrowserPage's month-navigation pills used to page through the table
    # CLIENT-SIDE (2000 rows/request via `truncated` above) and bucket by month in
    # the browser. That looked correct but relied on `truncated`, which was wrong:
    # `len(rows) >= q.limit` compared the returned count against the CLIENT's
    # requested limit (2000), while PostgREST had already silently clamped the
    # actual rows to its own `db-max-rows` (1000 on this stack) — so `1000 >= 2000`
    # read as "that's everything" after the very first page, and every badge
    # undercounted by however much of the table lived past row ~1000 (observed
    # 6-9x on the real corpus). `_paged_select` above already solves exactly this
    # for the dashboard's aggregates by comparing each chunk against the FIXED
    # page size it itself requested — this route reuses it instead of inventing a
    # second way to page. Bounded at `INCOMING_DOCS_MONTH_INDEX_MAX_ROWS` (default
    # 100k, matching the old client-side cap); `sampled: true` says so rather than
    # ever presenting a partial count as if it were exact.
    @bp.post("/repos/<repo>/documents/month-index")
    def month_index(repo: str):
        cfg = reg.get(repo)
        body = request.get_json(silent=True) or {}
        date_col = str(body.get("date_col") or "").strip()
        if not date_col:
            raise ValidationError("date_col is required")
        valid_cols = {c.name for c in cfg.columns}
        if date_col not in valid_cols:
            raise ValidationError(f"unknown column '{date_col}' on repo '{repo}'")
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        max_rows = int(os.getenv("INCOMING_DOCS_MONTH_INDEX_MAX_ROWS", "100000"))
        sampled = False
        if cfg.backend == "supabase":
            transport = getattr(repo_obj, "transport", None)
            if transport is None:
                raise ValidationError("supabase repo has no transport")
            rows = _paged_select(
                transport, table=repo_obj.table, select=[date_col],
                order_col=cfg.primary_key, max_rows=max_rows,
                schema=repo_obj.schema,
            )
            sampled = len(rows) >= max_rows
        else:
            # gsheet-backed repos are small enough for a single unpaged read — no
            # equivalent silent-cap trap exists for them.
            rows = repo_obj.fetch_all(columns=[date_col])

        buckets: dict[str, int] = {}
        no_date = 0
        bad_date = 0
        for r in rows:
            v = r.get(date_col)
            key = _month_key_of(v)
            if key is not None:
                buckets[key] = buckets.get(key, 0) + 1
            elif str(v or "").strip() == "":
                no_date += 1
            else:
                bad_date += 1

        # `no_date` COUNTS EXACTLY WHAT THE UI CAN THEN OPEN, and that is the whole reason
        # the two are split. The "ללא תאריך" bucket drills down with `{op:'is_null'}` — the
        # only single operator PostgREST can express for "has no date" — while this loop
        # used to lump NULLs together with rows whose value is PRESENT but unparseable.
        # Measured live 2026-08-12 on DOC_DATE: 7,657 advertised, 7,631 opened, a 30-row
        # lie of exactly that shape (values like '23/06/26' that `month_key_of` rejects).
        # They are reported as `bad_date` instead of being hidden inside `no_date`: rows
        # carrying an unreadable date are a data-quality fact worth seeing, and the UI
        # states the number without offering a drill-down it cannot honour.
        return jsonify(
            {
                "success": True,
                "buckets": [
                    {"key": k, "count": c} for k, c in sorted(buckets.items(), reverse=True)
                ],
                "no_date": no_date,
                "bad_date": bad_date,
                "total": len(rows),
                "sampled": sampled,
            }
        )

    # ----- /repos/<r>/stats : row count + columns + last event time
    # In-process row-count cache: {repo_name: (count, expiry_epoch)}
    _stats_cache: dict[str, tuple[int, float]] = {}
    _stats_cache_lock = threading.Lock()
    _STATS_TTL = 30  # seconds

    def _get_cached_row_count(cfg_name: str, repo_obj) -> int | None:  # noqa: D401
        """Exact row count, cached for `_STATS_TTL` seconds.

        `len(repo_obj.fetch_all())` used to back this — an unbounded select that PostgREST
        silently caps at its configured `db-max-rows` (1000 on this stack), so a repo past that
        size reported a `row_count` that was really just "however many rows fit in one page",
        with no error and no sign anything was wrong. `repo_obj.count()` asks PostgREST for the
        exact total via `Prefer: count=exact` (Content-Range), which is a single cheap request —
        not a full-table read — and is not capped by db-max-rows at all.
        """
        # THE CACHE KEY CARRIES THE TENANT. Without it the first instance to warm the cache
        # answers for every other one — a wrong number that looks authoritative and is the same
        # class of cross-instance bleed the schema split exists to end.
        cfg_name = f"{cfg_name}@{_request_schema()}"
        now = time.monotonic()
        with _stats_cache_lock:
            entry = _stats_cache.get(cfg_name)
            if entry and entry[1] > now:
                return entry[0]
        try:
            # Only the supabase backend has an exact `count()` (PostgREST `Prefer: count=exact`);
            # gsheet/in-memory repos read everything in one call anyway and have no page cap to
            # defeat, so they keep the plain `len(fetch_all())` they always used.
            count = (repo_obj.count(Query(mode="all")) if hasattr(repo_obj, "count")
                    else len(repo_obj.fetch_all()))
        except Exception:
            # Return stale value if available, else None
            with _stats_cache_lock:
                entry = _stats_cache.get(cfg_name)
                return entry[0] if entry else None
        with _stats_cache_lock:
            _stats_cache[cfg_name] = (count, now + _STATS_TTL)
        return count

    @bp.get("/repos/<repo>/stats")
    def repo_stats(repo: str):
        cfg = reg.get(repo)
        # `factory(cfg)` reads the config's own schema, so this counted `public` — i.e. instance
        # one — whichever instance the caller named. Same fix as /account/detail above.
        repo_obj = repo_for(cfg, request.args.get("instance") or None)
        row_count = _get_cached_row_count(cfg.name, repo_obj)
        return jsonify(
            {
                "success": True,
                "name": cfg.name,
                "backend": cfg.backend,
                "row_count": row_count,
                "columns": (_resolved_columns(cfg, repo_obj)
                            or [c.model_dump(by_alias=True) for c in cfg.columns]),
                "kafka_enabled": cfg.kafka.enabled,
                "row_count_stale": row_count is None,
            }
        )

    # ----- /accounts + /account/* : INDOX instances ---------------------------
    #
    # The Drive/Mail/Chat "connected accounts" contract, applied to INDOX. One
    # instance = one registered repo (see the module-level note above for what
    # selection does and does not scope). Everything here projects data that
    # already exists; nothing new is stored except the one-line active-instance
    # pointer.
    # `_resolve_active` used to be defined here too. It is now the module-level
    # helper that `_scope()` calls, because "which instance is active" must have
    # exactly one implementation — two copies is how the switcher and the readers
    # end up disagreeing about which company you are looking at.
    def _global_registry_count() -> int:
        """`sync_registry` is a single global settings key on this stack, so this
        count is the same for every instance. Reported anyway (rather than
        omitted) because the switcher's details panel is where an operator looks
        to answer "does this instance have any pipes at all"."""
        try:
            rows = _config_transport().select(
                schema=_request_schema(), table="settings",
                select=["key", "value"], filter=_tenant({"key": "sync_registry"}), limit=1,
            )
        except Exception:
            return 0
        value = rows[0].get("value") if rows else None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return 0
        return len(value) if isinstance(value, list) else 0

    def _global_config_counts() -> dict[str, int]:
        """`settings` / `companies` / `tag_rules` row counts.

        WHY THIS EXISTS. `_instance_account` has always accepted a `counts`
        argument, and `/accounts` was the one caller that never passed it — so
        the switcher reported `0 הגדרות · 0 חברות · 0 כללים` for every instance,
        including the one `/account/detail` simultaneously reported as 71/6/23.
        Three zeros read as "this instance is empty", which is the single worst
        thing to tell someone choosing which company to work on.

        Like `_global_registry_count`, this is deliberately ONE read shared by
        every account rather than one read per account: these three tables have
        no `instance` column on this stack, so the numbers are genuinely the same
        for every instance. Phase 6.2 adds that column, at which point this
        becomes a per-instance count and the loop below stops sharing a result —
        the shape of the answer does not change, only its scoping.
        """
        # tag_rules retired 2026-09-03 (owner Decision N1): the label rules have ONE store, the
        # mail app's organizer settings; INDOX counts only what it still owns.
        out = {"settings": 0, "companies": 0}
        try:
            t = _config_transport()
        except Exception:
            return out
        for key, table, col in (("settings", "settings", "key"),
                                ("companies", "companies", "id")):
            try:
                out[key] = len(t.select(schema=_request_schema(), table=table,
                                        select=[col], limit=_CONFIG_READ_LIMIT))
            except Exception:
                pass  # one unreachable table costs its own number, not the list
        return out

    def _instance_account(cfg: RepoConfig, *, registry_count: int = 0,
                          docs: int | None = None, counts: dict | None = None) -> dict:
        counts = counts or {}
        return {
            "id": cfg.name,
            "provider": "indox",
            "label": cfg.name,
            "identity": _instance_target(cfg),
            "color": _instance_color(cfg.name),
            # The active instance can't be removed out from under the app; the
            # UI reads `builtin` to disable its delete affordance.
            "builtin": False,
            # An instance whose row count can't be read is not "broken" — the
            # backing store may simply be slow or briefly unreachable — so it
            # reports a warning rather than an error.
            "status": "ok" if docs is not None else "warning",
            "reason": None if docs is not None else "row count unavailable",
            "backend": cfg.backend,
            "docs": docs or 0,
            "registry": registry_count,
            "settings_count": counts.get("settings", 0),
            "companies": counts.get("companies", 0),
            "tag_rules": counts.get("tag_rules", 0),
            "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
        }

    @bp.before_request
    def _bind_instance_schema():
        """Resolve `?instance=` ONCE per request and hang it on `g`.

        Every read helper then follows the operator's instance without a parameter threaded through
        a dozen signatures — which is what left the dashboard, the action log and the sync board
        reading `public` while the documents grid had already moved. Resolution is cached for 60s.

        A request that NAMES an instance never proceeds without it. The first draft swallowed every
        resolution failure and left `g` unset, so `_request_schema()` fell back to `public` — a levi
        screen operating on hacohen's data behind a success envelope, including the action-log
        purge. Unknown instance → the ValidationError/RepoNotFound handlers (400/404); a transient
        resolution failure (registry unreachable) → 503, because refusing costs a retry and
        rebinding silently costs a cross-tenant write."""
        inst = request.args.get("instance")
        g.indox_schema = None
        if not inst:
            return
        try:
            g.indox_schema = _instance_schema(inst)
        except (ValidationError, RepoNotFound):
            raise
        except Exception as e:
            _log.warning("instance %r could not be resolved: %s", inst, e)
            return jsonify({
                "success": False,
                "error": "instance_unresolvable",
                "message": "המופע המבוקש לא ניתן לזיהוי כרגע — הבקשה לא בוצעה. נסה שוב.",
                "instance": inst,
            }), 503

    # ── READING ONE TENANT'S DATA ────────────────────────────────────────────────────────────
    #
    # The repo config points at schema `public`, where `incoming_documents` is a COMPAT VIEW over
    # `indox_hacohen`. So without this, every read — whichever instance the operator picked —
    # returns instance one's rows. A instance selector over that is worse than none: it presents a
    # choice the data does not honour, which is the cross-instance read wearing a UI.
    #
    # `?instance=<id>` resolves that id in `public.indox_instances` and builds the repo against
    # THAT schema instead. No instance means the config's own schema, unchanged, so every existing
    # caller behaves exactly as before.
    #
    # This scopes the BFF's own reads only. indoxApi01's `public` fallback is a separate path and
    # belongs to the tenancy cutover; until that lands, a workflow can still reach the view.
    _instance_schema_cache: dict[str, tuple[float, str]] = {}

    def _instance_schema(instance: str) -> str:
        if not _SAFE_ID.match(instance or ""):
            raise ValidationError(f"not a valid instance id: {instance!r}")
        hit = _instance_schema_cache.get(instance)
        now = time.time()
        if hit and (now - hit[0]) < 60.0:
            return hit[1]
        base = factory(reg.get(reg.list()[0].name)) if reg.list() else None
        transport = getattr(base, "transport", None) if base else None
        if transport is None or not hasattr(transport, "_exec_sql"):
            raise ValidationError("no sql transport available to resolve an instance")
        rows = transport._exec_sql(
            "select schema_name from public.indox_instances "
            f"where id = {_sql_lit(instance)}"
        ) or []
        if not rows:
            raise RepoNotFound(f"instance '{instance}' is not in public.indox_instances")
        schema = str(rows[0].get("schema_name") or "")
        if not _SAFE_SCHEMA.match(schema):
            raise ValidationError(f"registry gave an unusable schema name: {schema!r}")
        _instance_schema_cache[instance] = (now, schema)
        return schema

    _instance_tables_cache: dict[str, tuple[float, set[str]]] = {}

    def _instance_tables(schema: str) -> set[str]:
        """The instance's real tables — the allowlist `?table=` is checked against, so a table
        name from the URL is never interpolated into SQL on trust."""
        hit = _instance_tables_cache.get(schema)
        now = time.time()
        if hit and (now - hit[0]) < 60.0:
            return hit[1]
        base = factory(reg.get(reg.list()[0].name)) if reg.list() else None
        transport = getattr(base, "transport", None) if base else None
        if transport is None or not hasattr(transport, "_exec_sql"):
            return set()
        rows = transport._exec_sql(
            "select table_name from information_schema.tables "
            f"where table_schema = {_sql_lit(schema)} and table_type = 'BASE TABLE'"
        ) or []
        names = {str(r.get("table_name")) for r in rows if r.get("table_name")}
        _instance_tables_cache[schema] = (now, names)
        return names

    def repo_for(cfg, instance: str | None = None, table: str | None = None):
        """The repo object for `cfg`, scoped to `instance` and optionally to another TABLE.

        `?table=` is what makes the console a browser of the instance rather than of one repo:
        the same grid, the same catalog-driven columns, pointed at any table the instance has. It
        is validated against information_schema and refused if unknown — a table name off the URL
        never reaches SQL on trust."""
        if cfg.backend != "supabase" or cfg.supabase is None:
            return factory(cfg)
        schema = _instance_schema(instance) if instance else cfg.supabase.schema_
        target = cfg.supabase.table
        if table and table != target:
            if table not in _instance_tables(schema):
                raise RepoNotFound(f"table '{table}' is not in schema '{schema}'")
            target = table
        if schema == cfg.supabase.schema_ and target == cfg.supabase.table:
            return factory(cfg)
        scoped = cfg.model_copy(
            update={
                "supabase": cfg.supabase.model_copy(
                    update={"schema_": schema, "table": target}
                )
            }
        )
        return factory(scoped)

    # ── TENANTS — the registry proper, and NOT the old `/accounts` surface ───────────────────
    #
    # `/accounts` above derives "instances" from repos.json and reports a GLOBAL active one held
    # in active_instance.json. That file is a multi-instance bug: one operator switching instance
    # changes what a colleague sees AND what the CLI on that host targets. It is slated for
    # deletion, so nothing here reads or writes it.
    #
    # These two routes read `public.indox_instances`, which is where instances are managed —
    # platform.state.yaml keeps an entry only as a cold-boot fallback for the provisioning hook.
    # They are STATELESS on purpose: which instance you are looking at is view state, it belongs in
    # the URL, per user, and the server must not hold an opinion about it.
    @bp.get("/instances")
    def list_instance_registry():
        repo_obj = factory(reg.get(reg.list()[0].name)) if reg.list() else None
        transport = getattr(repo_obj, "transport", None) if repo_obj else None
        if transport is None or not hasattr(transport, "_exec_sql"):
            return jsonify({"success": True, "instances": [], "reason": "no sql transport"})
        try:
            rows = transport._exec_sql(
                "select id, schema_name, label, enabled from public.indox_instances order by id"
            ) or []
        except Exception as e:
            _log.warning("instance list failed: %s", e)
            return jsonify({"success": True, "instances": [], "reason": str(e)[:200]})
        return jsonify({"success": True, "instances": rows})

    @bp.get("/instances/<instance>/tables")
    def list_instance_tables(instance: str):  # noqa: D401
        """The tables inside one instance's schema, with REAL row counts.

        count(*), never pg_stat_user_tables.n_live_tup: that statistic reads 0 for any table
        autovacuum has not visited, and during the tenancy migration it reported 15 tables empty
        when three of them held 36,762 / 32,565 / 9,622 rows. A table browser that says "0 rows"
        about a table with 36k in it is worse than one that says nothing."""
        if not _SAFE_ID.match(instance or ""):
            raise ValidationError(f"not a valid instance id: {instance!r}")
        repo_obj = factory(reg.get(reg.list()[0].name)) if reg.list() else None
        transport = getattr(repo_obj, "transport", None) if repo_obj else None
        if transport is None or not hasattr(transport, "_exec_sql"):
            raise ValidationError("no sql transport available")
        row = transport._exec_sql(
            "select schema_name from public.indox_instances "
            f"where id = {_sql_lit(instance)}"
        ) or []
        if not row:
            raise RepoNotFound(f"instance '{instance}' is not in public.indox_instances")
        schema = row[0].get("schema_name")
        if not _SAFE_SCHEMA.match(str(schema or "")):
            raise ValidationError(f"registry gave an unusable schema name: {schema!r}")
        want_counts = str(request.args.get("counts", "")).lower() in ("1", "true", "yes")
        tables = transport._exec_sql(
            "select table_name from information_schema.tables "
            f"where table_schema = {_sql_lit(schema)} and table_type = 'BASE TABLE' "
            "order by table_name"
        ) or []
        out = []
        for tr in tables:
            name = tr.get("table_name")
            if not name:
                continue
            entry: dict[str, Any] = {"name": name, "schema": schema}
            if want_counts:
                try:
                    c = transport._exec_sql(
                        f'select count(*) as n from "{schema}"."{name}"'
                    ) or []
                    entry["rows"] = int(c[0].get("n", 0)) if c else None
                except Exception:
                    entry["rows"] = None  # unreadable is not zero
            out.append(entry)
        return jsonify({"success": True, "instance": instance, "schema": schema, "tables": out})

    @bp.get("/accounts")
    def list_instances():
        configs = reg.list()
        registry_count = _global_registry_count()
        counts = _global_config_counts()
        accounts = []
        for cfg in configs:
            try:
                docs = _get_cached_row_count(cfg.name, factory(cfg))
            except Exception:  # a broken backend must not blank the whole list
                docs = None
            accounts.append(_instance_account(cfg, registry_count=registry_count,
                                              docs=docs, counts=counts))
        return jsonify({"success": True, "accounts": accounts, "active": _resolve_active(configs)})

    @bp.post("/account/select")
    def select_instance():
        body = request.get_json(silent=True) or {}
        wanted = str(body.get("id") or body.get("account") or "")
        cfg = reg.get(wanted)  # 404s through the error envelope if unknown
        _write_active_instance(cfg.name)
        return jsonify(
            {"success": True, "active": cfg.name, "account": _instance_account(cfg)}
        )

    @bp.post("/account/add")
    def add_instance():
        """Provision a new instance = provision a new repo.

        Deliberately thin: it normalizes the switcher's instance vocabulary
        (label / table / backend) into a RepoConfig and hands it to the SAME
        `provision_repo` that POST /repos uses. Two creation paths that build the
        thing differently is how the two drift apart.
        """
        body = request.get_json(silent=True) or {}
        label = str(body.get("label") or body.get("id") or "").strip()
        if not label:
            raise ValidationError("למופע חדש נדרש שם")
        name = str(body.get("id") or label).strip()
        backend = "gsheet" if body.get("backend") == "gsheet" else "supabase"
        table = str(body.get("table") or name)
        columns = body.get("columns") or []
        if not columns:
            raise ValidationError(
                "an instance needs 'columns' — an INDOX table with no columns "
                "cannot be provisioned"
            )
        cfg_dict: dict = {
            "name": name,
            "backend": backend,
            "primary_key": str(body.get("primary_key") or "ID"),
            "columns": columns,
            "active": True,
            "poll_interval_seconds": int(body.get("poll_interval_seconds") or 30),
        }
        if backend == "gsheet":
            cfg_dict["gsheet"] = {"sheet_name": table, "spreadsheet_title": label}
        else:
            cfg_dict["supabase"] = {"schema": "public", "table": table}
        try:
            cfg = RepoConfig.model_validate(cfg_dict)
        except PydanticValidationError as e:
            raise ValidationError(
                "instance validation failed",
                errors=e.errors(include_url=False, include_context=False, include_input=False),
            ) from e
        provision_repo(cfg, registry=reg, repo_factory=factory, kafka_admin=admin)
        _write_active_instance(cfg.name)  # a just-created instance is the one you want
        configs = reg.list()
        return (
            jsonify(
                {
                    "success": True,
                    "account": _instance_account(cfg),
                    "accounts": [_instance_account(c) for c in configs],
                    "active": _resolve_active(configs),
                }
            ),
            201,
        )

    @bp.post("/account/remove")
    def remove_instance():
        """De-register an instance. The backing table/sheet is NOT dropped —
        same contract as DELETE /repos/<r>, and the only safe default when the
        target may hold years of a company's documents."""
        body = request.get_json(silent=True) or {}
        name = str(body.get("id") or "")
        reg.get(name)  # 404 through the envelope if it isn't registered
        if len(reg.list()) <= 1:
            raise ValidationError("לא ניתן למחוק את המופע האחרון שנותר")
        reg.delete(name)
        configs = reg.list()
        active = _resolve_active(configs)
        if _read_active_instance() != active and active:
            _write_active_instance(active)  # the pointer followed the deletion
        return jsonify(
            {
                "success": True,
                "accounts": [_instance_account(c) for c in configs],
                "active": active,
            }
        )

    @bp.get("/account/detail")
    def instance_detail():
        """Everything the active instance owns — the switcher's details panel.

        This is the information RepoDetailPage shows one navigation away. Every
        supabase-backed count degrades to 0 instead of failing the panel: an
        unreachable config table is a reason to show fewer numbers, not to hide
        the instance's own identity.
        """
        configs = reg.list()
        active = _resolve_active(configs)
        if not active:
            raise RepoNotFound("no INDOX instance is registered")
        cfg = reg.get(active)

        # ── THE PANEL DESCRIBES THE INSTANCE YOU ARE LOOKING AT ──────────────────────────────
        #
        # It used to describe whatever `_resolve_active` pointed at, while its settings/companies/
        # tag_rules counts already followed `?instance=` — a MIXED MODEL, and it showed. Measured
        # against the live stack before this change:
        #
        #   /account/detail?instance=levi  ->  docs = 25,995   (levi has 1)
        #                                      columns = 46    (levi's table has 125)
        #
        # 25,995 is hacohen's count rendered under levi's name: a cross-tenant number wearing the
        # other instance's label, which is the exact bleed the schema split exists to end.
        # `repo_for` points the repo at THIS instance's schema, and the row-count cache already
        # keys on the tenant, so both numbers now come from the instance the caller named.
        instance = request.args.get("instance") or None
        try:
            repo_obj = repo_for(cfg, instance)
        except Exception:  # an unknown instance must not take the panel down
            repo_obj = factory(cfg)
        try:
            docs = _get_cached_row_count(cfg.name, repo_obj)
        except Exception:
            docs = None

        registry: list = []
        settings: list = []
        companies = tag_rules = 0
        try:
            transport = _config_transport()
            rows = transport.select(
                schema=_request_schema(), table="settings", select=["key", "value"],
                filter=_tenant(), limit=_CONFIG_READ_LIMIT,
            )
            settings = [
                {"key": r.get("key"), "value": r.get("value")}
                for r in rows if isinstance(r, dict)
            ]
            raw = next((r.get("value") for r in rows if r.get("key") == "sync_registry"), None)
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (ValueError, TypeError):
                    raw = []
            registry = raw if isinstance(raw, list) else []
            companies = len(transport.select(schema=_request_schema(), table="companies",
                                             select=["id"], filter=_tenant(),
                                             limit=_CONFIG_READ_LIMIT))
        except Exception:
            pass  # supabase unreachable — identity still renders

        counts = {
            "docs": docs or 0,
            "registry": len(registry),
            "settings": len(settings),
            "companies": companies,
        }
        return jsonify(
            {
                # AN INSTANCE IDENTIFIES ITSELF BY ITS INSTANCE ID. `_instance_account` reports
                # `cfg.name` — the REPO — so this panel described levi with the id
                # 'incoming-documents-main'. That is the repo/instance conflation the routing
                # cutover removed from the URL; it has no more business in the payload.
                "account": {
                    **_instance_account(
                        cfg, registry_count=len(registry), docs=docs,
                        counts={"settings": len(settings), "companies": companies},
                    ),
                    **({"id": instance, "label": instance} if instance else {}),
                },
                "repo": cfg.model_dump(mode="json", by_alias=True),
                "target": getattr(repo_obj, "table", None) or _instance_target(cfg),
                # LAYER 0 IS THE DATABASE, not repo.json. `cfg.columns` is the registry's DECLARED
                # list and has drifted to 46 against a table that has 126 — the same gap the grid
                # stopped trusting. Introspection answers here too; the declared list survives only
                # as the fallback for a backend that cannot be introspected.
                "columns": (_resolved_columns(cfg, repo_obj)
                            or [c.model_dump(by_alias=True) for c in cfg.columns]),
                "registry": registry,
                "settings": settings,
                "counts": counts,
            }
        )

    # ----- /repos/<r>/documents/<id> : single doc GET
    @bp.get("/repos/<repo>/documents/<doc_id>")
    def get_document(repo: str, doc_id: str):
        cfg = reg.get(repo)
        # `factory(cfg)` reads the config's own schema — `public`, i.e. instance one. Opening ANY
        # document of any other instance 404'd: "document 'levi_doc_0001' not found in
        # 'incoming-documents-main'", on a row that exists, from a link the app itself generated.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        rows = repo_obj.fetch_by_ids([doc_id])
        if not rows:
            raise RepoNotFound(f"document '{doc_id}' not found in '{repo}'")
        return jsonify({"success": True, "row": rows[0]})

    # ----- /documents/<id>/thumbnail : the page raster apitools already holds ------------
    #
    # [owner Decision 10, 2026-09-03] No thumbnail FILES exist any more: the upload workflow used
    # to store apitools' full-page raster in the drive on every run (48,384 objects, 42 GB, 28k
    # byte-duplicates on the laptop). The preview is now DERIVED: the document's API_TOOLS_ID is
    # the md5 apitools keys its raster by, and this route streams that raster with cache
    # headers. 404 = no raster yet (the document never reached OCR, or apitools evicted it) —
    # the UI shows "אין עדיין תצוגה מקדימה", never a broken image.
    @bp.get("/documents/<doc_id>/thumbnail")
    def document_thumbnail(doc_id: str):
        from flask import Response
        try:
            configs = reg.list()
        except Exception:
            configs = []
        active = _resolve_active(configs)
        cfg = next((c for c in configs if c.name == active), None)
        if cfg is None:
            return jsonify({"error": "no active instance"}), 404
        try:
            repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
            rows = repo_obj.fetch_by_ids([doc_id])
        except Exception as e:
            return jsonify({"error": str(e)}), 404
        if not rows:
            return jsonify({"error": "document not found"}), 404
        file_id = str(rows[0].get("API_TOOLS_ID") or "").strip()
        if not file_id:
            return jsonify({"error": "no_raster", "reason": "the document has no OCR upload id yet"}), 404
        try:
            data = _thumbnail_from_apitools(file_id)
        except Exception as e:
            return jsonify({"error": "apitools unreachable", "reason": str(e)}), 404
        if not data:
            return jsonify({"error": "no_raster", "reason": "apitools holds no raster for this id"}), 404
        resp = Response(data, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "private, max-age=3600"
        resp.headers["X-Apitools-File-Id"] = file_id
        return resp

    # ----- /repos/<r>/documents/<id> : PATCH single doc (sugar over batch upsert)
    @bp.patch("/repos/<repo>/documents/<doc_id>")
    def patch_document(repo: str, doc_id: str):
        cfg = reg.get(repo)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        body = {**body, cfg.primary_key: doc_id}
        # WORSE THAN THE READ. Unscoped, an edit made while viewing instance B is applied to
        # instance A's row of the same id — a cross-tenant WRITE that reports success. Ids are
        # per-instance sequences, so collisions are ordinary, not hypothetical.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        current_rows = repo_obj.fetch_by_ids([doc_id])
        diff = compute_diff(
            current_rows=current_rows, incoming=[body], config=cfg
        )
        updated = repo_obj.batch_update(diff.updates) if diff.updates else []
        created = repo_obj.batch_create(diff.creates) if diff.creates else []
        envelopes: list[EventEnvelope] = []
        if cfg.kafka.enabled:
            existing_by_pk = {
                str(r.get(cfg.primary_key, "")): r for r in current_rows
            }
            for u in diff.updates:
                base = existing_by_pk.get(str(u.pk), {})
                full_row = {**base, **u.changes, cfg.primary_key: u.pk}
                envelopes.append(
                    EventEnvelope(
                        repo=cfg.name,
                        event_type="ROW_CHANGED",
                        row=full_row,
                    )
                )
            for c in diff.creates:
                envelopes.append(
                    EventEnvelope(
                        repo=cfg.name, event_type="ROW_CREATED", row=dict(c)
                    )
                )
            if envelopes:
                producer.publish_many(envelopes)
                producer.flush()
        return jsonify(
            {
                "success": True,
                "updated": updated,
                "created": created,
                "noop": diff.noops,
                "events_published": len(envelopes),
            }
        )

    # ----- /repos/<r>/documents/<id>/history : kafka events keyed on this row
    @bp.get("/repos/<repo>/documents/<doc_id>/history")
    def document_history(repo: str, doc_id: str):
        cfg = reg.get(repo)
        if not cfg.kafka.enabled:
            return jsonify({"success": True, "events": []})
        max_events = int(request.args.get("max", "100"))
        events = consumer.history(
            topic=topic_for(cfg.name), key=doc_id, max_messages=max_events
        )
        return jsonify({"success": True, "events": events})

    # ----- /repos/<r>/sync : poll sheet → diff → publish events
    @bp.post("/repos/<repo>/sync")
    def sync_repo(repo: str):
        cfg = reg.get(repo)
        if not cfg.kafka.enabled:
            raise ValidationError(f"kafka disabled for repo '{repo}'")
        from pathlib import Path as _Path
        snapshot_dir = _Path(reg.path).parent / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        repo_obj = factory(cfg)
        result = _sync_repo_once(cfg, repo_obj, snapshot_dir, producer)
        return jsonify({"success": True, **result})

    # ----- /sync/* : proxy the n8n INDOX manage webhook + read the registry
    #
    # The SPA cannot reach the n8n webhook (different origin, unauthenticated
    # cross-service) nor supabase directly, so the BFF is the single front door.
    # Only the read-only STATUS proxy + registry read are exposed here; the
    # destructive verbs (SCAN/RESET/INJECT) are deliberately NOT wired yet.
    def _manage_webhook_url() -> str:
        return os.getenv(
            "INDOX_MANAGE_WEBHOOK_URL",
            "http://n8n-webhook:5678/webhook/indox-manage",
        )

    # tiny server-side cache for STATUS (it does live drive/gmail listing and
    # can take seconds; mirrors the console's short overlay cache).
    _sync_cache: dict[str, tuple[object, float]] = {}
    _sync_cache_lock = threading.Lock()
    _SYNC_STATUS_TTL = 3.0  # seconds

    @bp.get("/sync/registry")
    def sync_registry():
        """The `settings.sync_registry` value — CONFIG **and** LIVE STATE.

        Each entry carries its own `counts` and `failures[]` plus the health of
        the connection it pulls from, so the page reads one list instead of
        correlating two (INDOX-SYNC-PORT §2). Degrades to
        ``{registry: [], reachable: false, error}`` — never 500.
        """
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:  # supabase unreachable / not configured
            return jsonify({"registry": [], "reachable": False, "error": str(e),
                            "n8n_base": _n8n_public_base()})
        # DB-only since 2026-09-02: counts come from the sync_item_counts view (see
        # _enrich_registry); `?with_items` is accepted and ignored — there is no live walk left.
        # `n8n_base` rides along so any screen can turn an execution id into a link without a
        # dedicated read (the document page's action follow does exactly that).
        enriched = _enrich_registry(transport, entries, _scope(reg))
        return jsonify({"registry": enriched,
                        "reachable": True,
                        "summary": _sync_summary(transport, enriched),
                        "n8n_base": _n8n_public_base()})

    @bp.get("/sync/registry/<name>/items")
    def sync_registry_items(name: str):
        """The pipe's sync items, newest first — the items drawer behind a clickable legend
        segment. `?status=` narrows (discovered|claimed|delivered|failed|needs_review),
        `?limit=` caps (default 100, max 500). DB-only: one read of sync_ledger."""
        status = (request.args.get("status") or "").strip()
        try:
            limit = max(1, min(500, int(request.args.get("limit") or 100)))
        except (TypeError, ValueError):
            limit = 100
        try:
            transport = _sync_transport()
            flt: dict = {"source": {"op": "eq", "value": _ns(name)}}
            if status:
                flt["status"] = {"op": "eq", "value": status}
            rows = transport.select(
                schema=_request_schema(), table="sync_ledger",
                select=["platform_id", "status", "last_error", "attempts", "discovered_at",
                        "claimed_at", "delivered_at", "not_before", "doc_id", "listing"],
                filter=flt, order=[("discovered_at", "desc")], limit=limit, offset=0) or []
        except Exception as e:
            return jsonify({"items": [], "reachable": False, "error": str(e)})
        items = []
        for r in rows:
            lst = r.get("listing") if isinstance(r.get("listing"), dict) else {}
            items.append({
                "platform_id": r.get("platform_id"), "status": r.get("status"),
                "reason": r.get("last_error"), "attempts": r.get("attempts"),
                "discovered_at": r.get("discovered_at"), "delivered_at": r.get("delivered_at"),
                "not_before": r.get("not_before"), "doc_id": r.get("doc_id"),
                "listing": {"name": lst.get("name") or lst.get("subject"),
                            "from": lst.get("from"), "date": lst.get("date") or lst.get("createdTime"),
                            "size": lst.get("size"), "hasAttachment": lst.get("hasAttachment")}})
        return jsonify({"items": items, "reachable": True, "status": status or None,
                        "limit": limit})

    # ----- sync control plane: registry CRUD, run, items, connections --------
    #
    # Writes follow the same degradation contract the rest of this BFF uses (see
    # PUT /config/settings/<key>): an unreachable supabase answers 200 with
    # ``{success:false, reachable:false, error}`` rather than a 500, so the board
    # keeps rendering instead of erroring out. A write that did not happen never
    # reports success.
    def _degraded(err: Exception, **extra):
        return jsonify({"success": False, "reachable": False, "error": str(err),
                        "registry": [], **extra})

    def _entry_or_400(registry: list[dict], name: str) -> dict:
        entry = _find_entry(registry, name)
        if entry is None:
            raise RepoNotFound(f"sync '{name}' is not in the registry")
        return entry

    @bp.post("/sync/registry")
    def sync_registry_create():
        """Create a pipe = append to the ONE registry row (INDOX-SYNC-PORT §1).

        This is the UI's path. The DECLARATIVE path is
        `apps/indox/blueprint/fixtures/sync_registry.json`, converged by
        `apps/indox/hooks/sync-registry-converge.py` on every `bbox run` — and it
        calls THIS endpoint to create, so a fixture entry has to satisfy the same
        `require_complete=True` validation an operator would. An entry with an empty
        `connection` — or one still naming a `processor_wf` (proc retired 2026-08-31,
        every sync is thin) — cannot be reproduced on a fresh stack; `--selftest`
        reports which fixture rows those are rather than letting the fresh clone be
        where you find out.
        (The old "hand-edited in scripts/_reg.json" was retired 2026-08-06 — untracked,
        stale, read by nothing.)"""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        name = str(body.get("name") or "").strip()
        if not name:
            raise ValidationError("a sync entry needs a 'name'")
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e)
        if _find_entry(entries, name) is not None:
            raise ValidationError(f"כבר קיים מקור בשם '{name}'")
        entry = {k: v for k, v in body.items() if k != "name"}
        entry["name"] = name
        entry.setdefault("source", "drive")
        entry.setdefault("engine", "v3")
        # thin is the only mode (proc retired 2026-08-31): no processor default is minted, and a
        # caller that still names one is refused by _validate_sync_entry below — loudly, at write
        # time, not silently scrubbed.
        entry.setdefault("projection", "on")
        entry.setdefault("enabled", True)
        entry.setdefault("last_run", None)
        _validate_sync_entry(entry, require_complete=True)
        entries.append(entry)
        try:
            _write_sync_registry(transport, entries)
        except Exception as e:
            return _degraded(e)
        return jsonify({"success": True, "entry": entry,
                        "registry": _enrich_registry(transport, entries, _scope(reg))}), 201

    @bp.patch("/sync/registry/<name>")
    def sync_registry_patch(name: str):
        """Shallow merge into one entry — this is also how a pipe is paused
        (`{enabled:false}`), which the scheduler and run-all must honour."""
        patch = request.get_json(silent=True)
        if not isinstance(patch, dict):
            raise ValidationError("request body must be a JSON object")
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e)
        entry = _entry_or_400(entries, name)
        renamed = str(patch.get("name") or name).strip() or name
        if renamed != name and _find_entry(entries, renamed) is not None:
            raise ValidationError(f"כבר קיים מקור בשם '{renamed}'")
        # `batch` is merged KEY-WISE, not replaced. The editor only shows two of
        # its four knobs, and it builds a whole fresh object to PATCH with — so a
        # shallow `entry.update()` meant that editing a pipe's schedule silently
        # rewrote `chunk` 25 -> 5 and `timeout_min` 14 -> 10 on the way past.
        # Losing settings you never opened the drawer to change is not a merge.
        # Every other key stays a plain overwrite, which is what PATCH means.
        incoming = {k: v for k, v in patch.items() if k != "name"}
        merged_batch = incoming.pop("batch", None)
        if isinstance(merged_batch, dict):
            base = entry.get("batch")
            entry["batch"] = {**base, **merged_batch} if isinstance(base, dict) else merged_batch
        elif merged_batch is not None:
            entry["batch"] = merged_batch
        entry.update(incoming)
        entry["name"] = renamed
        _validate_sync_entry(entry, require_complete=bool(entry.get("connection")))
        try:
            _write_sync_registry(transport, entries)
        except Exception as e:
            return _degraded(e)
        return jsonify({"success": True, "entry": entry,
                        "registry": _enrich_registry(transport, entries, _scope(reg))})

    @bp.delete("/sync/registry/<name>")
    def sync_registry_delete(name: str):
        """Remove the pipe's CONFIG. Nothing in drive/gmail is touched — the
        items keep existing where they are; only INDOX stops watching them."""
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e)
        _entry_or_400(entries, name)
        entries = [e for e in entries if str(e.get("name") or "") != name]
        try:
            _write_sync_registry(transport, entries)
        except Exception as e:
            return _degraded(e)
        # [Decision 8/9 revised 2026-09-03] the pipe's rows go with its config — a deleted registry
        # never leaves orphan sync items behind (mail-private left 130). The UI confirms with the
        # entry's counts as facts before calling; the purge runs through the manage door.
        rows_removed = None
        purge_error = None
        try:
            payload: dict = {"INLINE_ACTION": "RESET", "sync": name, "purge": True}
            if _request_instance():
                payload["__instance"] = _request_instance()
            data, err = _svc_call("POST", _manage_webhook_url(), json_body=payload,
                                  timeout=float(os.getenv("INDOX_SCAN_TIMEOUT_S", "120")))
            if isinstance(data, list):
                data = data[0] if (data and isinstance(data[0], dict)) else {}
            if err or not isinstance(data, dict) or data.get("ok") is not True:
                purge_error = err or str((data or {}).get("error") or "purge refused")
            else:
                rows_removed = data.get("purged")
        except Exception as e:
            purge_error = str(e)
        return jsonify({"success": True, "deleted": True, "rows_removed": rows_removed,
                        "purge_error": purge_error,
                        "registry": _enrich_registry(transport, entries, _scope(reg))})

    @bp.post("/sync/registry/<name>/reset")
    def sync_registry_reset(name: str):
        """Re-drive this pipe's FAILED items from OUR rows: RESET through the manage door → the Sync
        Item API flips failed + needs_review rows back to `discovered` (attempts cleared) and the
        next pass takes them. Nothing at the source is touched. `{"all": true}` widens it to every
        non-discovered row of the pipe — a full re-drive, the CLI's meaning."""
        body = request.get_json(silent=True) or {}
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e)
        _entry_or_400(entries, name)
        payload: dict = {"INLINE_ACTION": "RESET", "sync": name}
        if body.get("all") is not True:
            payload["statuses"] = ["failed", "needs_review"]
        if _request_instance():
            payload["__instance"] = _request_instance()
        data, err = _svc_call("POST", _manage_webhook_url(), json_body=payload,
                              timeout=float(os.getenv("INDOX_SCAN_TIMEOUT_S", "120")))
        if isinstance(data, list):
            data = data[0] if (data and isinstance(data[0], dict)) else {}
        if not isinstance(data, dict):
            data = {}
        ok = (not err) and data.get("ok") is True
        # [owner 2026-09-02] a retry that flips rows and then waits up to 15 minutes for the tick
        # is a button that looks broken: start the pass now, and say whether it started.
        started = None
        if ok:
            try:
                sc = _scan_outcome(name)
                started = {"status": sc.get("status"), "execution": sc.get("execution"),
                           "detail": sc.get("detail") or sc.get("code") or sc.get("error")}
            except Exception as e2:  # the reset stands; only the kick-off is reported failed
                started = {"status": "error", "detail": str(e2)}
        return jsonify({"success": ok, "reset": data.get("reset"),
                        "no_listing": data.get("no_listing"), "started": started,
                        "error": err or (None if ok else str(data.get("error") or "reset refused")),
                        "execution": _exec_ref(data), "n8n_base": _n8n_public_base(),
                        "registry": _enrich_registry(transport, entries, _scope(reg))})

    #: What a run can be, and the third one is the whole point. A pipeline that only knows
    #: "worked" / "failed" has nowhere to put "did not run, and here is why", so it files that
    #: under one of the other two — which is how the sync board's run button spent an entire
    #: session reporting a debounced no-op as a completed pass. `skipped` is not a softer
    #: `error`: an error is something to fix, a skip is something to wait for or override.
    _SCAN_STATUSES = ("ran", "skipped", "error")

    def _scan_outcome(sync: str | None) -> dict:
        """What SCAN actually DID — `{status, claimed, code, error, detail, ref}`.

        Three outcomes (`_SCAN_STATUSES`), never two:

          ran      the v3 reconciler really ran this pipe. `claimed` is what it took; 0 is a
                   legitimate answer (nothing new at the source) and still a run.
          skipped  the pass never started: another `syncV3Main0001` pass held the reconcile lock
                   (`processLock01` PROCESS=syncV3Main0001 KEY=reconcile) and this firing exited
                   cleanly without queueing. NOT a failure and NOT a run.
          error    SCAN was refused, unreachable, or answered without saying what it did.

        WHY THIS EXISTS AS ITS OWN FUNCTION. `_scan_ref` returns `(count, error, ref)`, which can
        express two outcomes. A reconcile pass on this deployment averages 848–1223s against its own
        900s schedule, so the lock is held nearly continuously and a manual run is skipped far more
        often than it runs — measured live 2026-08-06: 10 of six hours' `syncV3Main0001` executions
        ended at `Skip: Already Running`, every one recorded `success` in 0–2s, 9 of them started by
        someone pressing the button, while every real claim came from the 15-minute scheduler. Folded
        into `(count, error)` that skip arrived as `claimed: 0` plus the string
        "exited cleanly - not queued, next 15min tick will retry", which names neither the lock nor
        the pass holding it and paints the board red. Split rather than widened, for the same reason
        `_scan_ref` was split from `_scan`: a dozen call sites want the count and nothing else.
        """
        payload: dict = {"INLINE_ACTION": "SCAN"}
        if sync:
            payload["sync"] = sync
        # Since the cutover, SyncApi's Scan Registry THROWS on a missing __instance — a scan
        # fired from an instance-bound screen must say whose registry it scans.
        if _request_instance():
            payload["__instance"] = _request_instance()
        data, err = _svc_call("POST", _manage_webhook_url(), json_body=payload,
                              timeout=float(os.getenv("INDOX_SCAN_TIMEOUT_S", "120")))
        ref = _exec_ref(data)
        out: dict = {"status": "error", "claimed": 0, "code": None,
                     "error": None, "detail": None, "ref": ref}
        if err:
            out.update(code="unreachable", error=err, ref=None)
            return out
        # n8n's `lastNode` response mode returns the last node's first item, but
        # a Respond node set to "all entries" returns an array — accept both
        # rather than mis-read an array as "no fields present".
        if isinstance(data, list):
            data = data[0] if (data and isinstance(data[0], dict)) else {}
        if not isinstance(data, dict):
            out.update(code="bad_body", error=f"SCAN returned an unexpected body: {data!r}")
            return out
        code = str(data.get("code") or "") or None
        # A SKIP IS ITS OWN OUTCOME, and it is checked BEFORE `ok is False` on purpose: the engine
        # reports a skip as ok:false (nothing ran), and collapsing it into the refusal branch below
        # is exactly the conflation this function exists to undo.
        if (str(data.get("status") or "") == "skipped"
                or data.get("skipped") is True or code == "lock_held"):
            out.update(status="skipped", code=code or "lock_held",
                       error=str(data.get("error")
                                 or "דילוג — ריצת סנכרון אחרת עדיין פעילה"),
                       detail=str(data.get("detail") or data.get("note") or "") or None)
            return out
        if data.get("ok") is False:
            out.update(code=code or "refused",
                       error=str(data.get("error")
                                 or f"SCAN was refused by n8n (action={data.get('action') or '?'})"))
            return out
        # The 2026-09-02 engine dispatches deliveries asynchronously: `status:'ran'` IS the
        # report; `units` rides along when the door knows it, and is never a count of documents.
        if str(data.get("status") or "") == "ran":
            try:
                n_units = int(data.get("units")) if data.get("units") is not None else 0
            except (TypeError, ValueError):
                n_units = 0
            out.update(status="ran", claimed=n_units,
                       detail=str(data.get("detail") or "") or None)
            return out
        for key in ("claimed", "scanned", "count"):
            if data.get(key) is None:
                continue
            try:
                out.update(status="ran", claimed=int(data[key]),
                           detail=str(data.get("detail") or "") or None)
                return out
            except (TypeError, ValueError):
                continue
        out.update(code="no_report",
                   error="SCAN answered without a claimed/scanned/count — the manage "
                         "webhook has no SCAN verb yet, so nothing was run")
        return out

    #: The one place a `skipped` SCAN outcome is turned into something an operator can read. Shaped
    #: like the entries `/sync/run` already puts in its `skipped[]` list for paused and v1 pipes,
    #: deliberately: the board already renders that list in a NEUTRAL callout ("what the run left
    #: alone"), which is exactly the register a debounced run belongs in — not the red banner that
    #: means the engine is broken, and not silence.
    def _skip_note(name: str, outcome: dict) -> dict:
        return {"sync": name,
                "reason": str(outcome.get("code") or "skipped"),
                "he": (f"'{name}' לא הורץ — ריצת סנכרון אחרת עדיין פעילה; "
                       "ההרצה הבאה תתפוס אותו (או המתן לסבב האוטומטי)"),
                "detail": outcome.get("detail") or outcome.get("error")}

    @bp.post("/sync/registry/<name>/run")
    def sync_registry_run(name: str):
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e, claimed=0)
        entry = _entry_or_400(entries, name)
        if entry.get("enabled") is False:
            raise ValidationError(f"המקור '{name}' מושהה — יש להפעיל אותו לפני הרצה")
        outcome = _scan_outcome(name)
        ref = outcome["ref"]
        # Recorded on the entry BEFORE the success branch, and persisted on failure too. The run
        # that needs a debug link most is the one that just told the operator it did nothing.
        if ref:
            entry["last_run_execution"] = ref.get("execution_id")
            entry["last_run_url"] = ref.get("url")
        if outcome["status"] != "ran":
            try:
                _write_sync_registry(transport, entries)
            except Exception:
                pass
            _sync_cache_clear()
            # `success` answers "did a run happen", so it is False for a skip too — a skipped run is
            # not a run. What separates them is `status`, which the caller BRANCHES on: the board
            # shows a skip in its neutral "left alone" callout and a real failure in the red one.
            # Returning success:true here would be the original defect wearing a new costume.
            body = {"success": False, "status": outcome["status"], "claimed": 0,
                    "code": outcome["code"], "error": outcome["error"],
                    "execution": ref, "n8n_base": _n8n_public_base(),
                    "registry": _enrich_registry(transport, entries, _scope(reg))}
            if outcome["status"] == "skipped":
                body["skipped"] = [_skip_note(name, outcome)]
            return jsonify(body)
        entry["last_run"] = _now_iso()
        try:
            _write_sync_registry(transport, entries)
        except Exception:
            pass  # the run happened; failing to stamp it must not report failure
        _sync_cache_clear()
        return jsonify({"success": True, "status": "ran", "claimed": outcome["claimed"],
                        "execution": ref, "n8n_base": _n8n_public_base(),
                        "registry": _enrich_registry(transport, entries, _scope(reg))})

    @bp.post("/sync/run")
    def sync_run_all():
        """SCAN every pipe SCAN can drive, and say plainly what it did not.

        Three outcomes, and conflating them is what made this endpoint lie:

          ran       an enabled v3 pipe that SCAN actually reconciled
          skipped   NOT APPLICABLE, not broken. A paused pipe (that is what pausing means) or a v1
                    pipe (SCAN drives the v3 reconciler; v1 runs on its own schedule). Neither is a
                    failure, and neither should colour the run red — a deployment with one v1 pipe
                    reported "הרצת כל המקורות לא בוצעה" on every single run while six other pipes
                    reconciled perfectly.
          errors    a pipe SCAN tried and could not do

        `success` therefore reflects the pipes actually ATTEMPTED. Skipping is still reported rather
        than silent, because "we did not run this and here is why" is the whole point of phase 0 —
        the fix for a misleading red banner is never a quieter one.

        2026-08-06 — a FOURTH source of `skipped`, and the one that was invisible: the engine itself
        refusing to start because a previous reconcile pass still holds the lock. `skipped` used to
        be decided entirely here, from the registry, BEFORE calling SCAN — so a pipe that was
        enabled, v3, and perfectly runnable but got turned away by the mutex fell through to the
        `ran` count and reported a pass that never happened. A pass averages 848–1223s against its
        own 900s schedule on this deployment, so that was not the rare case: it was most of them.
        The engine's own answer now lands in the same list, and `ran` counts only what really ran.
        """
        try:
            transport = _sync_transport()
            entries = _read_sync_registry(transport)
        except Exception as e:
            return _degraded(e, claimed=0)

        runnable, skipped = [], []
        for e in entries:
            name = str(e.get("name") or "")
            if not name:
                continue
            if e.get("enabled") is False:
                skipped.append({"sync": name, "reason": "paused",
                                "he": f"'{name}' מושהה — יש להפעיל אותו כדי שיסונכרן"})
            elif str(e.get("engine") or "v1") != "v3":
                skipped.append({"sync": name, "reason": "engine_not_v3",
                                "he": f"'{name}' פועל על מנוע v1 — הרצה ידנית מפעילה את מנוע v3 בלבד"})
            else:
                runnable.append(e)

        claimed, errors, stamped, runs, held = 0, [], 0, [], 0
        for entry in runnable:
            name = str(entry["name"])
            outcome = _scan_outcome(name)
            ref = outcome["ref"]
            # The execution is recorded for EVERY outcome, and the ones that did nothing matter
            # most: a run that reported nothing is exactly when someone needs to see what the
            # engine did.
            if ref:
                runs.append({"sync": name, "ok": outcome["status"] == "ran",
                             "status": outcome["status"], **ref})
                # kept on the pipe so the card can still link to it after the toast is gone —
                # a debug link that only exists for five seconds is not a debug link
                entry["last_run_execution"] = ref.get("execution_id")
                entry["last_run_url"] = ref.get("url")
            if outcome["status"] == "skipped":
                skipped.append(_skip_note(name, outcome))
                held += 1
                continue
            if outcome["status"] != "ran":
                errors.append(f"{name}: {outcome['error']}")
                continue
            claimed += outcome["claimed"]
            # `last_run` is stamped per pipe and ONLY for the pipes that really
            # ran. A pipe whose SCAN was refused keeps its previous timestamp,
            # so "last run" answers "when did work last happen here" rather than
            # "when did someone last press the button".
            entry["last_run"] = _now_iso()
            stamped += 1
        try:
            if stamped:
                _write_sync_registry(transport, entries)
            else:
                # nothing ran, so there is nothing to persist — writing the row
                # back unchanged would only invalidate caches and make the failed
                # attempt look like a registry mutation in the supabase log
                _sync_cache_clear()
        except Exception:
            pass
        _sync_cache_clear()
        ran = len(runnable) - len(errors) - held
        # `status` is the one field a caller should branch on, and it exists because `success`
        # alone cannot say "nothing ran, but nothing is broken". `success` stays as it was —
        # "did every pipe we attempted come back clean" — so an existing caller reading only that
        # is not silently given a new meaning.
        status = "error" if errors else ("ran" if ran else ("skipped" if held else "none"))
        return jsonify({"success": not errors, "status": status, "claimed": claimed,
                        "ran": ran,
                        "held": held,
                        "attempted": len(runnable),
                        "errors": errors,
                        "skipped": skipped,
                        "runs": runs,
                        "n8n_base": _n8n_public_base(),
                        "registry": _enrich_registry(transport, entries, _scope(reg))})

    # ----- /config/* : read/write the supabase INDOX config tables ------------
    #
    # The SPA cannot reach supabase directly (different origin, service key
    # server-side only), so the BFF is the single front door — same pattern as
    # /sync/registry above. All reads degrade gracefully to
    # ``{..., reachable: false, error}`` and NEVER 500 (a missing table just
    # renders as an empty state in the UI). Only writes to the small allowlist
    # of scalar/toggle settings keys are permitted.
    def _config_transport():
        from ..backends.supabase_transport import HttpxSupabaseTransport

        return HttpxSupabaseTransport()

    _CONFIG_READ_LIMIT = 2000

    @bp.get("/config/settings")
    def config_settings():
        """All rows from `settings` (key/value). Values can be large JSON —
        returned as-is; the UI decides how to render each key."""
        try:
            rows = _config_transport().select(
                schema=_request_schema(),
                table="settings",
                select=["key", "value"],
                filter=_tenant(),
                limit=_CONFIG_READ_LIMIT,
            )
        except Exception as e:  # supabase unreachable / table missing
            return jsonify({"settings": [], "reachable": False, "error": str(e)})
        settings = [
            {"key": r.get("key"), "value": r.get("value")}
            for r in rows
            if isinstance(r, dict)
        ]
        # the closed allowlist, plus every OPEN-family key that actually has a row:
        # the client renders an editor per key it is told about, and a pattern is not
        # a list it can check against
        editable = set(_EDITABLE_SETTINGS_KEYS)
        editable.update(
            s["key"] for s in settings
            if isinstance(s.get("key"), str) and _is_editable_setting_key(s["key"])
        )
        return jsonify(
            {
                "settings": settings,
                "editable_keys": sorted(editable),
                "reachable": True,
            }
        )

    @bp.get("/config/companies")
    def config_companies():
        """All rows from `companies` (SELECT *, Hebrew-keyed columns as-is).
        Paged read — complete even at ERP scale (PostgREST caps single
        requests at 1000 rows)."""
        try:
            rows = _paged_select(_config_transport(), table="companies", filter=_tenant())
        except Exception as e:
            return jsonify({"companies": [], "reachable": False, "error": str(e)})
        return jsonify({"companies": rows, "reachable": True})

    # /config/tag_rules is GONE (2026-09-03, owner Decision N1): the label rules have one store,
    # the mail app's organizer settings, edited in the mail console. The INDOX tab that showed a
    # read-only copy went with it; the Postgres table is renamed tag_rules_retired_20260903.

    @bp.put("/config/settings/<key>")
    def config_settings_put(key: str):
        """Upsert a single `settings` row — allowlisted scalar/toggle keys only.

        Two allowlists: the closed set of named scalars/toggles, and the open
        per-action router-cap family (`…action_router[.<ACTION>].max`), which is
        matched by pattern and range-checked here.

        Idempotent upsert by primary key ``key`` (no idempotency-key needed).
        400 if the key is not editable or the value is out of range;
        ``{reachable:false}`` if supabase is unreachable.
        """
        if not _is_editable_setting_key(key):
            raise ValidationError(
                f"settings key '{key}' is not editable from this endpoint",
                editable_keys=sorted(_EDITABLE_SETTINGS_KEYS),
            )
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "value" not in body:
            raise ValidationError("request body must be a JSON object with a 'value'")
        value = _coerce_settings_value(body["value"])
        if _ROUTER_CAP_RE.match(key):
            # a cap is a batch SIZE: 0 / "" / "abc" would leave the router emitting no
            # chunk for that action, which reads as "the action stopped" and not as a
            # bad setting. Reject it at the write, and store the normalized integer.
            try:
                capped = int(str(value).strip())
            except (TypeError, ValueError):
                capped = None
            if capped is None or not (_ROUTER_CAP_MIN <= capped <= _ROUTER_CAP_MAX):
                raise ValidationError(
                    f"router cap '{key}' must be a whole number between "
                    f"{_ROUTER_CAP_MIN} and {_ROUTER_CAP_MAX}"
                )
            value = str(capped)
        if key == "indox.extraction.type_priority":
            # A CLOSED VOCABULARY, normalized on write. SelectBase01 upper-cases what it reads and
            # compares it to 'AI' literally, so every other string — 'ai ', 'Local', 'gemini', a
            # typo — silently means LOCAL. That is a setting that looks changed and is not, which
            # is the failure this whole endpoint's range-checking exists to prevent.
            norm = str(value).strip().upper()
            if norm not in {"LOCAL", "AI"}:
                raise ValidationError(
                    f"indox.extraction.type_priority must be 'LOCAL' or 'AI' (got '{value}')")
            value = norm
        try:
            rows = _config_transport().upsert(
                schema=_request_schema(),
                table="settings",
                on_conflict="instance,key",
                rows=[{"instance": _instance(), "key": key, "value": value}],
            )
        except ValidationError:
            raise  # constraint / type error — surface as 400 to the user
        except Exception as e:  # supabase unreachable / backend outage
            return jsonify({"reachable": False, "error": str(e)}), 200
        _invalidate_settings_cache()  # H5: make the write visible now, not up to 20 min from now
        updated = rows[0] if rows else {"key": key, "value": value}
        return jsonify({"success": True, "setting": updated, "reachable": True})

    # ----- /config/<table>/<row_id> : inline-edit a companies cell
    #
    # Powers the editable data grid. UPDATE-ONLY (verifies the row exists first —
    # never creates via this path) and column-guarded (id / created_at are never
    # writable). Single-cell body {key, value}; merge-upsert on the table PK so
    # only the one column changes. The label rules are the mail app's (organizer
    # settings, edited in the mail console) — no rules table exists here any more.
    _EDITABLE_CONFIG_TABLES = {
        "companies": {"pk": "id", "deny": frozenset({"id", "created_at"})},
    }

    @bp.post("/config/unlock-all")
    def config_unlock_all():
        """Release EVERY doc_action process lock (the console settings operator button).

        Key shape (processLock01): ``n8n.process_lock.doc_action.<ID>::<ACTION>``. The locks
        are advisory — the driver's check_and_lock re-acquires per action and the dup-guard
        catches a genuine double entry — so the worst case of releasing one mid-work is a
        loud, blocked repeat, not corruption. Static route wins over ``/config/<table>``
        (werkzeug prefers static parts), so this never collides with the table editor."""
        try:
            cli = _actions_redis()
            released = 0
            cursor = 0
            while True:
                cursor, batch = cli.scan(
                    cursor=cursor, match="n8n.process_lock.doc_action.*", count=500)
                if batch:
                    released += cli.delete(*batch)
                if cursor == 0:
                    break
            return jsonify({"ok": True, "released": released})
        except Exception as e:  # redis unreachable — degrade, never 500
            return jsonify({"ok": False, "reachable": False, "error": str(e)}), 200

    @bp.post("/config/stop-all")
    def config_stop_all():
        """ONE-CLICK EMERGENCY STOP for the INDOX pipeline (console settings button).

        Order matters:
          1. ``indoxDrainOn=false`` — no new feeding (drainer quota lane + hourly sweep).
          2. n8n owner login (the same flow bbox's verify hook uses) → stop every running/
             queued execution via the internal ``POST /rest/executions/<id>/stop``.
          3. Flush the Bull queue lists, 3 passes over ~4s — self-POST continuations that
             were mid-flight land in the queue and must die there, not get picked up.
          4. Release all doc_action locks — killed executions leak theirs (measured 358,
             then 315, on the two manual stops this button replaces).
        Every stage degrades independently and the response says exactly what ran."""
        out: dict = {"ok": True}
        try:
            _config_transport().upsert(
                schema=_request_schema(), table="settings", on_conflict="instance,key",
                rows=[{"instance": _instance(), "key": "indoxDrainOn", "value": "false"}])
            out["gate"] = "false"
            # and sync (indoxSyncOn, the per-tenant sync gate syncV3Main0001 reads under its lock)
            _config_transport().upsert(
                schema=_request_schema(), table="settings", on_conflict="instance,key",
                rows=[{"instance": _instance(), "key": "indoxSyncOn", "value": "false"}])
            out["sync_gate"] = "false"
            # and the master (indoxOn, owner Decision 4 completed 2026-09-02): the one switch both
            # lanes read beside their own — an emergency stop shows as ONE red switch in settings,
            # and turning the pipeline back on is one flip there.
            _config_transport().upsert(
                schema=_request_schema(), table="settings", on_conflict="instance,key",
                rows=[{"instance": _instance(), "key": "indoxOn", "value": "false"}])
            out["master"] = "false"
        except Exception as e:
            out["ok"] = False
            out["gate_error"] = str(e)

        stopped = 0
        try:
            import httpx  # lazy
            base = os.environ.get("N8N_REST_BASE", "http://n8n:5678")
            email = os.environ.get("N8N_OWNER_EMAIL")
            pw = os.environ.get("N8N_OWNER_PASSWORD")
            if email and pw:
                import time as _t2
                rcli = _actions_redis()
                rounds = 0
                with httpx.Client(base_url=base, timeout=20.0) as ncli:
                    ncli.post("/rest/login",
                              json={"emailOrLdapLoginId": email, "password": pw}
                              ).raise_for_status()
                    # INTERLEAVED ROUNDS until quiet (≤5): stopping a parent does not cascade
                    # to sub-executions, and every finishing child self-POSTs one more hop into
                    # the queue — so each round stops what runs AND flushes what queued, then
                    # re-checks. One round provably does not converge (measured 2026-08-16:
                    # extraction children + the self-POST tail survived it).
                    for rnd in range(5):
                        rounds = rnd + 1
                        q = ncli.get("/rest/executions", params={
                            "filter": json.dumps({"status": ["new", "running"]}),
                            "limit": 250})
                        body = q.json() if q.status_code == 200 else {}
                        data = body.get("data") if isinstance(body, dict) else None
                        results = data.get("results") if isinstance(data, dict) else data
                        ids = [str(row["id"]) for row in (results or [])
                               if isinstance(row, dict) and row.get("id") is not None]
                        for eid in ids:
                            try:
                                s = ncli.post(f"/rest/executions/{eid}/stop")
                                if s.status_code < 300:
                                    stopped += 1
                            except Exception:
                                pass
                        try:
                            rcli.delete("bull:jobs:wait", "bull:jobs:delayed",
                                        "bull:jobs:prioritized", "bull:jobs:paused")
                        except Exception:
                            pass
                        if not ids:
                            break
                        _t2.sleep(2)
                out["stopped"] = stopped
                out["stop_rounds"] = rounds
            else:
                out["stopped_error"] = "N8N_OWNER_EMAIL/PASSWORD not configured"
        except Exception as e:
            out["stopped"] = stopped
            out["stopped_error"] = str(e)

        try:
            import time as _t
            rcli = _actions_redis()
            flushes = 0
            for i in range(3):
                flushes += int(rcli.delete("bull:jobs:wait", "bull:jobs:delayed",
                                           "bull:jobs:prioritized", "bull:jobs:paused") or 0)
                if i < 2:
                    _t.sleep(2)
            out["queue_flushes"] = flushes
        except Exception as e:
            out["queue_error"] = str(e)

        try:
            rcli = _actions_redis()
            released = 0
            cursor = 0
            while True:
                cursor, batch = rcli.scan(
                    cursor=cursor, match="n8n.process_lock.doc_action.*", count=500)
                if batch:
                    released += rcli.delete(*batch)
                if cursor == 0:
                    break
            out["locks_released"] = released
        except Exception as e:
            out["locks_error"] = str(e)
        return jsonify(out)

    @bp.patch("/config/<table>/<row_id>")
    def config_row_patch(table: str, row_id: str):
        meta = _EDITABLE_CONFIG_TABLES.get(table)
        if not meta:
            raise ValidationError(f"table '{table}' is not editable")
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "key" not in body:
            raise ValidationError("request body must be a JSON object with a 'key' and 'value'")
        key = str(body.get("key"))
        value = body.get("value")
        pk = meta["pk"]
        if key in meta["deny"] or key == pk:
            raise ValidationError(f"column '{key}' is not editable")
        # coerce a numeric PK so PostgREST matches the int column exactly
        pk_val: object = row_id
        try:
            pk_val = int(row_id)
        except (TypeError, ValueError):
            pk_val = row_id
        try:
            transport = _config_transport()
            existing = transport.select(
                schema=_request_schema(), table=table, select=[pk],
                filter=_tenant({pk: pk_val}), limit=1)
            if not existing:
                return jsonify({"ok": False, "error": "row not found"}), 404
            # pure UPDATE (PATCH) — companies.id is GENERATED ALWAYS, so a
            # merge-upsert (which names the PK in its INSERT clause) is rejected.
            rows = transport.update(
                schema=_request_schema(), table=table,
                match=_tenant({pk: pk_val}), values={key: value})
        except ValidationError:
            raise
        except Exception as e:  # supabase unreachable / constraint — never 500
            return jsonify({"ok": False, "reachable": False, "error": str(e)}), 200
        updated = rows[0] if rows else {pk: pk_val, key: value}
        return jsonify({"ok": True, "row": updated})

    @bp.post("/config/<table>")
    def config_row_add(table: str):
        """Add a row to an editable config table. Body may seed columns; the
        GENERATED-ALWAYS PK is assigned by the DB. Returns the new row."""
        meta = _EDITABLE_CONFIG_TABLES.get(table)
        if not meta:
            raise ValidationError(f"table '{table}' is not editable")
        body = request.get_json(silent=True) or {}
        pk = meta["pk"]
        seed = {
            k: v for k, v in body.items()
            if isinstance(k, str) and k != pk and k not in meta["deny"]
            and k != "instance"
        }
        # The INSERT must carry `instance` itself — PATCH/DELETE scope through a
        # filter, but an insert has no row to filter, so the column is the only
        # place the component can be stated. Without it the transport's tenant
        # gate rejects the write (correctly: an unscoped row lands on the default
        # instance), which is exactly how "＋ הוסף שורה" and CSV/XLSX import both
        # failed SILENTLY — the UI only reads `ok`, and never showed the reason.
        # A client-supplied `instance` is dropped above rather than honoured: the
        # server decides which component it is writing, never the browser.
        seed["instance"] = _instance()
        try:
            rows = _config_transport().insert(
                schema=_request_schema(), table=table, rows=[seed])
        except ValidationError:
            raise
        except Exception as e:  # supabase unreachable / constraint — never 500
            return jsonify({"ok": False, "reachable": False, "error": str(e)}), 200
        return jsonify({"ok": True, "row": rows[0] if rows else seed})

    @bp.delete("/config/<table>/<row_id>")
    def config_row_delete(table: str, row_id: str):
        """Delete a row from an editable config table by its PK."""
        meta = _EDITABLE_CONFIG_TABLES.get(table)
        if not meta:
            raise ValidationError(f"table '{table}' is not editable")
        pk = meta["pk"]
        pk_val: object = row_id
        try:
            pk_val = int(row_id)
        except (TypeError, ValueError):
            pk_val = row_id
        try:
            # instance-scoped, like every other read/write on a tenant table — an
            # unscoped delete is refused by the transport gate, which is what made
            # both the row ✕ and the bulk "מחק N" do nothing at all.
            _config_transport().delete(
                schema=_request_schema(), table=table, match=_tenant({pk: pk_val}))
        except ValidationError:
            raise
        except Exception as e:  # supabase unreachable — never 500
            return jsonify({"ok": False, "reachable": False, "error": str(e)}), 200
        return jsonify({"ok": True, "id": pk_val})

    # ----- /tests/* : drive the INDOX n8n E2E suites (sync + state machine)
    #
    # The SPA stays self-contained: it never talks to n8n directly. All three
    # endpoints degrade gracefully and never 500 when n8n is unreachable.
    @bp.get("/tests/suites")
    def tests_suites():
        """List the INDOX n8n E2E test suites + their last-run pass/fail summary."""
        reachable = True
        err = None
        # light reachability probe of the n8n host (webhook base's origin + /healthz)
        try:
            import httpx  # lazy

            origin = _n8n_webhook_base().rsplit("/webhook", 1)[0]
            with httpx.Client(timeout=5.0) as c:
                c.get(origin + "/healthz")  # any HTTP response = host reachable
        except Exception as e:  # connection refused / DNS flap → n8n down
            reachable = False
            err = str(e)
        suites = []
        for key, cfg in _N8N_TEST_SUITES.items():
            last = _TEST_LAST.get(key) or {}
            suites.append(
                {
                    "name": key,
                    "label": cfg["label"],
                    "group": cfg["group"],
                    "description": cfg["description"],
                    "case_count": last.get("case_count", len(cfg["lanes"])),
                    "cases_passed": last.get("cases_passed"),
                    "all_passed": last.get("all_passed"),
                    "last_run": last.get("last_run"),
                }
            )
        return jsonify(
            {"suites": suites, "groups": _TEST_GROUPS, "reachable": reachable, "error": err}
        )

    @bp.post("/tests/run")
    def tests_run():
        """Start a run — a single suite (body ``{suite}``), a whole group
        (``{group}``), or everything. Returns ``{run_id}`` immediately; lanes fire
        concurrently in a background thread tracked in ``_TEST_RUNS``."""
        body = request.get_json(silent=True) or {}
        suite = body.get("suite") or None
        group = body.get("group") or None
        if suite and suite in _N8N_TEST_SUITES:
            suite_keys = [suite]
        elif group:
            suite_keys = [k for k, c in _N8N_TEST_SUITES.items() if c["group"] == group]
        else:
            suite_keys = list(_N8N_TEST_SUITES.keys())
        if not suite_keys:
            return jsonify({"error": "unknown suite/group"}), 400
        cases_total = sum(len(_N8N_TEST_SUITES[k]["lanes"]) for k in suite_keys)
        run_id = uuid.uuid4().hex
        with _TEST_RUNS_LOCK:
            # prune old finished runs so the dict can't grow unbounded
            if len(_TEST_RUNS) > 40:
                stale = [
                    k for k, v in _TEST_RUNS.items() if v.get("status") != "running"
                ]
                for k in stale[: len(_TEST_RUNS) - 40]:
                    _TEST_RUNS.pop(k, None)
            _TEST_RUNS[run_id] = {
                "run_id": run_id,
                "suite": suite,
                "status": "running",
                "started": _now_iso(),
                "finished": None,
                "cases_total": cases_total,
                "cases_done": 0,
                "passed": 0,
                "failed": 0,
                "per_case": [],
                "error": None,
            }
        threading.Thread(
            target=_run_tests_bg, args=(run_id, suite_keys), daemon=True
        ).start()
        return jsonify({"run_id": run_id})

    @bp.get("/tests/run/<run_id>")
    def tests_run_status(run_id: str):
        """Return the live progress object for a run (404 if unknown)."""
        with _TEST_RUNS_LOCK:
            run = _TEST_RUNS.get(run_id)
            if run is None:
                return jsonify({"run_id": run_id, "status": "unknown"}), 404
            return jsonify(dict(run))

    # ----- /dashboard/stats : the maintained read model for the ops dashboard
    #
    # Used to be one paged read of the WHOLE live supabase table, aggregated in Python, on every
    # request — see the `indox_dashboard_stats` block comment above `_compute_dashboard_stats_payload`
    # for the full story (measured 1.2-2.2s at 6,250 rows; unbounded past it). This is now one
    # primary-key SELECT into that maintained table. Degrades gracefully (never 500).
    @bp.get("/dashboard/stats")
    def dashboard_stats():
        # The dashboard is the ACTIVE instance's dashboard — it sits under the
        # same instance chip as everything else. It used to read the literal
        # `incoming_documents`, so switching company changed the chip and left
        # every number on the screen describing the previous company's table.
        scope = _scope(reg)
        if not scope.doc_table:
            # gsheet-backed (or nothing registered): there is no supabase table to
            # aggregate. Saying so is the same degradation an unreachable supabase
            # gets — and is strictly better than showing another instance's totals.
            return jsonify({"reachable": False,
                            "error": "the active INDOX instance has no supabase "
                                     "document table to aggregate"})

        # ----- time window (?win=all|15m|30m|1h|today|month, &tz=<getTimezoneOffset>)
        # `all` (the default) is the maintained read-model fast path below —
        # byte-identical behaviour to before the window existed. A narrow window
        # is computed LIVE against a `created_at >= …` SQL filter instead: the
        # read model stores exactly one payload per table (the all-time one),
        # and a windowed row set is small BY CONSTRUCTION (the WHERE clause cuts
        # it down server-side), so a live aggregate over it is cheap where the
        # all-time one was not. A short shared cache absorbs the 15s UI poll.
        # `win` is echoed so the UI can prove which window the SERVER actually
        # applied rather than trusting the one it asked for.
        win = (request.args.get("win") or "all").strip().lower()
        if win not in _DASH_WINDOWS:
            win = "all"
        # ----- driving column (?basis=created_at|updated_at|TIMESTAMP|doc_date_norm)
        # Absent -> `created_at`, i.e. exactly the column this endpoint used to
        # hard-code. Echoed below for the same reason `win` is: so the UI can
        # prove which column the SERVER cut on.
        basis = _dash_basis(request.args.get("basis"))
        tz_arg = request.args.get("tz")
        since_iso = _dash_win_since(win, tz_arg)
        if since_iso is not None:
            try:
                transport = _sync_transport()
                # THE BASIS IS PART OF THE CACHE KEY. Without it the 10s shared
                # cache would happily serve `created_at`'s aggregate to an
                # `updated_at` request — the two differ by two orders of
                # magnitude in a 30m window, so that is not a rounding error,
                # it is the original bug wearing a different hat.
                # THE SCHEMA TOO: scope.doc_table is the same string in every
                # instance schema, so without it a levi request inside the TTL
                # of a hacohen request was served hacohen's window aggregate.
                payload = _sync_cached(
                    f"dashwin:{_request_schema()}:{scope.doc_table}:{win}:"
                    f"{request.args.get('tz') or ''}:{basis}",
                    _TTL_DASH_WIN,
                    lambda: _compute_dashboard_stats_payload(
                        transport, scope.doc_table, since_iso=since_iso,
                        basis=basis, tz_off_min=tz_arg),
                )
            except Exception as e:
                # includes a doc table that predates the `created_at` column —
                # reporting the real reason beats silently widening to all-time
                # and labelling a full aggregate as a filtered one
                return jsonify({"reachable": False, "error": str(e),
                                "win": win, "since": since_iso,
                                "basis": basis, "bases": _dash_bases_catalogue()})
            return jsonify({
                "reachable": True,
                "instance": scope.instance,
                "table": scope.doc_table,
                "computed": True,
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "win": win,
                # `win_effective` differs from `win` ONLY on a day-granularity
                # basis, where 30m/1h cannot mean anything narrower than the
                # day. Saying so is the whole point: a board carrying a day's
                # numbers under a "30 דק׳" label is a lie the UI would have no
                # way to detect. `since_applied` is the bound that ACTUALLY went
                # into the WHERE clause, in the basis column's own shape, so the
                # claim is checkable against SQL rather than trusted.
                "win_effective": _dash_win_effective(win, basis),
                "since": since_iso,
                "since_applied": _dash_since_for_basis(since_iso, basis, tz_arg),
                "basis": basis,
                "basis_active": True,
                "bases": _dash_bases_catalogue(),
                **payload,
            })

        try:
            transport = _sync_transport()
            row = _dashboard_stats_read(transport, scope.doc_table)
        except Exception as e:  # supabase unreachable — never 500
            return jsonify({"reachable": False, "error": str(e)})

        if row is None or not row.get("payload"):
            # COLD START ONLY: nothing computed yet for this table (fresh DB, or the trigger
            # migration has not been applied). Compute once, synchronously, and write it back so
            # every request after this one is the fast path — the background loop then keeps it
            # warm. This is the one place this endpoint can still be slow, and only ever once
            # per doc_table for the lifetime of the process (or until the row is lost).
            try:
                payload = _compute_dashboard_stats_payload(transport, scope.doc_table)
                _dashboard_stats_write(transport, scope.doc_table, payload, None)
            except Exception as e:
                return jsonify({"reachable": False, "error": str(e)})
            computed_at = datetime.now(timezone.utc).isoformat()
        else:
            payload = row.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = {}
            computed_at = row.get("updated_at")
            if row.get("error") and not payload:
                return jsonify({"reachable": False, "error": row["error"]})

        return jsonify({
            "reachable": True,
            # stated in the payload so "which instance is this counting?" is
            # answerable from the response alone — the bug this replaced was
            # invisible precisely because the answer was never written down
            "instance": scope.instance,
            "table": scope.doc_table,
            "computed": True,
            "computed_at": computed_at,
            "win": "all",
            "since": None,
            # `all` applies NO time filter, so no column is driving anything —
            # the maintained read model is one payload per table and is
            # basis-independent by construction. The requested basis is echoed
            # (so the UI's control keeps its selection across a switch to
            # "הכל"), but `basis_active:false` says plainly that it is not
            # cutting anything right now. Claiming otherwise would be the
            # cache-key bug in reverse: the right numbers, mislabelled.
            "basis": basis,
            "basis_active": False,
            "bases": _dash_bases_catalogue(),
            **payload,
        })

    # ----- /dashboard/actions : the action-log timeline (see the ACTION LOG block above)
    #
    # Same window vocabulary as /dashboard/stats — `?win=` + `?tz=` — because it is the SAME
    # control on the same page. What it deliberately does NOT take is `?basis=`: a basis picks
    # which DOCUMENT DATE COLUMN a window cuts on, and an action is not a document. Its instant
    # is the epoch inside its own stamp, so "the last 30 minutes" here means the actions of the
    # last thirty minutes, on whatever documents. (The pairing stays coherent because the UI
    # already forbids the one combination that would disagree: selecting a day-granularity
    # basis moves a sub-day window to `today` before either panel asks for anything.)
    #
    # `?limit/offset` page the TIMELINE, not the documents, `?cls/label/q` filter it and
    # `?sort/dir` order it. All of them are served from ONE cached scan, so paging, sorting
    # and filtering cost a list walk rather than another 13-19 MB read.
    #
    @bp.post("/dashboard/actions/purge")
    def dashboard_actions_purge():
        """Delete the dispatch-log rows of ONE time window (owner button on the log page).

        Body: {"win": "<same vocabulary as GET /dashboard/actions>", "tz": "<IANA tz>"}.
        Deletes from public.indox_action_execution_log WHERE STARTED_AT >= window start
        (win=all → the whole table). Straight PostgREST filtered DELETE with the service
        key — the same trust path every config write here already uses. Returns the count
        it deleted, counted immediately before the delete on the same filter."""
        body = request.get_json(silent=True) or {}
        win = str(body.get("win") or "all").strip().lower()
        if win not in _DASH_WINDOWS:
            win = "all"
        since_iso = _dash_win_since(win, body.get("tz"))
        # A DESTRUCTIVE ROUTE THAT WAS CROSS-TENANT. It built a raw PostgREST DELETE against
        # `{base}/rest/v1/<table>` with NO schema at all, so it always hit `public` — purging the
        # action log while viewing `לוי` deleted הכהן's rows, and it would 404 outright the moment
        # the compat views come down. It now goes through the same transport every other read and
        # write uses, so it lands in the schema the request is scoped to and nowhere else.
        try:
            transport = _sync_transport()
            schema = _request_schema()
            flt: dict[str, Any] = (
                {"STARTED_AT": {"op": "gte", "value": since_iso}} if since_iso
                else {"STARTED_AT": {"op": "not_null"}}
            )
            # Counted immediately before the delete, on the same filter, so the number reported
            # is what was actually removed rather than an estimate.
            total = transport.count(schema=schema, table=_ACTIONS_PG_TABLE, filter=flt)
            if since_iso:
                transport.delete(schema=schema, table=_ACTIONS_PG_TABLE,
                                 match={"STARTED_AT": {"op": "gte", "value": since_iso}})
            else:
                transport.delete(schema=schema, table=_ACTIONS_PG_TABLE,
                                 match={"STARTED_AT": {"op": "not_null"}})
            return jsonify({"ok": True, "deleted": total, "win": win, "since": since_iso,
                            "schema": schema})
        except Exception as e:  # supabase unreachable — degrade, never 500
            return jsonify({"ok": False, "error": str(e), "win": win}), 200

    # `cls` and `label` accept a COMMA-SEPARATED list (`cls=blocked,no_action`), because the
    # grid's header filter is a multi-select checkbox list. A single value is the same request
    # it always was, so nothing that already calls this endpoint has to change.
    @bp.get("/dashboard/actions")
    def dashboard_actions():
        scope = _scope(reg)
        if not scope.doc_table:
            return jsonify({"reachable": False,
                            "error": "the active INDOX instance has no supabase "
                                     "document table to read an action log from"})

        win = (request.args.get("win") or "all").strip().lower()
        if win not in _DASH_WINDOWS:
            win = "all"
        tz_arg = request.args.get("tz")
        since_iso = _dash_win_since(win, tz_arg)

        def _int(name: str, default: int, lo: int, hi: int) -> int:
            try:
                return max(lo, min(hi, int(request.args.get(name, default))))
            except (TypeError, ValueError):
                return default

        limit = _int("limit", _ACTIONS_LIMIT_DEFAULT, 1, _ACTIONS_LIMIT_MAX)
        offset = _int("offset", 0, 0, 10_000_000)
        # multi-select capable; unknown class names are DROPPED rather than erroring, and an
        # all-unknown list leaves no filter at all — an unrecognised value must widen, never
        # silently show zero rows under a filter chip the server did not understand.
        cls_sel = {c for c in _csv_arg(request.args.get("cls")) if c.lower() in _ACTION_CLASSES}
        cls_sel = {c.lower() for c in cls_sel}
        label_sel = set(_csv_arg(request.args.get("label")))
        q = (request.args.get("q") or "").strip().lower()
        sort = (request.args.get("sort") or "ts").strip().lower()
        if sort not in _ACTION_SORT_KEYS:
            sort = "ts"
        desc = (request.args.get("dir") or "desc").strip().lower() != "asc"

        # SOURCE: the router's dispatch-bracket TABLE (see _actions_scan_pg) — real dispatches
        # only, one row per (doc, action, execution), duration + done state per row.
        #
        # [2026-08-21] `?source=log` is GONE, with the ACTION_LOG column it read. It survived the
        # 2026-08-16 switch only because it was still the sole reader of the pre-bracket history;
        # that history has since been backfilled into the columns that needed it
        # (GMAIL_LABELS_COMPLETED / FAILED_FOLDER_COMPLETED) and archived whole in
        # _actionlog_backup_20260820. The parameter is accepted and ignored rather than rejected,
        # so a bookmarked `?source=log` URL still renders instead of 400-ing; the response says
        # which source actually answered.
        source = "pg"
        ttl = _TTL_DASH_ACTIONS if win in _DASH_WINDOW_SECONDS else _TTL_DASH_ACTIONS_WIDE
        try:
            # 10s cache: liveness the eye can't distinguish from live, at 1/Nth the
            # table load — a full day is ~151k rows and the page polls every few seconds
            scan = _actions_cached(
                f"pg:{scope.instance}:{win}:{tz_arg or ''}",
                _ACTIONS_LIVE_CACHE_S,
                lambda: _actions_scan_pg(since_iso),
            )
        except Exception as e:  # redis/supabase unreachable — degrade, never 500
            return jsonify({"reachable": False, "error": str(e), "win": win,
                            "source": source, "since": since_iso})

        stamps = scan["stamps"]
        docs = scan["docs"]
        # DUPLICATE-PAIR DETECTION (owner order 2026-08-16): the same (doc, action) in more
        # than one execution should never happen — when it does it must POP OUT. Counted on
        # every request over the whole window so the UI badge is always current; `?dup=1`
        # filters to exactly those rows and orders them grouped (doc, action, newest first)
        # so each pair sits together. pg source only — the legacy ACTION_LOG parser repeats
        # (doc, label) legitimately on every pass, so the count would be meaningless there.
        dup_only = (request.args.get("dup") or "").strip().lower() in ("1", "true")
        dup_pairs = dup_rows = None
        if source != "log":
            from collections import Counter as _Counter
            pair_n = _Counter((s[3], s[2]) for s in stamps)
            dup_pairs = sum(1 for c in pair_n.values() if c > 1)
            dup_rows = sum(c for c in pair_n.values() if c > 1)
            if dup_only:
                stamps = sorted((s for s in stamps if pair_n[(s[3], s[2])] > 1),
                                key=lambda s: (s[3], s[2], -s[0]))
        if cls_sel:
            stamps = [s for s in stamps if _action_class(s[2]) in cls_sel]
        if label_sel:
            stamps = [s for s in stamps if s[2] in label_sel]
        if q:
            # every column the grid actually PRINTS — the action, the document id and its
            # name. A search box over a table that searched two of its five visible columns
            # would look broken from the one row it failed to find.
            stamps = [s for s in stamps
                      if q in s[3].lower() or q in s[2].lower()
                      or q in (docs.get(s[3], {}).get("name") or "").lower()]
        matched = len(stamps)

        # ORDER. The scan is already newest-first, so the default costs nothing and `ts asc`
        # is a reversal; every other key sorts the FILTERED list (≤ retained, measured ~150ms
        # at the 200,000 cap) rather than the window.
        #
        # NO EXPLICIT TIE-BREAK KEY, on purpose: `sorted` is stable and the input is already
        # in newest-first order, so equal keys keep it — in BOTH directions. Folding the tie
        # break into the sort key as `(key, -seq)` would have been the obvious move and is
        # wrong: `reverse=True` reverses the WHOLE tuple, so descending would have ordered
        # ties oldest-first while ascending ordered them newest-first.
        if sort == "ts":
            if not desc:
                stamps = stamps[::-1]
        else:
            keyfn = _ACTION_SORT_KEYS[sort]
            stamps = sorted(stamps, key=lambda s: keyfn(s, docs), reverse=desc)
        page = stamps[offset:offset + limit]

        return jsonify({
            "reachable": True,
            "instance": scope.instance,
            "table": scope.doc_table,
            "source": source,
            "dup": dup_only,
            "dup_pairs": dup_pairs,
            "dup_rows": dup_rows,
            "win": win,
            "since": since_iso,
            # the epoch the rows were actually cut on — the claim this panel makes is
            # checkable against the numbers it prints, rather than trusted
            "since_ms": (int(datetime.fromisoformat(since_iso).timestamp() * 1000)
                         if since_iso else None),
            "scanned_at": scan["scanned_at"],
            "scanned_rows": scan["scanned_rows"],
            "rows_capped": scan["rows_capped"],
            # how much of what was scanned the parser could attribute to an action
            "ts_tokens": scan["ts_tokens"],
            "stamps_parsed": scan["stamps_parsed"],
            "unparsed": scan["unparsed"],
            # `window_total` = every action in the window (exact). `retained` = how many of
            # them this endpoint can page through. `matched` = how many survive the filters.
            "window_total": scan["window_total"],
            "retained": scan["retained"],
            "truncated": scan["truncated"],
            "matched": matched,
            "limit": limit,
            "offset": offset,
            # echoed as the server READ them, so a grid chip that says "נחסם" can be checked
            # against what was actually applied rather than trusted
            "cls": sorted(cls_sel),
            "label": sorted(label_sel),
            "q": request.args.get("q") or "",
            "sort": sort,
            "dir": "desc" if desc else "asc",
            "labels": scan["labels"],
            "classes": scan["classes"],
            "rows": [{
                "ts": s[0],
                "label": s[2],
                "cls": _action_class(s[2]),
                "id": s[3],
                "name": docs.get(s[3], {}).get("name") or "",
                "status": docs.get(s[3], {}).get("status") or "",
                "exec": s[4] or None,
                # pg source only: dispatch duration + completion. The legacy ACTION_LOG
                # parser emits 5-tuples, so these render as None there — the UI shows "—".
                "dur_s": s[5] if len(s) > 5 else None,
                "done": s[6] if len(s) > 6 else None,
            } for s in page],
        })

    # ----- /dashboard/actions/document/<id> : ONE document's whole timeline
    #
    # The drill-down behind a row of the action log. Deliberately NOT windowed: the question it
    # answers is "what happened to this document, in order, from the beginning" — the timeline
    # view above it already owns "what happened in this window".
    #
    # [2026-08-21] SOURCE CHANGED: public.indox_action_execution_log, not the ACTION_LOG column.
    # That column is gone — the state machine stopped deriving anything from it, its 66 writers
    # were removed, and it was dropped. What this endpoint shows changed with it, and honestly:
    #
    #   * it now shows DISPATCHED ACTIONS ONLY. The old parser also surfaced node-level labels
    #     ('Extract Base Doc', 'Update NAME', 'COMPANY RESOLVER <hash>') that were never actions
    #     and exist nowhere else. Nothing decided on them — verified before the removal — but an
    #     operator reading this page sees less detail than before.
    #   * `trimmed`/`log_chars`/`unparsed` are gone with the source they described. There is no
    #     6,000-char middle-trim to warn about any more: the dispatch log is rows, not a string,
    #     so "the whole story" is now an honest claim without a caveat.
    #   * each row gains `dur_s` and `done` — a dispatch is a bracket, so this page can finally
    #     show how long an action took and whether it ever finished.
    #
    # Still deliberately NOT windowed: the question is "what happened to this document, in order,
    # from the beginning". The timeline view above it owns "what happened in this window".
    @bp.get("/dashboard/actions/document/<path:doc_id>")
    def dashboard_actions_document(doc_id: str):
        scope = _scope(reg)
        if not scope.doc_table:
            return jsonify({"reachable": False,
                            "error": "the active INDOX instance has no supabase "
                                     "document table to read an action log from"})
        try:
            transport = _sync_transport()
            head = transport.select(
                schema=_request_schema(), table=scope.doc_table,
                select=["ID", "NAME", "STATUS"],
                filter={"ID": doc_id}, limit=1,
            ) or []
            rows = transport.select(
                schema=_request_schema(), table=_ACTIONS_PG_TABLE,
                select=["ACTION", "EXECUTION_ID", "DOC_STATUS", "STARTED_AT", "ENDED_AT"],
                filter={"ID": doc_id}, limit=_ACTIONS_PG_MAX_ROWS,
            ) or []
        except Exception as e:
            return jsonify({"reachable": False, "error": str(e), "id": doc_id})
        if not head:
            return jsonify({"reachable": True, "found": False, "id": doc_id,
                            "rows": [], "total": 0})

        r = head[0]
        out = []
        for a in rows:
            if not isinstance(a, dict):
                continue
            lab = str(a.get("ACTION") or "").strip()
            if not lab:
                continue
            try:
                st = datetime.fromisoformat(str(a.get("STARTED_AT")))
            except (TypeError, ValueError):
                continue
            dur = None
            if a.get("ENDED_AT"):
                try:
                    dur = round(
                        (datetime.fromisoformat(str(a["ENDED_AT"])) - st).total_seconds(), 2)
                except (TypeError, ValueError):
                    dur = None
            out.append({"ts": int(st.timestamp() * 1000), "label": lab,
                        "ts_raw": str(a.get("STARTED_AT")),
                        "cls": _action_class(lab),
                        "exec": str(a.get("EXECUTION_ID") or "") or None,
                        "dur_s": dur, "done": bool(a.get("ENDED_AT"))})
        # oldest FIRST here, unlike the timeline: one document's history is read as a story,
        # and a story starts at the beginning
        out.sort(key=lambda x: x["ts"])
        return jsonify({
            "reachable": True,
            "found": True,
            "id": r.get("ID") or doc_id,
            "name": r.get("NAME") or "",
            "status": r.get("STATUS") or "",
            "rows": out,
            "total": len(out),
            "classes": {c: sum(1 for x in out if x["cls"] == c) for c in _ACTION_CLASSES},
            "first_ts": out[0]["ts"] if out else None,
            "last_ts": out[-1]["ts"] if out else None,
            "open": sum(1 for x in out if not x["done"]),
        })

    # ── GET /timeline/spans — INDOX projected as concurrency spans ────────────────────────────
    #
    # Feeds the `מסמכים נכנסים` section of any-concurrency, which pulls this endpoint as a
    # `SPAN_SOURCE_INDOX` lane (declared in apps/indox/app.json `contributes.env`; a layer-2 base
    # app may not name a layer-3 app, so the declaration lives here and reconcile.py merges it).
    #
    # WHY THIS SIDE OWNS THE PROJECTION: the two tables it reads are already span tables —
    # `indox_action_execution_log` is literally (STARTED_AT, ENDED_AT) per dispatch and
    # `sync_ledger` is (claimed_at, delivered_at) per item — but knowing that `ACTION_RESTART`
    # means "still moving" while `MERGED` means "at rest for good" is INDOX's knowledge, not the
    # timeline's. So INDOX answers in the timeline's schema and the timeline only draws.
    #
    # Contract (any-concurrency's `span_pull_loop`):
    #   ?hours=<h>  the whole window, served straight through to its /api/spans
    #   ?since=<ms> the delta poll — see _TIMELINE_DELTA_LOOKBACK_S for what "delta" can and
    #               cannot promise here
    @bp.get("/timeline/spans")
    def timeline_spans():
        scope = _scope(reg)
        if not scope.doc_table:
            return jsonify({"spans": [], "reachable": False,
                            "error": "the active INDOX instance has no supabase document table"})

        want = {r for r in _csv_arg(request.args.get("rows")) if r in _TIMELINE_ROWS} or set(_TIMELINE_ROWS)
        try:
            limit = max(1, min(_TIMELINE_LIMIT_MAX,
                               int(request.args.get("limit", _TIMELINE_LIMIT_DEFAULT))))
        except (TypeError, ValueError):
            limit = _TIMELINE_LIMIT_DEFAULT

        # `since` wins over `hours` when both are sent. The lookback is what makes a delta poll
        # able to report a CLOSING span: a bracket that opened 20 minutes ago and stamps ENDED_AT
        # now has a STARTED_AT far behind `since`, so a strict `STARTED_AT >= since` would never
        # re-send it and the timeline would draw it running forever. Anything that outlives the
        # lookback is still corrected by the next full `?hours=` read, which any-concurrency
        # issues on every UI refresh — the delta is an optimisation, never the only path.
        now_ms = int(time.time() * 1000)
        since_raw = request.args.get("since")
        if since_raw is not None:
            try:
                since_ms = max(0, int(float(since_raw)) - int(_TIMELINE_DELTA_LOOKBACK_S * 1000))
            except (TypeError, ValueError):
                since_ms = now_ms - int(_TIMELINE_DELTA_LOOKBACK_S * 1000)
            delta = True
        else:
            try:
                hours = max(0.01, min(_TIMELINE_MAX_HOURS, float(request.args.get("hours", 24))))
            except (TypeError, ValueError):
                hours = 24.0
            since_ms = now_ms - int(hours * 3600 * 1000)
            delta = False
        since_iso = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()

        spans: list[dict] = []
        truncated: list[str] = []
        try:
            transport = _sync_transport()
            if "doc" in want:
                spans.extend(_timeline_doc_spans(transport, scope.doc_table, since_iso,
                                                 limit, delta, truncated))
            if "action" in want:
                spans.extend(_timeline_action_spans(transport, since_iso, limit, truncated))
            if "sync" in want:
                spans.extend(_timeline_sync_spans(transport, since_iso, limit, truncated))
        except Exception as e:
            # Degrade to an empty lane rather than a 500: any-concurrency treats a failed fetch
            # as "serve the ring", and a 200 with `reachable:false` says WHY on /healthz.
            return jsonify({"spans": [], "reachable": False, "error": str(e)})

        spans.sort(key=lambda s: s["s"])
        return jsonify({
            "spans": spans,
            "reachable": True,
            "total": len(spans),
            "since": since_iso,
            "delta": delta,
            # Named explicitly, because a silently-capped list reads as "this is everything that
            # happened" — the one lie a timeline must not tell.
            "truncated": truncated,
        })

    # ══════════════════════════════════════════════════════════════════════
    # PIPELINE COMMAND — see the module-level section above for the two
    # databases, the read-only pinning and why the n8n env var is not
    # `N8N_DB_DSN`.
    # ══════════════════════════════════════════════════════════════════════

    @bp.get("/pipeline/status")
    def pipeline_status():
        """Everything the pipeline bar needs, in ONE poll.

        Three independent sources — INDOX postgres, n8n postgres, redis — each
        degrading alone. `db_available` / `n8n_available` / `locks_available` say
        which of them answered, so the bar can draw "—" for a number nobody
        knows instead of a zero it would have to invent.
        """
        def build():
            scope = _scope(reg)
            indox = _pipeline_indox_numbers(scope.doc_table, scope.instance or _instance(),
                                            _request_schema())
            n8n = _pipeline_n8n_numbers()
            locks = _pipeline_locks()
            payload: dict = {
                "drain": (n8n or {}).get("live"),
                "drivers": int((n8n or {}).get("drivers") or 0),
                "errors_1h": int((n8n or {}).get("errors_1h") or 0),
                "non_terminal": int((indox or {}).get("non_terminal") or 0),
                "action_restart": int((indox or {}).get("action_restart") or 0),
                "dispatch_5m": int((indox or {}).get("dispatch_5m") or 0),
                "parallel": int((indox or {}).get("parallel") or 0),
                "drain_on": bool((indox or {}).get("drain_on")),
                # The DB clock, never this container's and never the browser's.
                # Absent when the database did not answer — a freshness stamp
                # from a fallback clock is the one field that must not guess.
                "as_of": (indox or {}).get("as_of") or "",
                "db_available": indox is not None,
                "n8n_available": n8n is not None,
                **locks,
            }
            return payload

        now = time.monotonic()
        memo_key = _request_schema()
        with _PIPELINE_STATUS_LOCK:
            hit = _PIPELINE_STATUS_MEMO.get(memo_key)
            if hit and float(hit.get("expires") or 0) > now:
                return jsonify(hit.get("value"))
        value = build()  # built outside the lock: it does network I/O
        with _PIPELINE_STATUS_LOCK:
            _PIPELINE_STATUS_MEMO[memo_key] = dict(
                expires=now + _PIPELINE_STATUS_TTL_S, value=value
            )
        return jsonify(value)

    @bp.post("/pipeline/drain")
    def pipeline_drain():
        """Fire exactly ONE drainer.

        THE SINGLE-DRAINER RULE LIVES HERE, not in operator discipline. A drain
        already runs its own pool of `indox.statemachine.drain.parallel` lanes,
        so a second one multiplies the configured ceiling rather than adding
        throughput — measured 2026-08-23, six alive at once put four drivers on
        a six-core host at load 12. If one is alive this answers 409 carrying
        that execution, so the operator lands on the run that already exists.

        A guard that cannot READ is not a guard: an unreachable n8n database
        answers 503 rather than firing blind. Refusing costs a retry; firing
        blind costs the ceiling this rule exists to hold.

        The webhook is deliberately OUTSIDE the `indoxDrainOn` master gate (a
        direct call is operator intent, which is also what makes a dry run
        possible without opening the gate), so this never touches that setting.
        """
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        mode = str(body.get("mode") or "").strip().lower()
        if mode not in ("all", "changed", "ids"):
            raise ValidationError(
                "mode must be one of 'all', 'changed', 'ids'", got=body.get("mode")
            )
        dry = bool(body.get("dry"))
        inst = request.args.get("instance")
        ids: list[str] = []
        if mode == "ids":
            # [one-selector 2026-08-24] mode 'ids' takes `ids` OR a `filter` selector
            # (+`repo`, default the main repo) — the same one-datum contract as
            # documents/bulk and documents/dispatch, resolved by _resolve_selection.
            # Scoped with repo_for like both of those: factory() resolved the filter
            # through the config schema, so a drain fired while viewing instance B
            # enumerated instance A's documents.
            sel_repo = str(body.get("repo") or "incoming-documents-main")
            sel_cfg = reg.get(sel_repo)
            ids, _sel_trunc = _resolve_selection(sel_cfg, repo_for(sel_cfg, inst), body)
            if not ids:
                raise ValidationError("mode 'ids': the selection resolved to no documents")

        user = os.getenv("BS_WEBHOOK_USER", "")
        pw = os.getenv("BS_WEBHOOK_PASS", "")
        url = f"{_n8n_webhook_base()}/indox-drain"

        # check-then-fire under one lock — see _PIPELINE_FIRE_LOCK
        with _PIPELINE_FIRE_LOCK:
            n8n = _pipeline_n8n_numbers()
            if n8n is None:
                return jsonify({
                    "success": False,
                    "error": "drain_guard_unavailable",
                    "message": "לא ניתן לקרוא את מסד הנתונים של n8n, ולכן אי אפשר "
                               "לוודא שאין ניקוז פעיל. הניקוז לא הופעל.",
                }), 503
            if int(n8n.get("drains") or 0) > 0:
                live = n8n.get("live") or {}
                return jsonify({
                    "success": False,
                    "error": "drain_running",
                    "message": "ניקוז כבר רץ. ניקוז שני לא מוסיף קצב — הוא מכפיל "
                               "את תקרת המסלולים. פתח את ההרצה הקיימת.",
                    "execution_id": live.get("execution_id"),
                    "mode": live.get("mode"),
                    "started_at": live.get("started_at"),
                    "n8n_url": live.get("n8n_url"),
                }), 409

            payload: dict = {"mode": mode, "dry": dry}
            if ids:
                payload["ids"] = ids
            # The drain workflow reads body.__instance (Normalize Request) and scopes its whole
            # pass — the solo check, the action-log update and the document walk — to that
            # instance. A drain fired from an instance-bound screen must say which one, or the
            # workflow falls back to its legacy schema and drains a different tenant.
            if inst:
                payload["__instance"] = inst
            try:
                import httpx  # lazy

                # The webhook ACKs immediately — a Wait node downstream releases
                # the HTTP connection long before the drain finishes — so this is
                # a short call by construction, not a long one we gave up waiting
                # on. 20s is generous for an ACK.
                with httpx.Client(timeout=20.0) as c:
                    res = c.post(url, json=payload, auth=(user, pw) if pw else None)
                    res.raise_for_status()
                    data = res.json() if res.content else {}
            except Exception as e:
                return jsonify({
                    "success": False,
                    "error": "drain_unreachable",
                    "message": "הקריאה לניקוז נכשלה",
                    "detail": f"{type(e).__name__}: {e}",
                }), 502

            if isinstance(data, list):
                data = data[0] if (data and isinstance(data[0], dict)) else {}
            execution_id = str((data or {}).get("drain_execution") or "").strip()
            if not execution_id:
                return jsonify({
                    "success": False,
                    "error": "drain_no_execution",
                    "message": "הניקוז השיב ללא מזהה הרצה — לא ניתן לעקוב אחריו.",
                    "reply": data,
                }), 502
            _pipeline_remember_mode(execution_id, mode)

        # The bar polls immediately after this returns; a memo built moments ago
        # would report "no drain" for its whole TTL and make the button look dead.
        with _PIPELINE_STATUS_LOCK:
            _PIPELINE_STATUS_MEMO.clear()

        return jsonify({
            "execution_id": execution_id,
            "mode": mode,
            "dry": dry,
            "n8n_url": _pipeline_exec_url(execution_id),
        }), 202

    def _resolve_selection(cfg, repo_obj, body: dict) -> tuple[list[str], bool]:
        """[one-selector 2026-08-24, owner order] The selection IS a selector, not a list.

        Accepts either `ids: [...]` (explicit picks) or `filter: {...}` (+ optional
        `search`/`search_columns`/`except: [...]`) — the SAME filter object the grid's
        query endpoint takes, so the view, the shareable URL and the selection are one
        datum. Resolution happens HERE, once, at execution time: what matches NOW is
        what is acted on. Returns (ids, truncated) — truncated only
        fires on the runaway page guard below (500k rows, far beyond the table),
        never on policy: [2026-08-24, owner order] the selection has NO size cap.
        """
        raw_ids = body.get("ids")
        if isinstance(raw_ids, list) and raw_ids:
            seen: set[str] = set()
            out: list[str] = []
            for raw in raw_ids:
                one = str(raw or "").strip()
                if one and one not in seen:
                    seen.add(one)
                    out.append(one)
            return out, False
        flt = body.get("filter")
        if not isinstance(flt, dict):
            raise ValidationError("provide `ids` (non-empty array) or `filter` (object)")
        exclude = {str(x or "").strip() for x in (body.get("except") or []) if str(x or "").strip()}
        pk = cfg.primary_key
        ids: list[str] = []
        offset = 0
        page = 1000  # request exactly what PostgREST's clamp allows, so the
        # returned-vs-requested comparison below is honest (the month-index lesson)
        truncated = False
        for _ in range(500):
            # an EMPTY filter object is legal here and means "the whole view" —
            # Query's mode 'filter' rejects {}, so it walks as mode 'all' instead
            # (measured live 2026-08-24: select-all with no active filters 500'd).
            qbody = {
                "mode": "filter" if flt else "all", "select": [pk],
                "limit": page, "offset": offset,
            }
            if flt:
                qbody["filter"] = flt
            if body.get("search"):
                qbody["search"] = body["search"]
                qbody["search_columns"] = body.get("search_columns") or []
            q = Query.model_validate(qbody)
            rows = repo_obj.query(q)
            for r in rows:
                one = str((r or {}).get(pk) or "").strip()
                if one and one not in exclude:
                    ids.append(one)
            if len(rows) < page:
                break
            offset += len(rows)
        else:
            truncated = True
        return ids, truncated

    @bp.post("/repos/<repo>/documents/bulk")
    def bulk_patch_documents(repo: str):
        """Set STATUS on many documents THROUGH THE EXISTING WRITE PATH.

        This does not write SQL. It builds `{ID, STATUS}` items and hands them to
        `_perform_batch_upsert` — the same diff-engine + repo + ROW_CHANGED path
        `PATCH /repos/<r>/documents/<id>` uses — so the row-changed event, the
        column validation and the stats invalidation all still happen and there
        is still exactly one writer.

        STATUS-ONLY BY ALLOWLIST. Owner doctrine is that only the state machine
        changes a document row and ACTION_RESTART is its one sanctioned re-run;
        a bulk endpoint that could set any column would be a second writer with
        a nicer name.

        Ids are verified to EXIST first. The upsert path creates a row for an
        unknown primary key, so an unchecked bulk call with a typo'd id would
        silently invent documents; a missing id is reported per-id instead.

        STATUS is one of the repo's `priority_sync_columns`, so writing it also
        flips `priority_sync` — the diff engine mirrors n8n's own `Check Priority
        Sync`. That is the SAME second effect a single-document STATUS edit
        already has, which is the point of going through this path rather than
        around it, but it is a second effect and is stated here rather than
        discovered later.
        """
        cfg = reg.get(repo)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        patch = body.get("patch")
        if not isinstance(patch, dict) or not patch:
            raise ValidationError("`patch` must be a JSON object")
        # [2026-08-24, owner order] any schema column may be bulk-patched — same power the
        # single-document PATCH always had, same single write path. Protected columns and
        # the primary key stay out; STATUS keeps its token check when present.
        schema_cols = {c.name for c in cfg.columns}
        protected = _PIPELINE_BULK_PROTECTED_FIELDS | {cfg.primary_key}
        bad = [k for k in patch if k in protected or k not in schema_cols]
        if bad:
            raise ValidationError(
                "these columns cannot be bulk-patched (protected or unknown)",
                rejected=sorted(bad),
            )
        if "STATUS" in patch:
            status = str(patch.get("STATUS") or "").strip()
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,39}", status):
                raise ValidationError(
                    "STATUS must be an upper-case status token", got=patch.get("STATUS")
                )

        pk = cfg.primary_key
        # THE SELECTION IS RESOLVED INSIDE THE CALLER'S INSTANCE. Unscoped, a bulk edit or an
        # action dispatched while viewing instance B resolved its ids against instance A and
        # acted there — the same cross-tenant write as the single-document PATCH, multiplied by
        # the size of the selection.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        ids, sel_truncated = _resolve_selection(cfg, repo_obj, body)
        if not ids:
            raise ValidationError("the selection resolved to no documents")
        chunk_size = max(1, _max_batch_size())
        failed: list[dict] = []
        ok = 0

        for start in range(0, len(ids), chunk_size):
            chunk = ids[start:start + chunk_size]
            try:
                existing = {
                    str(r.get(pk))
                    for r in (repo_obj.fetch_by_ids(chunk, columns=[pk]) or [])
                    if isinstance(r, dict) and r.get(pk) is not None
                }
            except Exception as e:
                failed.extend(
                    {"id": one, "status": 502, "message": f"{type(e).__name__}: {e}"}
                    for one in chunk
                )
                continue

            present = [one for one in chunk if one in existing]
            failed.extend(
                {"id": one, "status": 404, "message": "המסמך לא נמצא"}
                for one in chunk if one not in existing
            )
            if not present:
                continue

            try:
                response = _perform_batch_upsert(
                    repo, [dict(patch, **{pk: one}) for one in present]
                )
                result = response.get_json() or {}
            except IncomingDocumentsError as e:
                failed.extend(
                    {"id": one, "status": e.status, "message": str(e)} for one in present
                )
                continue
            except Exception as e:
                failed.extend(
                    {"id": one, "status": 502, "message": f"{type(e).__name__}: {e}"}
                    for one in present
                )
                continue

            # Per-id outcome off the write path's OWN report, so a partial batch
            # is reported partially rather than as a whole-chunk success.
            #
            # ACCOUNTED BY EXCLUSION, and deliberately so. The batch response
            # reports `updated` and `created` as ROWS but noops only as a COUNT
            # in `stats` — unlike the single-document PATCH, which returns the
            # noop LIST. Matching ids against `updated` alone would therefore
            # score every already-correct row as a failure, which is precisely
            # what an idempotent re-apply consists of. So: a row that reached the
            # diff and came back neither created nor skipped got the STATUS asked
            # for, whether that took an UPDATE or nothing at all.
            outcome_created = {
                str(r.get(pk)) for r in (result.get("created") or [])
                if isinstance(r, dict) and r.get(pk) is not None
            }
            outcome_skipped = {
                str((entry or {}).get("item", {}).get(pk))
                for entry in (result.get("skipped") or [])
                if isinstance(entry, dict) and isinstance(entry.get("item"), dict)
            }
            stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
            if int(stats.get("incoming") or 0) != len(present):
                # The write path drops items carrying no value at all. A
                # `{ID, STATUS}` pair with a validated non-empty STATUS cannot be
                # one, so a shortfall here means something changed underneath
                # this endpoint. Fail the chunk rather than absorb a difference
                # this code can no longer attribute to specific ids.
                failed.extend(
                    {"id": one, "status": 500,
                     "message": "מנוע הכתיבה לא קיבל את כל השורות"}
                    for one in present
                )
                continue
            for one in present:
                if one in outcome_created:
                    # The row existed at the read and did not at the write. Report
                    # it rather than count it: a bulk STATUS patch must never be
                    # the thing that brings a document into being.
                    failed.append({"id": one, "status": 409,
                                   "message": "השורה נוצרה מחדש במקום להתעדכן"})
                elif one in outcome_skipped:
                    failed.append({"id": one, "status": 422,
                                   "message": "מנוע הכתיבה דילג על השורה"})
                else:
                    ok += 1

        return jsonify({"ok": ok, "failed": failed, "selection_truncated": sel_truncated})

    @bp.post("/repos/<repo>/documents/dispatch")
    def dispatch_documents(repo: str):
        """[2026-08-24, owner order] Fire ONE router action on many documents — the console's
        face of the sanctioned manual dispatch (full-row lines + ACTION + TRIGGER label,
        exactly the shape the drain's own driver sends). No decide in the middle: this is the
        operator saying "run THIS on THESE", the same door the ops scripts used.

        Guardrails: verbs from `_DISPATCH_ALLOWED_ACTIONS` only (restart is NOT here —
        ACTION_RESTART via STATUS stays its one sanctioned door); ids are existence-checked;
        lines go in batches of `_DISPATCH_BATCH` (the extraction cap, so one call never
        exceeds an action group's budget); heavy blob columns are stripped from the lines.
        Each batch is one router webhook call, sequential — the router itself owns
        parallelism. Failures are reported per-batch with the ids they carried.
        """
        cfg = reg.get(repo)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        action = str(body.get("action") or "").strip()
        if action not in _DISPATCH_ALLOWED_ACTIONS:
            raise ValidationError(
                "action not allowed for direct dispatch",
                allowed=sorted(_DISPATCH_ALLOWED_ACTIONS), got=action,
            )
        pk = cfg.primary_key
        # THE SELECTION IS RESOLVED INSIDE THE CALLER'S INSTANCE. Unscoped, a bulk edit or an
        # action dispatched while viewing instance B resolved its ids against instance A and
        # acted there — the same cross-tenant write as the single-document PATCH, multiplied by
        # the size of the selection.
        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        ids, sel_truncated = _resolve_selection(cfg, repo_obj, body)
        if not ids:
            raise ValidationError("the selection resolved to no documents")
        user = os.getenv("BS_WEBHOOK_USER") or ""
        pw = os.getenv("BS_WEBHOOK_PASS") or ""
        url = f"{_n8n_webhook_base()}/indox-action-router"
        trigger = "console_manual"

        import httpx  # lazy, same as the settings invalidator

        dispatched = 0
        failed: list[dict] = []
        missing: list[str] = []
        with httpx.Client(timeout=600.0) as client:
            for start in range(0, len(ids), _DISPATCH_BATCH):
                chunk = ids[start:start + _DISPATCH_BATCH]
                try:
                    rows = [r for r in (repo_obj.fetch_by_ids(chunk) or [])
                            if isinstance(r, dict) and r.get(pk)]
                except Exception as e:
                    failed.append({"ids": chunk, "message": f"read: {type(e).__name__}: {e}"})
                    continue
                found = {str(r.get(pk)) for r in rows}
                missing.extend(one for one in chunk if one not in found)
                if not rows:
                    continue
                lines = []
                for r in rows:
                    line = {k: v for k, v in r.items() if k not in _DISPATCH_STRIP}
                    line["ACTION"] = action
                    line["DOC_TYPE"] = _DISPATCH_DOC_TYPE.get(
                        str(r.get("TYPE") or "").upper(), "invoice")
                    line["TRIGGER_TYPE"] = trigger
                    # ON THE LINE, not the body: the router resolves the schema per action line
                    # ($json), and since the cutover its Log Action Start THROWS on a missing
                    # __instance — a console dispatch without it dies before logging anything.
                    if request.args.get("instance"):
                        line["__instance"] = request.args.get("instance")
                    lines.append(line)
                try:
                    resp = client.post(
                        url, json={"ACTION_LINES": lines, "TRIGGER_TYPE": trigger},
                        auth=(user, pw) if pw else None)
                    if resp.status_code == 200:
                        dispatched += len(lines)
                    else:
                        failed.append({"ids": [str(r.get(pk)) for r in rows],
                                       "message": f"router HTTP {resp.status_code}"})
                except Exception as e:
                    failed.append({"ids": [str(r.get(pk)) for r in rows],
                                   "message": f"{type(e).__name__}: {e}"})

        return jsonify({
            "action": action, "dispatched": dispatched,
            "missing": missing, "failed": failed, "trigger": trigger,
            "selection_truncated": sel_truncated,
        })

    @bp.post("/repos/<repo>/documents/export")
    def export_documents(repo: str):
        """[2026-08-24, owner order] Stream the WHOLE selection as CSV, not the visible page.

        Same one-selector body as documents/bulk and documents/dispatch (`ids`
        OR `filter` + `search`/`search_columns`/`except`), plus an optional
        `columns` subset+order. The client-side exports (BinaTable.tsx /
        ActionLogPage.tsx) can only save the rows the grid holds — one page;
        this is the server half, so "export the selection" and "the selection"
        stay one datum here too.

        STREAMED, NEVER MATERIALISED. Rows are fetched in `_EXPORT_FETCH_CHUNK`
        fetch_by_ids chunks (ids mode) or 500-row full-width filter pages (the
        same Query pattern `_resolve_selection` walks) and written line by
        line, so a 100k-row export costs one page of memory. Everything the generator touches is
        captured BEFORE the Response is built — a streaming body outlives the
        request context, so the generator reads only these locals, never
        `request`.

        TRUNCATION IS IN-BAND, one mechanism for both modes: headers are on the
        wire before the fetch loop learns how many rows match, so no
        `X-Total-Rows`/`X-Truncated` header can be honest. When a row
        materialises past `_EXPORT_MAX_ROWS`, the stream ends with a final row
        whose FIRST cell is `__TRUNCATED__` (rest empty) — a consumer checks
        the last line, not the headers. An empty selection is a header-only CSV.
        """
        cfg = reg.get(repo)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")

        pk = cfg.primary_key
        schema_order = [pk] + [c.name for c in cfg.columns if c.name != pk]
        raw_cols = body.get("columns")
        if raw_cols is not None and not isinstance(raw_cols, list):
            raise ValidationError("`columns` must be an array of column names")
        cols: list[str] = []
        for raw in (raw_cols or []):
            one = str(raw or "").strip()
            if one and one not in cols:
                cols.append(one)
        known = set(schema_order)
        unknown = [c for c in cols if c not in known]
        if unknown:
            raise ValidationError(
                "these columns are not in the repo schema",
                unknown=unknown, allowed=schema_order,
            )
        if not cols:  # absent/empty → pk first, then schema order
            cols = schema_order

        repo_obj = repo_for(cfg, request.args.get("instance"), request.args.get("table"))
        ids: list[str] | None = None
        flt: dict | None = None
        exclude: set[str] = set()
        raw_ids = body.get("ids")
        if isinstance(raw_ids, list) and raw_ids:
            # ids branch of the shared resolver: normalise/dedupe only, no cap
            ids, _ = _resolve_selection(cfg, repo_obj, body)
        else:
            flt = body.get("filter")
            if not isinstance(flt, dict):
                raise ValidationError(
                    "provide `ids` (non-empty array) or `filter` (object; {} = the whole view)"
                )
            exclude = {str(x or "").strip() for x in (body.get("except") or [])
                       if str(x or "").strip()}
        search = str(body.get("search") or "")
        search_columns = list(body.get("search_columns") or [])
        filename = f"documents-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"

        def _rows():
            # FULL rows, never an explicit select list: the repo schema declares columns
            # (e.g. COMPANY_DOC_ID) that are not physical table columns, and PostgREST
            # 400s the whole request on the first one (measured live 2026-08-24). The
            # proven dispatch path fetches full rows the same way; the CSV writer below
            # emits only the requested `cols`, and a virtual column simply yields what
            # the repo layer put in the row — or an honest empty cell.
            if ids is not None:
                for start in range(0, len(ids), _EXPORT_FETCH_CHUNK):
                    chunk = ids[start:start + _EXPORT_FETCH_CHUNK]
                    for r in (repo_obj.fetch_by_ids(chunk) or []):
                        if isinstance(r, dict):
                            yield r
                return
            offset = 0
            # 500, not the 1000 the pk-only resolver pages: these rows carry every
            # column, including the 30k-char extraction blobs.
            page = 500
            while True:
                # {} = the whole view (mode 'all'); Query rejects an empty filter clause
                qbody = {
                    "mode": "filter" if flt else "all",
                    "limit": page, "offset": offset,
                }
                if flt:
                    qbody["filter"] = flt
                if search:
                    qbody["search"] = search
                    qbody["search_columns"] = search_columns
                rows = repo_obj.query(Query.model_validate(qbody))
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    if str(r.get(pk) or "").strip() in exclude:
                        continue
                    yield r
                if len(rows) < page:
                    return
                offset += len(rows)

        def _gen():
            # BOM first — the platform convention (both client-side CSV exports
            # prepend exactly this) so Hebrew opens correctly in Excel. `\n` row
            # ends for the same reason: byte-parity with the client exports;
            # fields containing newlines are quoted, so `\n` stays unambiguous.
            try:
                yield "\ufeff" + ",".join(_csv_cell(c) for c in cols) + "\n"
                written = 0
                for row in _rows():
                    if written >= _EXPORT_MAX_ROWS:
                        yield "__TRUNCATED__" + "," * (len(cols) - 1) + "\n"
                        return
                    yield ",".join(_csv_cell(row.get(c)) for c in cols) + "\n"
                    written += 1
            except GeneratorExit:  # client hung up — nothing left to finish
                return
            except Exception as e:
                # Headers and rows are already on the wire, so no error envelope
                # is possible; the aborted chunked stream is the client's signal.
                # Log it so the abort is attributable server-side.
                _log.warning("documents/export: stream aborted: %s: %s",
                             type(e).__name__, e)
                raise

        return Response(
            _gen(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ----- archive: move rows between a live repo and its `-archive` twin -----

    def _archive_move(repo: str, *, to_archive: bool):
        """[archive 2026-08-24, owner order] Move a SELECTION between a repo and its twin.

        One transaction per call: INSERT into the destination (only ids not already
        there) + DELETE exactly the ids that inserted, commit, done — a crash leaves
        both tables as they were, never a row in two places or in none. Columns move
        by NAME INTERSECTION of the two physical tables (information_schema at call
        time), so a column added to one side degrades to "not carried", never to an
        error; `archived_at` is stamped now() on the way in and dropped on the way out.

        Same one-selector body as documents/bulk (`ids` OR `filter` +
        `search`/`except`), resolved against the SOURCE repo — the view the operator
        is looking at is the thing that moves. No size cap (owner order). Raw SQL on
        purpose, not the upsert path: rows LEAVE the live system here — no ROW_CHANGED,
        no priority-sync flip, values and flags preserved verbatim (the value+flag law).
        A conflict (id already present at the destination) is skipped and reported,
        never overwritten.
        """
        suffix = "-archive"
        if to_archive:
            if repo.endswith(suffix):
                raise ValidationError("this repo IS the archive — use unarchive", got=repo)
            src_name, dst_name = repo, repo + suffix
        else:
            if not repo.endswith(suffix):
                raise ValidationError("unarchive runs on the -archive repo", got=repo)
            src_name, dst_name = repo, repo[: -len(suffix)]
        src_cfg = reg.get(src_name)
        dst_cfg = reg.get(dst_name)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        # THE SELECTION AND THE MOVE MUST READ THE SAME SCHEMA. factory(src_cfg) resolved the
        # selection through the config schema (`public` = instance one's compat view) while the
        # INSERT/DELETE below runs in _request_schema() — so a filter-archive under ?instance=levi
        # enumerated hacohen's ids and moved levi rows that merely shared them (per-instance ID
        # sequences collide by design). repo_for() scopes the selection to the same instance the
        # SQL half writes.
        repo_obj = repo_for(src_cfg, request.args.get("instance"))
        ids, sel_truncated = _resolve_selection(src_cfg, repo_obj, body)
        if not ids:
            raise ValidationError("the selection resolved to no documents")
        src_table = _pipeline_safe_table(
            src_cfg.supabase.table if src_cfg.supabase else None)
        dst_table = _pipeline_safe_table(
            dst_cfg.supabase.table if dst_cfg.supabase else None)
        if not src_table or not dst_table:
            raise ValidationError("archive moves need two supabase-backed repos")
        pk = src_cfg.primary_key

        conninfo = _pipeline_indox_conninfo()
        if not conninfo:
            return jsonify({
                "success": False, "error": "archive_db_unconfigured",
                "message": "חיבור הכתיבה למסד לא מוגדר (PIPELINE_INDOX_*) — "
                           "ההעברה לא בוצעה.",
            }), 503

        import psycopg  # lazy, same as _pipeline_query

        # [multi-instance 2026-08-28] This whole block addressed `public."<table>"` — an
        # introspection, a SELECT, an INSERT and a DELETE. `public` is a compatibility view over ONE
        # instance, so archiving while viewing another client moved THAT client's rows; and once the
        # views are dropped the introspection returns no columns and the move fails on an empty
        # column list rather than loudly. The schema comes from the request like every other read
        # and write. It is re-validated here because it is interpolated into SQL rather than bound:
        # _instance_schema() already gates it, and a second check at the point of interpolation costs
        # nothing next to an injected identifier.
        _sch = _request_schema()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", _sch or ""):
            raise ValidationError("bad schema for archive move", schema=_sch)

        cols_sql = ("select column_name from information_schema.columns "
                    "where table_schema=%s and table_name=%s "
                    "order by ordinal_position")
        try:
            # NOT _pipeline_query: that helper pins default_transaction_read_only=on
            # (it exists to make accidental writes fail). This is the deliberate write.
            with psycopg.connect(conninfo, autocommit=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(cols_sql, (_sch, src_table))
                    src_cols = [r[0] for r in cur.fetchall()]
                    cur.execute(cols_sql, (_sch, dst_table))
                    dst_cols = {r[0] for r in cur.fetchall()}
                    common = [c for c in src_cols
                              if c in dst_cols and c != "archived_at"]
                    if pk not in common:
                        raise ValidationError(
                            "the two tables do not share the primary key column",
                            pk=pk)
                    col_list = ", ".join(f'"{c}"' for c in common)
                    if to_archive:
                        insert_cols = col_list + ', "archived_at"'
                        select_cols = col_list + ", now()"
                    else:
                        insert_cols = col_list
                        select_cols = col_list
                    cur.execute(
                        f'select "{pk}" from "{_sch}"."{src_table}" '
                        f'where "{pk}" = any(%s)', (ids,))
                    present = [r[0] for r in cur.fetchall()]
                    missing = sorted(set(ids) - set(present))
                    moved_ids: list[str] = []
                    if present:
                        cur.execute(
                            f'insert into "{_sch}"."{dst_table}" ({insert_cols}) '
                            f'select {select_cols} from "{_sch}"."{src_table}" s '
                            f'where s."{pk}" = any(%s) and not exists ('
                            f'  select 1 from "{_sch}"."{dst_table}" d '
                            f'  where d."{pk}" = s."{pk}") '
                            f'returning "{pk}"', (present,))
                        moved_ids = [r[0] for r in cur.fetchall()]
                        if moved_ids:
                            cur.execute(
                                f'delete from "{_sch}"."{src_table}" '
                                f'where "{pk}" = any(%s)', (moved_ids,))
                    conn.commit()
        except ValidationError:
            raise
        except Exception as e:
            _log.warning("archive move failed: %s: %s", type(e).__name__, e)
            return jsonify({
                "success": False, "error": "archive_move_failed",
                "message": "ההעברה נכשלה ובוטלה במלואה",
                "detail": f"{type(e).__name__}: {e}",
            }), 502

        conflicts = sorted(set(present) - set(moved_ids))
        # the status memo counts live-table rows — a move just changed that
        with _PIPELINE_STATUS_LOCK:
            _PIPELINE_STATUS_MEMO.clear()
        return jsonify({
            "moved": len(moved_ids),
            "direction": "archive" if to_archive else "unarchive",
            "source": src_name, "destination": dst_name,
            "conflicts": conflicts, "missing": missing,
            "selection_truncated": sel_truncated,
        })

    @bp.post("/repos/<repo>/documents/archive")
    def archive_documents(repo: str):
        return _archive_move(repo, to_archive=True)

    @bp.post("/repos/<repo>/documents/unarchive")
    def unarchive_documents(repo: str):
        return _archive_move(repo, to_archive=False)

    # ----- /auth/me : surface Authentik ForwardAuth headers
    @bp.get("/auth/me")
    def auth_me():
        h = request.headers
        username = h.get("X-authentik-username") or h.get("X-Authentik-Username")
        email = h.get("X-authentik-email") or h.get("X-Authentik-Email")
        groups_raw = (
            h.get("X-authentik-groups") or h.get("X-Authentik-Groups") or ""
        )
        groups = [g.strip() for g in groups_raw.split("|") if g.strip()]
        return jsonify(
            {
                "success": True,
                "authenticated": bool(username),
                "username": username,
                "email": email,
                "groups": groups,
                "is_admin": "incoming-docs-admin" in groups,
            }
        )

    # ----- /openapi.json : minimal hand-rolled spec (zero extra deps)
    @bp.get("/openapi.json")
    def openapi_spec():
        return jsonify(_build_openapi(prefix))

    # ----- חילוץ מסמכים — dataset extraction runner + visualiser (own module)
    from ..extraction import register_extraction

    register_extraction(bp)

    # Start background poller (daemon thread, idempotent per-process)
    if os.getenv("INCOMING_DOCS_DISABLE_POLLER", "").lower() not in ("1", "true", "yes"):
        start_polling(reg, factory, producer)

    # The read-model refreshers (INDOX-UNIFIED-N8N-SPEC.md §5 — "counts maintained on write, never
    # counted at request time"). Same idempotent-per-process guard as the poller above; single
    # gunicorn worker (gthread) means exactly one of each runs, no cross-worker coordination needed.
    if os.getenv("INCOMING_DOCS_DISABLE_STATS_REFRESH", "").lower() not in ("1", "true", "yes"):
        # Dashboard stats are computed purely from this deployment's OWN database (the document
        # table), so this refresher always runs — it never reaches out to another service.
        start_dashboard_stats_refresher()

        # (The sync-stats refresher — a background walk of Gmail/Drive — was DELETED 2026-09-02:
        # the board reads the sync_item_counts view; the BFF makes no cross-app call, ever.)

    return bp
