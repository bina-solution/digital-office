#!/usr/bin/env python3
"""digital-assets/content/status.py — what the content library holds, against what it is to hold.

    python3 apps/digital-assets/content/status.py                 # per type: planned, written, in range
    python3 apps/digital-assets/content/status.py --list          # one line per piece: state, words, file
    python3 apps/digital-assets/content/status.py --jobs [--repo PATH] [--no-import]
                                                                  # what is left, as args for content/workflow.js

The plan is assignments.yaml; a piece is "ok" when its file parses, has a title, and its body is within
10% of its type's range (BRIEF.md). Anything else — missing, broken, short, long — is left to write or
fix, and `--jobs` prints exactly those pieces in the shape the workflow takes ({pieces, categories}).
A file under content/<type>/ that the plan does not name is listed as "extra" and never dropped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:                                      # the Mac host has none; the engine guest does
    sys.exit("status.py needs PyYAML: pip install pyyaml — or run `./bbox digital-assets content-status`")

HERE = Path(__file__).resolve().parent
RANGE = {"article": (1800, 2400), "project": (450, 650), "tutorial": (1000, 2200), "comparison": (1200, 1800),
         "directory": (1500, 3000), "news": (400, 800), "report": (1000, 2500), "post": (40, 700),
         "glossary": (300, 6000)}


def planned() -> list[dict]:
    d = yaml.safe_load((HERE / "assignments.yaml").read_text(encoding="utf-8"))
    out = [{**f, "type": "article"} for f in d.get("flagship") or []]
    for plane, c in (d.get("projects") or {}).items():
        out += [{"type": "project", "slug": s, "plane": plane, "category": c["category"], "category_he": c["he"]}
                for s in c["slugs"]]
    out += list(d.get("pieces") or [])
    return out


def state(p: dict) -> tuple[str, int]:
    f = HERE / p["type"] / f"{p['slug']}.he.md"
    if not f.exists():
        return "missing", 0
    lines = f.read_text(encoding="utf-8").splitlines()
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---") if lines and lines[0].strip() == "---" else None
        front = yaml.safe_load("\n".join(lines[1:end])) if end else None
    except (StopIteration, yaml.YAMLError):
        front = None
    if not isinstance(front, dict) or not front.get("title"):
        return "broken", 0
    words = len("\n".join(lines[end + 1:]).split())
    lo, hi = RANGE[p["type"]]
    if words < lo * 0.9:
        return "short", words
    if words > hi * 1.1:
        return "long", words
    return "ok", words


def main(argv: list[str]) -> int:
    plan = planned()
    rows = [(p, *state(p)) for p in plan]
    named = {f"{p['type']}/{p['slug']}" for p in plan}
    extra = sorted(f"{f.parent.name}/{f.name.removesuffix('.he.md')}" for f in HERE.glob("*/*.he.md")
                   if f"{f.parent.name}/{f.name.removesuffix('.he.md')}" not in named)
    if "--jobs" in argv:
        left = [p for p, st, _ in rows if st != "ok"]
        cats: dict[str, dict] = {}
        for p in (x for x in left if x["type"] == "project"):
            c = cats.setdefault(p["category"], {"plane": p["plane"], "category": p["category"], "he": p["category_he"], "slugs": []})
            c["slugs"].append(p["slug"])
        out = {"pieces": [{k: v for k, v in p.items() if v is not None} for p in left if p["type"] != "project"],
               "categories": list(cats.values())}
        if "--repo" in argv:
            out["repo"] = argv[argv.index("--repo") + 1]
        if "--no-import" in argv:
            out["import"] = False
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if "--list" in argv:
        for p, st, w in rows:
            print(f"{st:<8} {w:>5}  {p['type']}/{p['slug']}")
        for e in extra:
            print(f"{'extra':<8} {'':>5}  {e}")
        return 0
    by: dict[str, list] = {}
    for p, st, w in rows:
        by.setdefault(p["type"], []).append((st, w))
    print(f"{'type':<11} {'planned':>7} {'ok':>4} {'short':>5} {'long':>4} {'broken':>6} {'missing':>7} {'words':>8}")
    for t, xs in sorted(by.items()):
        n = lambda s: sum(1 for st, _ in xs if st == s)
        print(f"{t:<11} {len(xs):>7} {n('ok'):>4} {n('short'):>5} {n('long'):>4} {n('broken'):>6} {n('missing'):>7} {sum(w for _, w in xs):>8,}")
    ok = sum(1 for _, st, _ in rows if st == "ok")
    print(f"{'total':<11} {len(rows):>7} {ok:>4}  — {sum(w for _, _, w in rows):,} words written; extra files: {len(extra)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
