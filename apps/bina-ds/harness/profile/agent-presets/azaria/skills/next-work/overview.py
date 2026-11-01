#!/usr/bin/env python3
"""next-work/overview.py — the open work of the digital office, offline.

WHY IT EXISTS. `/next` has to say what is open even when Plane is unreachable (it runs in the
hp-laptop office, and the link between offices goes down — measured repeatedly), and it must not
invent a picture from a chat memory. The declared work DOES live in this repository, in the plan
files that are applied INTO Plane: `apps/project-pln/plans/dgo-dev.yaml` (the DGO-Extend roadmap,
phases p0…rel) and `apps/project-pln/plans/office.yaml` (everything else that is open). This script
reads those two files and the open issue records, and prints a plain report — no network, no API key,
no Plane, no state of its own.

WHAT IT CANNOT KNOW. Whether an item is done. Completion lives in Plane (that is what `tasks list`
is for), and an item that left a plan is never deleted from it. So this is the DECLARATION — "what
the office says is open" — and the skill says out loud when Plane was not consulted.

Usage:
    python3 overview.py [--root DIR] [--plan office|dgo-dev|all] [--limit N] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
PLANS = ("dgo-dev", "office")
OPEN_ISSUE_STATES = {"open", "in-progress", "blocked"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def find_root(start: Path) -> Path:
    """The checkout: the first directory at or above `start` that holds the plan files."""
    for candidate in (start, *start.parents):
        if (candidate / "apps/project-pln/plans").is_dir():
            return candidate
    raise SystemExit("next-work: no checkout found (looked for apps/project-pln/plans above %s)" % start)


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # noqa: PLC0415 — the only dependency, imported where its absence is reportable
    except ImportError:  # pragma: no cover - the office image always has PyYAML
        raise SystemExit("next-work: PyYAML is missing; pip install pyyaml (or skip --plan)")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def plan_items(root: Path, which: str) -> tuple[list[dict], list[str]]:
    """Every declared item of one plan, plus the modules it lives in."""
    path = root / "apps/project-pln/plans" / f"{which}.yaml"
    if not path.is_file():
        return [], []
    document = load_yaml(path)
    items: list[dict] = []
    for module in document.get("modules") or []:
        for item in module.get("items") or []:
            items.append({
                "plan": which,
                "module": module.get("key") or "",
                "module_name": module.get("name") or "",
                "key": item.get("key") or "",
                "name": (item.get("name") or "").strip(),
                "priority": (item.get("priority") or "none").strip() or "none",
                "labels": list(item.get("labels") or []),
                "assignee": item.get("assignee") or "",
            })
    return items, [m.get("key") or "" for m in document.get("modules") or []]


def open_issues(root: Path) -> list[dict]:
    """Issue records that are not resolved — each one is a defect with measurements behind it."""
    records: list[dict] = []
    for path in sorted((root / "issues").glob("*.yaml")):
        try:
            document = load_yaml(path)
        except Exception:  # noqa: BLE001 — one unreadable record must not hide the rest
            continue
        if not isinstance(document, dict):
            continue
        status = str(document.get("status") or "").lower()
        if status not in OPEN_ISSUE_STATES:
            continue
        records.append({
            "file": str(path.relative_to(root)),
            "title": (document.get("title") or "").strip(),
            "status": status,
            "severity": str(document.get("severity") or "").lower(),
            "category": str(document.get("category") or "").lower(),
            "opened": str(document.get("opened") or ""),
        })
    records.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), r["opened"]))
    return records


def report(root: Path, plans: tuple[str, ...], limit: int) -> dict:
    items: list[dict] = []
    modules: dict[str, list[str]] = {}
    for which in plans:
        found, module_keys = plan_items(root, which)
        items.extend(found)
        modules[which] = module_keys
    items.sort(key=lambda i: (PRIORITY_ORDER.get(i["priority"], 9), i["plan"], i["key"]))
    by_priority: dict[str, int] = {}
    by_module: dict[str, int] = {}
    for item in items:
        by_priority[item["priority"]] = by_priority.get(item["priority"], 0) + 1
        by_module[item["module"]] = by_module.get(item["module"], 0) + 1
    return {
        "root": str(root),
        "plans": {which: {"modules": modules[which],
                          "items": len([i for i in items if i["plan"] == which])} for which in plans},
        "counts": {"items": len(items), "by_priority": by_priority, "by_module": by_module},
        "top": [i for i in items if i["priority"] in ("urgent", "high")][:limit],
        "issues": open_issues(root),
    }


def render(data: dict) -> str:
    out: list[str] = []
    out.append("OPEN WORK — declared in the plan files (completion lives in Plane)")
    out.append("checkout: %s" % data["root"])
    for which, info in data["plans"].items():
        out.append("  plan %-8s %3d item(s) in %d module(s): %s"
                   % (which, info["items"], len(info["modules"]), " ".join(info["modules"])))
    counts = data["counts"]
    out.append("  %d item(s) total · by priority: %s"
               % (counts["items"],
                  " ".join("%s=%d" % (k, v) for k, v in sorted(counts["by_priority"].items(),
                                                               key=lambda kv: PRIORITY_ORDER.get(kv[0], 9)))))
    out.append("")
    out.append("URGENT / HIGH (the head of the queue — %d shown)" % len(data["top"]))
    for item in data["top"]:
        labels = (" [" + ",".join(item["labels"]) + "]") if item["labels"] else ""
        who = (" →" + item["assignee"]) if item["assignee"] else ""
        out.append("  %-9s %-8s %-9s %s%s%s"
                   % (item["priority"], item["module"], item["key"], item["name"][:96], labels, who))
    out.append("")
    out.append("OPEN ISSUE RECORDS (%d) — each one is a defect with measurements" % len(data["issues"]))
    for issue in data["issues"]:
        out.append("  %-9s %-12s %-9s %s"
                   % (issue["severity"] or "-", issue["status"], issue["category"] or "-",
                      issue["title"][:92]))
        out.append("            %s" % issue["file"])
    return "\n".join(out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="the office's open work, offline")
    parser.add_argument("--root", default=os.getcwd(), help="the checkout (default: cwd)")
    parser.add_argument("--plan", default="all", choices=(*PLANS, "all"))
    parser.add_argument("--limit", type=int, default=40, help="how many urgent/high items to print")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = find_root(Path(args.root).resolve())
    plans = PLANS if args.plan == "all" else (args.plan,)
    data = report(root, plans, args.limit)
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
