"""General-purpose runner for feature validation suites."""

from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import requests

DEFAULT_BASE_URL = "http://apitools:8080"
DEFAULT_UPLOAD_ENDPOINT = "/documentOcr"
REQUEST_TIMEOUT = 120
USER_AGENT = "feature-validation/1.0"

DEFAULT_METADATA_KEYS = {"notes"}
DEFAULT_EXPECTED_BY_OPERATOR = {
    "truthy": True,
    "falsy": True,
    "is_none": True,
    "not_none": True,
}
DEFAULT_ASSERTION_REGISTRY = {
    "match_present": {"source": "analysis.result_value", "operator": "truthy"},
    "validations_passed": {"source": "analysis.error", "operator": "is_none"},
    "drawing_path_created": {"source": "analysis.drawing_path", "operator": "truthy"},
    "result_value_equals": {"source": "analysis.result_value", "operator": "equals"},
    "aligned_value_equals": {"source": "analysis.aligned_value", "operator": "equals"},
    "text_match_equals": {"source": "analysis.text_match", "operator": "equals"},
    "result_value_contains": {"source": "analysis.result_value", "operator": "contains"},
    "aligned_value_contains": {"source": "analysis.aligned_value", "operator": "contains"},
    "text_match_contains": {"source": "analysis.text_match", "operator": "contains"},
    "result_value_starts_with": {"source": "analysis.result_value", "operator": "starts_with"},
    "aligned_value_starts_with": {"source": "analysis.aligned_value", "operator": "starts_with"},
    "text_match_starts_with": {"source": "analysis.text_match", "operator": "starts_with"},
    "result_value_ends_with": {"source": "analysis.result_value", "operator": "ends_with"},
    "aligned_value_ends_with": {"source": "analysis.aligned_value", "operator": "ends_with"},
    "text_match_ends_with": {"source": "analysis.text_match", "operator": "ends_with"},
}


def normalize_string(value: Any, *, casefold: bool = False, strip: bool = False) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if strip:
        value = value.strip()
    if casefold:
        value = value.casefold()
    return value


def levenshtein_distance(first: str, second: str) -> int:
    if first == second:
        return 0
    if not first:
        return len(second)
    if not second:
        return len(first)

    if len(first) < len(second):
        first, second = second, first

    previous_row = list(range(len(second) + 1))
    for i, char in enumerate(first, start=1):
        current_row = [i]
        for j, other_char in enumerate(second, start=1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (char != other_char)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run feature validation cases")
    parser.add_argument("--base-url", help="Override the base API host")
    parser.add_argument(
        "--case",
        action="append",
        dest="case_filters",
        metavar="NAME",
        help="Only run specific case names (can be supplied multiple times)",
    )
    parser.add_argument("--list-cases", action="store_true", help="List available cases and exit")
    parser.add_argument(
        "--no-upload-cache",
        action="store_true",
        help="Disable file upload caching between cases",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failing assertion",
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def upload_document(
    session: requests.Session,
    base_url: str,
    endpoint: str,
    file_path: Path,
    params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(file_path.name)
    with file_path.open("rb") as fh:
        response = session.post(
            f"{base_url}{endpoint}",
            files={"file": (file_path.name, fh, mime_type or "application/octet-stream")},
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"Upload error for {file_path.name}: {payload['error']}")
    return payload


def run_query(
    session: requests.Session,
    base_url: str,
    endpoint: str,
    params: Mapping[str, Any],
    body: Mapping[str, Any],
) -> Dict[str, Any]:
    response = session.post(
        f"{base_url}{endpoint}",
        params=params,
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload and "result" not in payload:
        raise RuntimeError(f"{endpoint} error: {payload['error']}")
    return payload


def analyze_query_response(result_payload: Mapping[str, Any]) -> Dict[str, Any]:
    result_section = result_payload.get("result") if isinstance(result_payload, Mapping) else {}
    if not isinstance(result_section, Mapping):
        result_section = {"result": result_section}

    process_context = result_section.get("process_context") or {}
    find_results = process_context.get("find_results") or {}

    aligned_value = find_results.get("aligned_value")
    if aligned_value is None:
        aligned_annotation = find_results.get("aligned_annotation") or {}
        aligned_value = aligned_annotation.get("description")

    text_match = process_context.get("text_match")
    if not text_match:
        text_match_annotation = find_results.get("text_match_annotation") or {}
        text_match = text_match_annotation.get("description")

    return {
        "result_section": dict(result_section),
        "result_value": result_section.get("result"),
        "process_context": dict(process_context),
        "find_results": dict(find_results),
        "aligned_value": aligned_value,
        "text_match": text_match,
        "drawing_path": result_payload.get("drawing_path"),
        "error": result_payload.get("error"),
    }


def resolve_path(payload: Any, dotted_path: str) -> Any:
    current = payload
    for segment in dotted_path.split("."):
        if isinstance(current, Mapping):
            current = current.get(segment)
        elif isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def apply_operator(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "equals":
        if isinstance(expected, Mapping) and "value" in expected:
            options = expected
            target_value = options.get("value")
            casefold = bool(options.get("casefold"))
            strip = bool(options.get("strip"))

            actual_norm = normalize_string(actual, casefold=casefold, strip=strip)
            target_norm = normalize_string(target_value, casefold=casefold, strip=strip)
            if actual_norm is None or target_norm is None:
                return False

            if "max_distance" in options:
                try:
                    max_distance = int(options["max_distance"])
                except (TypeError, ValueError) as exc:
                    raise ValueError("max_distance must be an integer") from exc
                if max_distance < 0:
                    raise ValueError("max_distance must be non-negative")
                distance = levenshtein_distance(actual_norm, target_norm)
                return distance <= max_distance

            return actual_norm == target_norm

        return actual == expected
    if operator == "truthy":
        return bool(actual) == bool(expected)
    if operator == "falsy":
        return (not bool(actual)) == bool(expected)
    if operator == "is_none":
        return (actual is None) == bool(expected)
    if operator == "not_none":
        return (actual is not None) == bool(expected)
    if operator == "contains":
        if actual is None or expected is None:
            return False
        return expected in actual
    if operator == "in":
        if expected is None:
            return False
        return actual in expected
    if operator == "starts_with":
        if actual is None or expected is None:
            return False
        actual_str = str(actual)
        expected_str = str(expected)
        return actual_str.startswith(expected_str)
    if operator == "ends_with":
        if actual is None or expected is None:
            return False
        actual_str = str(actual)
        expected_str = str(expected)
        return actual_str.endswith(expected_str)
    raise ValueError(f"Unsupported operator '{operator}'")


def evaluate_assertions(
    assertions: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    expected_overrides: Mapping[str, Any],
) -> Dict[str, Any]:
    summary: Dict[str, bool] = {}
    details: List[Dict[str, Any]] = []

    for assertion in assertions:
        name = assertion.get("name")
        source = assertion.get("source")
        operator = assertion.get("operator", "equals")
        if not name or not source:
            continue

        # Skip assertions that are not declared in expected_overrides
        # unless they have a default expected value for their operator
        if name not in expected_overrides and operator not in DEFAULT_EXPECTED_BY_OPERATOR:
            continue

        expected = expected_overrides.get(name, assertion.get("expected"))
        if expected is None and operator in DEFAULT_EXPECTED_BY_OPERATOR:
            expected = DEFAULT_EXPECTED_BY_OPERATOR[operator]

        actual = resolve_path(context, source)

        try:
            passed = apply_operator(operator, actual, expected)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            passed = False
            details.append(
                {
                    "name": name,
                    "source": source,
                    "operator": operator,
                    "expected": expected,
                    "actual": actual,
                    "passed": passed,
                    "error": str(exc),
                }
            )
            summary[name] = passed
            continue

        details.append(
            {
                "name": name,
                "source": source,
                "operator": operator,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
        )
        summary[name] = passed

    return {"summary": summary, "details": details}


def determine_assertions(
    scenario: Mapping[str, Any],
    cases: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    assertions = scenario.get("assertions")
    if assertions:
        return list(assertions)

    expected_keys = set()
    scenario_expected = scenario.get("expected") or {}
    expected_keys.update(k for k in scenario_expected if k not in DEFAULT_METADATA_KEYS)

    for case in cases:
        case_expected = case.get("expected") or {}
        expected_keys.update(k for k in case_expected if k not in DEFAULT_METADATA_KEYS)

    derived: List[Dict[str, Any]] = []
    for key in sorted(expected_keys):
        template = DEFAULT_ASSERTION_REGISTRY.get(key)
        if not template:
            continue
        entry = {"name": key}
        entry.update(template)
        derived.append(entry)

    if not derived:
        return [
            {"name": "validations_passed", "source": "analysis.error", "operator": "is_none"}
        ]

    return derived


def merge_expected_values(*expected_groups: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for group in expected_groups:
        if not group:
            continue
        for key, value in group.items():
            if key in DEFAULT_METADATA_KEYS:
                continue
            merged[key] = value
    return merged


def collect_notes(*expected_groups: Mapping[str, Any]) -> List[str]:
    notes: List[str] = []
    for group in expected_groups:
        if not group:
            continue
        note = group.get("notes")
        if note:
            notes.append(str(note))
    return notes


def derive_case_name(case: Mapping[str, Any]) -> str:
    name = case.get("name")
    if name:
        return str(name)
    source_rel = case.get("source_file")
    if source_rel:
        return Path(str(source_rel)).stem
    return "case"


def available_capabilities() -> set:
    """Capabilities available in THIS environment, used to gate cases that need an
    external service. Default = local-only, so a fresh/CI run (no external keys) is
    deterministic and green on everything it can actually run. Override/extend with
    FV_CAPABILITIES (comma-separated), e.g. FV_CAPABILITIES=local,google_vision,gemini.
    A real Gemini key (AIza...) auto-enables the google/gemini engines."""
    raw = os.getenv("FV_CAPABILITIES")
    if raw is not None:
        return {c.strip() for c in raw.split(",") if c.strip()}
    caps = {"local"}
    if os.getenv("GEMINI_API_KEY", "").startswith("AIza"):
        caps |= {"gemini", "google_vision"}
    return caps


def case_requirements(case: Mapping[str, Any]) -> List[str]:
    """A case may declare `"requires": "google_vision"` or a list. Empty = local-only."""
    req = case.get("requires") or []
    return [req] if isinstance(req, str) else list(req)


def run_feature(feature_root: Path, argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    scenario = load_json(feature_root / "scenario.json")
    cases_path = feature_root / scenario.get("cases_source", "fixtures/fixtures.json")
    cases_data: List[Dict[str, Any]] = load_json(cases_path)

    case_filters = set(args.case_filters or [])
    if args.list_cases:
        for case in cases_data:
            print(derive_case_name(case))
        return 0

    # Scenario-level capability gate: a whole feature (e.g. the orchestration/integration
    # E2E) can declare `"requires": [...]`. If this environment lacks it, the feature is
    # SKIPPED wholesale (green, no cases run) rather than failing a local/CI run.
    scenario_missing = [c for c in (scenario.get("requires") or []) if c not in available_capabilities()]
    if scenario_missing:
        caps = available_capabilities()
        print(f"Skipping feature '{scenario.get('feature', feature_root.name)}' "
              f"(requires {scenario_missing}; caps={sorted(caps)})")
        ts = datetime.now(timezone.utc).isoformat()
        bench = {"feature": scenario.get("feature", feature_root.name), "timestamp": ts,
                 "results": [], "failures": [], "all_passed": True, "case_count": 0,
                 "cases_passed": 0, "skipped": [{"name": derive_case_name(c),
                 "requires": scenario.get("requires")} for c in cases_data],
                 "skipped_count": len(cases_data), "capabilities": sorted(caps),
                 "feature_skipped": True}
        bdir = feature_root / "benchmarks"
        save_json(bdir / f"benchmark-{ts}.json", bench)
        save_json(bdir / "latest.json", bench)
        print(f"Feature skipped: {len(cases_data)} case(s) require {scenario_missing}")
        return 0

    known_case_names = {
        derive_case_name(case) for case in cases_data
    }.union({str(case.get("name")) for case in cases_data if case.get("name")})
    if case_filters and not case_filters.intersection(known_case_names):
        print("No cases matched the provided filters", file=sys.stderr)
        return 1

    base_url = (
        (args.base_url or os.getenv("APITOOLS_BASE_URL") or scenario.get("base_url") or DEFAULT_BASE_URL)
    ).rstrip("/")
    upload_endpoint = scenario.get("upload_endpoint", DEFAULT_UPLOAD_ENDPOINT)
    upload_query_params = scenario.get("upload_query_params", {})
    default_endpoint = scenario.get("endpoint", "/documentJsonQuery")
    base_query_params = scenario.get("query_params", {})

    scenario_expected = scenario.get("expected") or {}
    assertions = determine_assertions(scenario, cases_data)

    results: List[Dict[str, Any]] = []
    failures: List[str] = []
    skipped: List[Dict[str, Any]] = []
    caps = available_capabilities()
    upload_cache: Dict[Path, Dict[str, Any]] = {}

    with create_session() as session:
        for case in cases_data:
            case_name = derive_case_name(case)
            raw_name = str(case.get("name")) if case.get("name") else None
            if case_filters and case_name not in case_filters and (raw_name not in case_filters if raw_name else True):
                continue

            if case.get("skip"):
                print(f"Skipping case '{case_name}' (flagged skip)")
                continue

            # Capability gate: a case that requires an external service (google_vision,
            # gemini, ...) is SKIPPED — not failed — when that capability isn't available
            # in this environment. Keeps a local/CI run green on everything it can run.
            missing = [c for c in case_requirements(case) if c not in caps]
            if missing:
                print(f"Skipping case '{case_name}' (requires {missing}; caps={sorted(caps)})")
                skipped.append({"name": case_name, "requires": case_requirements(case)})
                continue

            source_rel = case.get("source_file")
            file_id = case.get("file_id")
            upload_payload: Dict[str, Any] = {}

            if not file_id and not source_rel:
                failures.append(f"Case '{case_name}' missing source_file or file_id")
                continue

            if not file_id and source_rel:
                source_path = (feature_root / source_rel).resolve()
                if not source_path.exists():
                    failures.append(f"Case '{case_name}' fixture missing: {source_rel}")
                    continue

                if not args.no_upload_cache and source_path in upload_cache:
                    upload_payload = upload_cache[source_path]
                else:
                    try:
                        upload_payload = upload_document(session, base_url, upload_endpoint, source_path, params=upload_query_params)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        failures.append(f"Case '{case_name}' upload failed: {exc}")
                        results.append(
                            {
                                "name": case_name,
                                "source_file": source_rel,
                                "status": "error",
                                "error": str(exc),
                            }
                        )
                        if args.fail_fast:
                            break
                        continue
                    upload_cache[source_path] = upload_payload

                file_id = upload_payload.get("file_hash") or upload_payload.get("file_id")
                if not file_id:
                    failures.append(f"Case '{case_name}' missing file identifier post-upload")
                    if args.fail_fast:
                        break
                    continue

            ocr_query = copy.deepcopy(case.get("ocr_json_query") or {})
            request_body = copy.deepcopy(case.get("request_body") or {})

            if request_body:
                request_body.setdefault("file_id", file_id)
            else:
                if not ocr_query:
                    failures.append(f"Case '{case_name}' missing request payload definition")
                    if args.fail_fast:
                        break
                    continue
                request_body = {"file_id": file_id, "ocr_json_query": ocr_query}
                if "match_index" in case:
                    request_body["match_index"] = case["match_index"]

            endpoint = case.get("endpoint", default_endpoint)
            query_params = dict(base_query_params)
            query_params.update(case.get("query_params", {}))

            try:
                query_response = run_query(session, base_url, endpoint, query_params, request_body)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                failures.append(f"Case '{case_name}' query failed: {exc}")
                results.append(
                    {
                        "name": case_name,
                        "source_file": source_rel,
                        "file_id": file_id,
                        "status": "error",
                        "error": str(exc),
                        "request_body": request_body,
                        "query_params": query_params,
                    }
                )
                if args.fail_fast:
                    break
                continue

            analysis = analyze_query_response(query_response)
            merged_expected = merge_expected_values(scenario_expected, case.get("expected") or {})
            notes = collect_notes(scenario_expected, case.get("expected") or {})

            evaluation_payload = evaluate_assertions(
                assertions,
                {
                    "analysis": analysis,
                    "query_response": query_response,
                    "upload_response": upload_payload,
                    "case": case,
                    "scenario": scenario,
                },
                merged_expected,
            )

            evaluation_summary = evaluation_payload["summary"]
            all_passed = all(evaluation_summary.values()) if evaluation_summary else True
            status = "passed" if all_passed else "failed"

            if not all_passed:
                failing_parts = [
                    f"{detail['name']} (expected {detail['operator']} {detail['expected']} got {detail['actual']})"
                    for detail in evaluation_payload["details"]
                    if not detail.get("passed")
                ]
                failures.append(
                    f"Case '{case_name}' failed: " + "; ".join(failing_parts) if failing_parts else f"Case '{case_name}' failed"
                )
                if args.fail_fast:
                    results.append(
                        {
                            "name": case_name,
                            "source_file": source_rel,
                            "file_id": file_id,
                            "status": status,
                            "evaluations": evaluation_summary,
                            "evaluation_details": evaluation_payload["details"],
                            "analysis": analysis,
                            "notes": notes,
                            "upload_response": upload_payload,
                            "query_response": query_response,
                        }
                    )
                    break

            results.append(
                {
                    "name": case_name,
                    "source_file": source_rel,
                    "file_id": file_id,
                    "status": status,
                    "evaluations": evaluation_summary,
                    "evaluation_details": evaluation_payload["details"],
                    "analysis": analysis,
                    "notes": notes,
                    "upload_response": upload_payload,
                    "query_response": query_response,
                }
            )

    timestamp = datetime.now(timezone.utc).isoformat()
    passed_count = sum(1 for result in results if result.get("status") == "passed")
    benchmark = {
        "feature": scenario.get("feature", feature_root.name),
        "timestamp": timestamp,
        "base_url": base_url,
        "upload_endpoint": upload_endpoint,
        "endpoint": default_endpoint,
        "query_params": base_query_params,
        "assertions": assertions,
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
    print(f"Cases: {passed_count}/{len(results)} passed" +
          (f" ({len(skipped)} skipped — need {sorted({r for s in skipped for r in s['requires']})})" if skipped else ""))
    if failures:
        print("Failures detected:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    return 0


__all__ = ["run_feature"]
