#!/usr/bin/env python3
"""Document OCR upload validation — tests the /documentOcr pipeline directly."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import requests

DEFAULT_BASE_URL = "http://apitools:8080"
REQUEST_TIMEOUT = 120
USER_AGENT = "feature-validation/1.0"


def _capabilities() -> set:
    """Env capabilities for gating external-service cases (see lib/validate_feature_base).
    Default local-only; override with FV_CAPABILITIES=local,google_vision,gemini."""
    raw = os.getenv("FV_CAPABILITIES")
    if raw is not None:
        return {c.strip() for c in raw.split(",") if c.strip()}
    caps = {"local"}
    if os.getenv("GEMINI_API_KEY", "").startswith("AIza"):
        caps |= {"gemini", "google_vision"}
    return caps


def _requirements(case: Dict[str, Any]) -> List[str]:
    req = case.get("requires") or []
    return [req] if isinstance(req, str) else list(req)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run document-ocr validation cases")
    parser.add_argument("--base-url", help="Override the base API host")
    parser.add_argument(
        "--case", action="append", dest="case_filters", metavar="NAME",
        help="Only run specific case names",
    )
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def upload_document(
    session: requests.Session,
    base_url: str,
    endpoint: str,
    file_path: Path,
    params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(file_path.name)
    with file_path.open("rb") as fh:
        resp = session.post(
            f"{base_url}{endpoint}",
            files={"file": (file_path.name, fh, mime_type or "application/octet-stream")},
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )
    return {"status_code": resp.status_code, "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text}


def evaluate_upload(case: Dict[str, Any], resp: Dict[str, Any]) -> Dict[str, Any]:
    """Check assertions about the upload response."""
    assertions = case.get("assertions", {})
    body = resp.get("body", {})
    status_code = resp.get("status_code", 0)
    if not isinstance(body, dict):
        body = {}

    evals: Dict[str, bool] = {}
    details: List[Dict[str, Any]] = []

    def add(name: str, passed: bool, expected: Any, actual: Any):
        evals[name] = passed
        details.append({"name": name, "passed": passed, "expected": expected, "actual": actual, "operator": "custom"})

    expect_error = assertions.get("expect_error", False)

    if expect_error:
        has_err = bool(body.get("error")) or status_code >= 400
        add("expect_error", has_err, True, {"error": body.get("error"), "status_code": status_code})
        return {"summary": evals, "details": details}

    if assertions.get("has_file_hash"):
        val = body.get("file_hash")
        add("has_file_hash", bool(val), True, val)

    if assertions.get("no_error"):
        err = body.get("error")
        add("no_error", err is None, True, err)

    if assertions.get("has_annotations"):
        ocr_json = body.get("ocr_json") or {}
        annotations = ocr_json.get("textAnnotations") or ocr_json.get("text_annotations") or []
        add("has_annotations", len(annotations) > 0, True, len(annotations))

    if assertions.get("no_annotations"):
        ocr_json = body.get("ocr_json") or {}
        annotations = ocr_json.get("textAnnotations") or ocr_json.get("text_annotations") or []
        add("no_annotations", len(annotations) == 0, True, len(annotations))

    engine_expected = assertions.get("engine_is")
    if engine_expected:
        ocr_json = body.get("ocr_json") or {}
        engine_actual = body.get("ocr_engine") or ocr_json.get("ocr_engine")
        add("engine_is", engine_actual == engine_expected, engine_expected, engine_actual)

    return {"summary": evals, "details": details}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    feature_root = Path(__file__).resolve().parent
    scenario = load_json(feature_root / "scenario.json")
    cases_path = feature_root / scenario.get("cases_source", "fixtures/fixtures.json")
    cases: List[Dict[str, Any]] = load_json(cases_path)

    if args.list_cases:
        for c in cases:
            print(c.get("name", "unknown"))
        return 0

    base_url = (
        args.base_url or os.getenv("APITOOLS_BASE_URL") or scenario.get("base_url") or DEFAULT_BASE_URL
    ).rstrip("/")
    upload_endpoint = scenario.get("upload_endpoint", "/documentOcr")
    case_filters = set(args.case_filters or [])

    results: List[Dict[str, Any]] = []
    failures: List[str] = []
    skipped: List[Dict[str, Any]] = []
    caps = _capabilities()

    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT})
        for case in cases:
            name = case.get("name", "unknown")
            if case_filters and name not in case_filters:
                continue
            if case.get("skip"):
                continue
            missing = [c for c in _requirements(case) if c not in caps]
            if missing:
                print(f"Skipping case '{name}' (requires {missing}; caps={sorted(caps)})")
                skipped.append({"name": name, "requires": _requirements(case)})
                continue

            source_rel = case.get("source_file")
            if not source_rel:
                failures.append(f"Case '{name}' missing source_file")
                continue

            source_path = (feature_root / source_rel).resolve()
            if not source_path.exists():
                failures.append(f"Case '{name}' fixture missing: {source_rel}")
                continue

            params = dict(case.get("upload_params", {}))
            try:
                resp = upload_document(session, base_url, upload_endpoint, source_path, params=params)
            except Exception as exc:
                expect_error = case.get("assertions", {}).get("expect_error", False)
                if expect_error:
                    results.append({
                        "name": name, "source_file": source_rel, "status": "passed",
                        "evaluations": {"expect_error": True},
                        "evaluation_details": [{"name": "expect_error", "passed": True, "expected": True, "actual": str(exc)}],
                        "analysis": {}, "notes": [case.get("notes", "")],
                        "upload_response": {"error": str(exc)}, "query_response": {},
                    })
                    continue
                failures.append(f"Case '{name}' upload failed: {exc}")
                results.append({
                    "name": name, "source_file": source_rel, "status": "error",
                    "error": str(exc), "analysis": {}, "notes": [case.get("notes", "")],
                    "upload_response": {}, "query_response": {},
                })
                if args.fail_fast:
                    break
                continue

            evaluation = evaluate_upload(case, resp)
            all_passed = all(evaluation["summary"].values()) if evaluation["summary"] else True
            status = "passed" if all_passed else "failed"

            if not all_passed:
                failing = [f"{d['name']} (expected {d['expected']} got {d['actual']})" for d in evaluation["details"] if not d["passed"]]
                failures.append(f"Case '{name}' failed: " + "; ".join(failing))
                if args.fail_fast:
                    results.append({
                        "name": name, "source_file": source_rel, "status": status,
                        "evaluations": evaluation["summary"],
                        "evaluation_details": evaluation["details"],
                        "analysis": {}, "notes": [case.get("notes", "")],
                        "upload_response": resp, "query_response": {},
                    })
                    break

            results.append({
                "name": name, "source_file": source_rel, "status": status,
                "evaluations": evaluation["summary"],
                "evaluation_details": evaluation["details"],
                "analysis": {"result_value": resp.get("body", {}).get("file_hash") if isinstance(resp.get("body"), dict) else None},
                "notes": [case.get("notes", "")],
                "upload_response": resp, "query_response": {},
            })

    timestamp = datetime.now(timezone.utc).isoformat()
    passed_count = sum(1 for r in results if r.get("status") == "passed")
    benchmark = {
        "feature": scenario.get("feature", feature_root.name),
        "timestamp": timestamp,
        "base_url": base_url,
        "upload_endpoint": upload_endpoint,
        "endpoint": upload_endpoint,
        "query_params": {},
        "assertions": [],
        "results": results,
        "failures": failures,
        "all_passed": not failures,
        "case_count": len(results),
        "cases_passed": passed_count,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "capabilities": sorted(caps),
    }

    benchmarks_dir = feature_root / "benchmarks"
    output_path = benchmarks_dir / f"benchmark-{timestamp}.json"
    save_json(output_path, benchmark)
    save_json(benchmarks_dir / "latest.json", benchmark)

    print(f"Wrote benchmark to {output_path.relative_to(feature_root)}")
    print(f"Cases: {passed_count}/{len(results)} passed")
    if failures:
        print("Failures detected:")
        for f in failures:
            print(f" - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
