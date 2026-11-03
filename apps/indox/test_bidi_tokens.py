#!/usr/bin/env python3
"""test_bidi_tokens — a Latin token inside a Hebrew sentence keeps its own edges.

    python3 apps/indox/test_bidi_tokens.py [--out <dir>]

DGO-534. The owner's scan found four sentences where a Latin token's EDGE — the `*` of «q_v3_*», the
parentheses of «(documentDraw)» — was drawn on the wrong side of it. Hebrew runs right to left, the
token runs left to right, and a neutral character at the seam (`*`, `/`, a bracket) takes the
direction of the sentence around it instead of the token's: «q_v3_*» reaches the reader as «*q_v3_».

TWO CHECKS, AND THE SECOND IS THE ONE THAT MATTERS.
  1. SOURCE: every token this file knows about must sit inside `ltr(…)` in the app's own source. That
     is what catches the day somebody unwraps one while editing the sentence around it.
  2. RENDERED, in a real Chromium: the isolated token's edge is drawn at the token's END — measured as
     the x of the mark against the x of the token's first letter — and the SAME sentence without the
     isolate is measured too, so the run shows the defect it is about rather than asserting a fix
     against nothing.

Guarded: no playwright here means "not run" and exit 0, the way this office's other browser checks
behave. Exit 1 only when a sentence is unwrapped or the rendered edge is wrong.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                     # pragma: no cover - host without it
    print("not run: no playwright here (the ui-capture image has it)")
    sys.exit(0)

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "app" / "webapp" / "src"
LRI, PDI = "\u2066", "\u2069"

#: (file, the token, the sentence it lives in as the app writes it now). The sentence is read out of
#: the source below; this table is the list of places the rule applies to.
CASES = [
    ("pages/ExtractionDocPage.tsx", "q_v3_*", "עריכת השאילתות נעשית בטבלת settings (מפתחות {tok}) — ללא שינוי בתהליכים."),
    ("pages/ExtractionPage.tsx", "q_v3_*", "קריאת apitools אחת לכל ערך; השאילתות נטענות מההגדרות ({tok})."),
    ("components/DocumentStage.tsx", "(documentDraw)", "לא הופק סימון חילוץ {tok} למסמך זה — זו תצוגה מקדימה של הקובץ בלבד."),
    ("components/DocumentStage.tsx", "(/documentDraw)", "הסימון מצויר על ידי apitools עצמו {tok}: עוגן ירוק, ערך כחול."),
]


def source_has_token_wrapped(rel: str, token: str) -> bool:
    """Is this token inside an `ltr(…)` call in the file as it stands?"""
    text = (SRC / rel).read_text(encoding="utf-8")
    if f"ltr('{token}')" in text:
        return True
    return f"{LRI}{token}{PDI}" in text          # an isolate written out by hand counts too


PAGE = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>body{{margin:0;padding:18px;font:15px/1.7 system-ui,sans-serif}}
div.s{{margin:0 0 10px}}</style></head><body>
{sentences}
</body></html>"""

#: for one sentence: the x of the token's first letter against the x of the character that must sit at
#: its far edge. `idx` is computed in the page, so nothing here has to know where the token starts.
PROBE = """(sel) => {
  const el = document.querySelector(sel);
  const text = el.firstChild.nodeValue;
  const rectOf = (i) => { const r = document.createRange(); r.setStart(el.firstChild, i);
                          r.setEnd(el.firstChild, i + 1); return r.getBoundingClientRect(); };
  const out = [];
  for (let i = 0; i < text.length; i++) out.push([text[i], Math.round(rectOf(i).left)]);
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("BIDI_OUT", "/tmp/indox-bidi"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    bad = 0
    print("── source: every token is wrapped")
    for rel, token, _ in CASES:
        ok = source_has_token_wrapped(rel, token)
        print(f"   [{'ok ' if ok else 'FAIL'}] {rel}  «{token}»")
        bad += 0 if ok else 1

    # each case renders twice: as the app writes it now (isolated), and without the isolate
    rows = []
    plain = []
    for n, (rel, token, sentence) in enumerate(CASES):
        rows.append(f'<div class="s" id="iso{n}">{sentence.format(tok=LRI + token + PDI)}</div>')
        plain.append(f'<div class="s" id="raw{n}">{sentence.format(tok=token)}</div>')
    page = out / "bidi.html"
    page.write_text(PAGE.format(sentences="\n".join(rows) + "\n<hr>\n" + "\n".join(plain)),
                    encoding="utf-8")

    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("BIDI_CHROME", "/usr/bin/chromium"),
                               args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_page(viewport={"width": 900, "height": 600})
        pg.goto(page.as_uri(), wait_until="load", timeout=30000)
        print("\n── rendered: where the edge lands")
        for n, (rel, token, _) in enumerate(CASES):
            for arm, sel in (("isolated", f"#iso{n}"), ("bare", f"#raw{n}")):
                chars = pg.evaluate(PROBE, sel)
                text = "".join(c for c, _ in chars)
                first = text.index(token[0])                      # the token's first letter
                edge_ch = token[-1] if token[-1] != ")" else ")"
                # the LAST character of the token on the line, by index in the isolated/bare text
                start = text.index(token) if token in text else None
                if start is None:                                 # the isolate split it: find the run
                    start = first
                x_first = chars[first][1]
                x_edge = chars[start + len(token) - 1][1]
                edge_at_end = x_edge > x_first
                tag = "ok  " if edge_at_end else "FAIL"
                if arm == "isolated" and not edge_at_end:
                    bad += 1
                print(f"   [{tag}] {arm:8} {rel.split('/')[-1]:24} «{token}»  first x={x_first}"
                      f"  edge({edge_ch!r}) x={x_edge}  → {'edge at the end' if edge_at_end else 'edge on the WRONG side'}")
        pg.screenshot(path=str(out / "bidi.png"))
        b.close()

    print(f"\n{'FAIL' if bad else 'PASS'} — {len(CASES)} sentence(s); screenshots in {out}/bidi.png")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
