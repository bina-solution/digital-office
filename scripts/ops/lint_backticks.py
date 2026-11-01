#!/usr/bin/env python3
"""Reject unescaped backticks inside a .workflow.ts jsCode/query template literal.

WHY THIS EXISTS
---------------
`jsCode:` and `query:` node parameters are TypeScript template literals. A backtick written
inside one -- even inside a // comment, even inside prose -- CLOSES the literal. The n8n-as-code
transformer then compiles the truncated prefix, `bbox n8n push` reports `ok update+activate`,
and the live node silently loses everything after that character.

Measured 2026-08-23: the phrase "skipped at the `continue` below" in a comment in
indoxV2ActionsGlobal01 'Adjudicate Merge' cut a 12KB node down to 2,269 characters, ending
mid-sentence with no `return`. Every action_merge_doubles dispatch then died with
"Code doesn't return items properly" -- the merge path was fully down and the push had said ok.

Escape them as \\` or, better, drop them from prose.

Exit 1 if any risky backtick is found. Run before every push.
"""
import glob
import io
import os
import re
import sys

DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "apps", "indox", "blueprint", "n8n")

OPENERS = re.compile(r"(?:jsCode|query)\s*:\s*`")


def literal_spans(text):
    """Yield (start, end) character offsets of every jsCode/query template literal body.

    Walks the body honouring backslash escapes, so an escaped \\` does not end the span --
    which is exactly the distinction the transformer makes.
    """
    for m in OPENERS.finditer(text):
        i = start = m.end()
        while i < len(text):
            c = text[i]
            if c == "\\":
                i += 2
                continue
            if c == "`":
                break
            i += 1
        yield start, i


def scan(path):
    """Find literals whose walk stopped on a backtick that cannot be the real close.

    Position alone cannot tell a truncating backtick from a legitimate one -- the walk stops at
    the FIRST unescaped backtick either way, which is precisely why the bug is invisible. What
    separates them is what FOLLOWS: a parameter's closing backtick is followed by `,` `}` or `)`
    (the object literal continues); a backtick in prose is followed by more prose.
    """
    text = io.open(path, encoding="utf-8").read()
    lines = text.split("\n")
    line_of = []
    ln = 1
    for ch in text:
        line_of.append(ln)
        if ch == "\n":
            ln += 1
    line_of.append(ln)

    findings = []
    for _, end in literal_spans(text):
        if end >= len(text):
            findings.append((line_of[min(end, len(text) - 1)], "<unterminated literal>"))
            continue
        j = end + 1
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j < len(text) and text[j] in ",})":
            continue                      # legitimate close
        n = line_of[end]
        findings.append((n, lines[n - 1].strip()[:100]))
    return findings


def main(argv):
    targets = argv[1:] or sorted(glob.glob(os.path.join(DEFAULT_DIR, "*.workflow.ts")))
    bad = 0
    for path in targets:
        for line, src in scan(path):
            print("  %s:%d: unescaped backtick inside a jsCode/query literal\n      %s"
                  % (os.path.basename(path), line, src))
            bad += 1
    if bad:
        print("  FAIL: %d unescaped backtick(s). Each one TRUNCATES the live node at that "
              "character while push still reports ok." % bad)
        return 1
    print("  ok: no unescaped backticks in %d file(s)" % len(targets))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
