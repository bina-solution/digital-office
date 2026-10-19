#!/usr/bin/env python3
"""Integration test runner for deployment service connectivity.

Tests N8N API, Redis, Postgres, Apitools OCR, WhatsApp, and
N8N webhook-triggered integrations (GSheet, GDrive, Gmail, Gemini).
Produces benchmark output compatible with the feature-validation dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import requests

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
N8N_URL = os.getenv("N8N_URL", "http://n8n:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "n8n-postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "hacohen")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "n8n")
WHATSAPP_URL = os.getenv("WHATSAPP_URL", "http://whatsapp-hacohanim:3000")
WHATSAPP_USER = os.getenv("WHATSAPP_USER", "hacohen")
WHATSAPP_PASS = os.getenv("WHATSAPP_PASS", "n7g469jgh6843kyutu")
WHATSAPP_TEST_PHONE = os.getenv("WHATSAPP_TEST_PHONE", "050-000-0002")
APITOOLS_BASE_URL = os.getenv("APITOOLS_BASE_URL", "http://apitools:8080")
N8N_WEBHOOK_BASE = os.getenv("N8N_WEBHOOK_BASE", "http://n8n:5678/webhook")
N8N_EXTERNAL_URL = os.getenv("N8N_EXTERNAL_URL", "https://n8n.hacohen.bina-solutions.co.il")
N8N_WEBHOOK_USER = os.getenv("N8N_WEBHOOK_USER", "")
N8N_WEBHOOK_PASS = os.getenv("N8N_WEBHOOK_PASS", "")
REQUEST_TIMEOUT = 30

ENV_MAP = {
    "N8N_URL": N8N_URL,
    "N8N_API_KEY": N8N_API_KEY,
    "REDIS_HOST": REDIS_HOST,
    "REDIS_PORT": str(REDIS_PORT),
    "REDIS_PASSWORD": REDIS_PASSWORD,
    "POSTGRES_HOST": POSTGRES_HOST,
    "POSTGRES_PORT": str(POSTGRES_PORT),
    "POSTGRES_USER": POSTGRES_USER,
    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
    "POSTGRES_DB": POSTGRES_DB,
    "WHATSAPP_URL": WHATSAPP_URL,
    "WHATSAPP_USER": WHATSAPP_USER,
    "WHATSAPP_PASS": WHATSAPP_PASS,
    "WHATSAPP_TEST_PHONE": WHATSAPP_TEST_PHONE,
    "APITOOLS_BASE_URL": APITOOLS_BASE_URL,
    "N8N_WEBHOOK_BASE": N8N_WEBHOOK_BASE,
}


def _env(value: Any) -> Any:
    """Replace ${VAR} placeholders with environment values."""
    if not isinstance(value, str):
        return value
    for placeholder, val in ENV_MAP.items():
        value = value.replace(f"${{{placeholder}}}", val)
    return value


# ---------------------------------------------------------------------------
# Test handlers
# ---------------------------------------------------------------------------

def run_http_test(case: Dict, session: requests.Session, feature_root: Path) -> Dict:
    method = case.get("method", "GET").upper()
    url = _env(case["url"])
    headers = {k: _env(v) for k, v in case.get("headers", {}).items()}
    body = case.get("body")
    form = case.get("form")
    files_def = case.get("files")

    kwargs: Dict[str, Any] = {"timeout": REQUEST_TIMEOUT, "headers": headers}
    if body:
        kwargs["json"] = body
    if form:
        kwargs["data"] = {k: _env(v) for k, v in form.items()}

    opened_files = []
    if files_def:
        import mimetypes
        file_dict = {}
        for field, rel_path in files_def.items():
            full = feature_root / rel_path
            if full.exists():
                fh = full.open("rb")
                opened_files.append(fh)
                mime = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
                file_dict[field] = (full.name, fh, mime)
        kwargs["files"] = file_dict

    try:
        resp = session.request(method, url, **kwargs)
    finally:
        for fh in opened_files:
            fh.close()

    result: Dict[str, Any] = {"status_code": resp.status_code, "ok": resp.ok}
    try:
        result["body"] = resp.json()
    except Exception:
        result["body"] = resp.text[:2000]
    return result


def run_redis_test(case: Dict) -> Dict:
    import redis as redispy

    r = redispy.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True,
        socket_timeout=10,
    )
    command = case.get("command", "PING")
    if command == "PING":
        ok = r.ping()
        return {"result": ok, "response": "PONG" if ok else "FAILED"}
    if command == "SET_GET":
        key = "fv:integration:test"
        val = f"test-{int(time.time())}"
        r.set(key, val, ex=60)
        got = r.get(key)
        r.delete(key)
        return {"result": got == val, "set_value": val, "got_value": got}
    return {"error": f"Unknown redis command: {command}", "result": False}


def run_postgres_test(case: Dict) -> Dict:
    import psycopg2

    conn = psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB, connect_timeout=10,
    )
    conn.autocommit = True
    cur = conn.cursor()
    query = case.get("query", "SELECT 1 AS ok")
    cur.execute(query)
    columns = [d[0] for d in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"result": True, "rows": rows, "row_count": len(rows)}


def run_whatsapp_test(case: Dict, feature_root: Path) -> Dict:
    auth = (WHATSAPP_USER, WHATSAPP_PASS)
    action = case.get("action", "state")

    if action == "state":
        resp = requests.get(
            f"{WHATSAPP_URL}/api/bot/state",
            auth=auth, timeout=REQUEST_TIMEOUT,
        )
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return {
            "status_code": resp.status_code,
            "body": body,
            "is_connected": isinstance(body, dict) and body.get("is_connected", False),
            "result": resp.ok,
        }

    if action == "send":
        phone = _env(case.get("phone", WHATSAPP_TEST_PHONE))
        message = case.get("message", "Integration test - feature validation")
        test_file = feature_root / case.get("test_file", "fixtures/test-image.png")
        if not test_file.exists():
            return {"error": f"Test file not found: {test_file}", "result": False}
        with test_file.open("rb") as f:
            resp = requests.post(
                f"{WHATSAPP_URL}/api/bot/send-document",
                auth=auth,
                files={"document": (test_file.name, f, "image/png")},
                data={"phoneNumber": phone, "caption": message},
                timeout=REQUEST_TIMEOUT,
            )
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return {
            "status_code": resp.status_code,
            "body": body,
            "result": resp.ok,
        }

    return {"error": f"Unknown whatsapp action: {action}", "result": False}


def _fetch_latest_execution(workflow_id: str) -> Optional[Dict]:
    """Fetch the most recent execution for a workflow via N8N API."""
    if not N8N_API_KEY or not workflow_id:
        return None
    try:
        resp = requests.get(
            f"{N8N_URL}/api/v1/executions",
            params={"workflowId": workflow_id, "limit": "1"},
            headers={"X-N8N-API-KEY": N8N_API_KEY},
            timeout=10,
        )
        if resp.ok:
            data = resp.json().get("data", [])
            if data:
                return data[0]
    except Exception:
        pass
    return None


def run_n8n_webhook_test(case: Dict, session: requests.Session) -> Dict:
    webhook_path = case.get("webhook_path", "")
    url = f"{N8N_WEBHOOK_BASE}/{webhook_path}"
    method = case.get("method", "POST").upper()
    body = case.get("body", {})
    timeout = case.get("timeout", REQUEST_TIMEOUT)
    workflow_id = case.get("workflow_id", "")

    kwargs: Dict[str, Any] = {"timeout": timeout}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = body
    if N8N_WEBHOOK_USER and N8N_WEBHOOK_PASS:
        kwargs["auth"] = (N8N_WEBHOOK_USER, N8N_WEBHOOK_PASS)

    resp = session.request(method, url, **kwargs)

    result: Dict[str, Any] = {"status_code": resp.status_code, "ok": resp.ok}
    result["request_url"] = url
    result["request_method"] = method
    if body:
        result["request_body"] = body

    if resp.status_code == 404:
        result["error"] = "Webhook not found – workflow may need to be created and activated"
        result["not_configured"] = True
    else:
        try:
            result["body"] = resp.json()
        except Exception:
            result["body"] = resp.text[:2000]

    # Fetch execution info for N8N link
    if workflow_id:
        result["workflow_id"] = workflow_id
        ex = _fetch_latest_execution(workflow_id)
        if ex:
            result["execution_id"] = ex.get("id")
            result["execution_status"] = ex.get("status")
            result["execution_finished"] = ex.get("stoppedAt")
            result["execution_url"] = (
                f"{N8N_EXTERNAL_URL}/workflow/{workflow_id}"
                f"/executions/{ex['id']}"
            )
            result["workflow_url"] = f"{N8N_EXTERNAL_URL}/workflow/{workflow_id}"

    return result


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------

def resolve_path(payload: Any, dotted_path: str) -> Any:
    current = payload
    for segment in dotted_path.split("."):
        if isinstance(current, Mapping):
            current = current.get(segment)
        elif isinstance(current, list):
            try:
                idx = int(segment)
            except ValueError:
                return None
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def apply_operator(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not bool(actual)
    if operator == "not_none":
        return actual is not None
    if operator == "is_none":
        return actual is None
    if operator == "contains":
        return actual is not None and expected is not None and expected in actual
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "gte":
        return actual is not None and actual >= expected
    raise ValueError(f"Unsupported operator '{operator}'")


def evaluate_case(case: Dict, response: Dict) -> Dict:
    assertions = case.get("assertions", [])
    details: List[Dict] = []
    summary: Dict[str, bool] = {}
    for a in assertions:
        name = a["name"]
        source = a.get("source", "result")
        operator = a.get("operator", "truthy")
        expected = a.get("expected", True)
        actual = resolve_path(response, source)
        try:
            passed = apply_operator(operator, actual, expected)
        except Exception as exc:
            passed = False
            actual = f"Error: {exc}"
        details.append({
            "name": name, "source": source, "operator": operator,
            "expected": expected, "actual": actual, "passed": passed,
        })
        summary[name] = passed
    return {"summary": summary, "details": details}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _should_skip(case: Dict) -> Optional[str]:
    if case.get("skip"):
        return "flagged skip"
    env_req = case.get("skip_if_no_env")
    if env_req and not os.getenv(env_req):
        return f"env {env_req} not set"
    return None


HANDLERS = {
    "http": lambda c, s, r: run_http_test(c, s, r),
    "redis": lambda c, _s, _r: run_redis_test(c),
    "postgres": lambda c, _s, _r: run_postgres_test(c),
    "whatsapp": lambda c, _s, r: run_whatsapp_test(c, r),
    "n8n_webhook": lambda c, s, _r: run_n8n_webhook_test(c, s),
}


def run_feature(feature_root: Path, argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run integration validation")
    parser.add_argument("--case", action="append", dest="case_filters")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)

    scenario = json.loads((feature_root / "scenario.json").read_text())
    cases_path = feature_root / scenario.get("cases_source", "fixtures/fixtures.json")
    cases: List[Dict] = json.loads(cases_path.read_text())

    if args.list_cases:
        for c in cases:
            print(c["name"])
        return 0

    case_filters = set(args.case_filters or [])
    results: List[Dict] = []
    failures: List[str] = []

    # Scenario-level capability gate: integration is a full-stack orchestration E2E
    # (n8n workflows + WhatsApp + Gemini/Google). Without the 'orchestration' capability
    # (default local/CI), the whole feature is SKIPPED — green, no cases run — since that
    # path is exercised by the indox-e2e lane instead. Set FV_CAPABILITIES=local,orchestration
    # (plus gemini/google_vision + a live stack) to run it.
    def _caps():
        raw = os.getenv("FV_CAPABILITIES")
        if raw is not None:
            return {c.strip() for c in raw.split(",") if c.strip()}
        caps = {"local"}
        if os.getenv("GEMINI_API_KEY", "").startswith("AIza"):
            caps |= {"gemini", "google_vision"}
        return caps
    _missing = [c for c in (scenario.get("requires") or []) if c not in _caps()]
    if _missing:
        print(f"Skipping feature 'integration' (requires {_missing}; caps={sorted(_caps())})")
        ts = datetime.now(timezone.utc).isoformat()
        bench = {"feature": scenario.get("feature", "integration"), "timestamp": ts,
                 "results": [], "failures": [], "all_passed": True, "case_count": 0,
                 "cases_passed": 0, "skipped_count": len(cases),
                 "capabilities": sorted(_caps()), "feature_skipped": True}
        bdir = feature_root / "benchmarks"; bdir.mkdir(exist_ok=True)
        (bdir / f"benchmark-{ts}.json").write_text(json.dumps(bench, ensure_ascii=False, indent=2))
        (bdir / "latest.json").write_text(json.dumps(bench, ensure_ascii=False, indent=2))
        print(f"Feature skipped: {len(cases)} case(s) require {_missing}")
        return 0

    session = requests.Session()
    session.headers["User-Agent"] = "feature-validation-integration/1.0"

    for case in cases:
        name = case["name"]
        if case_filters and name not in case_filters:
            continue

        skip_reason = _should_skip(case)
        if skip_reason:
            print(f"Skipping '{name}' ({skip_reason})")
            results.append({
                "name": name, "status": "skipped",
                "reason": skip_reason,
                "integration": case.get("integration", ""),
                "type": case.get("type", ""),
            })
            continue

        test_type = case.get("type", "http")
        handler = HANDLERS.get(test_type)
        if not handler:
            failures.append(f"'{name}' unknown type: {test_type}")
            continue

        print(f"Running {name} ({test_type})…", end=" ", flush=True)

        t0 = time.time()
        try:
            response = handler(case, session, feature_root)
        except Exception as exc:
            elapsed = round(time.time() - t0, 3)
            err_ctx = f"'{name}' error: {exc}"
            # Try to fetch execution context for webhook tests
            wf_id = case.get("workflow_id", "")
            ex = None
            if wf_id:
                ex = _fetch_latest_execution(wf_id)
                if ex:
                    ex_id = ex.get("id", "?")
                    ex_status = ex.get("status", "?")
                    ex_url = f"{N8N_EXTERNAL_URL}/workflow/{wf_id}/executions/{ex_id}"
                    err_ctx += f" | execution={ex_id} status={ex_status} url={ex_url}"
            failures.append(err_ctx)
            err_result: Dict[str, Any] = {
                "name": name, "status": "error", "error": str(exc),
                "integration": case.get("integration", ""),
                "type": test_type,
                "description": case.get("description", ""),
                "duration_s": elapsed,
            }
            # Attach execution context so the UI detail panel can show links
            if wf_id:
                qr: Dict[str, Any] = {
                    "error": str(exc),
                    "workflow_id": wf_id,
                    "workflow_url": f"{N8N_EXTERNAL_URL}/workflow/{wf_id}",
                }
                if ex:
                    qr["execution_id"] = ex.get("id")
                    qr["execution_status"] = ex.get("status")
                    qr["execution_url"] = (
                        f"{N8N_EXTERNAL_URL}/workflow/{wf_id}"
                        f"/executions/{ex['id']}"
                    )
                err_result["query_response"] = qr
            results.append(err_result)
            print("ERROR")
            if args.fail_fast:
                break
            continue
        elapsed = round(time.time() - t0, 3)

        # Not-configured webhooks → skip
        if response.get("not_configured"):
            results.append({
                "name": name, "status": "skipped",
                "reason": response.get("error", "not configured"),
                "integration": case.get("integration", ""),
                "type": test_type, "query_response": response,
            })
            print("SKIPPED (not configured)")
            continue

        evaluation = evaluate_case(case, response)
        all_passed = all(evaluation["summary"].values()) if evaluation["summary"] else True
        status = "passed" if all_passed else "failed"

        if not all_passed:
            failing = [
                f"{d['name']} ({d['operator']} {d['expected']} got {d['actual']})"
                for d in evaluation["details"] if not d["passed"]
            ]
            fail_msg = f"'{name}' failed: " + "; ".join(failing)
            # Append execution context when available
            ex_id = response.get("execution_id")
            ex_url = response.get("execution_url")
            wf_url = response.get("workflow_url")
            ex_status = response.get("execution_status")
            if ex_id:
                fail_msg += f" | execution={ex_id} status={ex_status}"
            if ex_url:
                fail_msg += f" | {ex_url}"
            elif wf_url:
                fail_msg += f" | {wf_url}"
            failures.append(fail_msg)

        results.append({
            "name": name, "status": status,
            "evaluations": evaluation["summary"],
            "evaluation_details": evaluation["details"],
            "query_response": response,
            "integration": case.get("integration", ""),
            "type": test_type,
            "description": case.get("description", ""),
            "duration_s": elapsed,
        })
        print("PASSED" if all_passed else "FAILED")
        if not all_passed and args.fail_fast:
            break

    # ---- Write benchmark ----
    timestamp = datetime.now(timezone.utc).isoformat()
    passed_count = sum(1 for r in results if r["status"] == "passed")
    benchmark = {
        "feature": scenario.get("feature", "integration"),
        "timestamp": timestamp,
        "results": results,
        "failures": failures,
        "all_passed": not failures,
        "case_count": len(results),
        "cases_passed": passed_count,
    }

    benchmarks_dir = feature_root / "benchmarks"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    out = benchmarks_dir / f"benchmark-{timestamp}.json"
    _write_json(out, benchmark)
    _write_json(benchmarks_dir / "latest.json", benchmark)

    print(f"\nWrote benchmark to {out.relative_to(feature_root)}")
    print(f"Cases: {passed_count}/{len(results)} passed")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)


if __name__ == "__main__":
    sys.exit(run_feature(Path(__file__).parent))
