#!/usr/bin/env python3
"""value-domain-lint — gate G54: a producer never writes outside a column's canonical value domain.

    python3 scripts/refactor/value-domain-lint.py [--self-test]

WHY THIS EXISTS. On 2026-08-06 the new extraction path (`BaseDocEx01` -> `Select Base`) began
writing **lowercase** `TYPE` values — `invoice`, `shipment`, `order`, `unknown`, `balance_sheet` —
into `incoming_documents`, alongside six years of UPPERCASE ones. 90 rows landed between 10:48 and
14:18 before it was caught, and the count was still climbing while it was being discussed.

It was invisible for the reason that makes this class dangerous: `resolveDocType()` uppercases, so
ROUTING kept working and nothing errored. Only the literal comparisons broke — SQL filters, the
webapp's STATUS/TYPE enums, dashboards, the sync map's own counts — each silently skipping the
lowercase documents. A silent undercount, growing with every document processed.

This is the same shape as three other defects found the same day (`FIGURE_COMPANY_COMPLETED` written
under a different name than the decider reads; trigger schemas; the gate registry): **two sources of
truth for one fact, one of them silent.** The new extraction path was built without the value
contract the old per-value steps satisfied being written down anywhere enforceable. This gate writes
it down.

WHAT IT CHECKS. For each (column, canonical domain) below, every literal a blueprint assigns to that
column must be in the domain, case-sensitively. Only literals are checked — an expression
(`={{ ... }}`, a variable) cannot be resolved statically and is skipped rather than guessed at, so
this gate has false negatives by design and no false positives.

NOT A SUBSTITUTE for normalising at the writer. The fix for the incident above was
`String(v).trim().toUpperCase()` in the one node that writes canonical `TYPE`; this gate is what
notices the next producer that forgets.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
# [2026-08-23] Blueprints are code (.workflow.ts) since 52b32aa4. This gate globbed *.json,
# matched zero files on disk, and reported PASS while checking nothing. n8n_blueprint is the
# ONE reader — see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

# column -> canonical domain. Sourced from apps/indox/blueprint/fixtures/schema.sql and the
# values six years of production rows actually carry.
DOMAINS: dict[str, set[str]] = {
    "TYPE": {"INVOICE", "SHIPMENT", "ORDER", "BALANCE_SHEET", "UNKNOWN", "GARBAGE"},
}

# `"TYPE": "invoice"` (n8n Set node) and `TYPE: 'invoice'` (Code node object literal).
ASSIGN = re.compile(
    r"""["']?(?P<col>[A-Z][A-Z0-9_]*)["']?\s*:\s*["'](?P<val>[A-Za-z_][A-Za-z0-9_ -]*)["']""")


def findings_for(text: str) -> list[tuple[str, str]]:
    out = []
    for m in ASSIGN.finditer(text):
        col, val = m.group("col"), m.group("val")
        dom = DOMAINS.get(col)
        if dom and val not in dom and val.upper() in dom:
            out.append((col, val))
    return out


SELF_TEST = [
    ("lowercase TYPE literal — must catch", True, '{"TYPE": "invoice"}'),
    ("code-node object literal — must catch", True, "return [{json:{TYPE: 'shipment'}}]"),
    ("correct uppercase — must allow", False, '{"TYPE": "INVOICE"}'),
    ("expression, unresolvable — must allow (never guess)", False,
     '{"TYPE": "={{ $json.TYPE }}"}'),
    ("a different column — must allow", False, '{"STATUS": "completed"}'),
    ("value outside the domain entirely — must allow (not a casing drift)", False,
     '{"TYPE": "kablan"}'),
]


def self_test() -> int:
    bad = 0
    for label, should, text in SELF_TEST:
        got = bool(findings_for(text))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG54 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()

    findings: list[tuple[str, str, str, str]] = []
    checked = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(str(path))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {path.relative_to(REPO)}: {e}")
                continue
            checked += 1
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for node in doc.get("nodes", []) or []:
                blob = json.dumps(node.get("parameters") or {}, ensure_ascii=False)
                for col, val in findings_for(blob):
                    findings.append((rel, str(node.get("name")), col, val))

    # A gate that read nothing has checked nothing. Where the blueprints cannot be compiled (no
    # node, no toolchain) every load above fails, and this used to end in PASS over zero of them.
    if not checked:
        print("G54 FAIL — read ZERO blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    if not findings:
        print(f"G54 PASS — across {checked} blueprint(s), every literal written to "
              f"{', '.join(DOMAINS)} is in its canonical domain.")
        return 0

    print(f"G54 FAIL — {len(findings)} literal(s) differ from the canonical value domain only by\n"
          f"case. Routing helpers normalise, so nothing errors — but every literal consumer (SQL\n"
          f"filters, the webapp enums, dashboards, sync counts) silently skips these rows:\n")
    for rel, node, col, val in findings:
        print(f"  {rel}")
        print(f"      node {node!r}: {col} = {val!r}  (canonical: {val.upper()!r})")
    print("\n  Normalise at the writer — e.g. String(v).trim().toUpperCase() — not at each reader.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
