#!/usr/bin/env python3
"""raw-exception-lint — gate G76: an exception's class name is never put into a sentence a person reads.

    python3 scripts/refactor/raw-exception-lint.py            # exit 1 on a finding
    python3 scripts/refactor/raw-exception-lint.py --self-test

WHY THIS EXISTS. "שירות הרשתות החברתיות אינו זמין (ConnectionError)" stood in an amber line at the top
of a Hebrew screen (2026-10-07). It was not one slip: `f"<a Hebrew sentence> ({type(e).__name__})"`
was the house way to report a failed call — 57 places in 10 apps — and every one of them printed a
Python class name to whoever happened to be looking when a neighbour service was down. The name
tells that reader nothing ("URLError" is a DNS record to add, a port to open or a machine to wake),
and the reader who could use it has the log.

THE RULE. A string that holds Hebrew — a sentence for a person — does not format an exception's
class into itself: no `type(x).__name__` and no `x.__class__.__name__` among the values of an
f-string, a `%` format or a `.format()` whose text has a Hebrew letter. The engine's word has two
places: the log (`log.warning("…: %r", e)`), and a field that is ABOUT detail (`detail=`, a step's
third argument) — a string of its own, with no sentence in it, which this gate does not touch.

SCOPE. First-party Python under apps/ and platform-base/, tests and self-tests excluded (a test may
quote the thing it forbids). Read with `ast`, so a comment or a docstring that mentions the pattern
is not a finding, and neither is a detail string that merely sits on the same line as a sentence.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys
import tempfile
import warnings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
HEBREW = re.compile("[֐-׿]")


def _is_class_name(node: ast.AST) -> bool:
    """`type(x).__name__` or `x.__class__.__name__`, anywhere inside `node`."""
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == "__name__":
            v = n.value
            if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "type":
                return True
            if isinstance(v, ast.Attribute) and v.attr == "__class__":
                return True
    return False


def _text(node: ast.AST) -> str:
    """The literal text of a string expression (the constant parts of an f-string)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def findings(source: str) -> list[tuple[int, str]]:
    """[(line, what)] for one file's source."""
    out = []
    with warnings.catch_warnings():                 # a file's own "invalid escape sequence" is G12's to say
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):                              # f"…{type(e).__name__}…"
            if HEBREW.search(_text(node)) and any(isinstance(v, ast.FormattedValue) and _is_class_name(v.value)
                                                  for v in node.values):
                out.append((node.lineno, "an f-string"))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):  # "…%s…" % (type(e).__name__, …)
            if HEBREW.search(_text(node.left)) and _is_class_name(node.right):
                out.append((node.lineno, "a % format"))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
              and HEBREW.search(_text(node.func.value))                      # "…{}…".format(type(e).__name__)
              and any(_is_class_name(a) for a in [*node.args, *[k.value for k in node.keywords]])):
            out.append((node.lineno, "a .format()"))
    return sorted(set(out))


def tracked(repo: pathlib.Path) -> list[pathlib.Path]:
    names = subprocess.run(["git", "-C", str(repo), "ls-files", "--", "apps", "platform-base"],
                           capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    return [repo / n for n in names
            if n.endswith(".py") and "/tests/" not in n and "selftest" not in n
            and not n.rsplit("/", 1)[-1].startswith("test_")]


def check(repo: pathlib.Path) -> int:
    bad = 0
    files = tracked(repo)
    for f in files:
        try:
            hits = findings(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue                                                     # G12 (compile-lint) owns that
        for line, what in hits:
            bad += 1
            print(f"  FAIL  {f.relative_to(repo).as_posix()}:{line}  {what} puts an exception's class name into a "
                  f"Hebrew sentence")
    print(f"raw-exception-lint — G76: {len(files)} files · "
          + (f"{bad} sentence(s) carry a class name — say what happened in words; the name goes to the log "
             f"or to a detail field of its own" if bad else "no sentence a person reads carries an exception's class name"))
    return 1 if bad else 0


def self_test() -> int:
    """Each shape is caught; a detail string, a log line and a comment are not."""
    cases = {
        "f-string": ('def f(e):\n    return f"השירות אינו זמין ({type(e).__name__})"\n', 1),
        "dunder class": ('def f(e):\n    return f"הבדיקה נכשלה: {e.__class__.__name__}"\n', 1),
        "percent": ('def f(e):\n    return "נכשל: %s" % type(e).__name__\n', 1),
        "format": ('def f(e):\n    return "נכשל ({})".format(type(e).__name__)\n', 1),
        "detail of its own": ('def f(e):\n    return ("השירות אינו זמין", f"{type(e).__name__}: {e}")\n', 0),
        "a log line": ('def f(e, log):\n    log.warning("vault: %s %r", type(e).__name__, e)\n    return "השירות אינו זמין"\n', 0),
        "a comment and a docstring": ('def f(e):\n    """was f"… ({type(e).__name__})" — שגיאה"""\n    # ({type(e).__name__}) שגיאה\n'
                                      '    return "השירות אינו זמין"\n', 0),
        "english only": ('def f(e):\n    return f"unavailable ({type(e).__name__})"\n', 0),
    }
    got = {name: len(findings(src)) for name, (src, _n) in cases.items()}
    ok = all(got[name] == want for name, (_src, want) in cases.items())
    # …and the gate as a whole: a tree with one finding is not green
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        (tmp / "apps" / "x").mkdir(parents=True)
        (tmp / "apps" / "x" / "app.py").write_text(cases["f-string"][0], encoding="utf-8")
        (tmp / "apps" / "x" / "test_app.py").write_text(cases["f-string"][0], encoding="utf-8")   # a test may quote it
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp) == 1
        (tmp / "apps" / "x" / "app.py").write_text(cases["detail of its own"][0], encoding="utf-8")
        ok = ok and check(tmp) == 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nraw-exception-lint self-test: "
          + ("4 shapes caught; a detail string, a log line, a comment and an English string are not; a test is not read"
             if ok else "FAILED — got " + str(got)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else check(REPO))
