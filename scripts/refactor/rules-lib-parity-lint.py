#!/usr/bin/env python3
r"""rules-lib-parity-lint — the rule editor's preview library must be the label engine's, verbatim.

    python3 scripts/refactor/rules-lib-parity-lint.py

The mail app evaluates label rules in TWO places: the n8n label engine (the `Lable Engine` Code node
in apps/mail/blueprint/n8n/mailLabelEngine01.workflow.ts) and the rules editor's "תצוגה מקדימה",
which runs the same rule in the browser over the last N messages so an author can see what a rule
would do before saving it. A preview evaluated with a helper library that differs from the engine's
— by one lower-casing, one `@` strip, one regex flag — is not a preview, it is a second opinion, and
it is the kind of drift nothing notices until a rule matches in the editor and not in production.

So apps/mail/mailview/static/rules-lib.js carries two regions copied VERBATIM from the engine
(PART 1, the helpers, and PART 2's data-object builders), each fenced by marker comments, and this
gate fails when either copy differs from the engine's text.

What "verbatim" means here, mechanically: the engine's code lives inside a TypeScript template
literal, so its backslashes, backticks and `${` are escaped once (`\\u0590`, `` \` ``, `\$`); those
escapes are undone before comparing. Whitespace is normalised (lines stripped, blank lines dropped),
because the two files indent differently and trailing spaces carry no meaning. Everything else is
compared character for character, and the first differing line is printed with both spellings.
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "apps" / "mail" / "blueprint" / "n8n" / "mailLabelEngine01.workflow.ts"
LIB = REPO / "apps" / "mail" / "mailview" / "static" / "rules-lib.js"

# Each region is located by CONTENT, never by line number — the engine's Code node is edited and
# thinned, and a line offset is stale the moment someone adds a comment above it. Two anchors per
# edge: the section heading the engine uses today, and a fallback on the code itself (the first
# helper definition / the last helper's closing) for the day a heading is reworded or dropped.
#   (name, [engine start-line regexes], [engine end-line regexes], lib start marker, lib end marker)
# A start regex matches the FIRST line of the region (inclusive); an end regex matches the first
# line AFTER it (exclusive) — except an end regex prefixed with "@last:", which matches the region's
# LAST line (inclusive), for the fallback that ends on the last helper's `};`.
REGIONS = [
    ("helpers",
     [r"^\s*// ─── STRING UTILITIES", r"^\s*const contains = "],
     [r"PART 2: DATA OBJECT BUILDERS", r"^\s*// ─── ATTACHMENT ENRICHMENT", r"@last:^\s*};\s*$"],
     "// @rules-lib:helpers:start", "// @rules-lib:helpers:end"),
    ("builders",
     [r"^\s*// ─── ATTACHMENT ENRICHMENT", r"^\s*const HEBREW_REGEX = "],
     [r"PART 3: RULE EVALUATOR", r"^\s*function evaluateRule\(", r"@last:^\s*}\s*$"],
     "// @rules-lib:builders:start", "// @rules-lib:builders:end"),
]

# The engine's section separators (`// ═══…`) sit between the regions; they are not code and the
# library does not carry them.
SEPARATOR = re.compile(r"^\s*//\s*═+\s*$")


def unescape_template(text):
    """Undo ONE level of TypeScript template-literal escaping: `\\x` -> `x` for any x. That covers
    `\\\\` -> `\\`, `\\`` -> `` ` `` and `\\$` -> `$` in one rule, which is exactly the set the
    .workflow.ts convention uses (see the jsCode escaping note in the project memory)."""
    return re.sub(r"\\(.)", r"\1", text)


def _first_match(lines, patterns, lo=0):
    """(line index, pattern) of the earliest line at or after `lo` matching the first pattern that
    matches anywhere; patterns are tried in order so the heading wins over the code fallback."""
    for pat in patterns:
        rx = re.compile(pat[len("@last:"):] if pat.startswith("@last:") else pat)
        for i in range(lo, len(lines)):
            if rx.search(lines[i]):
                return i, pat
    return None, None


def engine_region(lines, start_res, end_res):
    start, spat = _first_match(lines, start_res)
    if start is None:
        return None, "engine: none of the start anchors %r found" % (start_res,)
    # the code fallback starts at the first helper, so it must not swallow the heading above it —
    # but if the heading is what matched, keep it (the library carries the same heading line)
    end, epat = None, None
    for pat in end_res:
        if pat.startswith("@last:"):
            # inclusive: the LAST line matching, searched from the start forward, stopping at the
            # first line that looks like the next section (a `// ═══` separator)
            rx = re.compile(pat[len("@last:"):])
            last = None
            for i in range(start + 1, len(lines)):
                if SEPARATOR.match(lines[i]):
                    break
                if rx.search(lines[i]):
                    last = i
            if last is not None:
                end, epat = last + 1, pat
                break
        else:
            i, _ = _first_match(lines, [pat], start + 1)
            if i is not None:
                end, epat = i, pat
                break
    if end is None:
        return None, "engine: none of the end anchors %r found after line %d" % (end_res, start + 1)
    # back off over the `// ═══` separator line(s) that precede the next PART heading
    while end > start and SEPARATOR.match(lines[end - 1]):
        end -= 1
    text = "\n".join(lines[start:end])
    return unescape_template(text), None


def lib_region(text, start_marker, end_marker):
    a = text.find(start_marker)
    if a < 0:
        return None, "rules-lib.js: marker %r not found" % start_marker
    a = text.find("\n", a)
    b = text.find(end_marker, a)
    if b < 0:
        return None, "rules-lib.js: marker %r not found" % end_marker
    return text[a + 1:b], None


def normalise(text):
    """Stripped, non-blank lines. The section heading comments (`// ─── STRING UTILITIES ───…`) are
    dropped on both sides too: they are labels, not code, and which of the two anchors matched must
    not decide whether the copies agree."""
    out = []
    for l in text.split("\n"):
        s = l.strip()
        if not s:
            continue
        if s.startswith("// ───") or s.startswith("// ═══"):
            continue
        out.append(s)
    return out


def main():
    # The diff lines carry Hebrew and the engine's Unicode escapes; a cp1255 console (Windows) must
    # not turn the report into a UnicodeEncodeError of its own.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if not ENGINE.exists() or not LIB.exists():
        print("FAIL  missing file: %s" % (ENGINE if not ENGINE.exists() else LIB))
        return 1
    engine_lines = ENGINE.read_text(encoding="utf-8").split("\n")
    lib_text = LIB.read_text(encoding="utf-8")
    failures = 0
    for name, s_re, e_re, s_mark, e_mark in REGIONS:
        eng, err = engine_region(engine_lines, s_re, e_re)
        if err:
            print("FAIL  %-9s %s" % (name, err)); failures += 1; continue
        lib, err = lib_region(lib_text, s_mark, e_mark)
        if err:
            print("FAIL  %-9s %s" % (name, err)); failures += 1; continue
        a, b = normalise(eng), normalise(lib)
        n = max(len(a), len(b))
        diff = next((i for i in range(n) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), None)
        if diff is None:
            print("  ok    %-9s %d lines identical" % (name, len(a)))
            continue
        failures += 1
        print("  FAIL  %-9s first difference at normalised line %d of %d (engine) / %d (rules-lib)"
              % (name, diff + 1, len(a), len(b)))
        print("        engine   : %s" % (a[diff] if diff < len(a) else "<end of region>"))
        print("        rules-lib: %s" % (b[diff] if diff < len(b) else "<end of region>"))
    if failures:
        print("\n%d region(s) drifted. Mirror the change into the other copy — the engine's Code node and"
              "\nrules-lib.js must evaluate a rule identically." % failures)
        return 1
    print("\nrules-lib.js matches the engine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
