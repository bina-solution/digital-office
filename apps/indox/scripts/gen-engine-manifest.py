#!/usr/bin/env python3
"""Generate the INDOX sync-engine manifest FROM the blueprints. `--check` is gate G29.

(The --check mode ran in CI as "G23", which is gallery-default-lint.py's number.
Registry: scripts/refactor/GATES.md.)

The sync screen draws the engine — which workflow calls which, what each stage is for, where the
ledger sits. That picture has to come from the workflows themselves, because a hand-drawn one is a
comment: correct on the day it is written and quietly wrong forever after. Someone adds a stage, the
diagram keeps showing four boxes, and the diagram is now actively misleading about the thing an
operator is using it to reason about.

So the topology is READ from `apps/indox/blueprint/n8n/*.json` — triggers, sub-workflow calls, node
counts — and only the prose (what a stage is FOR) is authored here, because no amount of parsing
recovers intent.

    python3 apps/indox/scripts/gen-engine-manifest.py            # write the manifest
    python3 apps/indox/scripts/gen-engine-manifest.py --check    # fail if it is stale (CI)

`--check` is the part that matters: it makes a topology change fail the build until the picture is
regenerated, which is the only way a generated diagram stays true.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
BP = ROOT / "apps" / "indox" / "blueprint" / "n8n"
OUT = ROOT / "apps" / "indox" / "blueprint" / "engine-manifest.json"

#: The stages, in the order work flows through them. `id` is the n8n workflow id; everything else
#: about each stage is derived. Only `role` and `why` are authored — they are intent, not structure.
STAGES = [
    ("SyncApi0000000001", "שער ה-API",
     "כל פעולה ידנית מהמסך נכנסת דרך כאן — SCAN, STATUS, RELEASE, RESET.",
     "The only door in. The registry is enforced here, server-side: an unknown pipe, a paused one, "
     "or a v1 pipe are refusals rather than silent no-ops."),
    ("syncV3Main0001", "הסורק",
     "קורא את הרישום של כל המופעים ומפצל לעבודה — יחידה אחת לכל צמד תיקיות.",
     "The only stage that reads ACROSS instances (instance:'*'), because finding the work is its "
     "job and it has no work item to derive a tenant from."),
    ("syncV3Unit0001", "היחידה",
     "משווה מקור מול הרישום, תופסת פריטים, ומעבירה אותם למסירה.",
     "Where the claim happens: DIFF, then CLAIM, then deliver. The claim is what makes 'in progress' "
     "a real state and 'stuck' an honest one."),
    ("syncV3Deliver0001", "המסירה",
     "מוריד, מחלץ ורושם כל מסמך — ומחזיר תפיסה שנכשלה.",
     "Delivery then RECORD, in that order, always. A failed delivery RELEASEs its claim so the item "
     "returns to the todo instead of vanishing."),
    ("syncLedgerApi01", "הרישום",
     "ספר החשבונות: מה נתפס, מה נמסר, מה בהמתנה לבדיקה.",
     "The kernel. CLAIM is an INSERT whose primary key decides the race; RELEASE only ever touches "
     "status='claimed', so it can never erase a delivery."),
]


def read(wf_id: str) -> dict | None:
    p = BP / f"{wf_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def calls_of(doc: dict) -> list[str]:
    """Sub-workflows this one invokes. Expression-valued ids (`={{ $json.processor_wf }}`) are kept
    as-is and marked dynamic — pretending a runtime-chosen target is a fixed edge would draw an
    arrow to one processor when there are five."""
    out = set()
    for n in doc.get("nodes", []) or []:
        wid = (n.get("parameters") or {}).get("workflowId")
        if isinstance(wid, dict):
            wid = wid.get("value")
        if wid:
            out.add(str(wid))
    return sorted(out)


def triggers_of(doc: dict) -> list[str]:
    out = []
    for n in doc.get("nodes", []) or []:
        t = str(n.get("type") or "").lower()
        if "trigger" in t or t.endswith("webhook"):
            kind = ("schedule" if "schedule" in t else
                    "webhook" if "webhook" in t else
                    "called" if "executeworkflow" in t else
                    "manual" if "manual" in t else "other")
            out.append({"name": n.get("name"), "kind": kind})
    return out


def build() -> dict:
    stages = []
    known = {sid for sid, *_ in STAGES}
    for sid, title, role, why in STAGES:
        doc = read(sid)
        if doc is None:
            stages.append({"id": sid, "title": title, "role": role, "why": why,
                           "present": False, "nodes": 0, "calls": [], "triggers": []})
            continue
        calls = calls_of(doc)
        stages.append({
            "id": sid,
            "title": title,
            "role": role,
            "why": why,
            "present": True,
            "name": doc.get("name") or sid,
            "nodes": len(doc.get("nodes") or []),
            "triggers": triggers_of(doc),
            # split so the UI can draw the spine solid and the leaves faint
            "calls": [c for c in calls if c in known],
            "calls_external": [c for c in calls if c not in known and not c.startswith("=")],
            "calls_dynamic": [c for c in calls if c.startswith("=")],
        })
    return {"generated_by": "apps/indox/scripts/gen-engine-manifest.py", "stages": stages}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed manifest no longer matches the blueprints")
    args = ap.parse_args()

    fresh = build()
    text = json.dumps(fresh, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not OUT.exists():
            print(f"engine-manifest: MISSING {OUT.relative_to(ROOT)} — run this script")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print("engine-manifest: STALE — the workflows changed and the engine view did not.\n"
                  "  run: python3 apps/indox/scripts/gen-engine-manifest.py\n"
                  "  (a diagram that no longer matches the engine is worse than none: it is the\n"
                  "   thing an operator trusts while debugging.)")
            return 1
        print("engine-manifest: OK — the drawn engine matches the built one")
        return 0

    OUT.write_text(text, encoding="utf-8")
    n = sum(1 for s in fresh["stages"] if s.get("present"))
    print(f"engine-manifest: wrote {OUT.relative_to(ROOT)} ({n}/{len(fresh['stages'])} stages present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
