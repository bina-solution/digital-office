#!/usr/bin/env python3
"""Fail the build when the INDOX document view sizes itself from the VIEWPORT.

WHY THIS EXISTS. The document view shipped with `max-height:76vh` on its image pane and
`height:74vh` on its PDF frame. Inside the console those numbers are 76% and 74% of the
IFRAME, and they excluded the tab strip, the caption and the card's own padding — so the card
was taller than the region holding it, the page grew a second scrollbar behind the pane's own,
and on a shorter window the caption fell off the bottom entirely. Measured on the live console
2026-09-02: a 663px card inside a 665px scroll region at 1917x1078, and worse at every smaller
size.

THE RULE IT ENFORCES. The shell owns the viewport; everything below it takes the height it is
given. `.app-shell` is the ONE place a viewport unit is correct, and it is allowlisted by name.
Anywhere else in the document view — the stage component, the document page, and every
`.doc-*` / `.stage-*` rule in the stylesheet — a viewport unit is the bug this file exists to
stop, so it is an error rather than a warning.

Deliberately NOT a repo-wide ban. Other screens (the aging-report line table, the instance
picker's list) legitimately cap their own height against the viewport and are none of this
gate's business; widening the net would only teach people to skip it. Those are reported as
notes and never fail.

Usage:  python3 scripts/ops/lint_viewport_units.py [--all]
Exit 1 on any violation inside the document view.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The report below is written with non-ASCII marks, and a Windows console on the ANSI codepage
# (cp1255 on a Hebrew install) raises UnicodeEncodeError on the first one — turning a gate that
# had something to say into a traceback. Same fix, same reason, as .claude/hooks/work-left.py.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / "apps" / "indox" / "app" / "webapp" / "src"

# A viewport unit as it appears in CSS or in a JS style object: a number immediately followed by
# vh/dvh/svh/lvh/vmin/vmax. `vw` is included for symmetry — a width taken from the viewport is
# the same mistake on its side.
UNIT_RE = re.compile(r"(?<![\w-])\d*\.?\d+\s*(vh|dvh|svh|lvh|vw|dvw|svw|lvw|vmin|vmax)(?![\w-])")

# Files in the document view where a viewport unit is always wrong.
BANNED_FILES = [
    Path("components/DocumentStage.tsx"),
    Path("pages/DocumentDetailPage.tsx"),
]

# In the stylesheet, only the document view's own rules are covered. A rule "belongs" to the
# document view when its selector names one of these prefixes.
CSS_FILE = Path("index.css")
CSS_SELECTOR_PREFIXES = (".doc-", ".stage")

# The one legitimate owner of the viewport, matched on the selector text.
CSS_ALLOWED_SELECTORS = (".app-shell",)


def css_rules(text: str):
    """Yield `(selector, body, line_of_selector)` for every top-level-ish rule in a stylesheet.

    A deliberately small parser: this file only needs to know which selector a declaration sits
    under, and CSS in this project is plain (no nesting). At-rules are walked into rather than
    skipped, so a rule inside `@media` or `@container` is still attributed to its selector.
    """
    line = 1
    i = 0
    n = len(text)
    while i < n:
        brace = text.find("{", i)
        if brace < 0:
            break
        selector_raw = text[i:brace]
        line += selector_raw.count("\n")
        selector = " ".join(selector_raw.split())
        # find the matching close brace
        depth = 1
        j = brace + 1
        while j < n and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[brace + 1: j - 1]
        if selector.startswith("@"):
            # an at-rule: its body holds real rules, so recurse into it and keep the line count
            for sel, bod, ln in css_rules(body):
                yield sel, bod, line + ln - 1
            line += body.count("\n") + 1
        else:
            yield selector, body, line
            line += body.count("\n") + 1
        i = j


def strip_comments(text: str) -> str:
    """Blank out /* … */ so a viewport unit QUOTED IN A COMMENT is not a violation.

    Every one of these files explains the bug it is avoiding, and those explanations name the
    units. A linter that fails on its own rationale would be deleted within the week. Newlines
    are preserved so reported line numbers stay true.
    """
    out = []
    i = 0
    while i < len(text):
        start = text.find("/*", i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])
        end = text.find("*/", start + 2)
        if end < 0:
            out.append("\n" * text.count("\n", start))
            break
        out.append("\n" * text.count("\n", start, end))
        i = end + 2
    return "".join(out)


def strip_line_comments(text: str) -> str:
    """Same, for `//` comments in TS/TSX (kept crude on purpose — no string parsing)."""
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in text.splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true",
                    help="also list viewport units elsewhere in the webapp (never fails)")
    args = ap.parse_args()

    violations: list[str] = []
    notes: list[str] = []

    for rel in BANNED_FILES:
        path = WEBAPP / rel
        if not path.exists():
            violations.append(f"{rel}: MISSING — this gate names a file that no longer exists; "
                              f"update BANNED_FILES or restore the file")
            continue
        src = strip_line_comments(strip_comments(path.read_text(encoding="utf-8")))
        for i, ln in enumerate(src.splitlines(), 1):
            m = UNIT_RE.search(ln)
            if m:
                violations.append(f"{rel}:{i}: `{m.group(0).strip()}` — the container gives the "
                                  f"height here; only .app-shell may read the viewport")

    css_path = WEBAPP / CSS_FILE
    if css_path.exists():
        raw = css_path.read_text(encoding="utf-8")
        clean = strip_comments(raw)
        for selector, body, line in css_rules(clean):
            if any(a in selector for a in CSS_ALLOWED_SELECTORS):
                continue
            owned = any(p in selector for p in CSS_SELECTOR_PREFIXES)
            for off, ln in enumerate(body.splitlines()):
                m = UNIT_RE.search(ln)
                if not m:
                    continue
                where = f"{CSS_FILE}:{line + off}: `{selector}` uses `{m.group(0).strip()}`"
                if owned:
                    violations.append(where + " — the document view takes the height it is given")
                elif args.all:
                    notes.append(where)

    if notes:
        print("viewport units elsewhere in the webapp (not covered by this gate):")
        for n in notes:
            print(f"  · {n}")
        print()

    if violations:
        print("FAIL — the document view is sizing itself from the viewport:")
        for v in violations:
            print(f"  ✗ {v}")
        print("\nThe shell owns the viewport (.app-shell). Below it, height flows down the flex\n"
              "chain: .wrap → .page-fill → .doc-split → .doc-stagecol → .stage. A component that\n"
              "names a viewport unit is measuring the wrong box — inside the console iframe it is\n"
              "not even the window. See components/DocumentStage.tsx for the whole argument.")
        return 1

    print("OK — the INDOX document view names no viewport units "
          f"({len(BANNED_FILES)} files + the .doc-*/.stage rules in {CSS_FILE}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
