#!/usr/bin/env python3
"""portability-lint — gate G10: every script must work on Linux, Windows and macOS.

    python3 scripts/refactor/portability-lint.py

The rule is that nothing here is allowed to be "Linux-only". It is not a preference: claiming a
feature cannot run on an OS, without having tried, is how `bbox ui-map` sat marked
"cannot run on Windows (MSYS paths)" for weeks. It ran fine once the paths were converted — the
whole fix was nine call sites.

The recurring Windows failure is path FORM, and it is silent-ish in a way that reads like a
missing file rather than a portability bug:

    scripts/lib.sh sets MSYS_NO_PATHCONV=1 so Git-Bash stops rewriting CONTAINER-side paths
    (/data, /blueprints/...). The cost is that HOST paths stay MSYS-shaped (/c/Users/...), and
    python.exe / docker.exe are native Windows binaries that do not understand them:

        python3 /c/x/report.py     -> can't open 'C:\\c\\x\\report.py'
        docker build /c/x/ctx      -> unable to prepare context: path "/c/x/ctx" not found
        docker run -v /c/x:/data   -> mounts nothing useful

`npath()` (scripts/lib.sh) converts at that boundary: cygpath -m on Git-Bash/MSYS/Cygwin,
identity on Linux and macOS. This gate checks two things:

  1. a HOST path variable handed to a native binary goes through npath()
  2. any script that CALLS npath() actually sources lib.sh — otherwise the call expands to the
     empty string and the path silently becomes relative, which is worse than the original bug

Container-side paths (/data, /app/..., /blueprints/...) must NOT be converted, so only
${VAR}-shaped host paths are considered.
"""
import pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# Host-path variables — these hold a path on the machine running the script.
# Host-path variables. Matched by SHAPE, not by an allowlist: an explicit list goes stale the
# moment someone adds a new one, and that is exactly what happened — SEED_DIR was missing, so
# this gate passed while `docker cp "${SEED_DIR}/seed_demo.py"` silently failed on Windows and
# my-docs rendered empty in every screenshot.
HOST_VARS = r"(?:[A-Z][A-Z0-9_]*_(?:DIR|ROOT|PATH)|REPO_ROOT|SCRIPTS|DATA|ART|SHOTS)"
# Does this line invoke a native binary at all?
# `docker cp` takes a HOST path too, and omitting it is what let the ui-map seed fail silently:
# `docker cp "${SEED_DIR}/seed_demo.py"` never reached the container on Windows, so my-docs
# rendered EMPTY in every screenshot and the pixel diff read as a 14% UI regression.
INVOKES_NATIVE = re.compile(r"(?:python3?|curl|docker\s+(?:build|run|cp))\b")

# A LITERAL host /tmp path handed to curl. With MSYS_NO_PATHCONV=1 set (lib.sh does, so every
# script inherits it), curl.exe takes "/tmp/x" at face value and writes it under the Windows drive
# root, while the shell's own grep/rm read the MSYS /tmp — two different files that look like one.
# ci-verify.sh wrote its auth cookie to one and looked for it in the other, so the n8n active-state
# check reported "login=0, UNVERIFIED" on Windows and could never have passed there.
# Only curl: `docker exec … /tmp/x` and `docker cp … c:/tmp/x` are CONTAINER paths and must stay raw.
CURL_LITERAL_TMP = re.compile(r"\bcurl\b[^|;&]*?\s-[a-zA-Z]+\s+/tmp/")

# A `python3 -c "..."` / `-c '...'` block, which may span several lines. Scanned whole so a raw
# host path on a continuation line is not missed the way the per-line scan misses it.
PYC_BLOCK = re.compile(r"""python3?\s+-c\s+"[^"]*"|python3?\s+-c\s+'[^']*'""", re.S)
# An already-converted use. These are STRIPPED from the line before looking for offenders —
# checking "is npath anywhere on this line?" is not good enough: one line legitimately carries
# both a converted and an unconverted path, and skipping it whole made this gate blind to the
# exact ui-map bug it was written for (caught by its own self-test).
CONVERTED = re.compile(r"""\$\(npath\s+"\$\{""" + HOST_VARS + r"""\}"\)""")
# A raw host-path variable still in MSYS form.
RAW = re.compile(r"""\$\{""" + HOST_VARS + r"""\}""")
# A host var used AS A PATH: immediately followed by a slash. Distinguishes a real file path
# (${REPO_ROOT}/data) from a host var mentioned in a diagnostic string (${DATA}:/data mount text).
RAW_PATH = re.compile(r"""\$\{""" + HOST_VARS + r"""\}/""")
# `$(cd … && pwd)` — a command substitution that RETURNS a host path. Same bug, third shape, and
# matching only ${VAR} missed it: apps/indox/hooks/test ran
#     python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/test.py"
# so python.exe was handed /c/Users/… and answered "can't open file C:\c\Users\…". Every INDOX
# suite failed on Windows before running a single test, and the baseline read it as a red suite.
# `.*?` and not `[^)]*`: the real offender nests another substitution inside —
# $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) — and excluding ')' stopped at the inner one, so
# the first version of this rule passed the very line it was written for. Caught by its self-test.
PWD_SUBST = re.compile(r"\$\(cd\b.*?&&\s*pwd\s*\)")
SOURCES_LIB = re.compile(r"^\s*\.\s+.*lib\.sh", re.M)
# Hebrew block + the bidi isolate marks. Printing either crashes python on Windows unless stdout
# is forced to UTF-8 — it defaults to the ANSI codepage (cp1255 on this machine).
HEBREW_OR_BIDI = re.compile("[֐-׿⁦-⁩]")

TARGETS = [REPO / "bbox"] + sorted(
    # app hooks are scripts too — and being three levels deeper is exactly how one broke
    p for p in list((REPO / "apps").glob("*/hooks/*")) + list((REPO / "platform-base").glob("*/hooks/*"))
    if p.is_file()) + sorted(
    p for p in (REPO / "scripts").rglob("*")
    # .py included: scripts/ is full of python, and excluding it made this gate blind —
    # its own self-test (a Hebrew-printing .py with no remedy) went unflagged.
    if p.is_file() and p.suffix in ("", ".sh", ".py") and "__pycache__" not in p.as_posix())


def main() -> int:
    # [2026-08-23 G66/C] AN EMPTY SCAN IS A RED, NEVER A PASS. This repo has already lived the
    # other way: twelve gates globbed apps/*/blueprint/n8n/*.json after blueprints became
    # .workflow.ts in 52b32aa4, matched nothing, looped over nothing, and printed their success
    # line for weeks. Green and blind are indistinguishable from OUTSIDE, so nothing surfaced it.
    # The glob is right today; this guard is what makes it stay honest if the layout moves again.
    if not TARGETS:
        print("G10 FAIL - scanned 0 script(s) via %s. That is not a clean run, it is no run:"
              " a measurement over zero inputs is not a low score, it is no score." % 'the three globs built at import time')
        return 1
    unconverted, orphan_npath = [], []
    # A script that prints Hebrew but never inherits lib.sh's UTF-8 io will die on Windows with
    # UnicodeEncodeError (python defaults stdout to the ANSI codepage, cp1255 here). Linux/macOS
    # are already UTF-8, so this fails on exactly one platform — the definition of the bug class
    # this gate exists to stop.
    no_utf8 = []
    for f in TARGETS:
        rel = f.relative_to(REPO).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not text.lstrip().startswith("#!") and f.suffix != ".sh":
            continue

        # npath() is a SHELL function — a .py mentioning it is documentation or a regex, not a
        # call, so this check applies to shell scripts only.
        if (f.suffix != ".py" and "npath" in text
                and not SOURCES_LIB.search(text) and rel != "scripts/lib.sh"):
            orphan_npath.append(rel)

        # A .py PRINTS directly, so it needs the remedy in itself. A shell script only needs it
        # if it invokes python at all. Requiring INVOKES_NATIVE for both meant a pure-python
        # script printing Hebrew was never flagged.
        needs_utf8 = f.suffix == ".py" or INVOKES_NATIVE.search(text)
        if (rel != "scripts/lib.sh"
                and not SOURCES_LIB.search(text)
                and "PYTHONIOENCODING" not in text
                # a python file may fix it itself; that is equally valid
                and "reconfigure(encoding=" not in text
                and HEBREW_OR_BIDI.search(text)
                and needs_utf8):
            no_utf8.append(rel)

        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            m = INVOKES_NATIVE.search(line)
            if not m:
                continue
            # Only ARGUMENTS matter — inspect what follows the binary. `cd "${REPO_ROOT}" &&
            # python3 scripts/x.py` is correct: cd is a shell builtin that handles MSYS paths,
            # and python then gets a relative path. Flagging that would be noise.
            args = line[m.end():].split(" #")[0]
            # Drop already-correct uses first: one line legitimately carries both a converted and
            # an unconverted path, so "is npath anywhere on this line?" is not good enough — that
            # exclusion made this gate blind to the exact ui-map bug it was written for.
            # strip the already-correct `$(npath …)` uses before looking for either raw shape
            bare = CONVERTED.sub("", args)
            bare = re.sub(r"\$\(npath\s+[^)]*\)", "", bare)
            if RAW.search(bare) or PWD_SUBST.search(bare):
                unconverted.append((rel, n, s[:96]))
            elif CURL_LITERAL_TMP.search(line):
                unconverted.append((rel, n, s[:96]))

        # Multi-line `python3 -c "..."` blocks. The line scan above only inspects the line that
        # holds `python3`, so a host path on a CONTINUATION line slips through — which is exactly
        # how baseline.sh handed native python an MSYS `${REPO_ROOT}/...` inside a multi-line -c and
        # P8 warned "? views failed" on Windows. Scan each -c block as a whole.
        for m in PYC_BLOCK.finditer(text):
            block = m.group(0)
            bare = re.sub(r"\$\(npath\s+[^)]*\)", "", CONVERTED.sub("", block))
            # RAW_PATH, not RAW: only a host var used AS A PATH (followed by `/`). `${DATA}/x` is a
            # file python will open; `the ${DATA}:/data mount` in a diagnostic string is not, and
            # flagging that was a false positive on run_capture.sh's preflight message.
            if RAW_PATH.search(bare):
                ln = text[:m.start()].count("\n") + 1
                snippet = " ".join(block.split())[:96]
                if (rel, ln, snippet) not in unconverted:
                    unconverted.append((rel, ln, snippet))

    if not unconverted and not orphan_npath and not no_utf8:
        print(f"G10 PASS — every host path reaching a native binary is converted "
              f"({len(TARGETS)} script(s) checked; Linux/Windows/macOS).")
        return 0

    if unconverted:
        print(f"G10 FAIL — {len(unconverted)} host path(s) handed to a native binary unconverted:")
        for rel, n, line in unconverted:
            print(f"  {rel}:{n}: {line}")
        print('  -> wrap it: python3 "$(npath "${DIR}")/x.py"   /   -v "$(npath "${D}"):/data"')
    if no_utf8:
        print(f"\nG10 FAIL — {len(no_utf8)} script(s) print Hebrew/bidi but do not inherit "
              f"UTF-8 io, so they crash on Windows:")
        for rel in no_utf8:
            print(f"  {rel}")
        print('  -> source lib.sh (it exports PYTHONIOENCODING=utf-8), or export it yourself')

    if orphan_npath:
        print(f"\nG10 FAIL — {len(orphan_npath)} script(s) call npath() without sourcing lib.sh, "
              f"so it expands to nothing:")
        for rel in orphan_npath:
            print(f"  {rel}")
        print('  -> add: . "${SCRIPT_DIR}/lib.sh"')
    return 1


if __name__ == "__main__":
    sys.exit(main())
