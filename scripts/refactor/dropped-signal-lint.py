#!/usr/bin/env python3
"""dropped-signal-lint — gate G50: a caller may not silently discard what the callee TOLD it.

    python3 scripts/refactor/dropped-signal-lint.py [--self-test]

WHY THIS EXISTS. G48 (`noop-success-lint`) enforces one half of this platform's dominant
silent-failure rule — that a reply must NAME its outcome — but it reads n8n blueprints, and the
other half of every one of those conversations is Python. A function can return the most careful
`(value, notes)` contract in the codebase and a caller can still erase it with one underscore:

    current, _notes = _entry_items(transport, entry, _SYNC_STATES, docs, scope)

`_entry_items` is annotated `-> tuple[list[dict], list[str]]` and that second list is where it puts
everything it could not determine. Dropped here, `_move_items` proceeds as though every item's state
were known — and the surface that consumed it rendered 2,435 completed documents as `0`. Nothing
raised. The information existed, was computed, was returned, and was thrown away in the same
expression that received it — which is the same defect as G48's, arriving from the opposite
direction: there the callee refused to say, here the caller refuses to listen.

It is not catchable by review, because the evidence is an ABSENCE: a diff that adds `_notes` looks
like a diff that carefully named an unused value. That is why it is caught here instead.

WHAT THIS CHECKS

  A. NAMED SIGNAL, DISCARDED. A tuple-unpacking assignment from a call, where one target is an
     underscore-prefixed name whose stem is a signal word (`_notes`, `_err`, `_errors`, `_warnings`,
     `_reason`, `_skipped`, `_partial`, `_degraded`, `_failed`, `_status`, `_ok`, ...). The name is
     the evidence: the author knew what they were dropping and said so.

  B. PAIRED RETURN, SUBSCRIPTED AWAY. `f(...)[0]` where `f` is defined IN THE SAME FILE with an
     explicit return annotation `tuple[A, B]` whose second element is diagnostics-shaped
     (`list[str]`, `str | None`, `Optional[str]`). Same spelling of the same discard, and the
     annotation — not a naming convention — is what makes it provable. This catches
     `_drive_snapshot(entry, scope)[0]`, which sits two lines below the `_notes` drop above, in the
     same function, and had gone equally unnoticed.

  C. THE LIST CANNOT ROT. An `ALLOWED` entry that matches nothing FAILS, exactly as in G31's DEBT
     list and G34's `ALLOWED`. A discard that is fixed or deleted must lose its declaration with it,
     or the allow-list silently becomes a blanket exemption — which is precisely how you end up back
     where this started.

WHAT THIS DELIBERATELY DOES NOT CHECK, both rejected on MEASURED noise rather than taste:

  * `x, _ = f()` — the bare underscore. 104 sites across the 392 first-party Python files, and
    almost all of them are stdlib idiom: `guess_type()`, `cv2.imencode()`, `minAreaRect()`,
    `str.split()`. A bare `_` also carries no claim about what was dropped, so there is nothing to
    check it against. Flagging it would train people to ignore this gate.
  * matching a `[0]` subscript to a callee by NAME ACROSS FILES. Tried, measured: 57 "hits", of
    which essentially all were `str.split()` being matched to an unrelated two-tuple-returning
    `split()` defined in `gsheet_transport.py`. That is exactly the "probably right" heuristic
    `feedback_prefer_existing_mechanism_over_new_heuristic` warns about, and it would have made this
    gate wrong on its first run. Check B resolves within one file only, and demands an annotation.

ADDED KNOWN-FAILING, on purpose, exactly like G41–G46. Two findings remain at the time of writing,
both in `apps/indox/app/incoming_documents/api/__init__.py`'s `_move_items` and both owned by
another lane. The gate's job is to make sure they cannot go quiet again once fixed, and to stop a
third one from being written.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("apps", "platform-base", "platform", "scripts")
#: vendored / captured trees — not first-party source, and not ours to change.
EXCLUDE_PARTS = ("/node_modules/", "/.venv/", "/venv/", "/context-collection/", "/site-packages/")

#: The stem (leading underscores removed, lowercased) of a name that means "here is what I could not
#: do / what went wrong / what I left out". A caller dropping one of these is dropping the answer.
SIGNAL_STEMS = frozenset({
    "note", "notes", "err", "error", "errors", "warn", "warning", "warnings",
    "reason", "reasons", "skipped", "refused", "partial", "degraded", "failed",
    "status", "ok",
})

#: The second half of a `tuple[value, diagnostics]` return, as SOURCE TEXT of the annotation.
#: Deliberately a small closed set: this is the shape the codebase actually uses for
#: "and here is what I could not tell you", and widening it to any second element would flag every
#: honest 2-tuple (a coordinate pair, a min/max) as a dropped signal.
DIAGNOSTIC_ANNOTATIONS = frozenset({
    "list[str]", "List[str]", "str | None", "str|None", "None | str", "Optional[str]",
    "list[dict]", "dict | None", "dict|None",
})

#: (repo-relative path, enclosing function, token, why it is allowed).
#: `token` is `<name><-<callee>()` for check A and `[0]<-<callee>()` for check B — deliberately NOT a
#: line number, which rots on the next edit above it. Same shape and same contract as G34's ALLOWED:
#: a declaration is a claim that a human looked, and it must name a reason a human can argue with.
ALLOWED: list[tuple[str, str, str, str]] = [
    ("apps/drive/connections_client.py", "list_instances", "_err<-vault_instances()",
     "DOCUMENTED degrade. `list_instances` says so in its own docstring: a secret-base that is down "
     "returns an EMPTY list rather than failing, because the drive must keep LISTING when the "
     "credential plane is unavailable. The distinction that matters — 'the vault is down' vs 'that "
     "connection was deleted' — is consumed by `resolve_active`, which does NOT drop it."),
    ("apps/drive/connections_client.py", "default_instance", "_err<-vault_instances()",
     "The zero-config guarantee: which instance a deployment that has selected nothing acts as. "
     "Every failure path here already returns None (no admin profile, no match), so a vault error "
     "and an absent default are the same answer to this question — 'nothing is selected'."),
    ("apps/drive/bootstrap.py", "instance_for", "_err<-cx.vault_instances()",
     "Recovery path: re-finds a profile's instance by id, falling back to the vault's account_hint. "
     "An unreachable vault and an unknown instance both mean 'cannot resolve it right now', and the "
     "caller repairs rather than believes the row either way."),
    ("apps/drive/app.py", "engine_profiles_list", "_err<-cx.vault_instances()",
     "Admin LISTING screen for profiles; the instance id is an annotation on each row, not the "
     "subject. Same degrade-while-listing rule `list_instances` documents — a profile with an "
     "unresolved connection still has to appear, or it cannot be repaired from the UI."),
    # The n8n-layout-lint.py exemption was removed 2026-08-21: gates.sh's own comments record
    # that file as deleted on 2026-08-06, so the entry excused nothing and was itself the
    # "ALLOWED entry matches nothing" this gate was failing on.
]


# ─────────────────────────────────────────────────────────────────────────────
def first_party_files(repo: pathlib.Path = REPO):
    for root in ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            sp = str(p).replace("\\", "/")
            if any(x in sp for x in EXCLUDE_PARTS):
                continue
            yield p


def callee_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        base = getattr(f.value, "id", None)
        return f"{base}.{f.attr}" if base else f.attr
    return getattr(f, "id", "?")


def enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    """node -> the name of the INNERMOST function containing it.

    Innermost matters: half this repo's Flask surface lives in closures inside one
    `create_blueprint()`, so an outermost-wins map would file every finding in `api/__init__.py`
    under `create_blueprint()` and the ALLOWED key would neither locate the discard nor survive a
    sibling closure being added. `_move_items()` is the answer a reader needs.
    """
    out: dict[ast.AST, str] = {}

    def descend(node, current):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                descend(child, child.name)
            else:
                if current is not None:
                    out[child] = current
                descend(child, current)

    descend(tree, None)
    return out


def is_signal_name(name: str) -> bool:
    """check A: an underscore-prefixed target whose stem says what was dropped."""
    return name.startswith("_") and name != "_" and name.lstrip("_").lower() in SIGNAL_STEMS


def paired_return_functions(tree: ast.AST) -> set[str]:
    """check B: functions in THIS file annotated `-> tuple[A, B]` with a diagnostics-shaped B."""
    out: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ann = fn.returns
        if not isinstance(ann, ast.Subscript):
            continue
        head = getattr(ann.value, "id", None) or getattr(ann.value, "attr", None)
        if head not in ("tuple", "Tuple"):
            continue
        elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else []
        if len(elts) != 2:
            continue
        try:
            second = ast.unparse(elts[1]).replace(" ", "")
        except Exception:
            continue
        if second in {a.replace(" ", "") for a in DIAGNOSTIC_ANNOTATIONS}:
            out.add(fn.name)
    return out


def scan_source(src: str) -> list[tuple[str, str, str]]:
    """(enclosing function, token, kind) for every dropped signal in one file's source."""
    tree = ast.parse(src)
    enc = enclosing_functions(tree)
    paired = paired_return_functions(tree)
    found: list[tuple[str, str, str]] = []
    for n in ast.walk(tree):
        # A — named signal in a tuple unpack
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Tuple) and isinstance(n.value, ast.Call)):
            callee = callee_name(n.value)
            for el in n.targets[0].elts:
                if isinstance(el, ast.Name) and is_signal_name(el.id):
                    found.append((enc.get(n, "<module>"), f"{el.id}<-{callee}()", "A"))
        # B — same-file paired return, subscripted away
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Call):
            idx = n.slice
            if isinstance(idx, ast.Constant) and idx.value == 0:
                callee = callee_name(n.value)
                if callee in paired:
                    found.append((enc.get(n, "<module>"), f"[0]<-{callee}()", "B"))
    return found


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    ("the real bug verbatim — a named `_notes` dropped from a call: must catch", 1,
     "def _move_items(t, e):\n"
     "    current, _notes = _entry_items(t, e)\n"
     "    return current\n"),
    ("the same call with the notes actually used: must allow", 0,
     "def _move_items(t, e):\n"
     "    current, notes = _entry_items(t, e)\n"
     "    return current, notes\n"),
    ("a bare `_` is out of scope (104 sites, almost all stdlib idiom): must allow", 0,
     "def f():\n"
     "    kind, _ = guess_type(p)\n"
     "    return kind\n"),
    ("an underscore name that is NOT a signal word: must allow", 0,
     "def f():\n"
     "    a, _tmp = g()\n"
     "    return a\n"),
    ("check B — same-file paired return subscripted away: must catch", 1,
     "def snap(e) -> tuple[dict[str, list[dict]], list[str]]:\n"
     "    return {}, []\n"
     "def caller(e):\n"
     "    by_folder = snap(e)[0]\n"
     "    return by_folder\n"),
    ("check B — [0] on a function with NO annotation is invisible, not a false catch", 0,
     "def snap(e):\n"
     "    return {}, []\n"
     "def caller(e):\n"
     "    return snap(e)[0]\n"),
    ("check B — an honest 2-tuple (not diagnostics-shaped) must NOT be flagged", 0,
     "def bounds(x) -> tuple[int, int]:\n"
     "    return 0, 1\n"
     "def caller(x):\n"
     "    return bounds(x)[0]\n"),
    ("check B — [1] takes the diagnostics, so nothing was dropped: must allow", 0,
     "def snap(e) -> tuple[dict, list[str]]:\n"
     "    return {}, []\n"
     "def caller(e):\n"
     "    return snap(e)[1]\n"),
    ("a cross-file name collision cannot reach check B (same-file resolution only)", 0,
     "def caller(s):\n"
     "    return s.split('=')[0]\n"),
    ("both shapes in one function, as they appear in _move_items: must catch both", 2,
     "def _move_items(t, e, s):\n"
     "    def _snap(e, s) -> tuple[dict, list[str]]:\n"
     "        return {}, []\n"
     "    current, _notes = _entry_items(t, e)\n"
     "    by_folder = _snap(e, s)[0]\n"
     "    return current, by_folder\n"),
]


def self_test() -> int:
    bad = 0
    for label, want, src in SELF_TEST:
        got = len(scan_source(src))
        ok = got == want
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] found={got} (want {want}): {label}")
    print(f"\nG50 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    allowed = {(f, fn, tok) for f, fn, tok, _ in ALLOWED}
    hits: set[tuple[str, str, str]] = set()
    findings: list[tuple[str, str, str, str]] = []
    scanned = 0
    for path in first_party_files():
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            found = scan_source(src)
        except (OSError, SyntaxError):
            continue
        scanned += 1
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        for fn, token, kind in found:
            key = (rel, fn, token)
            if key in allowed:
                hits.add(key)
                continue
            findings.append((rel, fn, token, kind))

    stale = [(f, fn, tok, why) for f, fn, tok, why in ALLOWED if (f, fn, tok) not in hits]

    if not findings and not stale:
        print(f"G50 PASS — {scanned} first-party Python file(s) scanned; every dropped callee signal "
              f"is one of the {len(ALLOWED)} declared, and every declaration still matches.")
        return 0

    print("G50 FAIL")
    if findings:
        print(f"\n  {len(findings)} undeclared dropped signal(s) — the callee said something and "
              f"this caller erased it:")
        for rel, fn, token, kind in sorted(findings):
            what = ("a named signal discarded in a tuple unpack" if kind == "A"
                    else "a same-file `-> tuple[value, diagnostics]` return subscripted away")
            print(f"    {rel}  ::  {fn}()  {token}")
            print(f"        {what}")
    if stale:
        print(f"\n  {len(stale)} ALLOWED entry(ies) match nothing — the discard was fixed or moved, "
              f"so the exemption is now a blanket one:")
        for rel, fn, token, _why in stale:
            print(f"    {rel}  ::  {fn}()  {token}")
        print("    Delete the entry. An allow-list that outlives what it excused is how G34's "
              "predecessor grew to 293 files.")
    if findings:
        print(
            "\n  USE the value, or DECLARE it in ALLOWED with a reason a reviewer can argue with.\n"
            "  There is no third option on purpose: a value that is computed, returned and dropped\n"
            "  costs exactly as much as one that is used, and buys a surface that cannot tell the\n"
            "  difference between 'nothing to report' and 'I never looked'."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
