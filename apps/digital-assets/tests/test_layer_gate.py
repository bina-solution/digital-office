"""the layer gate (DGO-664): content/layer_gate.py says, item by item, whether a SEO layer is perfect — layer 1's lists
exist, are sourced, were checked within 91 days and have their place on the site; layer 2's pieces are written and
pass the quarterly check; layer 3 stays closed until layer 2 passes. Runs on a scratch repository.

    python3 apps/digital-assets/tests/test_layer_gate.py
"""
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "content"))
import layer_gate  # noqa: E402

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def repo() -> Path:
    r = Path(tempfile.mkdtemp(prefix="layers-"))
    c = r / "apps" / "digital-assets" / "content"
    (c / "index").mkdir(parents=True)
    for f in ("status.py", "recheck.py"):
        shutil.copy(HERE / "content" / f, c / f)
    (c / "FACTS.md").write_text("# facts\n", encoding="utf-8")
    old = datetime.datetime(2026, 10, 1).timestamp()        # outside git, FACTS.md is dated by its file time
    os.utime(c / "FACTS.md", (old, old))
    src = [{"url": "https://gov.il/x", "date": "2026-10-01", "what": "w", "grade": "A"}]
    rows = lambda ids, at: [{"id": i, "sources": src, "verified_at": at, "licence": "MIT",  # noqa: E731
                             "github": f"https://github.com/x/{i}"} for i in ids]
    (c / "index" / "fresh.json").write_text(json.dumps({"rows": rows(["a", "b"], "2026-11-01")}), encoding="utf-8")
    (c / "index" / "stale.json").write_text(json.dumps({"rows": rows(["c"], "2026-07-01")}), encoding="utf-8")
    (c / "index" / "unsourced.json").write_text(json.dumps({"rows": [{"id": "d", "sources": [{"url": "http://x"}],
                                                                       "verified_at": "2026-11-01"}]}), encoding="utf-8")
    (c / "index" / "nopage.json").write_text(json.dumps({"rows": rows(["e"], "2026-11-01")}), encoding="utf-8")
    (c / "index" / "_indexes.json").write_text(json.dumps({"fresh": {}, "stale": {}, "unsourced": {}}), encoding="utf-8")
    (c / "index" / "open-source-business-apps.json").write_text(
        json.dumps({"rows": rows(["n8n", "plane"], "2026-11-01") + [{"id": "thin", "sources": src,
                                                                      "verified_at": "2026-11-01"}]}), encoding="utf-8")
    (c / "assignments.yaml").write_text("""flagship:
  - { slug: n8n, plane: DGO-692, title: "n8n" }
  - { slug: plane, plane: DGO-693, title: "Plane" }
projects:
  automation: { he: "אוטומציה", category: automation, slugs: [ n8n, thin, gone ] }
pieces:
  - { type: report, slug: done, plane: DGO-1, title: "done" }
""", encoding="utf-8")
    (c / "report").mkdir()
    (c / "report" / "done.he.md").write_text("---\ntype: report\nslug: done\ntitle: d\nupdated: 2026-11-01\n---\n# d\n\n"
                                             + "מילה " * 1200 + "\n", encoding="utf-8")
    (r / "ai" / "seo").mkdir(parents=True)
    (r / "ai" / "seo" / "map.yaml").write_text("checked: 2026-11-01\nsource: https://example.org/x\n", encoding="utf-8")
    (r / "ai" / "seo" / "old.yaml").write_text("checked: 2026-01-01\nsource: https://example.org/x\n", encoding="utf-8")
    (r / "ai" / "seo" / "nosource.yaml").write_text("checked: 2026-11-01\n", encoding="utf-8")
    return r


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = layer_gate.main(argv)
    return rc, out.getvalue()


def checks() -> None:
    r = repo()
    layer_gate.LAYER1 = [
        ("k1", "R-1", "fresh", "index", "fresh"), ("k2", "R-2", "stale", "index", "stale"),
        ("k3", "R-3", "unsourced", "index", "unsourced"), ("k4", "R-4", "nopage", "index", "nopage"),
        ("k5", "R-5", "missing", "index", "missing"), ("k6", "R-6", "map", "file", "ai/seo/map.yaml"),
        ("k7", "R-7", "old", "file", "ai/seo/old.yaml"), ("k8", "R-8", "nosource", "file", "ai/seo/nosource.yaml"),
        ("k9", "R-9", "flagship", "projects", "flagship"), ("k10", "R-10", "projects", "projects", "projects")]
    rc, out = run(["--layer", "1", "--repo", str(r), "--today", "2026-11-10", "--json"])
    doc = json.loads(out)
    by = {i["key"]: i for i in doc["items"]}
    check(rc == 1 and not doc["perfect"] and doc["passed"] == 3, f"3 of 10 pass, the layer is not perfect: {doc['passed']}")
    check(by["k1"]["ok"] and by["k6"]["ok"] and by["k9"]["ok"], "a fresh sourced list with a page, a dated sourced file, "
          "and projects that all have facts rows pass")
    check("91" in " ".join(by["k2"]["gaps"]), f"a list not checked within 91 days: {by['k2']['gaps']}")
    check("https" in " ".join(by["k3"]["gaps"]), f"a row without an https source: {by['k3']['gaps']}")
    check("_indexes.json" in " ".join(by["k4"]["gaps"]), f"a list with no page on the site: {by['k4']['gaps']}")
    check("index/missing.json" in " ".join(by["k5"]["gaps"]), f"a missing list is named: {by['k5']['gaps']}")
    check("2026-01-01" in " ".join(by["k7"]["gaps"]) and "https" in " ".join(by["k8"]["gaps"]),
          f"a stale file, a file with no source: {by['k7']['gaps']} {by['k8']['gaps']}")
    gaps10 = " ".join(by["k10"]["gaps"])
    check("1 מתוך 3" in gaps10 and "gone" in gaps10 and "thin" in gaps10,
          f"a project with no facts row, and one with no licence or repository: {gaps10}")
    rc, text = run(["--layer", "1", "--repo", str(r), "--today", "2026-11-10"])
    check("עוד לא (3 מתוך 10)" in text and "✓ k1" in text, f"the plain report: {text[:200]}")

    (r / "apps/digital-assets/content/assignments.yaml").write_text(        # layer 2 judges every planned piece:
        "pieces:\n  - { type: report, slug: done, plane: DGO-1, title: done }\n", encoding="utf-8")  # here, one
    rc2, out2 = run(["--layer", "2", "--repo", str(r), "--today", "2026-11-10", "--json"])
    doc2 = json.loads(out2)
    check(rc2 == 0 and doc2["perfect"] and doc2["passed"] == 1, f"a written piece that passes the check: {doc2}")
    rc3, out3 = run(["--layer", "3", "--repo", str(r), "--today", "2026-11-10", "--json"])
    check(rc3 == 0 and json.loads(out3)["perfect"], "layer 3 opens when layer 2 has passed")
    (r / "apps/digital-assets/content/report/done.he.md").write_text("---\ntitle: d\nupdated: 2026-11-01\n---\n# d\n\n"
                                                                     "קצר, 49 ₪.\n", encoding="utf-8")
    rc2, out2 = run(["--layer", "2", "--repo", str(r), "--today", "2026-11-10", "--json"])
    gaps = json.loads(out2)["items"][0]["gaps"]
    check(rc2 == 1 and any("short" in g for g in gaps) and any("מחירים בלי שנה" in g for g in gaps),
          f"a short piece with an undated price fails layer 2: {gaps}")
    rc3, out3 = run(["--layer", "3", "--repo", str(r), "--today", "2026-11-10", "--json"])
    check(rc3 == 1 and "סגורה" in out3, f"…and layer 3 is closed: {out3[:200]}")


def main() -> int:
    try:
        checks()
    except Exception:                                     # noqa: BLE001 — a crash is a failure, said as one
        FAIL.append("the check itself raised: " + traceback.format_exc(limit=4))
    for f in FAIL:
        print("FAIL:", f)
    print(f"test_layer_gate: {'OK' if not FAIL else f'{len(FAIL)} failure(s)'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
