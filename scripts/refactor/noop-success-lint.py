#!/usr/bin/env python3
"""noop-success-lint — gate G48: an operation that did nothing never reports success.

    python3 scripts/refactor/noop-success-lint.py [--self-test]

WHY THIS EXISTS. This is the dominant silent-failure shape in this codebase, and unlike the others
it is not one bug — it is a missing THIRD VALUE. A workflow branch that skips has only two words
available to describe itself, "worked" and "failed", so it picks one, and either choice is a lie
that costs hours. Three confirmed instances, all in the sync engine, all found the same night
(2026-08-06):

  #66  `syncV3Main0001`'s `Try Lock` guard: when a previous reconcile pass still holds the mutex,
       `Skip: Already Running` exits cleanly returning `{skipped, reason, note}` — no outcome field
       at all. n8n records the execution as `success` (it did exit cleanly), and the CALLER, unable
       to see a skip, fell through to its "the reconciler built no work unit" branch and reported
       `code:'no_units'` with the skip node's internal note as the error. Two proof attempts were
       abandoned as pipeline failures. Measured live: 10 of six hours' executions ended there, all
       `success`, all 0–2s.
  #69  the same node from the operator's side: a pass averages 848–1223s against its own 900s
       schedule, so the lock is held almost continuously and the sync board's "run now" button was
       effectively debounced to the scheduler's cadence — reporting a run every time.
  #68  `SyncApi0000000001`'s `Release Result`: RELEASE took the fully-qualified ledger identity
       `<instance>/<pipe>` while SCAN took the plain pipe name. A plain name matched zero ledger
       rows, the DELETE returned nothing, and the reply was a flat `ok:true` with
       "nothing was claimed - nothing to release". ~50 minutes were spent watching 50 stuck claims
       while every release call said it had worked.

Same shape as G7 (a bare `docker compose` resolving zero services and exiting 0), G19 (a
sub-workflow call silently passing null), G38 (a dangling errorWorkflow eating every failure) and
G41 (a switch dropping an unmatched item): something that should be either handled or loud is
instead quiet. The rule this gate encodes is the one those bugs cost us:

    A SKIP, A NO-OP AND A COMPLETED ACTION MUST BE DISTINGUISHABLE BY THE CALLER —
    from a field it can BRANCH on, not from prose in a `note` it would have to parse.

`status` is that field ('ran' | 'skipped' | 'refused' | 'noop' | 'error' | …). It is deliberately
separate from `ok`: `ok` answers "is anything wrong", `status` answers "what happened", and the
whole defect class lives in the gap between those two questions.

WHAT THIS CHECKS, two independent conditions, either one fails the gate:

  A. STRUCTURAL (scans every blueprint file, no per-file mapping needed): a Code node that emits a
     SKIP MARKER (`skipped:`, `_refuse:`, `_no_units:`) and is TERMINAL — nothing in the workflow
     consumes its output, so n8n hands exactly this object back to whoever called the workflow —
     must also emit `status:`. A terminal skip node IS the reply; if it cannot name itself, no
     caller can. Non-terminal guard nodes (`Scan Guard`, `Release Req`, `Build Units`) are
     deliberately out of scope: their markers are consumed by an `if` a few pixels to the right and
     never reach a caller, so requiring an outcome word there would be noise, and noise is how a
     gate gets ignored.

  B. REPLY CONTRACT (an explicit, hand-maintained map — `REPLY_NODES` below — of the Code nodes
     whose output an external caller actually reads; same reasoning as G39's `UPSERT_TARGETS` and
     G41's `DECIDE_SWITCH_PAIRS`: inferring "which node is the answer" from naming conventions is
     exactly the "probably right" heuristic `feedback_prefer_existing_mechanism_over_new_heuristic`
     warns against). Each declared reply node must
       B1. emit `status:`, and
       B2. never pair a hardcoded `ok:true` with a skip marker in the same node — that literal
           combination is #68 and #66 written out.

WHAT THIS DELIBERATELY DOES NOT CHECK. That the `status` VALUES are right, or that a caller
branches on them. A regex cannot know whether `released: 0` was a genuine no-op or a mis-addressed
delete — which is precisely why #68's real fix was to make the mis-addressed case IMPOSSIBLE
(`Release Req` now refuses a source `sync_registry` does not know) rather than to describe it
better. This gate keeps the vocabulary from disappearing again; it cannot supply the judgement.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

#: A Code node returning any of these is describing a NON-EVENT: an item/branch/pass that was not
#: acted on. `_empty` is absent on purpose — `Take X`/`Empty Result` use it as an internal "this
#: page had nothing" marker consumed one node later, never as a reply.
_SKIP_MARKER = re.compile(r"\b(?:skipped|_refuse|_no_units)\s*:")
#: the branchable outcome word. `ok:` alone does not count — that is the two-valued vocabulary this
#: gate exists because of.
_STATUS = re.compile(r"\bstatus\s*:")
#: a HARDCODED success, i.e. one that cannot depend on whether work happened.
_OK_TRUE = re.compile(r"\bok\s*:\s*true\b")

#: workflow blueprint path (repo-relative) -> the Code nodes whose output an EXTERNAL caller reads
#: (the BFF over the webhook, or a parent workflow over `executeWorkflow`). See docstring, check B.
REPLY_NODES: dict[str, list[str]] = {
    # the indox-manage door (2026-09-02: SCAN / RESET / unknown) — every verb's answer carries
    # `status` ('ran' | 'skipped' | 'error' | 'refused'); SCAN's `skipped` is the lock holder.
    "apps/indox/blueprint/n8n/SyncApi0000000001.workflow.ts": [
        "Scan Reply", "Reset Reply", "Unknown Action",
    ],
    # Sync Main's one caller-visible exit with nothing to run: Build Pipes emits the `_no_units`
    # sentinel (status 'noop'); the lock holder ends at a dead end, and the door reports it.
    "apps/indox/blueprint/n8n/syncV3Main0001.workflow.ts": [
        "Build Pipes",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
def terminal_code_nodes(doc: dict) -> list[dict]:
    """Code nodes whose `main` output nothing in this workflow consumes.

    n8n hands the last executed node's items back to the caller, so a branch that ends in one of
    these IS the workflow's answer on that path.
    """
    produces = set()
    for src, wiring in (doc.get("connections") or {}).items():
        for branch in (wiring.get("main") or []):
            if branch:
                produces.add(src)
    return [n for n in (doc.get("nodes") or [])
            if n.get("type") == "n8n-nodes-base.code" and n.get("name") not in produces]


def strip_comments(js_code: str) -> str:
    """`js_code` with `//` and `/* */` comments removed, string literals left intact.

    NOT cosmetic. Every node this gate reads carries a long explanatory header, and those headers
    quote the very shapes being linted — `Scan Result`'s own comment contains the sentence
    "ok:true ONLY when a unit really ran", which a naive regex reads as a hardcoded success. A gate
    that fires on its own documentation gets suppressed within a week. Quote tracking matters for
    the mirror-image reason: `'https://…'` and `detail:'…// …'` must not truncate real code.
    """
    out, i, n = [], 0, len(js_code or "")
    quote = None
    while i < n:
        c = js_code[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(js_code[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and js_code[i + 1] == "/":
            while i < n and js_code[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and js_code[i + 1] == "*":
            end = js_code.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def skip_without_status(js_code: str) -> bool:
    """check A / B1: describes a non-event but gives the caller nothing to branch on."""
    js = strip_comments(js_code or "")
    return bool(_SKIP_MARKER.search(js)) and not _STATUS.search(js)


def green_no_op(js_code: str) -> bool:
    """check B2: a hardcoded `ok:true` in the same breath as a skip marker."""
    js = strip_comments(js_code or "")
    return bool(_SKIP_MARKER.search(js)) and bool(_OK_TRUE.search(js))


def missing_status(js_code: str) -> bool:
    """check B1: a reply that never says what happened."""
    return not _STATUS.search(strip_comments(js_code or ""))


def find_node(doc: dict, name: str) -> dict | None:
    for n in doc.get("nodes") or []:
        if n.get("name") == name:
            return n
    return None


def _js(node: dict) -> str:
    return (node.get("parameters") or {}).get("jsCode") or ""


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    ("the #66 shape verbatim — a terminal skip with no outcome word: must catch", True,
     skip_without_status,
     "return [{json:{skipped:true, reason:'another pass is already running',"
     " note:'exited cleanly - not queued'}}];"),
    ("the same skip, now naming itself: must allow", False, skip_without_status,
     "return [{json:{ok:false, status:'skipped', code:'lock_held', skipped:true,"
     " reason:'another pass is already running'}}];"),
    ("a guard marker with a status: must allow", False, skip_without_status,
     "return [{json:{_refuse:true, status:'refused', code:'unknown_sync'}}];"),
    ("no skip marker at all — out of scope for this check: must allow", False, skip_without_status,
     "return [{json:{ok:true, delivered:3}}];"),
    ("the #68 shape — a hardcoded ok:true next to a skip marker: must catch", True, green_no_op,
     "return [{json:{ok:true, skipped:true, released:0, detail:'nothing to release'}}];"),
    ("ok computed from whether work happened, not hardcoded: must allow", False, green_no_op,
     "return [{json:{ok:n>0, status:n?'released':'noop', skipped:false, released:n}}];"),
    ("a reply with no status at all: must catch", True, missing_status,
     "return [{json:{ok:true, released:0}}];"),
    ("a reply that says what happened: must allow", False, missing_status,
     "return [{json:{ok:true, status:'released', released:2}}];"),
    ("a node whose own COMMENT quotes the linted shape: must allow (this exact false positive "
     "fired on 'Scan Result' before comments were stripped)", False, green_no_op,
     "// ok:true ONLY when a unit really ran\n"
     "/* a skipped:true pass is not ok:true */\n"
     "return [{json:{ok:okAll, status:'ran', skipped:false}}];"),
    ("a `//` inside a string literal must not truncate the code after it: must catch", True,
     green_no_op,
     "const u='https://n8n/rest';\nreturn [{json:{ok:true, skipped:true, u}}];"),
]

SELF_TEST_TERMINAL = [
    ("a Code node nothing consumes is terminal — it is the reply",
     {"nodes": [{"name": "Reply", "type": "n8n-nodes-base.code"},
                {"name": "Mid", "type": "n8n-nodes-base.code"}],
      "connections": {"Mid": {"main": [[{"node": "Reply"}]]}}},
     ["Reply"]),
    ("a branch wired to an EMPTY output list still counts its source as producing",
     {"nodes": [{"name": "A", "type": "n8n-nodes-base.code"}],
      "connections": {"A": {"main": [[]]}}},
     ["A"]),
    ("non-Code terminals are out of scope (no jsCode to read)",
     {"nodes": [{"name": "PG", "type": "n8n-nodes-base.postgres"}], "connections": {}},
     []),
]


def self_test() -> int:
    bad = 0
    print("predicates:")
    for label, should, fn, js in SELF_TEST:
        got = fn(js)
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {fn.__name__}: "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("terminal detection:")
    for label, doc, want in SELF_TEST_TERMINAL:
        got = [n["name"] for n in terminal_code_nodes(doc)]
        ok = got == want
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {got} (want {want}): {label}")
    total = len(SELF_TEST) + len(SELF_TEST_TERMINAL)
    print(f"\nG48 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings_a: list[tuple[str, str]] = []
    checked_a = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(path)
            except (OSError, ValueError):
                continue
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for node in terminal_code_nodes(doc):
                js = strip_comments(_js(node))
                if not _SKIP_MARKER.search(js):
                    continue
                checked_a += 1
                if skip_without_status(js):
                    findings_a.append((rel, str(node.get("name") or "?")))

    findings_b: list[tuple[str, str, str]] = []
    checked_b = 0
    for wf_rel, names in REPLY_NODES.items():
        wf_path = REPO / wf_rel
        if not wf_path.exists():
            findings_b.append((wf_rel, "?", "blueprint file not found — REPLY_NODES entry is stale"))
            continue
        try:
            doc = load_blueprint(wf_path)
        except (OSError, ValueError) as e:
            findings_b.append((wf_rel, "?", f"could not parse: {e}"))
            continue
        for name in names:
            checked_b += 1
            node = find_node(doc, name)
            if node is None:
                findings_b.append((wf_rel, name,
                                   "node not found — REPLY_NODES entry may be stale"))
                continue
            js = _js(node)
            if missing_status(js):
                findings_b.append((wf_rel, name,
                                   "reply declares no `status:` — the caller cannot tell a skip "
                                   "from a completed action"))
            if green_no_op(js):
                findings_b.append((wf_rel, name,
                                   "hardcoded `ok:true` alongside a skip marker — a no-op "
                                   "reporting success"))

    if not findings_a and not findings_b:
        print(f"G48 PASS — {checked_a} terminal skip node(s) name their outcome, and "
              f"{checked_b} declared reply node(s) honour the reply contract.")
        return 0

    print("G48 FAIL")
    if findings_a:
        print(f"\n  check A — {len(findings_a)} terminal skip node(s) with no `status:` "
              f"(the caller receives a non-event it cannot recognise):")
        for rel, name in findings_a:
            print(f"    {rel}  ::  {name!r}")
    if findings_b:
        print(f"\n  check B — {len(findings_b)} reply-contract violation(s):")
        for rel, name, why in findings_b:
            print(f"    {rel}  ::  {name!r}")
            print(f"        {why}")
    print(
        "\n  Give the reply an explicit `status:` ('ran' | 'skipped' | 'refused' | 'noop' | 'error')\n"
        "  and let `ok` mean only 'is anything wrong'. syncV3Main0001's 'Skip: Already Running' and\n"
        "  SyncApi0000000001's 'Release Result' are the worked examples. A caller that cannot BRANCH\n"
        "  on the outcome will guess, and every hour this defect class has cost was spent debugging\n"
        "  a pipeline that a green result said had already run."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
