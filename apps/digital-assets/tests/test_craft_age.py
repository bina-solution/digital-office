"""CRAFT.md's dates are read (DGO-1395): craft_age.py names the rules due for a re-check, and the content-angles
gate (DGO-1396) holds an idea while a rule of its format is due. Runs on scratch CRAFT files and ideas, and on
the real CRAFT.md (which must parse and carry at least one rule of every section the gate reads).

    python3 apps/digital-assets/tests/test_craft_age.py
"""
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE / "content"))
import craft_age  # noqa: E402

_spec = importlib.util.spec_from_file_location("gate", REPO / ".claude/skills/content-angles/scripts/gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

FAIL: list = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAIL.append(what)


CRAFT = """# CRAFT
| id | rule | source | source date | checked |
|---|---|---|---|---|
| V1 | Hook in the first second. | https://example.test/a | 2026-01-01 | 2026-11-05 |
| V2 | Captions on. | https://example.test/b | 2025-01-01 | 2026-01-02 |
| W1 | Answer first. | https://example.test/c | 2026-01-01 | 2026-11-05 (secondary) |
| H1 | A Hebrew voice. | https://example.test/d | 2026-01-01 | — |
"""

IDEA = {"id": "i1", "title": "t", "format": ["reel"], "claim": "a claim",
        "ours": {"kind": "measurement", "status": "have", "evidence": "measured 2026-11-05"},
        "hooks": ["one hook here", "a second hook", "a third hook"],
        "sources": [{"url": "https://a.example.test/x", "primary": True},
                    {"url": "https://b.example.test/y", "primary": True}],
        "top_results": {"query": "q", "what_they_say": "w", "our_difference": "d"}}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        craft = Path(tmp) / "CRAFT.md"
        craft.write_text(CRAFT, encoding="utf-8")
        today = dt.date(2026, 11, 10)
        check([r[0] for r in craft_age.rules(craft)] == ["V1", "V2", "W1", "H1"], "rules() reads every rule row, in order")
        check(craft_age.due_ids(today, 6, craft) == {"V2", "H1"},
              "due: checked over 6 months ago (V2) or never (H1); a weak source is not due by itself (W1)")
        check(craft_age.due_ids(dt.date(2027, 6, 1), 6, craft) == {"V1", "V2", "W1", "H1"}, "every rule is due a year on")

    # the gate holds an idea while a rule of ITS format is due, and names the rules
    check(gate.judge(IDEA)["verdict"] == "PASS", "a complete idea passes when no rule is due")
    held = gate.judge(IDEA, frozenset({"V2", "H1"}))
    check(held["verdict"] == "HOLD" and any("V2" in h and "H1" in h for h in held["hold"]),
          "a reel is held while a V or H rule is due, naming them")
    check(gate.judge(IDEA, frozenset({"W1"}))["verdict"] == "PASS", "a reel is not held by a written-format (W) rule")
    check(gate.judge(dict(IDEA, format=["article"]), frozenset({"W1"}))["verdict"] == "HOLD",
          "an article is held by a due W rule")
    check(gate.judge(dict(IDEA, format=["long-video"]), frozenset({"V13"}))["verdict"] == "HOLD",
          "a long video is held by a due V rule (V10–V13, V16 cover YouTube by their own text)")
    check(gate.judge(dict(IDEA, format=["carousel"]), frozenset({"V4"}))["verdict"] == "HOLD",
          "a carousel is held by a due V rule (V4/V5 cover Instagram carousels)")
    check(gate.judge(dict(IDEA, format=["article"]), frozenset({"A1"}))["verdict"] == "HOLD",
          "an article is held by a due A rule (being cited by the AI engines)")

    # «the only ones» stands only on its own written search, not on the our_difference every idea has
    only = dict(IDEA, claim="אנחנו היחידים שמפרסמים את העלות של כל פעולה")
    check(any("only ones" in f for f in gate.judge(only)["fail"]),
          "«the only ones» is rejected when nothing records the search that shows it")
    searched = dict(only, top_results=dict(IDEA["top_results"], only_ones_searched="searched X: none publish it"))
    check(not any("only ones" in f for f in gate.judge(searched)["fail"]),
          "«the only ones» stands when top_results.only_ones_searched records that search")

    # main reads the real CRAFT.md through craft_age (exit 0), and refuses when it cannot (exit 2)
    newest = max(dt.date.fromisoformat(m.group(1)) for _r, _t, c in craft_age.rules()
                 if (m := craft_age.DATE.search(c)))
    later = (newest + dt.timedelta(days=240)).isoformat()      # every rule past its 6-month re-check, whenever it ran
    with tempfile.TemporaryDirectory() as tmp:
        ideas = Path(tmp) / "ideas.json"
        ideas.write_text(json.dumps({"ideas": [IDEA]}), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            rc = gate.main([str(ideas), "--today", newest.isoformat()])
        card = json.loads(ideas.with_suffix(".gate.json").read_text(encoding="utf-8"))
        check(rc == 0 and card["pass"] == 1, "main judges with the real CRAFT.md read for the day")
        with redirect_stdout(io.StringIO()):
            gate.main([str(ideas), "--today", later])
        card = json.loads(ideas.with_suffix(".gate.json").read_text(encoding="utf-8"))
        check(card["hold"] == 1, f"the same idea is held once the real CRAFT.md's reel rules are past their re-check ({later})")

        def refused(**patch) -> int:
            saved = {k: getattr(gate, k) for k in patch}
            for k, v in patch.items():
                setattr(gate, k, v)
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return gate.main([str(ideas)])
            finally:
                for k, v in saved.items():
                    setattr(gate, k, v)
        empty = Path(tmp) / "empty.md"
        empty.write_text("# CRAFT\n\nno rules here\n", encoding="utf-8")
        partial = Path(tmp) / "partial.md"
        partial.write_text(CRAFT, encoding="utf-8")                     # V, W and H, but no Y and no A
        check(refused(CRAFT_MD=Path(tmp) / "missing.md") == 2, "the gate refuses (exit 2) when CRAFT.md is missing")
        check(refused(CRAFT_MD=empty) == 2, "…and when CRAFT.md holds no rule rows (an empty or reformatted rulebook)")
        check(refused(CRAFT_MD=partial) == 2, "…and when a section a format follows has no rule (Y, A here)")
        check(refused(CRAFT_AGE=Path(tmp) / "missing" / "craft_age.py") == 2, "…and when craft_age.py cannot be loaded")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            bad = gate.main([str(ideas), "--today", "2026-13-01"]), gate.main([str(ideas), "--today"])
        check(bad == (2, 2), "a bad or missing --today is a usage error (exit 2), not a traceback")

    real = {r[0][0] for r in craft_age.rules()}
    check({"V", "Y", "W", "H"} <= real, f"the real CRAFT.md carries the sections the gate reads (has {sorted(real)})")
    print(f"\n{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
