"""The AEO panel's report (DGO-1399, DGO-1404): one run of the fixed 40 prompts → the scorecard and the dated page.
What is counted is whether an answer NAMES us; a row a person checked overrides the engine's text, and an answer
about another entity that shares our Hebrew name is a collision, listed, not counted. Runs on synthetic rows and
the real prompts.json / checks.json, writing only to a temporary directory.

    python3 apps/digital-assets/tests/test_aeo_report.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
AEO = HERE / "aeo"
FAIL: list = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


def main() -> int:
    panel = json.loads((AEO / "prompts.json").read_text(encoding="utf-8"))
    ids = [p["id"] for p in panel["prompts"]]
    kinds = {p["kind"] for p in panel["prompts"]}
    check(len(ids) == 40 and len(set(ids)) == 40, f"the panel is 40 fixed prompts with unique ids ({len(ids)})")
    check({"category", "problem", "comparison", "brand", "local"} <= kinds, f"the panel's kinds are all present ({sorted(kinds)})")
    checks = json.loads((AEO / "checks.json").read_text(encoding="utf-8"))
    check(all(k.split(":", 1)[1] in ids and "why" in v and v.get("date") and v.get("run") for k, v in checks.items()),
          "every person-checked row names a prompt of the panel, the date and run it read, and why")
    source = (AEO / "aeo_report.py").read_text(encoding="utf-8")
    check(not re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![0-9a-fA-F])", source),
          "the report names no colour of its own — the page takes the office's palette (G82)")

    brand = next(p["id"] for p in panel["prompts"] if p["kind"] == "brand")
    other = next(p["id"] for p in panel["prompts"] if p["kind"] != "brand")
    rows = [
        {"id": other, "kind": "category", "engine": "chatgpt", "run": 1, "at": "2026-11-05T10:00:00Z",
         "result": {"named": True, "alts": ["Nextcloud", "Zoho"], "sources": ["Reddit"], "domains": ["example.org"]}},
        {"id": brand, "kind": "brand", "engine": "chatgpt", "run": 1, "at": "2026-11-05T10:01:00Z",
         "result": {"named": True, "alts": [], "sources": [], "domains": []}},
        {"id": other, "kind": "category", "engine": "google-aio", "run": 1, "at": "2026-11-05T10:02:00Z",
         "result": {"named": True, "alts": [], "sources": [], "domains": []}},
        {"id": brand, "kind": "brand", "engine": "google-aio", "run": 1, "at": "2026-11-05T10:03:00Z",
         "result": {"blocked": True}},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run1.jsonl"
        run.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        own = Path(tmp) / "checks.json"   # a person checked google-aio's run-1 answer: it was about someone else
        own.write_text(json.dumps({f"google-aio:{other}": {"date": "2026-11-05", "run": 1, "named": False,
                                                          "collision": True, "why": "another entity"}}),
                       encoding="utf-8")
        out = Path(tmp) / "out"
        done = subprocess.run([sys.executable, str(AEO / "aeo_report.py"), "--date", "2026-11-05", "--out", str(out),
                               "--checks", str(own), str(run)], capture_output=True, text=True)
        check(done.returncode == 0, f"the report runs (exit {done.returncode}) {done.stderr[-200:]}")
        card = json.loads((out / "aeo-2026-11-05.json").read_text(encoding="utf-8"))
        page = (out / "aeo-2026-11-05.html").read_text(encoding="utf-8")
        g, c = card["engines"]["google-aio"], card["engines"]["chatgpt"]
        check(c["named"] == 2 and c["unbranded_named"] == 1 and c["unbranded"] == 1,
              "ChatGPT: named in both, once in an unbranded prompt")
        check(g["answered"] == 1 and g["rows"] == 2, "a blocked answer is not counted as answered")
        check(g["named"] == 0 and len(card["collisions"]) == 1,
              "a person's check overrides the engine's «named», and the collision is listed, not counted")
        check(dict(c["alternatives"]).get("Nextcloud") == 1 and dict(c["sources"]).get("reddit.com") == 1,
              "the alternatives named and the sites cited are counted (a known label → its site)")
        check('dir="rtl"' in page and "2026-11-05" in page, "the page is dated and right to left")
        check("var(--olive)" in page and "@bina-theme-tokens" in page, "the page carries the office's palette, read at render")
        check("Gemini" in page and "Claude" in page and "1 ריצה" in page,
              "the page says what THIS run measured: one run per engine here, and the engines it did not read")

        # three runs in a week: the person's check is of run 1 only, so runs 2 and 3 count as the engine answered
        week = Path(tmp) / "week.jsonl"
        week.write_text("".join(json.dumps(dict(rows[2], run=n)) + "\n" for n in (1, 2, 3)), encoding="utf-8")
        out3 = Path(tmp) / "out3"
        done = subprocess.run([sys.executable, str(AEO / "aeo_report.py"), "--date", "2026-11-05", "--out", str(out3),
                               "--checks", str(own), str(week)], capture_output=True, text=True)
        card3 = json.loads((out3 / "aeo-2026-11-05.json").read_text(encoding="utf-8"))
        check(done.returncode == 0 and card3["engines"]["google-aio"]["named"] == 2 and len(card3["collisions"]) == 1
              and card3["runs"]["google-aio"] == 3,
              "a check overrides only the run it read: 3 runs → named in 2, one collision, «3 ריצות»")
        out4 = Path(tmp) / "out4"
        subprocess.run([sys.executable, str(AEO / "aeo_report.py"), "--date", "2026-11-12", "--out", str(out4),
                        "--checks", str(own), str(run)], capture_output=True, text=True)
        card4 = json.loads((out4 / "aeo-2026-11-12.json").read_text(encoding="utf-8"))
        check(card4["engines"]["google-aio"]["named"] == 1 and not card4["collisions"],
              "next week's answer to the same prompt is a new answer: last week's check does not touch it")
    print(f"\n{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
