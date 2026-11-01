#!/usr/bin/env python3
"""unread-error-lint — gate G66: a failure may not be reduced to a shape that looks like success.

    python3 scripts/refactor/unread-error-lint.py [--self-test]

WHY THIS EXISTS. Six times in one release-verification session, a component reported a failure
CORRECTLY and the layer above it threw the report away — an exit code, a stringified exception,
an empty list, a green PASS. Nothing crashed, nothing logged an error, and the system continued
on a value that looked like a result and was not one. The full write-up, with all six, is in
`issues/unread-failure-defect-class.md`; the three that are mechanically checkable are here.

None of the six was a missing error message. In every case the error existed, was accurate, and
was discarded by its reader. So "log more" is not the remedy, and neither is review: the evidence
is an ABSENCE, and a diff that swallows an error looks exactly like a diff that handles one.

WHAT THIS CHECKS

  A. THE EXCEPTION READ AFTER ITS HANDLER CLOSED.  `except X as e:` UNBINDS `e` when the clause
     ends — Python deletes the name (PEP 3110) so the traceback it holds can be collected. Any
     read of that name afterwards is a guaranteed UnboundLocalError, on EVERY path: if the
     handler ran, the name was deleted; if it did not, the name was never bound.

         except Exception as e:
             last = {'error': f'attempt {attempt}: {e}'}
         if exhausted or (not _transient(e) and attempt >= 2):   # <-- A
             return last

     That is scripts/extraction-corpus-check.py before 2026-08-23. pool.map re-raises, so the
     first exception from any document killed the whole extraction gate, which then reported
     "extraction gate FAILED --" with an empty reason. The exception it was written to absorb is
     a transient 429 from a starved apitools — the single likeliest thing to happen when the gate
     runs beside the rest of the stack, which is the only time it runs. The retry logic guarded
     there had therefore never once executed.

     There are no false positives in this check. The name is gone in every case; the only
     question is whether the line is reached.

  B. THE HTTP ERROR BODY DISCARDED.  A `try` whose body makes an HTTP call THAT RAISES ON A BAD
     STATUS, caught by a bare `except:` or `except Exception`, where the handler never reads the
     payload off the error and never re-raises. For urllib that payload is the whole report:
     `HTTPError` IS a response, and `e.read()` is the body. requests/httpx raise on a status only
     when asked (`raise_for_status()`), and then the error carries `.response`.

     What counts as such a call is decided on the syntax tree (`_raises_with_a_body`). It used to
     be decided by text — any line containing `.get(` or `.post(` in a file that imports an HTTP
     library — and that is what a DICT READ looks like: on 2026-10-06, 108 of the 146 findings
     were `task.get("slug")`, `os.environ.get(...)`, `int(j.get("status") or 0)`. A gate that is
     three-quarters noise is read as noise, and the 30 real discards under it were not being
     fixed; the count had drifted 43 over its ceiling without anyone looking.

         except Exception as e:
             print("ERR", e)      # <-- B: "HTTP Error 500: INTERNAL SERVER ERROR", and nothing else

     That is `bbox`'s ensure_converged before 2026-08-23. app-management answers `500` when
     reconcile RAN and is naming which apps failed, so the body was the list of failures. Cost: a
     full investigation into a phantom ordering bug. The ordering was right; the failure in front
     of it was unreadable, so blueprints were not yet imported when indox's onboard hook ran and
     the hook reported `workflow not found: IndoxResetFull01`.

  C. THE EMPTY SCAN THAT CAN STILL PASS.  A gate under scripts/refactor/ that builds its input by
     globbing and can reach its success exit with that collection empty. Twelve gates in this
     repo globbed `apps/*/blueprint/n8n/*.json` after blueprints became `.workflow.ts` in
     52b32aa4. Every one looped over nothing and printed its success line for weeks. GREEN AND
     BLIND ARE INDISTINGUISHABLE FROM OUTSIDE, which is the entire problem: a measurement over
     zero inputs is not a low score, it is no score.

     The same bug hid the node-coverage figure. `n8n-node-coverage.py` ERRORED rather than
     returning a smaller number — and an error is easier to dismiss than a bad number — so
     279/624 = 44.7% was quoted as live for weeks against a real 1339/1987 = 67.4%.

SCOPE. First-party Python only: scripts/, apps/*/hooks/, platform-base/*/. Never vendored trees
(node_modules, .venv, site-packages, dist) and never this file's own fixtures.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = ("scripts", "apps", "platform-base", "platform")
SKIP_PARTS = {
    "node_modules", ".venv", "venv", "site-packages", "dist", "build",
    "__pycache__", ".git", "vendor", "third_party", "digital-office",
}

# An HTTP call in the try-body is what makes a swallowed exception a swallowed REPORT — when its
# failure ARRIVES as an exception that carries the response. urllib's does by default (`urlopen`
# raises HTTPError for a 4xx/5xx; `Request(` is how the call is built for an opener). requests and
# httpx hand a 500 back as an ordinary response unless `raise_for_status()` is called, so without
# it there is no error for a handler to discard (an unchecked status is a different defect).
RAISES_WITH_A_BODY = ("urlopen", "urlretrieve", "Request", "raise_for_status")
HTTP_MODULES = ("urllib", "requests", "httpx", "http.client")

# Reading any of these off the bound exception counts as reading the report.
BODY_READS = ("read", "text", "json", "content", "body", "response",
              "code", "status", "status_code", "reason", "headers", "fp")

# Entries: (relative path, check, why it is allowed). Keep the reason arguable.
ALLOWED: list[tuple[str, str, str]] = [
    ("scripts/refactor/open-destructive-webhook-lint.py", "C",
     "it DOES refuse an empty scan — main() tests `paths = blueprints()` and returns 1 with "
     "'scanned ZERO blueprints'. Check C follows a glob only to the name it is assigned to, and "
     "here the glob lives in blueprints(). Following it through function returns was tried "
     "(2026-10-06) and flagged 15 gates whose function returns FINDINGS, not inputs — an empty "
     "list of findings is a pass, not an empty scan — so that needs a per-gate reading, not a rule."),
]


def _iter_py() -> list[Path]:
    out = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if set(p.parts) & SKIP_PARTS:
                continue
            out.append(p)
    return sorted(out)


def _end(node: ast.AST) -> int:
    return getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)


# -- scope helpers ---------------------------------------------------------------------------
# A COMPREHENSION IS A SCOPE. `[e for e in rows]` after `except X as e` rebinds nothing in
# the enclosing function -- Python 3 gives every comprehension its own frame. Leaving these
# out is what made this check's second run report 7 findings of which the three I opened by
# hand were all the same false positive: a generator variable that happened to be called e.
_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
          ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _scopes(tree: ast.AST):
    """The module plus every function/lambda, each yielded once."""
    yield tree
    for n in ast.walk(tree):
        if isinstance(n, _SCOPE):
            yield n


def _own(scope: ast.AST):
    """Nodes belonging DIRECTLY to `scope` -- never descending into a nested scope."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, _SCOPE):
            stack.extend(ast.iter_child_nodes(n))


# -- A ---------------------------------------------------------------------------------------
def check_exception_name_escapes(tree: ast.AST) -> list[tuple[int, str]]:
    """Reads of an `except ... as NAME` binding after the handler closed."""
    findings = []
    for scope in _scopes(tree):
        nodes = list(_own(scope))
        handlers = [n for n in nodes if isinstance(n, ast.ExceptHandler) and n.name]
        if not handlers:
            continue

        # Every re-binding of a name clears the finding from that line on. `except X as e` IS a
        # binding, and ast models it as a bare string on the handler -- not a Name(Store) node --
        # so it has to be added by hand. Missing that is what made this check's first run report
        # 188 findings, nearly all of them a second handler legally reusing `e`.
        stores: dict[str, list[int]] = {}
        for n in nodes:
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                stores.setdefault(n.id, []).append(n.lineno)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                stores.setdefault(n.name, []).append(n.lineno)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stores.setdefault(n.name, []).append(n.lineno)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    stores.setdefault((a.asname or a.name).split(".")[0], []).append(n.lineno)

        loads = [n for n in nodes
                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
        for h in handlers:
            name, h_end = h.name, _end(h)
            h_span = range(h.lineno, h_end + 1)
            for n in loads:
                if n.id != name or n.lineno <= h_end:
                    continue
                if n.lineno in h_span:
                    continue
                if any(h_end < st < n.lineno for st in stores.get(name, [])):
                    continue
                findings.append((n.lineno,
                                 f"'{name}' is read at line {n.lineno} but its handler "
                                 f"(line {h.lineno}) unbound it -- UnboundLocalError on every path"))
    # one finding per read site
    return sorted(set(findings))


# -- B ---------------------------------------------------------------------------------------
def _raises_with_a_body(stmts) -> bool:
    """Does this try-body call something whose bad status comes back as an exception?"""
    return any(isinstance(n, ast.Call)
               and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) in RAISES_WITH_A_BODY
               for s in stmts for n in ast.walk(s))


def check_http_body_discarded(tree: ast.AST, src: str) -> list[tuple[int, str]]:
    if not any(m in src for m in HTTP_MODULES):
        return []
    lines = src.splitlines()
    findings = []
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        if not _raises_with_a_body(t.body):
            continue

        # A TYPED handler on the same try that reads the payload means this try already does the
        # right thing; the broad clause after it is the ordinary catch-all, not a discard. Without
        # this, the canonical correct shape -- `except HTTPError as e: ... e.read()` followed by
        # `except Exception as e: print(e)` -- reports as a violation. It was this gate's own
        # self-test that caught that.
        typed_reads_body = False
        for h in t.handlers:
            broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
            if broad or not h.name:
                continue
            h_src = chr(10).join(lines[h.lineno - 1:_end(h)])
            if any(f"{h.name}.{a}" in h_src for a in BODY_READS):
                typed_reads_body = True
        if typed_reads_body:
            continue

        for h in t.handlers:
            broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
            if not broad:
                continue
            h_src = chr(10).join(lines[h.lineno - 1:_end(h)])
            if "raise" in h_src:
                continue
            if h.name and any(f"{h.name}.{a}" in h_src for a in BODY_READS):
                continue
            findings.append((h.lineno,
                             "broad `except` over an HTTP call discards the error body -- "
                             "catch the typed error and read its payload"))
    return findings


# -- C ---------------------------------------------------------------------------------------
def _nonzero_exit(node):
    """Does this branch actually FAIL -- return 1, sys.exit(non-zero), or raise?"""
    for n in ast.walk(node):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and                 n.value.value not in (0, None, False):
            return True
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nm == "exit" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and a.value not in (0, None):
                    return True
    return False


def _tests_emptiness(test, names):
    """`if not xs`, `if len(xs) == 0`, `if xs == []` -- for a name bound from a glob."""
    for n in ast.walk(test):
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            for m in ast.walk(n.operand):
                if isinstance(m, ast.Name) and m.id in names:
                    return True
        if isinstance(n, ast.Compare) and n.comparators:
            hit = any(isinstance(m, ast.Name) and m.id in names for m in ast.walk(n.left))
            if hit:
                c = n.comparators[0]
                if isinstance(c, ast.Constant) and c.value == 0:
                    return True
                if isinstance(c, (ast.List, ast.Tuple, ast.Set)) and not c.elts:
                    return True
    return False


def check_empty_scan_can_pass(path, src, tree):
    """A gate that globs its input and can still reach a PASS with that input empty.

    The first version of this check asked only whether the file MENTIONED emptiness anywhere --
    "len(" or "if not " or the word empty. Every gate in the repo satisfied that, so it reported
    nothing, which is precisely the vacuous pass this gate exists to name. It now demands the
    thing that actually matters: a branch that TESTS the globbed collection for emptiness and
    FAILS inside it.
    """
    rel = path.relative_to(ROOT).as_posix()
    if not rel.startswith("scripts/refactor/"):
        return []
    if not (rel.endswith("-lint.py") or rel.endswith("-gate.py")):
        return []

    globbed = set()
    glob_line = 0
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        calls = [c for c in ast.walk(n.value)
                 if isinstance(c, ast.Call)
                 and (getattr(c.func, "attr", None) in ("glob", "rglob", "iglob")
                      or getattr(c.func, "id", None) in ("glob", "iglob"))]
        if not calls:
            continue
        glob_line = glob_line or n.lineno
        for t in n.targets:
            for m in ast.walk(t):
                if isinstance(m, ast.Name):
                    globbed.add(m.id)
    if not globbed:
        return []

    for n in ast.walk(tree):
        if isinstance(n, ast.If) and _tests_emptiness(n.test, globbed) and _nonzero_exit(n):
            return []
        if isinstance(n, ast.Assert):
            if any(isinstance(m, ast.Name) and m.id in globbed for m in ast.walk(n.test)):
                return []
    return [(glob_line,
             "globs into %r but no branch tests it for EMPTY and fails -- "
             "green and blind are indistinguishable" % sorted(globbed))]


# ── self-test ────────────────────────────────────────────────────────────────────────────────
BAD_A = '''
def process(doc):
    for attempt in range(1, 9):
        try:
            return work(doc)
        except Exception as e:
            last = {"error": f"attempt {attempt}: {e}"}
        if not _transient(e) and attempt >= 2:
            return last
'''
GOOD_A = '''
def process(doc):
    err = None
    for attempt in range(1, 9):
        try:
            return work(doc)
        except Exception as exc:
            err = exc
            last = {"error": f"attempt {attempt}: {exc}"}
        if not _transient(err) and attempt >= 2:
            return last
'''
BAD_B = '''
import urllib.request
def go():
    try:
        r = urllib.request.urlopen(req, timeout=10)
        print(r.read().decode())
    except Exception as e:
        print("ERR", e)
'''
DICT_B = '''
import urllib.request
def go(j):
    try:
        n = int(j.get("duration_us") or 0)
    except Exception:
        n = 0
    return n
'''
BAD_B_STATUS = '''
import requests
def go():
    try:
        r = requests.post(url, json=doc, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}
'''
QUIET_B_STATUS = '''
import requests
def go():
    try:
        return requests.post(url, json=doc, timeout=5).json()
    except Exception as e:
        return {"error": str(e)}
'''
GOOD_B_STATUS = '''
import requests
def go():
    try:
        r = requests.post(url, json=doc, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        return {"error": f"{e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}
'''
GOOD_B = '''
import urllib.request, urllib.error
def go():
    try:
        r = urllib.request.urlopen(req, timeout=10)
        print(r.read().decode())
    except urllib.error.HTTPError as e:
        print("ERR HTTP", e.code, e.read().decode()[:2000])
    except Exception as e:
        print("ERR", e)
'''


def self_test() -> int:
    cases = [
        ("A bad", BAD_A, check_exception_name_escapes, True),
        ("A good", GOOD_A, check_exception_name_escapes, False),
    ]
    fails = 0
    for label, src, fn, want in cases:
        got = bool(fn(ast.parse(src)))
        ok = got == want
        fails += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: expected findings={want} got={got}")
    for label, src, want in (("B bad", BAD_B, True), ("B good", GOOD_B, False),
                             ("B a dict read is not an HTTP call", DICT_B, False),
                             ("B raise_for_status, body discarded", BAD_B_STATUS, True),
                             ("B no raise_for_status, nothing to discard", QUIET_B_STATUS, False),
                             ("B raise_for_status, response read", GOOD_B_STATUS, False)):
        got = bool(check_http_body_discarded(ast.parse(src), src))
        ok = got == want
        fails += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: expected findings={want} got={got}")
    print("  SELF-TEST PASS" if not fails else f"  SELF-TEST FAILED ({fails})")
    return 1 if fails else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    files = _iter_py()
    # RULE 1 APPLIED TO THIS GATE ITSELF. An empty scan is a red, never a pass — the defect this
    # gate exists to catch is the one it is most likely to have.
    if not files:
        print("G66 FAIL — scanned 0 Python files. That is not a clean run, it is no run.")
        print(f"  looked under: {', '.join(SCAN_DIRS)} (from {ROOT})")
        return 1

    allowed = {(r, c) for r, c, _ in ALLOWED}
    findings: list[tuple[str, int, str, str]] = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except SyntaxError:
            continue                              # compile-lint (G12) owns syntax
        for ln, msg in check_exception_name_escapes(tree):
            if (rel, "A") not in allowed:
                findings.append((rel, ln, "A", msg))
        for ln, msg in check_http_body_discarded(tree, src):
            if (rel, "B") not in allowed:
                findings.append((rel, ln, "B", msg))
        for ln, msg in check_empty_scan_can_pass(p, src, tree):
            if (rel, "C") not in allowed:
                findings.append((rel, ln, "C", msg))

    hard = [f for f in findings if f[2] in ("A", "C")]
    soft = [f for f in findings if f[2] == "B"]

    # THE RATCHET — and why B is on it while A and C are not.
    #
    # A is a guaranteed UnboundLocalError; C is a gate that can report on nothing. Neither has a
    # defensible instance, so any count above zero fails. B is genuinely different: a broad except
    # around an HTTP call is sometimes exactly right — a liveness poll that only cares whether the
    # port answered does not want the body — and there are ~100 of them here. Failing all of them
    # today would mean this gate is disabled by Friday, which is how a lint turns into something
    # people pass with --no-verify. So B is measured against a recorded ceiling and may only ever
    # go DOWN. Same shape as G65's coverage floor, for the same reason: a number nobody can move
    # is a number nobody reads.
    ceil_path = ROOT / "scripts" / "ci" / "unread-error-ceiling.json"
    try:
        ceiling = int(json.loads(ceil_path.read_text(encoding="utf-8"))["http_body_discarded"])
    except Exception:
        ceiling = None

    print(f"G66 unread-error-lint — {len(files)} first-party Python file(s) scanned")
    if not findings:
        print("  OK — no unread failures found.")
        return 0
    if not hard and ceiling is not None and len(soft) <= ceiling:
        print(f"  OK — A=0, C=0; B={len(soft)} at or under the recorded ceiling {ceiling}.")
        return 0

    by_check: dict[str, list] = {}
    for f in findings:
        by_check.setdefault(f[2], []).append(f)
    titles = {
        "A": "exception read after its handler closed (guaranteed UnboundLocalError)",
        "B": "HTTP error body discarded by a broad except",
        "C": "gate can pass on an empty scan",
    }
    for c in sorted(by_check):
        rows = by_check[c]
        print(f"\n  [{c}] {titles[c]} — {len(rows)}")
        for rel, ln, _c, msg in rows:
            print(f"    {rel}:{ln}  {msg}")
    print(
        "\n  Fix the reader, not the reporter. In every instance behind this gate the error was\n"
        "  produced correctly and destroyed on arrival — so a failure must never be reducible to\n"
        "  a shape that a success could also take."
    )
    if ceiling is None:
        print(f'\n  No ceiling recorded for [B]. Write {{"http_body_discarded": {len(soft)}}} to')
        print(f"  {ceil_path.relative_to(ROOT).as_posix()} to freeze it at today's count.")
    elif len(soft) > ceiling:
        print(f"\n  [B] {len(soft)} exceeds the recorded ceiling {ceiling} — "
              f"{len(soft) - ceiling} new discard(s).")
        print("  The ceiling comes down by FIXING one, never by editing the number up.")
    if not hard and ceiling is not None and len(soft) <= ceiling:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
