"""חילוץ מסמכים — dataset-based extraction runner + visualiser (JsonQueryExV3).

The BFF side of the extraction page: lists the grounded demo dataset (mounted
read-only at EXTRACTION_DATASET_DIR), runs extraction through the live n8n
JsonQueryExV3 workflows (webhooks ``jqexv3-run-{base,invoice,shipment,bs}`` —
one apitools /documentJsonQuery call per value), scores results against the
dataset ground truth, serves the original document file, and proxies the
apitools /documentDraw overlay (the query matches drawn on the document).

Everything n8n executes is driven by the ``q_v3_*`` settings rows, so the
extraction logic stays editable from the הגדרות tab — this module never embeds
a query.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

logger = logging.getLogger("incoming_documents.extraction")

# ── config ───────────────────────────────────────────────────────────────────
DATASET_DIR = Path(os.getenv("EXTRACTION_DATASET_DIR", "/app/.dataset"))
UPLOADS_DIR = Path(os.getenv("EXTRACTION_UPLOADS_DIR", "/app/.storage/extraction-uploads"))
DRAW_CACHE_DIR = Path(os.getenv("EXTRACTION_DRAW_CACHE_DIR", "/app/.storage/extraction-draws"))
RUNS_DIR = Path(os.getenv("EXTRACTION_RUNS_DIR", "/app/.storage/extraction-runs"))
RUNS_KEEP = int(os.getenv("EXTRACTION_RUNS_KEEP", "400"))
APITOOLS_BASE = os.getenv("APITOOLS_BASE", "http://apitools:8080").rstrip("/")


class _DocLookupFailed(Exception):
    """The `incoming_documents` row behind a document ASSET url could not be read.

    Distinct from "no such document" (404) and "document known, not OCR'd yet" (404): those
    are answers about a row that was successfully read. This one means the read itself did
    not happen — almost always because the request named no tenant and the routes fell back
    to a `public` schema whose compatibility views no longer exist. Without this the failure
    reached the app's catch-all handler and left the browser holding a 500 with no clue in it.
    """

# dataset folder -> n8n per-type hook + scored/extra fields + truth columns
TYPES: dict[str, dict] = {
    "invoice": {
        "hook": "jqexv3-run-invoice",
        "label": "חשבונית",
        # linked refs (SHIPMENT_ID/PURCHASE_ID) score WHEN the dataset row carries
        # truth for them — rows without truth stay unscored automatically
        "scored": [("COMPANY_ID", "COMPANY_ID"), ("DOC_DATE", "DOC_DATE"),
                   ("INVOICE_ID", "INVOICE_ID"), ("DOC_TOTAL_AMOUNT", "DOC_TOTAL_AMOUNT"),
                   ("SHIPMENT_ID", "SHIPMENT_ID"), ("PURCHASE_ID", "PURCHASE_ID")],
        "extra": [],
        "draw_category": "invoice",
    },
    "shipment": {
        "hook": "jqexv3-run-shipment",
        "label": "תעודת משלוח",
        # amount + purchase are scored WHEN the dataset row carries truth for them
        # (rows without truth stay unscored automatically)
        "scored": [("COMPANY_ID", "COMPANY_ID"), ("DOC_DATE", "DOC_DATE"),
                   ("SHIPMENT_ID", "SHIPMENT_ID"), ("DOC_TOTAL_AMOUNT", "DOC_TOTAL_AMOUNT"),
                   ("PURCHASE_ID", "PURCHASE_ID")],
        "extra": [],
        "draw_category": "shipment",
    },
    "balance_sheet": {
        "hook": "jqexv3-run-bs",
        "label": "דוח גיול",
        "scored": [("COMPANY_ID", "COMPANY_ID"), ("DOC_DATE", "DOCUMENT_DATE"),
                   ("BALANCE", "BALANCE")],
        "extra": [],
        "draw_category": "bs",
    },
}
MIME = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}

# ── AI-side shadow extraction (EXTRACTION-REFACTOR-PLAN.md §3 Phase 3) ────────
# The gate before any cutover: prove the (future) local path and the AI path
# produce the same values, graded against the SAME human-verified ground truth
# by the SAME comparators (`_score()` below), not two rubrics invented
# separately. This calls the live Gemini extractor webhooks directly against
# the identical dataset documents the local JQExV3 run already scores — no new
# scoring logic, no new dataset, no new tooling; just a second run mode.
#
# doc type -> AI extractor webhook. `invoice_extractor` is the one-prompt,
# 7-field Gemini extractor (indoxV2ExtractInvoiceGemini01) — it classifies AND
# extracts in one call, so it's the right hook for both invoice and shipment
# dataset docs (its own AI_TYPE output is what would tell them apart live).
# `bs_ex_2_dev` (indoxV2ExtractBalanceSheet01) is AI-only and document-level:
# it has no COMPANY_ID field in its schema at all (per the plan §2.2a — BS's
# per-document COMPANY_ID comes from the shared base-doc step, not from this
# extractor), so the AI-side BALANCE_SHEET score only ever covers DATE/BALANCE.
AI_HOOKS: dict[str, str] = {
    "invoice": "invoice_extractor",
    "shipment": "invoice_extractor",
    "balance_sheet": "bs_ex_2_dev",
}


def _ai_auth() -> tuple[str, str] | None:
    """Basic-auth for the AI extractor webhooks — the same 'Incoming Documents
    [env-managed]' credential indoxV2ExtractInvoiceGemini01 / ExtractBalanceSheet01
    already declare (BS_WEBHOOK_USER/PASS, per apps/indox/docker-compose.yml)."""
    user = os.getenv("BS_WEBHOOK_USER", "")
    pw = os.getenv("BS_WEBHOOK_PASS", "")
    return (user, pw) if user else None

# state: latest result per doc + run history. Everything is PERSISTED under
# RUNS_DIR (bind-mounted) so results and history survive restarts: every
# extraction — full run, selected run, single-doc rerun, upload — is a run
# record ({summary..., results: {doc_id: result}}) in its own JSON file, and
# latest.json snapshots the newest result per doc. In-memory _RUNS holds
# summaries only; full results are read from disk on demand. Single gunicorn
# worker (see gunicorn.conf.py) keeps this authoritative.
_RESULTS: dict[str, dict] = {}
# AI-side shadow results, kept in a SEPARATE store from `_RESULTS` on purpose —
# see AI_HOOKS above. Keeping it separate (rather than tagging one shared dict
# by mode) means the existing local run/results contract is completely
# unchanged: every pre-existing endpoint keeps returning exactly what it always
# returned, and the AI run mode is purely additive.
_RESULTS_AI: dict[str, dict] = {}
_UPLOADS: dict[str, dict] = {}
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()

_LATEST_PATH = RUNS_DIR / "latest.json"


def _write_json(path: Path, obj) -> None:
    """Atomic write — a mid-write crash never corrupts history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _run_path(run: dict) -> Path:
    # started-ms prefix keeps directory listing == chronological order
    return RUNS_DIR / f"{int((run.get('started') or 0) * 1000):013d}-{run['run_id']}.json"


def _run_files() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    return sorted((p for p in RUNS_DIR.glob("*.json") if p.name != "latest.json"),
                  reverse=True)


def _persist_run(run: dict, results: dict) -> None:
    try:
        _write_json(_run_path(run), {**{k: v for k, v in run.items() if k != "results"},
                                     "results": results})
    except Exception as e:
        logger.warning("run persist failed: %s", e)


def _persist_latest() -> None:
    try:
        with _LOCK:
            snap = {"results": dict(_RESULTS), "uploads": dict(_UPLOADS),
                     "results_ai": dict(_RESULTS_AI)}
        _write_json(_LATEST_PATH, snap)
    except Exception as e:
        logger.warning("latest persist failed: %s", e)


def _prune_runs() -> None:
    for p in _run_files()[RUNS_KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass


def _record_single_run(result: dict, scope: str, mode: str = "local") -> dict:
    """Single-doc rerun / upload as a persisted run record — every extraction
    shows up in history, not only batch runs."""
    run = {"run_id": uuid.uuid4().hex[:12], "status": "done", "scope": scope,
           "mode": mode,
           "docs_total": 1, "done": 1, "ok": result.get("ok", 0),
           "total": result.get("total", 0),
           "errors": 1 if result.get("error") else 0, "current": None,
           "started": result.get("at") or time.time(), "finished": time.time(),
           "cancelled": False}
    with _LOCK:
        _RUNS[run["run_id"]] = run
    _persist_run(run, {result["id"]: result})
    _persist_latest()
    return run


def _load_state() -> None:
    """Startup reload: latest results + run summaries from disk."""
    try:
        if _LATEST_PATH.exists():
            data = json.loads(_LATEST_PATH.read_text(encoding="utf-8"))
            _RESULTS.update(data.get("results") or {})
            _UPLOADS.update(data.get("uploads") or {})
            _RESULTS_AI.update(data.get("results_ai") or {})
    except Exception as e:
        logger.warning("extraction latest reload failed: %s", e)
    for p in _run_files():
        try:
            run = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rid = run.get("run_id")
        if not rid:
            continue
        if run.get("status") == "running":  # process died mid-run
            run["status"] = "interrupted"
        _RUNS[rid] = {k: v for k, v in run.items() if k != "results"}
    if _RESULTS or _RUNS:
        logger.info("extraction state reloaded: %d results, %d runs",
                    len(_RESULTS), len(_RUNS))


_load_state()


def _n8n_base() -> str:
    base = os.getenv("N8N_WEBHOOK_BASE")
    if base:
        return base.rstrip("/")
    return "http://n8n-webhook:5678/webhook"


# ── scoring (mirrors the verified harness comparators) ───────────────────────
def _dg(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _amtf(s) -> float:
    """Parse an extracted/truth amount. Locale-robust: a grouped number treats its LAST
    separator as the decimal ('1.589.00' == '1,589.00' == 1589.0 — Google Vision reads
    Israeli thousands-commas as dots). Mirrors apitools validations._canonical_amount."""
    s = str(s).replace("₪", "").replace("�", "").strip()
    neg = s.endswith("-")
    if neg:
        s = s[:-1].strip()
    s = re.sub(r"[^0-9.,\-]", "", s)
    seps = [c for c in s if c in ".,"]
    if len(seps) >= 2:
        last = max(s.rfind("."), s.rfind(","))
        s = re.sub(r"[.,]", "", s[:last]) + "." + s[last + 1:]
    else:
        s = s.replace(",", "")
    return -float(s) if neg else float(s)


def _dparts(s):
    m = re.findall(r"\d+", str(s or ""))
    if len(m) >= 3:
        d, mo, y = (m[0], m[1], m[2]) if len(m[0]) != 4 else (m[2], m[1], m[0])
        return d.zfill(2), mo.zfill(2), y[-2:]
    return None


def _score(field: str, got, want: str):
    """True/False vs truth, or None when the field has no ground truth."""
    if not want:
        return None
    if got is None or str(got) in ("", "None"):
        return False
    try:
        if field == "COMPANY_ID":
            return _dg(got) == _dg(want)
        if field in ("DOC_TOTAL_AMOUNT", "BALANCE"):
            return abs(abs(_amtf(got)) - abs(_amtf(want))) < 0.5
        if field == "DOC_DATE":
            a, b = _dparts(got), _dparts(want)
            return a is not None and a == b
        return _dg(got)[-5:] == _dg(want)[-5:] and _dg(want)[-5:] != ""
    except Exception:
        return False


# ── dataset ──────────────────────────────────────────────────────────────────
def _corr_field(typ: str, field: str) -> str:
    """corrected_truth.json audit key for (doc type, field): a doc's OWN id was
    audited under the canonical DOC_ID; linked refs (an invoice's SHIPMENT_ID /
    PURCHASE_ID) keep their own field name."""
    if field == "BALANCE":
        return "DOC_TOTAL_AMOUNT"
    if field == "INVOICE_ID" and typ == "invoice":
        return "DOC_ID"
    if field == "SHIPMENT_ID" and typ == "shipment":
        return "DOC_ID"
    return field


# expected-TYPE overrides from corrected_truth (field == "TYPE"): a doc that physically
# sits in one folder but should classify as another type — e.g. m-trvt-b-1.jpg lives under
# balance_sheet but is an unclassifiable scrap whose correct TYPE is "unknown".
_TYPE_TRUTH: dict = {}


def _load_corrections() -> tuple[dict, dict]:
    """The human-verified truth audit (corrected_truth.json, shipped WITH the
    dataset): entries verified WRONG carry the value read off the document;
    NOT_ON_DOC means the field genuinely isn't printed (truth = empty). A `field:"TYPE"`
    entry overrides the expected document TYPE (which otherwise = the folder)."""
    fix: dict = {}
    fix_typed: dict = {}
    _TYPE_TRUTH.clear()
    path = DATASET_DIR / "corrected_truth.json"
    if not path.exists():
        return fix, fix_typed
    try:
        for e in json.loads(path.read_text(encoding="utf-8")):
            if e.get("field") == "TYPE":
                _TYPE_TRUTH[os.path.basename(e.get("file", ""))] = str(e.get("new") or "")
                continue
            key = (os.path.basename(e.get("file", "")), e.get("field"))
            if e.get("verdict") == "WRONG":
                if e.get("type"):
                    fix_typed[(e["type"],) + key] = str(e.get("new"))
                else:
                    fix[key] = str(e.get("new"))
            elif e.get("verdict") == "NOT_ON_DOC":
                # honor the entry's type — the same basename exists in several type
                # folders (invoice/hvpyt-*.pdf HAS a total; shipment/hvpyt-*.pdf not)
                if e.get("type"):
                    fix_typed[(e["type"],) + key] = ""
                else:
                    fix[key] = ""
    except Exception as ex:  # malformed audit never blocks the dataset
        logger.warning("corrected_truth.json unreadable: %s", ex)
    return fix, fix_typed


def _load_dataset() -> list[dict]:
    """One row per COMPLETED dataset doc: id, type, file, ground truth
    (dataset.csv overlaid with the verified corrections)."""
    import csv

    fix, fix_typed = _load_corrections()
    docs: list[dict] = []
    for typ, cfg in TYPES.items():
        csv_path = DATASET_DIR / typ / "dataset.csv"
        if not csv_path.exists():
            continue
        with open(csv_path, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if (row.get("STATUS") or "").strip() != "COMPLETED":
                    continue
                rel = (row.get("LOCAL_PATH") or "").strip()
                path = DATASET_DIR / typ / rel
                if not rel or not path.exists() or rel.lower().endswith(".xlsx"):
                    continue
                truth = {}
                for f, col in cfg["scored"]:
                    corr = _corr_field(typ, f)
                    tkey = (typ, path.name, corr)
                    key = (path.name, corr)
                    if tkey in fix_typed:
                        truth[f] = fix_typed[tkey]
                    elif key in fix:
                        truth[f] = fix[key]
                    else:
                        truth[f] = (row.get(col) or "").strip()
                docs.append({
                    "id": f"{typ}/{path.name}",
                    "type": typ,
                    "type_label": cfg["label"],
                    "file": path.name,
                    "truth": truth,
                    "type_truth": _TYPE_TRUTH.get(path.name, typ),
                })
    return docs


def _doc_path(typ: str, name: str) -> Path | None:
    """Resolve a doc file safely inside the dataset (or uploads) tree."""
    name = os.path.basename(name)  # no traversal
    if typ == "upload":
        p = UPLOADS_DIR / name
        return p if p.exists() else None
    if typ not in TYPES:
        return None
    p = DATASET_DIR / typ / "files" / name
    return p if p.exists() else None


# ── apitools / n8n plumbing ──────────────────────────────────────────────────
def _ocr_hash(path: Path, fresh: bool = False) -> dict:
    """apitools OCR → {hash, ocr_ms, ocr_engine, apitools_version}. ``fresh=True``
    forces a re-OCR (cache=false), bypassing the apitools ocr_cache — used by the
    reset-cache action. The provenance fields ride along so every extraction can
    state which engine/build read the file and how long the OCR step took."""
    import httpx

    ext = path.suffix.lower().lstrip(".")
    # 900s, matching apitools' GUNICORN_TIMEOUT: under load this request WAITS in
    # apitools' OCR-slot queue (up to 600s) before the heavy OCR even starts. At
    # the old 300s the client gave up exactly when the worker got killed — the
    # infamous 'timed out' / fake-OOM pair.
    with httpx.Client(timeout=900.0) as c:
        r = c.post(
            f"{APITOOLS_BASE}/documentOcr",
            params={"cache": "false" if fresh else "true", "dont_return_ocr": "1"},
            files={"file": (path.name, path.read_bytes(), MIME.get(ext, "application/octet-stream"))},
        )
        r.raise_for_status()
        j = r.json()
        return {
            "hash": j.get("file_hash"),
            # provenance stamped INSIDE the ocr_json at OCR time (cache-persistent):
            # a cache hit reports the engine/build/duration that produced the OCR
            "ocr_ms": j.get("ocr_ms"),
            "ocr_at": j.get("ocr_at"),
            "ocr_engine": j.get("ocr_engine"),
            "ocr_apitools_version": j.get("ocr_apitools_version"),
            "apitools_version": j.get("apitools_version"),
        }


def _ocr_file_id(path: Path, fresh: bool = False) -> str:
    """JUST the apitools file id, as a string.

    This exists because `_ocr_hash` does not return a hash — it returns a provenance dict, and its
    name says otherwise. That mismatch has broken the same feature repeatedly: the drawn-overlay pane
    and the token map both did

        file_hash = _ocr_hash(path)                       # a dict
        c.get(..., params={"file_id": file_hash})         # -> file_id={'hash': 'abc', 'ocr_ms': 12,...}

    apitools then looked up a document whose id is the *repr of a dictionary*, found nothing, and
    answered 404. The UI showed a broken image, which reads as "drawing is broken" rather than "we
    asked for the wrong document". The cache path was corrupted the same way — `f"{file_hash}-…png"`
    became a filename containing braces and quotes, so the cache never hit and every view re-ran OCR.

    Three of the four call sites had this bug and only one (`_extract`) unpacked the dict correctly,
    which is why fixing it one site at a time kept appearing to work and then regressing.

    So: callers that want the id call THIS, and get a validated string or an exception. Callers that
    want the provenance call `_ocr_hash` and read its fields by name. There is no longer a way to
    reach for "the hash" and receive a dict.
    """
    ocr = _ocr_hash(path, fresh=fresh)
    file_id = ocr.get("hash")
    if not file_id:
        # Same failure the extraction path already guards against — apitools answered without a
        # hash, and every downstream use of it would be nonsense.
        raise RuntimeError("apitools OCR returned no hash")
    return str(file_id)


def _clear_draw_cache(file_hash: str | None) -> int:
    """Delete cached draw overlays for a document hash (all categories). Returns
    the count removed. The overlay regenerates from fresh OCR on next fetch."""
    if not file_hash or not DRAW_CACHE_DIR.exists():
        return 0
    n = 0
    for p in DRAW_CACHE_DIR.glob(f"{file_hash}-*.png"):
        try:
            p.unlink(); n += 1
        except OSError:
            pass
    return n


def _run_hook(hook: str, docs: list[dict], timeout_s: float = 600.0) -> list[dict]:
    """POST one batch to a JsonQueryExV3 run-hook; returns the collected rows."""
    import httpx

    with httpx.Client(timeout=timeout_s) as c:
        r = c.post(f"{_n8n_base()}/{hook}", json={"docs": docs})
        r.raise_for_status()
        out = r.json()
        return out if isinstance(out, list) else [out]


def _settings_queries() -> dict:
    """All q_v3_* rows (queries + routing) — the backend context panel."""
    from .backends.supabase_transport import HttpxSupabaseTransport

    transport = HttpxSupabaseTransport()
    # Tenant-scoped like every other config read (phase 6.3). Imported from the api module rather
    # than re-deriving the active instance here — two resolvers is how the two drift apart.
    # [multi-instance 2026-08-28] The SCHEMA follows the request's instance too, not just the
    # `instance` filter column. Those are different things and both are needed: the column separates
    # components ('incoming-documents-main'), the schema separates TENANTS. Hardcoding "public" here
    # meant every tenant read hacohen's settings through the compatibility view — and it stops
    # resolving at all once that view is dropped.
    from .api import _tenant, _request_schema
    rows = transport.select(schema=_request_schema(), table="settings", select=["key", "value"],
                            filter=_tenant()) or []
    out = {}
    for row in rows:
        k = row.get("key") or ""
        if k.startswith("q_v3_"):
            try:
                out[k] = json.loads(row.get("value") or "null")
            except Exception:
                out[k] = row.get("value")
    return out


def _resolved_queries() -> dict:
    """The same q_v3_* queries with the company registry BOUND — read-only preview.

    `public.extraction_queries` is the one place the `@registry_*` sentinels get
    substituted from the companies table (via public.bind_registry over
    public.company_registry), which is exactly how the n8n extractors read them. The
    UI panel previously rendered `@registry_ids` as a literal chip because it only
    ever saw the template.

    Deliberately SEPARATE from _settings_queries() rather than replacing it. The GET
    that feeds the settings panel is the same shape the PUT writes back to
    public.settings, so returning the bound form as `queries` would let a save bake
    ~2,378 company identifiers into the stored query — re-creating by accident the
    hardcoding that was just removed (q_v3_company went 4,860 chars with 114 hardcoded
    company names -> 602 chars with none). The template stays editable; this is for
    display only.

    Returns {} rather than raising if the view is absent, so a stack that has not yet
    applied the schema still serves the panel with the template alone.
    """
    from .backends.supabase_transport import HttpxSupabaseTransport
    from .api import _tenant, _request_schema

    try:
        # [multi-instance 2026-08-28] extraction_queries is a DERIVED view over that tenant's
        # settings and companies, so it exists once per tenant schema and must be read from the
        # request's own. hacohen's q_v3_company binds to 186,878 bytes and levi's to 522 — reading
        # the wrong schema does not fail, it silently previews another client's company registry.
        rows = HttpxSupabaseTransport().select(
            schema=_request_schema(), table="extraction_queries",
            select=["key", "query", "resolver_gen"], filter=_tenant()) or []
    except Exception:
        return {}
    out = {}
    for row in rows:
        k = row.get("key") or ""
        if k.startswith("q_v3_"):
            out[k] = {"query": row.get("query"), "resolver_gen": row.get("resolver_gen")}
    return out


def _extract_one(doc_id: str, typ: str, path: Path, fresh: bool = False) -> dict:
    """Full extraction for ONE document through the live n8n workflows:
    base pass (company/type/date) then the per-type pass. Scored vs truth by
    the caller. Timing + hash recorded for the backend-context panel.
    ``fresh=True`` forces a re-OCR and clears the doc's draw cache first."""
    t0 = time.time()
    ocr = _ocr_hash(path, fresh=fresh)
    file_hash = ocr.get("hash")
    if not file_hash:
        raise RuntimeError("apitools OCR returned no hash")
    # The token-map / overlay draws are disk-cached PNGs keyed by FILE hash, but the file
    # hash does NOT change when the OCR engine does — so a draw cached under an older engine
    # would show a different read than this extraction (e.g. a token-map "3462" next to a
    # result "3492"). Invalidate the draws on EVERY run so the next view regenerates from the
    # exact OCR this extraction used: the draw and the results can never disagree.
    _clear_draw_cache(file_hash)
    payload = [{"ID": doc_id, "API_TOOLS_ID": file_hash}]
    t_base = time.time()
    base_rows = _run_hook("jqexv3-run-base", payload)
    base = base_rows[0] if base_rows else {}
    base_s = round(time.time() - t_base, 1)
    detected = base.get("TYPE")
    per_type: dict = {}
    type_s = None
    hook = TYPES.get(typ, {}).get("hook")
    if hook:
        t_type = time.time()
        rows = _run_hook(hook, payload)
        per_type = rows[0] if rows else {}
        type_s = round(time.time() - t_type, 1)
    fields = {
        "COMPANY_ID": base.get("COMPANY_ID"),
        "BASE_DATE": base.get("DOC_DATE"),
        "DETECTED_TYPE": detected,
    }
    for k, v in per_type.items():
        if k not in ("ID", "TYPE", "API_TOOLS_ID", "_ERRORS", "_TIMINGS", "_META"):
            fields[k] = v
    # _ERRORS: per-field call failures the extractor's Collect node recorded (e.g.
    # "timeout of 300000ms exceeded"). A field listed here returned null because the
    # CALL DIED, not because the value is absent from the document — the two must
    # never be conflated (a silent timeout hid inside green runs for days).
    value_errors: dict = {}
    value_errors.update(base.get("_ERRORS") or {})
    value_errors.update(per_type.get("_ERRORS") or {})
    # Provenance + per-operation timing for the UI context panel: which engine and
    # apitools build produced this extraction, OCR time, per-hook time, and the
    # apitools-side per-field query times (_TIMINGS from the extractor's Collect).
    value_ms: dict = {}
    value_ms.update(base.get("_TIMINGS") or {})
    value_ms.update(per_type.get("_TIMINGS") or {})
    meta = per_type.get("_META") or base.get("_META") or {}
    ops = {
        "ocr_engine": ocr.get("ocr_engine") or meta.get("ocr_engine"),
        "ocr_ms": ocr.get("ocr_ms") if ocr.get("ocr_ms") is not None else meta.get("ocr_ms"),
        "ocr_at": ocr.get("ocr_at") or meta.get("ocr_at"),
        # build that PRODUCED the OCR (from the cached ocr_json) vs build serving now
        "ocr_apitools_version": ocr.get("ocr_apitools_version") or meta.get("ocr_apitools_version"),
        "apitools_version": ocr.get("apitools_version") or meta.get("apitools_version"),
        "base_hook_s": base_s,
        "type_hook_s": type_s,
        "value_ms": value_ms,
    }
    return {
        "hash": file_hash,
        "fields": fields,
        "value_errors": value_errors,
        "ops": ops,
        "elapsed_s": round(time.time() - t0, 1),
    }


def _run_ai_hook(hook: str, path: Path, timeout_s: float = 240.0) -> dict:
    """POST the raw file to an AI extractor webhook (invoice_extractor /
    bs_ex_2_dev). Confirmed from both workflows' own `Before Start`/`File Type
    Router` nodes (they read `.binary.data.mimeType`): a multipart upload with
    the file under field name ``data`` — n8n's default single-file binary
    property — not a JSON body, and not the `{ID, API_TOOLS_ID}` shape the
    local jqexv3-run-* hooks take (those reference an apitools file already
    OCR'd; the AI extractor OCRs its own copy from the uploaded bytes)."""
    import httpx

    ext = path.suffix.lower().lstrip(".")
    with httpx.Client(timeout=timeout_s) as c:
        r = c.post(
            f"{_n8n_base()}/{hook}",
            files={"data": (path.name, path.read_bytes(), MIME.get(ext, "application/octet-stream"))},
            auth=_ai_auth(),
        )
        r.raise_for_status()
        return r.json()


def _extract_one_ai(doc_id: str, typ: str, path: Path) -> dict:
    """AI-side counterpart to `_extract_one`: same return shape (hash / fields /
    value_errors / ops / elapsed_s), field names matching TYPES[typ]["scored"]
    exactly, so `_score_doc` grades it with the IDENTICAL comparators as the
    local run — one rubric, not two invented separately (plan §3 Phase 3)."""
    t0 = time.time()
    hook = AI_HOOKS.get(typ)
    if not hook:
        raise RuntimeError(f"no AI extractor hook for doc type {typ!r}")
    raw = _run_ai_hook(hook, path)
    fields: dict = {}
    value_errors: dict = {}
    # BOTH extractors wrap their real payload in {success, data:{...}} — confirmed
    # from indoxV2ExtractInvoiceGemini01.json's own "Format Response" node and from
    # indoxV2ActionsGlobal01.json's caller code, which reads $json.data.AI_COMPANY_ID
    # (never a flat $json.AI_COMPANY_ID). The extraction_ai_enabled "disabled" reply
    # this refactor adds carries the identical {success, data:{...empty}} shape
    # (see indoxV2ExtractInvoiceGemini01.json's "API Response - AI Disabled" node)
    # plus one extra flag, ai_disabled:true — so this parsing is correct for both.
    data = raw.get("data") if isinstance(raw, dict) else None
    ai_disabled = bool(isinstance(raw, dict) and raw.get("ai_disabled"))
    if typ in ("invoice", "shipment"):
        if not isinstance(data, dict):
            value_errors["_ai"] = f"unexpected response shape: keys={sorted(raw.keys()) if isinstance(raw, dict) else type(raw)}"
            data = {}
        fields["COMPANY_ID"] = data.get("AI_COMPANY_ID") or None
        fields["DOC_DATE"] = data.get("AI_DOC_DATE") or None
        fields["DOC_TOTAL_AMOUNT"] = data.get("AI_DOC_AMOUNT") or None
        fields["PURCHASE_ID"] = data.get("AI_ORDER_IDS") or None
        fields["DETECTED_TYPE"] = data.get("AI_TYPE")
        doc_ref = data.get("AI_DOC_ID") or None
        ship = data.get("AI_SHIPMENT_IDS")
        ship0 = (ship[0] if isinstance(ship, list) and ship else ship) or None
        if typ == "invoice":
            fields["INVOICE_ID"] = doc_ref
            fields["SHIPMENT_ID"] = ship0
        else:  # shipment: the doc's OWN id is its shipment id, per
               # extraction.py's own `_corr_field` truth-mapping convention
            fields["SHIPMENT_ID"] = doc_ref
        if ai_disabled:
            # A clean, deliberate no-op (extraction_ai_enabled=false) — not a
            # failure. Every field is genuinely absent, not lost to an error;
            # _score() will just score every field as a miss against truth,
            # same as any other doc where AI legitimately found nothing.
            value_errors.pop("_ai", None)
    elif typ == "balance_sheet":
        if ai_disabled:
            fields["DOC_DATE"] = None
            fields["BALANCE"] = None
        else:
            bs_data = data if isinstance(data, dict) else {}
            fields["DOC_DATE"] = bs_data.get("documentDate") or None
            fields["BALANCE"] = bs_data.get("documentTotalAmount") or bs_data.get("totalAmount") or None
            # COMPANY_ID intentionally absent — bs_ex_2_dev's own schema has no such
            # field (see AI_HOOKS docstring above); left unscored (None), not
            # fabricated as a false miss vs a value this extractor never produces.
            if isinstance(raw, dict) and raw.get("success") is False:
                value_errors["_ai"] = str(raw.get("error") or "extraction failed")
    return {
        "hash": None,  # the AI webhook OCRs its own copy — no shared apitools file hash to report
        "fields": fields,
        "value_errors": value_errors,
        "ops": {"mode": "ai", "hook": hook},
        "elapsed_s": round(time.time() - t0, 1),
    }


def _score_doc(doc: dict, extraction: dict) -> dict:
    cfg = TYPES[doc["type"]]
    fields = extraction["fields"]
    verrs = extraction.get("value_errors") or {}
    scored = []
    ok_n = 0
    tot = 0
    na_n = 0
    got_n = 0
    attempted = 0
    for field, _col in cfg["scored"]:
        got = fields.get(field)
        want = doc["truth"].get(field, "")
        ok = _score(field, got, want)
        attempted += 1
        if got is not None and str(got) not in ("", "None"):
            got_n += 1
        if ok is not None:
            tot += 1
            ok_n += 1 if ok else 0
        else:
            na_n += 1
        entry = {"field": field, "got": got, "want": want or None, "ok": ok}
        if field in verrs:
            entry["error"] = verrs[field]
        scored.append(entry)
    for field in cfg["extra"]:
        scored.append({"field": field, "got": fields.get(field), "want": None, "ok": None})
    return {
        "id": doc["id"],
        "type": doc["type"],
        "file": doc["file"],
        "hash": extraction["hash"],
        "detected_type": fields.get("DETECTED_TYPE"),
        "type_ok": fields.get("DETECTED_TYPE") == doc.get("type_truth", doc["type"]),
        "values": scored,
        # ACCURACY — `ok` of `total`, over the fields that HAVE ground truth. `_score()`
        # returns None when `want` is empty, and that None is excluded from `total` here,
        # so a field the document genuinely doesn't print is N/A and never a miss.
        "ok": ok_n,
        "total": tot,
        # COVERAGE — `got` of `attempted`, over every scored field regardless of truth.
        # This is a DIFFERENT denominator and answers a different question, and the record
        # used to expose only the accuracy pair. Twice in one day (2026-08-06) a reader took
        # a coverage ratio for an accuracy one and concluded shipment DOC_TOTAL_AMOUNT was
        # "1 of 15" — it is 1 of 1, with 14 documents that print no amount at all, because a
        # delivery note is a goods-received note and ~35-50% of them carry no price. Naming
        # both pairs explicitly is what stops that re-derivation; nothing here changes how
        # anything is scored, and the extraction gate still reads `ok`/`total` only.
        "got": got_n,
        "attempted": attempted,
        "na": na_n,
        # a dead value-call is a doc-level ERROR, not a quiet miss — it must show in
        # the run's error counter, exactly like an OCR crash would
        "error": ("value calls failed: " + "; ".join(
            f"{f}: {m}" for f, m in verrs.items())[:280]) if verrs else None,
        # provenance + per-operation timing (engine, apitools build, ocr/hook/value ms)
        "ops": extraction.get("ops"),
        "elapsed_s": extraction["elapsed_s"],
        "at": time.time(),
    }


def _run_worker(run_id: str, docs: list[dict], conc: int = 6, mode: str = "local") -> None:
    """Execute a batch of documents. Each doc is independent — OCR (apitools) + two n8n
    query hooks, all blocking HTTP the BFF only WAITS on — so the docs run concurrently
    through a bounded thread pool (``conc``). apitools (8 gunicorn workers / 4 CPU) and
    n8n (queue mode) absorb the concurrency; results are identical to serial, only faster.
    Per-doc isolation, incremental crash-safe persistence and cancellation are all
    preserved. conc=1 reproduces the old serial behaviour.

    ``mode="ai"`` (EXTRACTION-REFACTOR-PLAN.md §3 Phase 3 shadow harness) runs the
    SAME documents through the AI extractor webhooks instead of the local jqexv3
    hooks, scored by the identical comparators, and writes to the separate
    `_RESULTS_AI` store — `_RESULTS` (the local/default mode) is untouched."""
    from concurrent.futures import ThreadPoolExecutor

    results_store = _RESULTS if mode != "ai" else _RESULTS_AI
    run_results: dict[str, dict] = {}
    conc = max(1, int(conc))
    stop = threading.Event()
    persist_lock = threading.Lock()

    def _persist(snap: dict, results_copy: dict) -> None:
        # _write_json is atomic (temp+rename), but serialize snapshots so concurrent
        # completions don't interleave their per-run history writes.
        with persist_lock:
            _persist_run(snap, results_copy)
            _persist_latest()

    def _process(doc: dict) -> None:
        if stop.is_set():
            return
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is None or run.get("cancelled"):
                stop.set()
                return
        # Up to 2 attempts: a doc-level failure here is almost always transient
        # (an apitools worker OOM-killed mid-OCR, a call timed out under a load
        # spike) — the same doc passes moments later. A run must not end with an
        # error it never even retried. The retry is per-doc, in this doc's own
        # worker slot, so it cannot double-count run counters.
        result = None
        for attempt in (1, 2):
            try:
                path = _doc_path(doc["type"], doc["file"])
                if path is None:
                    raise RuntimeError("file missing")
                extraction = (_extract_one(doc["id"], doc["type"], path) if mode != "ai"
                              else _extract_one_ai(doc["id"], doc["type"], path))
                result = _score_doc(doc, extraction)
                result["mode"] = mode
                # _score_doc sets error itself when value calls died — don't erase it
                result.setdefault("error", None)
            except Exception as e:  # per-doc isolation — one failure never kills the run
                logger.warning("extraction failed for %s (attempt %d): %s",
                               doc["id"], attempt, e)
                result = {"id": doc["id"], "type": doc["type"], "file": doc["file"],
                          "hash": None, "values": [], "ok": 0, "total": 0,
                          "detected_type": None, "type_ok": None, "mode": mode,
                          "elapsed_s": None, "at": time.time(),
                          "error": f"attempt {attempt}: {str(e)[:280]}"}
            if not result.get("error") or attempt == 2 or stop.is_set():
                break
            logger.warning("retrying %s after error: %s", doc["id"], result["error"])
            time.sleep(3)  # let the killed worker reboot / the spike drain
        with _LOCK:
            results_store[doc["id"]] = result
            run_results[doc["id"]] = result
            run = _RUNS.get(run_id)
            if run is None:
                stop.set()
                return
            run["done"] += 1
            run["ok"] += result["ok"]
            run["total"] += result["total"]
            if result.get("error"):
                run["errors"] += 1
            run["current"] = doc["id"]
            snap = dict(run)
            results_copy = dict(run_results)
        _persist(snap, results_copy)

    def _safe(doc: dict) -> None:
        try:
            _process(doc)
        except Exception as e:  # never let a worker thread die silently
            logger.warning("worker task crashed for %s: %s", doc.get("id"), e)

    if conc <= 1:
        for doc in docs:
            if stop.is_set():
                break
            _safe(doc)
    else:
        with ThreadPoolExecutor(max_workers=conc, thread_name_prefix="extract") as ex:
            list(ex.map(_safe, docs))

    with _LOCK:
        run = _RUNS.get(run_id)
        if run is not None:
            if not run.get("cancelled"):
                run["status"] = "done"
            run["current"] = None
            run["finished"] = time.time()
            snap = dict(run)
            results_copy = dict(run_results)
    if run is not None:
        _persist(snap, results_copy)


# ── blueprint ────────────────────────────────────────────────────────────────
def register_extraction(bp: Blueprint) -> None:
    """Mount the extraction endpoints on the main /incomingDocuments blueprint."""

    @bp.get("/extraction/dataset")
    def extraction_dataset():
        docs = _load_dataset()
        with _LOCK:
            for d in docs:
                d["result"] = _RESULTS.get(d["id"])
                # AI-side shadow result, if a shadow run has covered this doc —
                # additive field, existing consumers of "result" are unaffected.
                d["result_ai"] = _RESULTS_AI.get(d["id"])
            uploads = list(_UPLOADS.values())
        return jsonify({
            "docs": docs,
            "uploads": uploads,
            "dataset_dir": str(DATASET_DIR),
            "available": DATASET_DIR.exists(),
            "types": {k: v["label"] for k, v in TYPES.items()},
        })

    @bp.post("/extraction/run")
    def extraction_run():
        body = request.get_json(silent=True) or {}
        ids = body.get("ids")  # None => all
        mode = "ai" if body.get("mode") == "ai" else "local"
        docs = _load_dataset()
        if ids:
            wanted = set(ids)
            docs = [d for d in docs if d["id"] in wanted]
        if not docs:
            return jsonify({"error": "no documents matched"}), 400
        run_id = uuid.uuid4().hex[:12]
        scope = "selected" if ids else "all"
        try:
            conc = int(body.get("concurrency") or os.getenv("EXTRACTION_CONCURRENCY", "6"))
        except (TypeError, ValueError):
            conc = 6
        conc = max(1, min(conc, 16))
        with _LOCK:
            # single active run keeps apitools/n8n load sane (operator tool) —
            # AI and local runs share this gate too, same reason
            if any(r.get("status") == "running" for r in _RUNS.values()):
                return jsonify({"error": "extraction already running"}), 409
            run = {"run_id": run_id, "status": "running", "scope": scope, "mode": mode,
                   "docs_total": len(docs), "done": 0, "ok": 0, "total": 0,
                   "errors": 0, "current": None, "started": time.time(),
                   "finished": None, "cancelled": False, "concurrency": conc}
            _RUNS[run_id] = run
            snap = dict(run)
        _persist_run(snap, {})  # visible in history from the first second
        _prune_runs()
        threading.Thread(target=_run_worker, args=(run_id, docs, conc, mode), daemon=True).start()
        return jsonify({"run_id": run_id, "docs_total": len(docs), "concurrency": conc, "mode": mode})

    @bp.get("/extraction/run/<run_id>")
    def extraction_run_status(run_id: str):
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is None:
                return jsonify({"error": "unknown run"}), 404
            return jsonify(dict(run))

    @bp.post("/extraction/run/<run_id>/cancel")
    def extraction_run_cancel(run_id: str):
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is None:
                return jsonify({"error": "unknown run"}), 404
            run["cancelled"] = True
            run["status"] = "cancelled"
            run["finished"] = time.time()
        return jsonify({"ok": True})

    @bp.get("/extraction/runs")
    def extraction_runs():
        """Run history, newest first — every batch run, single rerun and upload."""
        with _LOCK:
            runs = sorted((dict(r) for r in _RUNS.values()),
                          key=lambda r: r.get("started") or 0, reverse=True)
        return jsonify({"runs": runs[:200]})

    @bp.get("/extraction/runs/<run_id>")
    def extraction_run_full(run_id: str):
        """One historical run WITH its per-doc results (read from disk)."""
        with _LOCK:
            summary = _RUNS.get(run_id)
        path = next((p for p in _run_files() if p.stem.endswith(f"-{run_id}")), None)
        if path is None and summary is None:
            return jsonify({"error": "unknown run"}), 404
        results: dict = {}
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results = data.get("results") or {}
                if summary is None:
                    summary = {k: v for k, v in data.items() if k != "results"}
            except Exception as e:
                logger.warning("run file unreadable %s: %s", path, e)
        return jsonify({**(summary or {}), "results": results})

    @bp.delete("/extraction/runs/<run_id>")
    def extraction_run_delete(run_id: str):
        with _LOCK:
            run = _RUNS.get(run_id)
            if run is not None and run.get("status") == "running":
                return jsonify({"error": "run is active"}), 409
            _RUNS.pop(run_id, None)
        for p in _run_files():
            if p.stem.endswith(f"-{run_id}"):
                try:
                    p.unlink()
                except OSError:
                    pass
        return jsonify({"ok": True})

    @bp.get("/extraction/history/<path:doc_id>")
    def extraction_history(doc_id: str):
        """One document's extractions across ALL persisted runs, newest first."""
        entries = []
        for p in _run_files()[:300]:
            try:
                run = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            res = (run.get("results") or {}).get(doc_id)
            if res:
                entries.append({"run_id": run.get("run_id"), "scope": run.get("scope"),
                                "run_status": run.get("status"),
                                "started": run.get("started"), "result": res})
        return jsonify({"history": entries})

    @bp.get("/extraction/file/<typ>/<name>")
    def extraction_file(typ: str, name: str):
        path = _doc_path(typ, name)
        if path is None:
            return jsonify({"error": "not found"}), 404
        ext = path.suffix.lower().lstrip(".")
        return send_file(path, mimetype=MIME.get(ext, "application/octet-stream"),
                         as_attachment=False, max_age=3600)

    @bp.get("/extraction/draw/<typ>/<name>")
    def extraction_draw(typ: str, name: str):
        """The apitools-drawn overlay: every per-type query's match boxed on the
        document. Cached on disk by (hash, category) — drawing is idempotent."""
        import httpx

        path = _doc_path(typ, name)
        if path is None:
            return jsonify({"error": "not found"}), 404
        category = TYPES.get(typ, {}).get("draw_category") or request.args.get("category", "invoice")
        try:
            file_hash = _ocr_file_id(path)
            DRAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = DRAW_CACHE_DIR / f"{file_hash}-{category}.png"
            if cache.exists() and cache.stat().st_size > 0:
                return send_file(cache, mimetype="image/png", max_age=3600)
            queries = _settings_queries()
            routing = (queries.get("q_v3_routing") or {})
            qmap = {**(routing.get("base") or {}), **(routing.get(category) or {})}
            specs = [{"label": f, "ocr_json_query": queries[qk]}
                     for f, qk in qmap.items() if qk in queries and f != "TYPE"]
            with httpx.Client(timeout=180.0) as c:
                r = c.post(f"{APITOOLS_BASE}/documentDraw", params={"format": "image"},
                           json={"file_id": file_hash, "queries": specs})
                r.raise_for_status()
                cache.write_bytes(r.content)
            return send_file(cache, mimetype="image/png", max_age=3600)
        except Exception as e:
            logger.warning("draw failed for %s/%s: %s", typ, name, e)
            return jsonify({"error": f"draw failed: {e}"}), 502

    @bp.get("/extraction/tokens/<typ>/<name>")
    def extraction_tokens(typ: str, name: str):
        """זיהוי תווים — EVERY OCR token boxed + labelled on the document (apitools
        /documentOcrDraw). Shows exactly what the character recognition read, before
        any query runs. Disk-cached by hash."""
        import httpx

        path = _doc_path(typ, name)
        if path is None:
            return jsonify({"error": "not found"}), 404
        try:
            file_hash = _ocr_file_id(path)
            DRAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = DRAW_CACHE_DIR / f"{file_hash}-tokens.png"
            if cache.exists() and cache.stat().st_size > 0:
                return send_file(cache, mimetype="image/png", max_age=3600)
            with httpx.Client(timeout=180.0) as c:
                r = c.get(f"{APITOOLS_BASE}/documentOcrDraw", params={"file_id": file_hash})
                r.raise_for_status()
                cache.write_bytes(r.content)
            return send_file(cache, mimetype="image/png", max_age=3600)
        except Exception as e:
            logger.warning("tokens draw failed for %s/%s: %s", typ, name, e)
            return jsonify({"error": f"tokens draw failed: {e}"}), 502

    # ── the same two overlays, for a PRODUCTION document ─────────────────────
    # The three routes above resolve a file inside the extraction-TESTING dataset by
    # `type/filename` (`_doc_path`). A real `incoming_documents` row is keyed by `ID`
    # (`doc_<hash>`), a namespace that never overlaps — which is why the document page
    # could not show its own document and had to pass nulls (verified live 2026-08-05:
    # /extraction/{file,draw,tokens} 404 `{"error":"not found"}` for every production id).
    # apitools never needed the dataset path: BOTH overlay endpoints key on the file
    # hash alone, and every production row already carries that hash in `API_TOOLS_ID`
    # (5775/6318 = 91% populated, measured 2026-08-06). So these routes reuse the SAME
    # apitools calls and the SAME disk cache off `API_TOOLS_ID` — one overlay
    # implementation, not a second spelling, and no invented URL.
    #
    # COVERAGE, measured rather than inferred: the column being 91% populated does NOT
    # mean 91% of documents render. The hash is historical and apitools' caches have been
    # evicted since (6 ocr_cache entries, 1150 files, 26 page images on 2026-08-06); on a
    # 25-document RANDOM sample every one of the 25 came back `404 file_not_found` from
    # apitools. Only the recently-processed tail resolves. Sampling `order by "ID" desc`
    # hides this completely — that ordering IS the tail. What these routes fix is the
    # namespace (they finally key on `incoming_documents.ID`) and the failure shape; the
    # remaining gap is data availability, which needs the bytes re-fetched from LINK and
    # re-OCR'd. Do not quote 91% as a render rate.

    # A COLD draw pays the document's OCR load once; the drawing itself is cheap.
    # The dataset routes use 180s, but dataset documents are already warm — on a cold
    # production document that expires mid-load and surfaces as a bogus 502
    # "draw failed: timed out" for an endpoint that was working fine.
    #
    # Sizing, measured on real production documents rather than guessed:
    #   2026-08-06, degraded stack (load avg 32, documentJsonQuery timing out):
    #       cold draw 67.2s for the first query spec, 7.5s for the second.
    #   2026-08-06, after the GlitchTip loop and documentJsonQuery were fixed
    #   (load avg 13.7): cold tokens 1.2-3.2s, cold draw 4.8-9.8s across 3 documents.
    # So the healthy cold case is ~10s and the worst degraded case seen is ~67s.
    # 240s leaves ~3.5x headroom over that worst case and ~24x over healthy, while
    # still bounding how long a browser tab can hang on an image that will never
    # arrive. It stays well inside apitools' own GUNICORN_TIMEOUT=900, so the client
    # is never the tighter of the two — which was the actual defect here.
    DOC_DRAW_TIMEOUT_S = float(os.getenv("INDOX_DOCUMENT_DRAW_TIMEOUT_S", "240"))

    def _document_draw_handle(doc_id: str) -> tuple[bool, str | None, str | None]:
        """``(row_exists, apitools file hash, draw category)`` for one production doc.

        Separates 'no such document' from 'document known, not OCR'd yet' — they are
        different answers and collapsing them sends the caller hunting the wrong bug.

        Raises ``_DocLookupFailed`` when the ROW ITSELF could not be read, which is a third
        answer again and used to be indistinguishable from the other two: the read threw,
        the app's catch-all handler logged a traceback and returned
        ``{"error": "Internal server error"}`` 500, and the browser — which cannot read a
        traceback — showed a document with no overlay. See ``_lookup_failed``."""
        from .backends.supabase_transport import HttpxSupabaseTransport
        from .api import _request_schema

        # [multi-instance 2026-08-28] Reads the REQUEST's tenant, not public. Document IDs are only
        # unique within a tenant, so a hardcoded schema here answers "no such document" for a real
        # document, or worse, returns a different client's row under a colliding id.
        try:
            rows = HttpxSupabaseTransport().select(
                schema=_request_schema(), table="incoming_documents",
                select=["ID", "TYPE", "API_TOOLS_ID"],
                ids=[doc_id], pk="ID", limit=1) or []
        except Exception as e:
            raise _DocLookupFailed(str(e)) from e
        if not rows:
            return False, None, None
        row = rows[0]
        file_hash = str(row.get("API_TOOLS_ID") or "").strip() or None
        # DB TYPE is the document's own vocabulary; TYPES above is the dataset's.
        # UNKNOWN/ORDER/NULL have no per-type query set — fall back to the base pass.
        category = {"INVOICE": "invoice", "SHIPMENT": "shipment",
                    "BALANCE_SHEET": "bs"}.get(str(row.get("TYPE") or "").upper(), "invoice")
        return True, file_hash, category

    def _lookup_failed(doc_id: str, err: "_DocLookupFailed"):
        """The answer when the document ROW could not be read at all.

        Two different causes, two different answers, neither of them 500:

        * **No tenant named.** Every document asset route is tenant-scoped, so a request with
          no `?instance=` reads schema `public` — and `public.incoming_documents` stopped
          existing when the compatibility views were dropped (2026-08-28). That is a caller
          error and says so, with the parameter it is missing. This is the exact shape of the
          bug found on 2026-09-02: the webapp's `<img>` urls carried no instance, PostgREST
          answered 404, and the operator saw a document with the overlay silently absent.
        * **Named, but the read failed anyway.** Postgres down, a schema that does not exist,
          a transport error. That is ours, not the caller's: 502, and the schema we tried is
          in the body so the next person does not have to guess it from a log."""
        from .api import _request_schema

        if not (request.args.get("instance") or "").strip():
            return jsonify({
                "error": "instance required",
                "document": doc_id,
                "hint": "document asset routes are tenant-scoped — append ?instance=<id>",
            }), 400
        return jsonify({
            "error": "document lookup failed",
            "document": doc_id,
            "schema": _request_schema(),
            "detail": str(err)[:300],
        }), 502

    def _nothing_to_draw(doc_id: str, exists: bool, file_hash: str | None):
        """A 404 body when there is nothing to draw, else None."""
        if file_hash:
            return None
        if not exists:
            return jsonify({"error": "unknown document", "document": doc_id}), 404
        return jsonify({"error": "no apitools OCR for this document yet",
                        "document": doc_id}), 404

    def _cache_and_send(cache, content: bytes, content_type: str | None):
        """Persist an apitools overlay and serve it under the type apitools actually
        returned. The overlay is JPEG or PNG depending on the source document; naming
        the file .png and always claiming image/png (as the dataset routes do) mislabels
        every JPEG overlay and only survives because browsers sniff."""
        cache.write_bytes(content)
        mime = (content_type or "").split(";")[0].strip().lower()
        return send_file(cache, mimetype=mime if mime.startswith("image/") else "image/png",
                         max_age=3600)

    def _send_cached(cache):
        """Serve an already-drawn overlay under its real type, sniffed from the bytes
        (the cache filename says .png but apitools returns JPEG for some documents)."""
        head = cache.open("rb").read(3)
        return send_file(cache, mimetype="image/jpeg" if head == b"\xff\xd8\xff" else "image/png",
                         max_age=3600)

    @bp.get("/documents/<path:doc_id>/file")
    def document_file(doc_id: str):
        """מסמך מקורי — the REAL document's own page image, via API_TOOLS_ID.

        Not cached on disk here: apitools serves this straight off the rasterised page
        it already keeps for the OCR (`.storage/ocr_pdf_images/<hash>.jpg`), so a second
        copy under this app's cache would just be a stale duplicate of a file that is
        already on disk one hop away."""
        import httpx

        try:
            exists, file_hash, _ = _document_draw_handle(doc_id)
        except _DocLookupFailed as e:
            return _lookup_failed(doc_id, e)
        missing = _nothing_to_draw(doc_id, exists, file_hash)
        if missing:
            return missing
        try:
            with httpx.Client(timeout=DOC_DRAW_TIMEOUT_S) as c:
                r = c.get(f"{APITOOLS_BASE}/documentImage", params={"file_id": file_hash})
            if r.status_code == 404:
                return jsonify({"error": "no stored page image for this document",
                                "document": doc_id}), 404
            r.raise_for_status()
            mime = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            return Response(r.content, mimetype=mime if mime.startswith("image/") else "image/jpeg",
                            headers={"Cache-Control": "private, max-age=3600"})
        except Exception as e:
            logger.warning("document file fetch failed for %s: %s", doc_id, e)
            return jsonify({"error": f"document image failed: {e}"}), 502

    @bp.get("/documents/<path:doc_id>/tokens")
    def document_tokens(doc_id: str):
        """זיהוי תווים for a REAL document — every OCR token boxed, via API_TOOLS_ID."""
        import httpx

        try:
            exists, file_hash, _ = _document_draw_handle(doc_id)
        except _DocLookupFailed as e:
            return _lookup_failed(doc_id, e)
        missing = _nothing_to_draw(doc_id, exists, file_hash)
        if missing:
            return missing
        try:
            DRAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = DRAW_CACHE_DIR / f"{file_hash}-tokens.png"
            if cache.exists() and cache.stat().st_size > 0:
                return _send_cached(cache)
            with httpx.Client(timeout=DOC_DRAW_TIMEOUT_S) as c:
                r = c.get(f"{APITOOLS_BASE}/documentOcrDraw", params={"file_id": file_hash})
                r.raise_for_status()
                return _cache_and_send(cache, r.content, r.headers.get("content-type"))
        except Exception as e:
            logger.warning("document tokens draw failed for %s: %s", doc_id, e)
            return jsonify({"error": f"tokens draw failed: {e}"}), 502

    @bp.get("/documents/<path:doc_id>/draw")
    def document_draw(doc_id: str):
        """חילוץ מסומן for a REAL document — each per-type query's match boxed,
        via API_TOOLS_ID. Same disk cache key as the dataset route (hash, category)."""
        import httpx

        try:
            exists, file_hash, category = _document_draw_handle(doc_id)
        except _DocLookupFailed as e:
            return _lookup_failed(doc_id, e)
        missing = _nothing_to_draw(doc_id, exists, file_hash)
        if missing:
            return missing
        category = request.args.get("category") or category
        try:
            DRAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache = DRAW_CACHE_DIR / f"{file_hash}-{category}.png"
            if cache.exists() and cache.stat().st_size > 0:
                return _send_cached(cache)
            queries = _settings_queries()
            routing = (queries.get("q_v3_routing") or {})
            qmap = {**(routing.get("base") or {}), **(routing.get(category) or {})}
            specs = [{"label": f, "ocr_json_query": queries[qk]}
                     for f, qk in qmap.items() if qk in queries and f != "TYPE"]
            if not specs:
                return jsonify({"error": f"no query set configured for category {category}"}), 404
            with httpx.Client(timeout=DOC_DRAW_TIMEOUT_S) as c:
                r = c.post(f"{APITOOLS_BASE}/documentDraw", params={"format": "image"},
                           json={"file_id": file_hash, "queries": specs})
                r.raise_for_status()
                return _cache_and_send(cache, r.content, r.headers.get("content-type"))
        except Exception as e:
            logger.warning("document draw failed for %s: %s", doc_id, e)
            return jsonify({"error": f"draw failed: {e}"}), 502

    @bp.post("/extraction/rerun/<path:doc_id>")
    def extraction_rerun(doc_id: str):
        """Synchronous single-doc rerun (detail page) — a few seconds. ``?fresh=1``
        forces a re-OCR (bypassing the apitools ocr_cache) and clears this doc's
        draw cache first — the 'reset cache & rerun' action, for a guaranteed clean
        run after an engine change. ``?mode=ai`` runs the AI shadow extractor
        instead (see AI_HOOKS) and writes to the separate `_RESULTS_AI` store —
        the default local mode and its `_RESULTS` store are unaffected."""
        fresh = request.args.get("fresh") in ("1", "true", "yes")
        mode = "ai" if request.args.get("mode") == "ai" else "local"
        typ, _, name = doc_id.partition("/")
        if typ == "upload":
            if mode == "ai":
                return jsonify({"error": "mode=ai is only for dataset documents, not uploads"}), 400
            # re-extract from the persisted file (also re-registers the upload record
            # if latest.json predates it). 404s if no file.
            return _do_upload_extract(name, fresh=fresh)
        docs = [d for d in _load_dataset() if d["id"] == doc_id]
        if not docs:
            return jsonify({"error": "unknown document"}), 404
        doc = docs[0]
        path = _doc_path(typ, name)
        if path is None:
            return jsonify({"error": "file missing"}), 404
        try:
            extraction = (_extract_one(doc_id, typ, path, fresh=fresh) if mode != "ai"
                          else _extract_one_ai(doc_id, typ, path))
            result = _score_doc(doc, extraction)
            result["mode"] = mode
            # _score_doc sets error itself when value calls died — don't erase it
            result.setdefault("error", None)
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 502
        with _LOCK:
            (_RESULTS_AI if mode == "ai" else _RESULTS)[doc_id] = result
        _record_single_run(result, "reset" if fresh else "single", mode=mode)
        return jsonify(result)

    def _do_upload_extract(name: str, fresh: bool = False):
        """Extract an uploaded doc: base pass detects the type, then the matching
        per-type pass. No ground truth — values only."""
        path = UPLOADS_DIR / os.path.basename(name)
        if not path.exists():
            return jsonify({"error": "upload missing"}), 404
        doc_id = f"upload/{path.name}"
        try:
            t0 = time.time()
            file_hash = _ocr_file_id(path, fresh=fresh)
            if fresh:
                _clear_draw_cache(file_hash)
            payload = [{"ID": doc_id, "API_TOOLS_ID": file_hash}]
            base = (_run_hook("jqexv3-run-base", payload) or [{}])[0]
            detected = base.get("TYPE")
            per_type = {}
            hook = TYPES.get(detected or "", {}).get("hook")
            if hook:
                per_type = (_run_hook(hook, payload) or [{}])[0]
            values = [{"field": "COMPANY_ID", "got": base.get("COMPANY_ID"), "want": None, "ok": None},
                      {"field": "BASE_DATE", "got": base.get("DOC_DATE"), "want": None, "ok": None}]
            for k, v in per_type.items():
                if k not in ("ID", "TYPE", "API_TOOLS_ID"):
                    values.append({"field": k, "got": v, "want": None, "ok": None})
            rec = {"id": doc_id, "type": "upload", "file": path.name, "hash": file_hash,
                   "detected_type": detected, "type_ok": None, "values": values,
                   "ok": 0, "total": 0, "elapsed_s": round(time.time() - t0, 1),
                   "at": time.time(), "error": None,
                   "draw_category": TYPES.get(detected or "", {}).get("draw_category", "invoice")}
            with _LOCK:
                _UPLOADS[doc_id] = {"id": doc_id, "file": path.name, "type": "upload",
                                    "type_label": "העלאה", "truth": {}, "result": rec}
                _RESULTS[doc_id] = rec
            _record_single_run(rec, "upload")
            return jsonify(rec)
        except Exception as e:
            logger.warning("upload extraction failed for %s: %s", name, e)
            return jsonify({"error": str(e)[:300]}), 502

    @bp.post("/extraction/upload")
    def extraction_upload():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file"}), 400
        ext = Path(f.filename).suffix.lower().lstrip(".")
        if ext not in MIME:
            return jsonify({"error": "pdf / jpg / png בלבד"}), 400
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\-֐-׿]", "_", os.path.basename(f.filename))
        path = UPLOADS_DIR / safe
        f.save(path)
        return _do_upload_extract(safe)

    @bp.get("/extraction/queries")
    def extraction_queries():
        """`queries` is the EDITABLE template (what PUT writes back); `resolved` is the
        same query with the company registry bound from the companies table, for display.
        Keeping them separate is what stops a save from baking the registry into the
        stored query. `resolved` is best-effort: the panel still renders without it."""
        try:
            return jsonify({"queries": _settings_queries(),
                            "resolved": _resolved_queries()})
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 502

    @bp.put("/extraction/queries/<key>")
    def extraction_query_put(key: str):
        """Edit ONE extraction query (settings q_v3_* row) from the הגדרות UI.

        The queries are the extraction logic — they load fresh from settings on
        every n8n run, so a save takes effect on the next extraction. Only
        q_v3_* keys are writable here; the value must be a JSON object (the
        query spec / the routing map). The draw-overlay cache is cleared —
        cached overlays render the OLD queries."""
        if not re.fullmatch(r"q_v3_[a-z0-9_]+", key):
            return jsonify({"error": "רק מפתחות q_v3_* ניתנים לעריכה כאן"}), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "value" not in body:
            return jsonify({"error": "גוף הבקשה חייב להכיל value"}), 400
        value = body["value"]
        if not isinstance(value, dict):
            return jsonify({"error": "השאילתה חייבת להיות אובייקט JSON"}), 400
        from .backends.supabase_transport import HttpxSupabaseTransport
        from .api import _instance, _request_schema

        # [multi-instance 2026-08-28] A WRITE, and the last hardcoded `public` on this path. It
        # mattered more than the reads: `public.settings` is an auto-updatable VIEW over ONE tenant,
        # so an operator viewing levi and saving a query wrote the new value into HACOHEN's settings
        # — silently, with a success response, and visible to the other client on their next
        # extraction. Note the two different `instance`s on this line and keep them apart: the COLUMN
        # is the component ('incoming-documents-main'), the SCHEMA is the tenant.
        try:
            HttpxSupabaseTransport().upsert(
                schema=_request_schema(), table="settings", on_conflict="instance,key",
                rows=[{"instance": _instance(), "key": key,
                       "value": json.dumps(value, ensure_ascii=False)}],
            )
        except Exception as e:
            return jsonify({"error": str(e)[:300]}), 502
        # stale overlays would render the pre-edit queries
        import shutil

        shutil.rmtree(DRAW_CACHE_DIR, ignore_errors=True)
        return jsonify({"success": True, "key": key})
