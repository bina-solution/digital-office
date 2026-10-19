#!/usr/bin/env python3
"""undefined-name-lint — gate G80: a name a python file reads is a name it binds.

    python3 scripts/refactor/undefined-name-lint.py [--self-test]

WHY THIS EXISTS. Python meets a name only when its line runs. A file that reads a name it never
binds parses (G12 passes), imports and serves — and raises NameError on the day that line is
reached. So the names nobody bound survive exactly where they cost the most: the `except` that
almost never fires, the option nobody passes, the fallback for a machine nobody has.

Five were in the tree on 2026-10-07, and each was the rare path of something that claimed to be
handled:

  * mailapi `thread(bodies=false)` called `_summary`, a function the file never had — every
    headers-only thread read was a 500;
  * browser42 `lease_connection` caught `HTTPError` / `URLError` and imported neither, so a refused
    lease — the branch its docstring promises is "reported AS ITSELF" — surfaced as a NameError;
  * apitools' text-layer reader logged a failed overlay render through a `logger` it never made, so
    a convenience picture that could not be written took the whole document's reading with it;
  * the memory-budget gate (G30) read a `state` it had stopped binding, and crashed on any machine
    whose `.env` names no PERFORMANCE_PROFILE;
  * the task runner's `span_push` used `Request` / `urlopen` without importing them, inside
    `except Exception: pass` — a function that could never have worked, and said nothing.

WHAT IT ENFORCES. In every tracked python file (`*.py`, and an extensionless file whose first line
is a python shebang): a name read at module level, or read as a global from a function or a class
body, is bound in that file's module scope — an assignment, an import, a def, a class, a `global`
write from a function — or is a builtin.

HOW. `symtable`, the interpreter's own name resolver: the question "is this name local, free or
global here" is answered by the code that answers it at run time. Nothing to install.

A STAR IMPORT IS REFUSED. `from x import *` binds names nobody can list, so a file with one
cannot be judged — and a file nobody can judge is where the next unbound name hides. The tree had
one (apitools' query engine, 17 validators); it imports them by name now.

OUTSIDE IT. A file that does not parse is G12's. Dunder names are the interpreter's.
Use-before-assignment, attributes and names built at run time (`globals()[k] = …`) are outside
what a symbol table knows.
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import symtable
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILTIN = frozenset(dir(builtins)) | {"WindowsError"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _tables(table):
    yield table
    for child in table.get_children():
        yield from _tables(child)


def undefined(src: str, name: str = "<src>") -> dict[str, tuple[str, int]] | None:
    """{name: (the scope that reads it, the first line that does)} — None when a star import makes
    the file's bindings unknowable. Raises SyntaxError for a file that does not parse."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")              # an invalid escape sequence is G12's to say
        top = symtable.symtable(src, name, "exec")
        tree = ast.parse(src)
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree)):
        return None
    bound = {s.get_name() for s in top.get_symbols()
             if s.is_assigned() or s.is_imported() or s.is_namespace()}
    for t in _tables(top):                           # `global x` and a write, from inside a function
        bound |= {s.get_name() for s in t.get_symbols()
                  if s.is_declared_global() and (s.is_assigned() or s.is_imported() or s.is_namespace())}
    # Where each scope's lines are, so the line reported is the read INSIDE that scope — the same
    # name is often a parameter or a local of some other function in the file.
    span = {(getattr(n, "name", "lambda"), n.lineno): (n.lineno, n.end_lineno) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))}
    reads = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            reads.setdefault(node.id, []).append(node.lineno)
    out = {}
    for t in _tables(top):
        at_top = t.get_type() == "module"
        lo, hi = (1, 10 ** 9) if at_top else span.get((t.get_name(), t.get_lineno()), (1, 10 ** 9))
        for s in t.get_symbols():
            n = s.get_name()
            if (n not in out and s.is_referenced() and (at_top or s.is_global()) and n not in bound
                    and n not in BUILTIN and not (n.startswith("__") and n.endswith("__"))):
                inside = [ln for ln in reads.get(n, []) if lo <= ln <= hi]
                out[n] = ("<module>" if at_top else t.get_name(), min(inside or reads.get(n) or [0]))
    return out


def tracked_python() -> list[str]:
    """Tracked python sources. Symlinks (git mode 120000) are not source — on a Windows checkout
    git writes one as a text file holding the target's path."""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    files = []
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) != 4 or parts[0] == "120000":
            continue
        rel = parts[3].strip()
        base = rel.rsplit("/", 1)[-1]
        if rel.endswith(".py"):
            files.append(rel)
        elif "." not in base:
            try:
                with open(ROOT / rel, "rb") as fh:
                    head = fh.readline()
            except OSError:
                continue
            if head.startswith(b"#!") and b"python" in head:
                files.append(rel)
    return files


def main() -> int:
    files = tracked_python()
    if not files:
        print("G80 FAIL — no tracked python file was found (is this a git checkout?). Nothing was "
              "read, which is not a pass.")
        return 1
    found, star, unparsed = [], [], 0
    for rel in files:
        try:
            res = undefined((ROOT / rel).read_text(encoding="utf-8"), rel)
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
            unparsed += 1
            continue
        if res is None:
            star.append(rel)
            continue
        found += [(rel, line, name, scope) for name, (scope, line) in sorted(res.items())]
    if found or star:
        print(f"G80 FAIL — {len(found)} name(s) are read and bound nowhere in their file"
              f"{f', and {len(star)} file(s) cannot be judged' if star else ''}:")
        for rel, line, name, scope in found:
            print(f"  {rel}:{line}  {name}  (read in {scope})")
        for rel in star:
            print(f"  {rel}  has a star import — the names it binds cannot be listed; import them by name")
        print("  Python raises NameError when such a line runs — and it has not run yet, or somebody\n"
              "  would have seen it. Bind the name (an import, a def) or delete the line that reads it.")
        return 1
    print(f"G80 PASS — {len(files) - unparsed} python file(s): every name read as a global is bound in "
          f"its file or is a builtin" + (f"; {unparsed} that do not parse are G12's" if unparsed else ""))
    return 0


def self_test() -> int:
    names = lambda src: None if (r := undefined(src)) is None else sorted(r)          # noqa: E731
    cases = [
        ("an except handler logs through a logger the file never made",
         "def render(p):\n    try:\n        return open(p)\n    except OSError as e:\n        logger.warning(e)\n",
         ["logger"]),
        ("an except clause names classes nobody imported",
         "from urllib.request import urlopen\ndef lease(u):\n    try:\n        return urlopen(u)\n"
         "    except HTTPError as e:\n        raise\n    except URLError:\n        raise\n",
         ["HTTPError", "URLError"]),
        ("a call to a function that is defined under another name",
         "def _msg_summary(u):\n    return u\ndef thread(u):\n    return _summary(u)\n", ["_summary"]),
        ("a name another function holds as its own local is not this one's",
         "def main():\n    enabled = load()\n    return state.get('x')\ndef load():\n    state = {}\n    return state\n",
         ["state"]),
        ("a class attribute read as a bare name inside a method",
         "class A:\n    LIMIT = 3\n    def f(self):\n        return LIMIT\n", ["LIMIT"]),
        ("a decorator and a default argument are read at module level",
         "@register\ndef f(x=DEFAULT):\n    return x\n", ["DEFAULT", "register"]),
        ("an import binds — also inside try/except, also under an alias",
         "import os.path\ntry:\n    import yaml as y\nexcept ImportError:\n    y = None\n"
         "def f():\n    return os.sep, y\n", []),
        ("a `global` write in one function binds the name for another",
         "def boot():\n    global CACHE\n    CACHE = {}\ndef get(k):\n    return CACHE[k]\n", []),
        ("builtins and dunders are the interpreter's",
         "def f():\n    return len(__file__), __name__, print, NotImplementedError\n", []),
        ("a comprehension's variable, a lambda's parameter and a closure's local are local",
         "def f(xs):\n    seen = set()\n    def g(x):\n        return x in seen\n"
         "    return [y for y in xs if g(y)], (lambda z: z)(1)\n", []),
        ("for / with / walrus / except-as bind at module level",
         "import io\nfor i in range(2):\n    pass\nwith io.StringIO() as fh:\n    pass\n"
         "if (n := i):\n    pass\ndef f():\n    return i, fh, n\n", []),
        ("a star import: the file's bindings cannot be listed (None — main refuses the file)",
         "from os.path import *\ndef f():\n    return join('a', whatever)\n", None),
    ]
    bad = 0
    for name, src, want in cases:
        got = names(src)
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("undefined-name-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
