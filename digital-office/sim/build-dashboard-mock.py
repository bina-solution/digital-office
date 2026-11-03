#!/usr/bin/env python3
"""Write ci-artifacts/dashboard-mock/: the control centre (apps/dashboard, DGO-1124) over a measured day.

The page is the app's own (apps/dashboard/static/index.html), copied untouched; only its data differs. The
app reads data/state.json, which its collector writes; here that file is dashboard-mock.data.json, the
morning of 2026-11-02 as measured, with Plane's totals counted from a `tasks list --json` dump when one is
given. data/ok.json is the same morning with every linked computer up (?state=ok). AGENTS.md rule 11.

    python3 digital-office/sim/build-dashboard-mock.py [--tasks ci-artifacts/king/dgo-tasks.json]

Query: ?state=ok · ?theme=dark · ?open=<computer id>.
"""
import argparse
import json
import pathlib
import shutil

repo = pathlib.Path(__file__).resolve().parents[2]
here = pathlib.Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--tasks", default="")
ap.add_argument("--out", default=str(repo / "ci-artifacts/dashboard-mock"))
args = ap.parse_args()

data = json.loads((here / "dashboard-mock.data.json").read_text(encoding="utf-8"))
if args.tasks:
    tasks = json.loads(pathlib.Path(args.tasks).read_text(encoding="utf-8"))["tasks"]
    open_ = [t for t in tasks if t["group"] not in ("completed", "cancelled")]
    data["totals"] = {
        "all": len(tasks),
        "completed": sum(t["group"] == "completed" for t in tasks),
        "started": sum(t["group"] == "started" for t in tasks),
        "owner": sum("בעלים" in t["labels"] for t in open_),
    }
ok = {**data,
      "computers": [{**c, "state": "up", "when": "עכשיו", "note": "מחובר, ואפשר להריץ בו פקודות."}
                    if c["state"] != "none" else c for c in data["computers"]],
      "feed": [f for f in data["feed"] if f["kind"] != "bad"]}

out = pathlib.Path(args.out)
(out / "data").mkdir(parents=True, exist_ok=True)
shutil.copyfile(repo / "apps/dashboard/static/index.html", out / "index.html")
for name, d in (("state", data), ("ok", ok)):
    (out / "data" / f"{name}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
print(f"{out}/index.html + data/state.json, data/ok.json · totals {data.get('totals')}")
