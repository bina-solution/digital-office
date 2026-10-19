#!/usr/bin/env python3
"""Merge the per-shard capture outputs into the single pair the report/composer expect."""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/browser42")
    a = ap.parse_args()
    d = Path(a.data)

    results = []
    for f in sorted(glob.glob(str(d / "ui-capture-results.*.json"))):
        results.extend(json.loads(Path(f).read_text(encoding="utf-8"))["results"])
    if results:
        (d / "ui-capture-results.json").write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    raw: dict = {}
    for f in sorted(glob.glob(str(d / "ui-raw-coverage.*.json"))):
        # shards own disjoint app sets, so a plain update is a safe merge
        raw.update(json.loads(Path(f).read_text(encoding="utf-8")))
    if raw:
        (d / "ui-raw-coverage.json").write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    cap = sum(1 for r in results if r["status"] == "captured")
    print(f"merged {len(results)} view results from shards "
          f"({cap} captured), coverage for {len(raw)} app(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
