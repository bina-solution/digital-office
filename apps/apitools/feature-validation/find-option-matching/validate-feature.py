#!/usr/bin/env python3
"""Find-option matching validation using the shared harness with custom analysis."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import lib.validate_feature_base as base  # noqa: E402


def analyze_find_option_response(result_payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Custom analyzer for 'find option' responses.

    The response structure is:
        { "result": { "process_context": {}, "result": { "matches": [...] } } }

    Each match: {"option": "...", "match_annotations": [...]}
    """
    outer_result = result_payload.get("result") if isinstance(result_payload, Mapping) else {}
    if not isinstance(outer_result, Mapping):
        outer_result = {}

    result_section = outer_result.get("result") or {}
    if not isinstance(result_section, Mapping):
        result_section = {}

    matches = result_section.get("matches") or []
    matched_option_names = sorted({m.get("option", "") for m in matches})
    match_count = len(matches)

    return {
        "result_section": dict(result_section),
        "result_value": result_section,
        "matches": matches,
        "match_count": match_count,
        "matched_option_names": matched_option_names,
        "unexpected_matches": [],  # populated per-case in fixtures
        "drawing_path": result_payload.get("drawing_path"),
        "error": result_payload.get("error"),
        "completed": True,
    }


# Monkey-patch the analyzer so the shared harness uses our version
_original_analyze = base.analyze_query_response
base.analyze_query_response = analyze_find_option_response


def main(argv: Optional[Sequence[str]] = None) -> int:
    feature_root = Path(__file__).resolve().parent
    return base.run_feature(feature_root, argv)


if __name__ == "__main__":
    sys.exit(main())
