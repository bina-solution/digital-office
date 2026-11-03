#!/usr/bin/env python3
"""Balance-sheet extraction validation.

Sends Google Drive document links to the N8N balance-sheet extraction webhook
and validates the structured response against expected values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
N8N_WEBHOOK_BASE = os.getenv("N8N_WEBHOOK_BASE", "http://n8n:5678/webhook")
N8N_URL = os.getenv("N8N_URL", "http://n8n:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")
N8N_EXTERNAL_URL = os.getenv(
    "N8N_EXTERNAL_URL", "https://n8n.hacohen.bina-solutions.co.il"
)
BS_WEBHOOK_USER = os.getenv("BS_WEBHOOK_USER", "")
BS_WEBHOOK_PASS = os.getenv("BS_WEBHOOK_PASS", "")
REQUEST_TIMEOUT = int(os.getenv("BS_REQUEST_TIMEOUT", "300"))
BALANCE_TOLERANCE = float(os.getenv("BS_BALANCE_TOLERANCE", "0.01"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_latest_execution(workflow_id: str) -> Optional[Dict]:
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
            return data[0] if data else None
    except Exception:
        pass
    return None


def _compare_numeric(actual: Any, expected: Any, tolerance: float = BALANCE_TOLERANCE) -> bool:
    """Compare two numeric values with tolerance."""
    try:
        a = float(actual)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    return abs(a - e) <= max(tolerance, abs(e) * 0.001)


def _compare_string(actual: Any, expected: Any) -> bool:
    """Compare string values, stripping and normalising."""
    if actual is None and expected == "":
        return True
    a = str(actual).strip() if actual is not None else ""
    e = str(expected).strip()
    if a == e:
        return True
    # Try stripping common prefixes (S vs SI, leading zeros, etc.)
    a_clean = a.lstrip("0").lstrip("S").lstrip("I").lstrip("N")
    e_clean = e.lstrip("0").lstrip("S").lstrip("I").lstrip("N")
    return a_clean == e_clean


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------

ASSERTIONS = [
    {"name": "webhook_ok", "description": "Webhook returned successful HTTP status"},
    {"name": "response_success", "description": "Response success field is true"},
    {"name": "has_lines", "description": "Response contains transaction lines"},
    {"name": "document_balance", "description": "Document balance matches expected"},
    {"name": "document_date", "description": "Document date matches expected"},
    {"name": "first_line_id", "description": "First line ID matches expected"},
    {"name": "first_line_amount", "description": "First line amount matches expected"},
    {"name": "first_line_date", "description": "First line date matches expected"},
]


def evaluate_case(case: Dict, http_status: int, response: Dict) -> Dict:
    """Evaluate all assertions for a case and return evaluation results."""
    expected = case.get("expected", {})
    line_idx = case.get("first_line_index", 0)
    data = response.get("data", {})
    lines = data.get("lines", []) if isinstance(data, dict) else []
    summary_data = data.get("summary", {}) if isinstance(data, dict) else {}

    # Pick the correct line
    line = {}
    if lines:
        idx = line_idx if line_idx >= 0 else len(lines) + line_idx
        if 0 <= idx < len(lines):
            line = lines[idx]

    evals = {}
    details = []

    def _check(name: str, passed: bool, actual: Any, exp: Any, operator: str = "equals"):
        evals[name] = passed
        details.append({
            "name": name, "passed": passed,
            "actual": actual, "expected": exp,
            "operator": operator,
        })

    _check("webhook_ok", http_status == 200, http_status, 200)
    _check("response_success", response.get("success") is True,
           response.get("success"), True)
    _check("has_lines", len(lines) > 0, len(lines), ">0", "gt")

    # Balance
    doc_total = summary_data.get("documentTotal")
    exp_balance = expected.get("balance")
    if exp_balance is not None:
        _check("document_balance",
               _compare_numeric(doc_total, exp_balance),
               doc_total, exp_balance)
    else:
        _check("document_balance", True, doc_total, "(not checked)", "skip")

    # Date
    doc_date = data.get("documentDate", "") if isinstance(data, dict) else ""
    exp_date = expected.get("document_date", "")
    if exp_date:
        _check("document_date", str(doc_date).strip() == str(exp_date).strip(),
               doc_date, exp_date)
    else:
        _check("document_date", True, doc_date, "(not checked)", "skip")

    # First line fields
    exp_id = expected.get("first_line_id", "")
    if exp_id:
        actual_id = line.get("id", "")
        _check("first_line_id", _compare_string(actual_id, exp_id),
               actual_id, exp_id)
    else:
        _check("first_line_id", True, line.get("id", ""), "(not checked)", "skip")

    exp_amount = expected.get("first_line_amount")
    if exp_amount is not None:
        actual_amount = line.get("amount")
        _check("first_line_amount",
               _compare_numeric(actual_amount, exp_amount),
               actual_amount, exp_amount)
    else:
        _check("first_line_amount", True, line.get("amount"), "(not checked)", "skip")

    exp_fdate = expected.get("first_line_date", "")
    if exp_fdate:
        actual_fdate = line.get("date", "")
        _check("first_line_date",
               str(actual_fdate).strip() == str(exp_fdate).strip(),
               actual_fdate, exp_fdate)
    else:
        _check("first_line_date", True, line.get("date", ""), "(not checked)", "skip")

    return {"summary": evals, "details": details}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_feature(feature_root: Path, argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run balance-sheet extraction validation")
    parser.add_argument("--case", action="append", dest="case_filters")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)

    scenario = json.loads((feature_root / "scenario.json").read_text())
    cases_path = feature_root / scenario.get("cases_source", "fixtures/fixtures.json")
    cases: List[Dict] = json.loads(cases_path.read_text())

    webhook_path = scenario.get("webhook_path", "bs_ex_2")
    workflow_id = scenario.get("workflow_id", "")
    webhook_url = f"{N8N_WEBHOOK_BASE}/{webhook_path}"

    if args.list_cases:
        for c in cases:
            print(c["name"])
        return 0

    case_filters = set(args.case_filters or [])
    results: List[Dict] = []
    failures: List[str] = []

    # Scenario-level capability gate: this is an END-TO-END BS extraction test via the
    # n8n webhook (not a pure apitools call), so it needs 'orchestration' (live n8n
    # workflow). Default local/CI lacks it -> whole feature SKIPPED (green); the indox-e2e
    # lane covers it. Grant with FV_CAPABILITIES=local,orchestration.
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
        print(f"Skipping feature 'balance-sheet-extraction' (requires {_missing}; caps={sorted(_caps())})")
        ts = datetime.now(timezone.utc).isoformat()
        bench = {"feature": scenario.get("feature", "balance-sheet-extraction"), "timestamp": ts,
                 "results": [], "failures": [], "all_passed": True, "case_count": 0,
                 "cases_passed": 0, "skipped_count": len(cases),
                 "capabilities": sorted(_caps()), "feature_skipped": True}
        bdir = feature_root / "benchmarks"; bdir.mkdir(exist_ok=True)
        (bdir / f"benchmark-{ts}.json").write_text(json.dumps(bench, ensure_ascii=False, indent=2))
        (bdir / "latest.json").write_text(json.dumps(bench, ensure_ascii=False, indent=2))
        print(f"Feature skipped: {len(cases)} case(s) require {_missing}")
        return 0

    session = requests.Session()
    session.headers["User-Agent"] = "feature-validation-balance-sheet/1.0"
    session.headers["Content-Type"] = "application/json"
    if BS_WEBHOOK_USER and BS_WEBHOOK_PASS:
        session.auth = (BS_WEBHOOK_USER, BS_WEBHOOK_PASS)

    for case in cases:
        name = case["name"]
        if case_filters and name not in case_filters:
            continue

        print(f"Running {name} ({case.get('display_name', '')})…", end=" ", flush=True)

        gdrive_link = case["gdrive_link"]
        body = {"LINK": gdrive_link, "use_cache": False}

        t0 = time.time()
        http_status = 0
        response: Dict[str, Any] = {}
        error_msg = None

        try:
            resp = session.post(webhook_url, json=body, timeout=REQUEST_TIMEOUT)
            http_status = resp.status_code
            try:
                response = resp.json()
            except Exception:
                response = {"raw": resp.text[:2000]}
        except Exception as exc:
            error_msg = str(exc)

        elapsed = round(time.time() - t0, 3)

        if error_msg:
            failures.append(f"'{name}' error: {error_msg}")
            error_entry: Dict[str, Any] = {
                "name": name, "status": "error", "error": error_msg,
                "type": "balance_sheet", "description": case.get("display_name", ""),
                "duration_s": elapsed,
                "integration": "balance-sheet",
            }
            if case.get("source_file"):
                error_entry["source_file"] = case["source_file"]
            results.append(error_entry)
            print("ERROR")
            if args.fail_fast:
                break
            continue

        evaluation = evaluate_case(case, http_status, response)
        all_passed = all(evaluation["summary"].values())
        status = "passed" if all_passed else "failed"

        if not all_passed:
            failing = [
                f"{d['name']} (expected {d['expected']} got {d['actual']})"
                for d in evaluation["details"] if not d["passed"]
            ]
            failures.append(f"'{name}' failed: " + "; ".join(failing))

        # Build query_response for dashboard compatibility
        query_response: Dict[str, Any] = {
            "status_code": http_status,
            "ok": 200 <= http_status < 300,
            "body": response,
            "request_url": webhook_url,
            "request_method": "POST",
            "request_body": body,
        }

        # N8N execution link
        if workflow_id:
            query_response["workflow_id"] = workflow_id
            query_response["workflow_url"] = f"{N8N_EXTERNAL_URL}/workflow/{workflow_id}"
            ex = _fetch_latest_execution(workflow_id)
            if ex:
                query_response["execution_id"] = ex.get("id")
                query_response["execution_status"] = ex.get("status")
                query_response["execution_url"] = (
                    f"{N8N_EXTERNAL_URL}/workflow/{workflow_id}"
                    f"/executions/{ex['id']}"
                )

        result_entry: Dict[str, Any] = {
            "name": name, "status": status,
            "evaluations": evaluation["summary"],
            "evaluation_details": evaluation["details"],
            "query_response": query_response,
            "type": "balance_sheet",
            "integration": "balance-sheet",
            "description": case.get("display_name", ""),
            "duration_s": elapsed,
        }
        if case.get("source_file"):
            result_entry["source_file"] = case["source_file"]
        results.append(result_entry)
        print("PASSED" if all_passed else "FAILED")
        if not all_passed and args.fail_fast:
            break

    # ---- Write benchmark ----
    timestamp = datetime.now(timezone.utc).isoformat()
    passed_count = sum(1 for r in results if r["status"] == "passed")
    benchmark = {
        "feature": scenario.get("feature", "balance-sheet"),
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
