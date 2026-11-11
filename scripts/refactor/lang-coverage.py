#!/usr/bin/env python3
"""lang-coverage — how much of a UI's Hebrew is actually translatable.

    python3 scripts/refactor/lang-coverage.py [FILE ...] [--all]
    python3 scripts/refactor/lang-coverage.py --since HEAD          # every changed UI file

WHY THIS EXISTS

The office is bilingual through one runtime (`platform-base/bina-ui/bina-lang.js`, see
`ai/context/platform-language.md`): a static element carries `data-lang-he` / `data-lang-en`, and a
string built in JS goes through `L(he, en)`. Everything else stays Hebrew in an English office, and
NOTHING reports that — the screen simply reads as unfinished, which is the kind of silent failure
this repo writes gates for.

This is a REPORT, not a gate, and the difference is deliberate: several installed apps have thousands
of unwrapped Hebrew strings today, so a gate would be red on arrival and ignored. It answers the
question a person actually has — "did I miss one?" — per file, with the line numbers of what it could
not classify.

WHAT COUNTS AS COVERED

  · `L("…", "…")` — the call spans the run (paren-matched, so a nested `L(` inside is not miscounted);
  · `data-lang-he="…"` / `data-lang-en="…"` — an attribute value;
  · a COMMENT (a `//` line comment, a `/* … */` block, an HTML `<!-- … -->`) — prose for maintainers,
    deliberately not translated;
  · a string the file itself marks with `/* @i18n-ok */` on the same line or the line above, for a
    value that must stay Hebrew because the code COMPARES it or a server returns it. The marker is
    the point: an exception should be visible in the file, not in a list inside a tool.

WHAT IT DOES NOT DECIDE: whether a Chinese-room `L("טקסט", "טקסט")` is a good translation, and
whether a covered string is user-visible at all. It counts what a translator would have to look at.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HEB = re.compile(r"[\u0590-\u05FF]")
OK_MARKERS = ("@i18n-ok", "i18n-ok", "@lang-ok")

#: Directories that hold no UI a person reads: vendored bundles, build output, fixtures.
SKIP_DIRS = ("node_modules", "/vendor/", "/dist/", "/_archive/", "/attic/", "/legacy/",
             "/fixtures/", "/static/revo-grid/", "/tests/", "/__pycache__/")
UI_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".ejs", ".vue", ".svelte")


def spans_js(text: str):
    """(start, end, kind) spans of COMMENTS in a JS-ish text.

    Quote-aware AND regex-literal-aware, and both matter. A naive `line.split("//")` reports every URL
    as prose; the first version of this scanner skipped quotes but not regex literals, so the line
    `/[&<>"']/g` in apps/computers opened a string that never closed and every comment after it became
    invisible — the tool then reported the file's own docblocks as untranslated Hebrew. A regex
    literal can start only where a value may: after `= ( , : [ ! & | ? { } ;` or at a line's start.
    """
    out, i, n = [], 0, len(text)
    prev = ""
    while i < n:
        c = text[i]
        if c in "\"'`":
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == c:
                    break
                i += 1
            i += 1
            prev = c
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append((i, j, "comment"))
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((i, j, "comment"))
            i = j
        elif c == "/" and prev in ("", "=", "(", ",", ":", "[", "!", "&", "|", "?", "{", "}", ";"):
            i += 1                              # a REGEX LITERAL, to its closing unescaped `/`
            in_class = False
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "[":
                    in_class = True
                elif text[i] == "]":
                    in_class = False
                elif text[i] == "/" and not in_class:
                    break
                elif text[i] == "\n":
                    break                       # a regex cannot span a line: that was a division
                i += 1
            i += 1
            prev = "/"
        else:
            if not c.isspace():
                prev = c
            i += 1
    return out


#: HTML elements with no closing tag — their start tag is the whole element.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}


def element_spans(text: str):
    """Every element carrying `data-lang-he`/`data-lang-en`, from its start tag to its matching end tag.

    The pair covers the element's SOURCE TEXT too: that Hebrew is the fallback the runtime replaces,
    not an untranslated string, and a scanner that flagged it would report every correctly translated
    element in the platform as a miss.
    """
    out = []
    for m in re.finditer(r"<([a-zA-Z][\w:-]*)\b[^>]*\bdata-lang-(?:he|en)\s*=[^>]*>", text):
        tag = m.group(1).lower()
        if tag in VOID_TAGS or m.group(0).rstrip().endswith("/>"):
            out.append((m.start(), m.end()))
            continue
        depth, i = 1, m.end()
        pat = re.compile(r"</?" + re.escape(tag) + r"\b", re.I)
        while depth and i < len(text):
            mm = pat.search(text, i)
            if not mm:
                break
            depth += -1 if text[mm.start() + 1] == "/" else 1
            i = mm.end()
        out.append((m.start(), i))
    return out


def spans_html_comments(text: str):
    return [(m.start(), m.end(), "comment") for m in re.finditer(r"<!--.*?-->", text, re.S)]


def call_spans(text: str, name: str = "L"):
    """(start, end) of every `L(...)` call, by paren matching. A string containing `)` is handled
    because quotes are skipped; a call that never closes ends at the file's end and is REPORTED
    (a runaway `L(` is a broken file, not a translation)."""
    out, unclosed = [], 0
    for m in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"\s*\(", text):
        i, depth, n = m.end() - 1, 0, len(text)
        while i < n:
            c = text[i]
            if c in "\"'`":
                q, i = c, i + 1
                while i < n:
                    if text[i] == "\\":
                        i += 2
                        continue
                    if text[i] == q:
                        break
                    i += 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth == 0:
            out.append((m.start(), i + 1))
        else:
            unclosed += 1
    return out, unclosed


def attr_spans(text: str):
    return [(m.start(), m.end()) for m in re.finditer(r'data-lang-(?:he|en)\s*=\s*"[^"]*"', text)]


def inside(pos: int, spans) -> bool:
    for s, e in ((a, b) for a, b, *_ in spans):
        if s <= pos < e:
            return True
    return False


def analyse(path: pathlib.Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    comments = spans_js(text) if path.suffix != ".html" else []
    comments += spans_html_comments(text)
    # A .html file's inline <script> is JS: run the JS scanner over those regions only, and keep the
    # HTML comments separate. Two scanners on one file, each where it applies.
    if path.suffix in (".html", ".htm", ".ejs"):
        for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", text, re.S | re.I):
            base = m.start(1)
            comments += [(base + a, base + b, k) for a, b, k in spans_js(m.group(1))]
        # <style> is CSS, where the only comment form is /* … */. Scanned separately rather than with
        # the JS scanner: `//` in a CSS url() would be read as a line comment and swallow the rest of
        # the sheet — a comment span that runs to the end of the file makes every later string
        # "covered", which is the false NEGATIVE side of the same bug.
        for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", text, re.S | re.I):
            base = m.start(1)
            for c in re.finditer(r"/\*.*?\*/", m.group(1), re.S):
                comments.append((base + c.start(), base + c.end(), "comment"))
    # `tt` is the same contract as `L` for a file that must also load outside a browser (the pairing
    # screen's parser is require()d by a test under node, where `window.L` does not exist).
    covered = (call_spans(text)[0] + call_spans(text, "tt")[0]
               + [(a, b) for a, b in attr_spans(text)] + [(a, b) for a, b in element_spans(text)])
    ok_lines = {i for i, ln in enumerate(lines) if any(mk in ln for mk in OK_MARKERS)}
    ok_lines |= {i - 1 for i in ok_lines}          # the marker may sit on the line above

    # A PAGE THAT CARRIES PAIRS BUT NOT THE RUNTIME is fully Hebrew, and this tool counted it as
    # covered: `data-lang-*` attributes are inert until `bina-lang.js` runs, and the JS's `L(...)`
    # throws with no `window.L`. It shipped that way for `sites` and `domains` (found on the live
    # server, 2026-10-11 — the pages rendered, the apps threw). So the runtime is part of the
    # evidence: markup with pairs and no script tag is reported, not passed.
    runtime_missing = bool(re.search(r"data-lang-(?:he|en)\s*=", text)) and \
        "bina-lang" not in text and path.suffix in (".html", ".htm", ".ejs")

    missed = []
    for ln, line in enumerate(lines):
        if ln in ok_lines:
            continue
        for run in HEB.finditer(line):
            pos = sum(len(x) + 1 for x in lines[:ln]) + run.start()
            if inside(pos, comments) or inside(pos, covered):
                continue
            missed.append((ln + 1, line.strip()[:110]))
            break                                   # one report per line is enough to act on
    return len(HEB.findall(text)), missed, call_spans(text)[1], runtime_missing


def targets(argv):
    files = [a for a in argv if not a.startswith("--")]
    if "--since" in argv:
        ref = argv[argv.index("--since") + 1]
        out = subprocess.run(["git", "diff", "--name-only", ref], cwd=ROOT,
                             capture_output=True, text=True).stdout
        files += [f.strip() for f in out.splitlines() if f.strip()]
    if "--all" in argv:
        files += [str(p.relative_to(ROOT)) for p in (ROOT / "apps").rglob("*")]
        files += [str(p.relative_to(ROOT)) for p in (ROOT / "platform-base").rglob("*")]
    seen, out = set(), []
    for f in files:
        p = (ROOT / f) if not pathlib.Path(f).is_absolute() else pathlib.Path(f)
        rel = str(p)
        if rel in seen or not p.is_file() or p.suffix not in UI_SUFFIXES:
            continue
        if any(s in f"/{rel}" for s in SKIP_DIRS):
            continue
        seen.add(rel)
        out.append(p)
    return sorted(out)


def main() -> int:
    # it prints Hebrew: a host whose default output encoding is not UTF-8 (cp1252 on Windows) must not kill
    # the report on its own first line (G10)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    files = targets(sys.argv[1:])
    if not files:
        print("lang-coverage: no UI files to scan (pass paths, --all, or --since <ref>)")
        return 0
    total_missed = total_runs = 0
    print(f"{'file':<58} {'hebrew':>7} {'uncovered':>10}")
    for p in files:
        runs, missed, unclosed, runtime_missing = analyse(p)
        total_runs += runs
        total_missed += len(missed)
        rel = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)
        flag = "" if not missed else "  <-- "
        print(f"{rel:<58} {runs:>7} {len(missed):>10}{flag}")
        for ln, txt in missed[:12]:
            print(f"      {rel}:{ln}  {txt}")
        if len(missed) > 12:
            print(f"      … and {len(missed) - 12} more line(s)")
        if unclosed:
            print(f"      WARNING: {unclosed} `L(` call(s) never close — the file is broken, "
                  f"not merely untranslated")
        # analyse() decides it (a page with pairs and no runtime); the EXW branch's tip computed it there but
        # never returned it, and read it here unbound, so every run died with NameError (the G80 shape).
        if runtime_missing:
            print("      WARNING: this page carries data-lang pairs but never loads bina-lang.js — "
                  "the pairs are inert and every L(...) in its JS throws.")
            total_missed += 1
    print(f"\n{len(files)} file(s) · {total_runs} Hebrew character(s) · "
          f"{total_missed} line(s) with untranslated, non-comment Hebrew")
    print("JUDGEMENT CALLS the tool cannot make: a value the code compares or sends to a server is "
          "correctly Hebrew — mark it `/* @i18n-ok */` and it stops being reported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
