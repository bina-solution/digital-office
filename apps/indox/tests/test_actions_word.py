#!/usr/bin/env python3
"""test_actions_word — INDOX's screens say «פעולות», never «שיגורים» (DGO-256).

    python3 apps/indox/tests/test_actions_word.py      (the repo only; no office, no docker)

THE OWNER (2026-09-03), on the document page's «שיגורים אחרונים»: «שיגורים אחרונים תחליף את המונח שיגורים
ב פעולות». On 2026-11-10 the term was still on five screens, 40 times: the document page, the action log,
the pipeline bar, the documents table and the settings. It was replaced by hand, because Hebrew agreement
changes with it: «שיגור אחד פתוח» became «פעולה אחת פתוחה». This test keeps it from coming back.

WHAT IS READ: everything INDOX shows or says. That is the webapp's source (apps/indox/app/webapp/src), the
BFF's Python (apps/indox/app/**/*.py, whose errors reach the screen), and the n8n blueprints, whose messages
reach the action log. Comments included: a comment that quotes the word is how it gets copied back.

THE WORD, in every form it took: the noun שיגור / שיגורים / שיגורי, and the verb, including the bare
imperative on a button («שגר · 12 מסמכים»): שגר / שוגר / ששוגרה / משוגרת / שוגרו / שיגר / לשגר / משגר /
ישגר / נשגר. «שגרה» (routine) is a different word: «לשגרה», «משגרה», «לשגרת» and «שגרתי» are not matched.
(The pattern is the second reader's, checked against both lists and against the tree.)
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORD = re.compile(r"שיגור|שוגר|שיגר|לשגר(?![הת])|משגר(?!ה)|(?<![א-ת])[וה]?[אינת]?שגר(?:ו|נו)?(?![א-ת])")
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def sources():
    """(screens, BFF, blueprints): read separately, so a folder that moves cannot hide behind the others."""
    app = ROOT / "apps" / "indox" / "app"
    web = [p for p in (app / "webapp" / "src").rglob("*") if p.suffix in (".ts", ".tsx", ".js", ".jsx", ".css", ".html")]
    py = [p for p in app.rglob("*.py") if "node_modules" not in p.parts]
    bp = sorted((ROOT / "apps" / "indox" / "blueprint" / "n8n").glob("*.workflow.ts"))
    return web, py, bp


def hits(text):
    return [(text.count("\n", 0, m.start()) + 1, m.group(0)) for m in WORD.finditer(text)]


def main():
    web, py, bp = sources()
    check(len(web) >= 20 and len(py) >= 1 and len(bp) >= 1,
          f"read {len(web)} screen, {len(py)} BFF and {len(bp)} blueprint file(s), each source on its own "
          f"(an empty read checks nothing)")
    files = web + py + bp
    found = []
    for p in files:
        for line, w in hits(p.read_text(encoding="utf-8", errors="replace")):
            found.append(f"{p.relative_to(ROOT)}:{line}  «{w}»")
    check(not found, "no INDOX screen, BFF message or workflow says «שיגורים»; the owner's word is «פעולות»"
          + "".join(f"\n        {f}" for f in found[:40]))

    # The scanner must catch every form the screens used, and leave «שגרה» alone.
    for s in ("שיגורים אחרונים", "שיגור אחד פתוח", "יומן השיגורים", "פעולה ששוגרה", "פעולה לא משוגרת",
              "שוגרו 5 מסמכים", "שיגורי פעולות", "שגר · 5 מסמכים", 'confirmLabel="שגר"', "הראוטר ישגר"):
        check(bool(hits(s)), f"self-check: catches «{s}»")
    for s in ("פעולות אחרונות", "שגרה יומית", "שגרתי", "יומן הפעולות", "חזרה לשגרה", "יציאה משגרה", "לשגרת העבודה"):
        check(not hits(s), f"self-check: does not flag «{s}»")

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
