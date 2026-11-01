"""Feature-validation API server.

Provides REST endpoints for running validations, querying benchmarks,
and serving a live feature observability dashboard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import mimetypes

import requests as http_requests
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FEATURES_ROOT = Path(os.getenv("FEATURES_ROOT", "/app/features"))
APITOOLS_BASE_URL = os.getenv("APITOOLS_BASE_URL", "http://apitools:8080")

# The upload cap belongs to apitools, not to this dashboard. apitools enforces MAX_CONTENT_LENGTH
# (apps/apitools/src/api/__init__.py) and answers 413 itself, so a second, DIFFERENT number here gave
# one OCR capability two contracts: this endpoint refused at 10MB what /documentOcr accepts at 50MB,
# and the UI advertised the smaller figure. A guard is still worth keeping -- this route buffers the
# whole file in memory before forwarding -- but it must be the SAME number, in one place.
APITOOLS_MAX_UPLOAD_BYTES = int(
    os.getenv("APITOOLS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
)

if str(FEATURES_ROOT) not in sys.path:
    sys.path.insert(0, str(FEATURES_ROOT))

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
SCHEDULE_INTERVAL_MINUTES = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "360"))
scheduler = BackgroundScheduler(daemon=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Feature Validation API", version="2.0.0")

_last_run_lock = threading.Lock()
_last_run: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def discover_features() -> List[Dict[str, Any]]:
    """Scan FEATURES_ROOT for directories containing scenario.json."""
    features: List[Dict[str, Any]] = []
    if not FEATURES_ROOT.is_dir():
        return features
    for child in sorted(FEATURES_ROOT.iterdir()):
        scenario_path = child / "scenario.json"
        if child.is_dir() and scenario_path.exists():
            try:
                with scenario_path.open() as f:
                    scenario = json.load(f)
            except Exception:
                scenario = {}
            features.append({
                "name": child.name,
                "description": scenario.get("description", ""),
                "feature": scenario.get("feature", child.name),
                "path": str(child),
            })
    return features


def get_latest_benchmark(feature_name: str) -> Optional[Dict[str, Any]]:
    latest = FEATURES_ROOT / feature_name / "benchmarks" / "latest.json"
    if not latest.exists():
        return None
    try:
        with latest.open() as f:
            return json.load(f)
    except Exception:
        return None


def list_benchmarks(feature_name: str) -> List[str]:
    bench_dir = FEATURES_ROOT / feature_name / "benchmarks"
    if not bench_dir.is_dir():
        return []
    return sorted(
        [f.name for f in bench_dir.glob("benchmark-*.json")],
        reverse=True,
    )


def read_benchmark(feature_name: str, filename: str) -> Optional[Dict[str, Any]]:
    bench_path = FEATURES_ROOT / feature_name / "benchmarks" / filename
    if not bench_path.exists():
        return None
    try:
        bench_path = bench_path.resolve()
        if not str(bench_path).startswith(str(FEATURES_ROOT.resolve())):
            return None
    except Exception:
        return None
    try:
        with bench_path.open() as f:
            return json.load(f)
    except Exception:
        return None


def summarize_benchmark(b: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a compact summary from a full benchmark dict."""
    results = b.get("results", [])
    case_summaries = []
    for r in results:
        evals = r.get("evaluations", {})
        details = r.get("evaluation_details", [])
        query_resp = r.get("query_response", {})
        analysis = r.get("analysis", {})
        summary_entry: Dict[str, Any] = {
            "name": r.get("name"),
            "status": r.get("status"),
            "source_file": r.get("source_file"),
            "file_id": r.get("file_id"),
            "assertions_passed": sum(1 for v in evals.values() if v),
            "assertions_total": len(evals),
            "ocr_json_query": query_resp.get("ocr_json_query"),
            "analysis": {
                k: analysis.get(k)
                for k in (
                    "result_value", "aligned_value", "text_match",
                    "drawing_path", "error", "match_count",
                    "matched_option_names",
                )
            },
            "failed_assertions": [
                {
                    "name": d["name"],
                    "expected": d.get("expected"),
                    "actual": d.get("actual"),
                    "operator": d.get("operator"),
                }
                for d in details
                if not d.get("passed")
            ],
        }
        # Integration-specific fields
        if r.get("integration"):
            summary_entry["integration"] = r["integration"]
        if r.get("type"):
            summary_entry["test_type"] = r["type"]
        if r.get("description"):
            summary_entry["description"] = r["description"]
        if r.get("duration_s") is not None:
            summary_entry["duration_s"] = r["duration_s"]
        # N8N / HTTP response details from query_response
        if query_resp.get("status_code") is not None:
            summary_entry["response_status"] = query_resp["status_code"]
        if query_resp.get("body") is not None:
            body = query_resp["body"]
            # Truncate large bodies for the summary
            body_str = json.dumps(body) if not isinstance(body, str) else body
            summary_entry["response_body"] = (
                body_str[:2000] if len(body_str) > 2000 else body_str
            )
        if query_resp.get("error"):
            summary_entry["response_error"] = query_resp["error"]
        if query_resp.get("request_url"):
            summary_entry["request_url"] = query_resp["request_url"]
        if query_resp.get("request_method"):
            summary_entry["request_method"] = query_resp["request_method"]
        if query_resp.get("request_body"):
            summary_entry["request_body"] = query_resp["request_body"]
        # N8N execution links
        if query_resp.get("execution_url"):
            summary_entry["execution_url"] = query_resp["execution_url"]
        if query_resp.get("workflow_url"):
            summary_entry["workflow_url"] = query_resp["workflow_url"]
        if query_resp.get("execution_id"):
            summary_entry["execution_id"] = query_resp["execution_id"]
        if query_resp.get("execution_status"):
            summary_entry["execution_status"] = query_resp["execution_status"]
        if query_resp.get("workflow_id"):
            summary_entry["workflow_id"] = query_resp["workflow_id"]
        # WhatsApp / Redis / Postgres specific
        if query_resp.get("is_connected") is not None:
            summary_entry["is_connected"] = query_resp["is_connected"]
        if query_resp.get("row_count") is not None:
            summary_entry["row_count"] = query_resp["row_count"]
        if query_resp.get("rows"):
            rows = query_resp["rows"]
            summary_entry["rows_preview"] = rows[:5]

        case_summaries.append(summary_entry)
    return {
        "feature": b.get("feature"),
        "timestamp": b.get("timestamp"),
        "all_passed": b.get("all_passed"),
        "case_count": b.get("case_count"),
        "cases_passed": b.get("cases_passed"),
        "failures": b.get("failures", []),
        "cases": case_summaries,
    }


def run_feature_validation(
    feature_name: str, case_filters: Optional[List[str]] = None
) -> Dict[str, Any]:
    feature_dir = FEATURES_ROOT / feature_name
    script = feature_dir / "validate-feature.py"
    if not script.exists():
        return {"error": f"No validate-feature.py in {feature_name}"}

    cmd = [sys.executable, str(script)]
    if case_filters:
        for c in case_filters:
            cmd.extend(["--case", c])

    try:
        # Balance-sheet cases can take 30-90s each; allow generous timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=str(feature_dir),
            env={**os.environ, "PYTHONPATH": str(FEATURES_ROOT)},
        )
        benchmark = get_latest_benchmark(feature_name)
        return {
            "feature": feature_name,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "benchmark": benchmark,
        }
    except subprocess.TimeoutExpired:
        return {"feature": feature_name, "error": "Validation timed out (300s)"}
    except Exception as exc:
        return {"feature": feature_name, "error": str(exc)}


def run_all_validations() -> Dict[str, Any]:
    features = discover_features()
    results = {}
    for feat in features:
        results[feat["name"]] = run_feature_validation(feat["name"])
    passed = sum(
        1 for r in results.values() if r.get("benchmark", {}).get("all_passed")
    )
    total = len(results)
    return {
        "results": results,
        "summary": {"total": total, "passed": passed, "failed": total - passed},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scheduled_run():
    global _last_run
    validations = run_all_validations()
    with _last_run_lock:
        _last_run = validations


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def api_health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/features")
def list_features_route():
    """List features with latest benchmark summary including per-case breakdown."""
    features = discover_features()
    for feat in features:
        latest = get_latest_benchmark(feat["name"])
        if latest:
            feat["latest_benchmark"] = summarize_benchmark(latest)
        else:
            feat["latest_benchmark"] = None
    return {"features": features}


@app.get("/api/features/{name}")
def get_feature(name: str):
    scenario_path = FEATURES_ROOT / name / "scenario.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Feature '{name}' not found")
    with scenario_path.open() as f:
        scenario = json.load(f)
    latest = get_latest_benchmark(name)
    benchmarks = list_benchmarks(name)
    return {
        "name": name,
        "scenario": scenario,
        "latest_benchmark": summarize_benchmark(latest) if latest else None,
        "benchmark_count": len(benchmarks),
        "benchmark_files": benchmarks[:20],
    }


@app.get("/api/features/{name}/benchmarks")
def get_benchmarks(name: str, limit: int = Query(default=10, ge=1, le=100)):
    scenario_path = FEATURES_ROOT / name / "scenario.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Feature '{name}' not found")
    benchmarks = list_benchmarks(name)
    return {"feature": name, "benchmarks": benchmarks[:limit]}


@app.get("/api/features/{name}/benchmarks/latest")
def get_latest(name: str):
    latest = get_latest_benchmark(name)
    if not latest:
        raise HTTPException(status_code=404, detail=f"No benchmarks for '{name}'")
    return latest


@app.get("/api/features/{name}/benchmarks/{filename}")
def get_benchmark_file(name: str, filename: str):
    if not filename.startswith("benchmark-") or not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid benchmark filename")
    data = read_benchmark(name, filename)
    if not data:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return data


@app.get("/api/features/{name}/history")
def get_feature_history(
    name: str, limit: int = Query(default=20, ge=1, le=100)
):
    """Return pass/fail trend over recent benchmarks."""
    scenario_path = FEATURES_ROOT / name / "scenario.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Feature '{name}' not found")
    filenames = list_benchmarks(name)[:limit]
    history = []
    for fn in filenames:
        b = read_benchmark(name, fn)
        if b:
            history.append({
                "timestamp": b.get("timestamp"),
                "all_passed": b.get("all_passed"),
                "cases_passed": b.get("cases_passed"),
                "case_count": b.get("case_count"),
            })
    return {"feature": name, "history": history}


@app.post("/api/run")
def run_all(tag: Optional[str] = Query(default=None)):
    features = discover_features()
    if tag:
        features = [f for f in features if tag in f.get("name", "")]
    if not features:
        raise HTTPException(status_code=404, detail="No matching features")
    results = {}
    for feat in features:
        results[feat["name"]] = run_feature_validation(feat["name"])
    passed = sum(
        1 for r in results.values() if r.get("benchmark", {}).get("all_passed")
    )
    total = len(results)
    with _last_run_lock:
        _last_run.update({
            "results": results,
            "summary": {"total": total, "passed": passed, "failed": total - passed},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return _last_run


@app.post("/api/run/{name}")
def run_single(name: str, cases: Optional[str] = Query(default=None)):
    scenario_path = FEATURES_ROOT / name / "scenario.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Feature '{name}' not found")
    case_filters = (
        [c.strip() for c in cases.split(",") if c.strip()] if cases else None
    )
    return run_feature_validation(name, case_filters)


@app.get("/api/status")
def deployment_status():
    """Feature validation status for homepage widget and dashboard."""
    features = discover_features()
    feature_status = []
    for feat in features:
        latest = get_latest_benchmark(feat["name"])
        entry = {
            "name": feat["name"],
            "description": feat["description"],
        }
        if latest:
            entry["all_passed"] = latest.get("all_passed")
            entry["cases_passed"] = latest.get("cases_passed")
            entry["case_count"] = latest.get("case_count")
            entry["last_run"] = latest.get("timestamp")
            entry["failures"] = latest.get("failures", [])
        else:
            entry["all_passed"] = None
            entry["last_run"] = None
            entry["failures"] = []
        feature_status.append(entry)

    features_passed = sum(
        1 for f in feature_status if f.get("all_passed") is True
    )
    features_total = len(feature_status)
    total_cases = sum(f.get("case_count", 0) or 0 for f in feature_status)
    passed_cases = sum(f.get("cases_passed", 0) or 0 for f in feature_status)

    if features_passed == features_total and features_total > 0:
        overall = "all_passed"
    elif features_passed > 0:
        overall = "partial"
    else:
        overall = "failing"

    return {
        "overall_status": overall,
        "features": feature_status,
        "summary": {
            "features_passed": features_passed,
            "features_total": features_total,
            "cases_passed": passed_cases,
            "cases_total": total_cases,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# File Serving & Drawing Proxy
# ---------------------------------------------------------------------------

ALLOWED_PREVIEW_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".bmp", ".tiff", ".webp",
    ".xlsx", ".xls", ".csv",
}


@app.get("/api/features/{name}/files/{filepath:path}")
def serve_feature_file(name: str, filepath: str):
    """Serve fixture files (images, PDFs) for document preview."""
    feature_dir = (FEATURES_ROOT / name).resolve()
    file_path = (FEATURES_ROOT / name / filepath).resolve()
    if not str(file_path).startswith(str(feature_dir) + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")
    if file_path.suffix.lower() not in ALLOWED_PREVIEW_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@app.get("/api/features/{name}/cases/{case_name}/drawing")
def serve_case_drawing(name: str, case_name: str):
    """Proxy the annotated drawing image from apitools for a benchmark case."""
    benchmark = get_latest_benchmark(name)
    if not benchmark:
        raise HTTPException(status_code=404, detail="No benchmark data")
    for r in benchmark.get("results", []):
        if r.get("name") == case_name:
            file_id = r.get("file_id")
            query_body = r.get("query_response", {}).get("ocr_json_query")
            if not file_id or not query_body:
                raise HTTPException(status_code=404, detail="No file_id/query for case")
            try:
                resp = http_requests.post(
                    f"{APITOOLS_BASE_URL}/documentJsonQuery",
                    params={"draw": "1", "format": "image"},
                    json={"file_id": file_id, "ocr_json_query": query_body},
                    timeout=30,
                )
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"apitools returned {resp.status_code}",
                    )
                ct = resp.headers.get("content-type", "image/png")
                return Response(content=resp.content, media_type=ct)
            except http_requests.RequestException as exc:
                raise HTTPException(status_code=502, detail=str(exc))
    raise HTTPException(status_code=404, detail="Case not found")


# ---------------------------------------------------------------------------
# Playground
# ---------------------------------------------------------------------------


@app.post("/api/playground/upload")
async def playground_upload(file: UploadFile = File(...)):
    """Upload a document to apitools for OCR processing."""
    content = await file.read()
    if len(content) > APITOOLS_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {APITOOLS_MAX_UPLOAD_BYTES // (1024 * 1024)}MB)",
        )
    try:
        resp = http_requests.post(
            f"{APITOOLS_BASE_URL}/documentOcr",
            files={
                "file": (
                    file.filename,
                    content,
                    file.content_type or "application/octet-stream",
                )
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except http_requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/playground/query")
async def playground_query(payload: dict = Body(...)):
    """Run a JSON query against apitools."""
    file_id = payload.get("file_id")
    ocr_json_query = payload.get("ocr_json_query")
    if not file_id or not ocr_json_query:
        raise HTTPException(
            status_code=400, detail="file_id and ocr_json_query required"
        )
    draw = str(payload.get("draw", "0"))
    try:
        resp = http_requests.post(
            f"{APITOOLS_BASE_URL}/documentJsonQuery",
            json={"file_id": file_id, "ocr_json_query": ocr_json_query},
            params={"draw": draw},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except http_requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/playground/drawing")
async def playground_drawing(payload: dict = Body(...)):
    """Fetch annotated drawing by re-running the query with format=image."""
    file_id = payload.get("file_id")
    ocr_json_query = payload.get("ocr_json_query")
    if not file_id or not ocr_json_query:
        raise HTTPException(status_code=400, detail="file_id and ocr_json_query required")
    try:
        resp = http_requests.post(
            f"{APITOOLS_BASE_URL}/documentJsonQuery",
            params={"draw": "1", "format": "image"},
            json={"file_id": file_id, "ocr_json_query": ocr_json_query},
            timeout=30,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"apitools returned {resp.status_code}",
            )
        ct = resp.headers.get("content-type", "image/png")
        return Response(content=resp.content, media_type=ct)
    except http_requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_PATH.read_text()


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


@app.on_event("startup")
def on_startup():
    if SCHEDULE_INTERVAL_MINUTES > 0:
        scheduler.add_job(
            scheduled_run,
            "interval",
            minutes=SCHEDULE_INTERVAL_MINUTES,
            id="scheduled_run",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),
        )
        scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
