#!/usr/bin/env python3
"""SHORT_DOC_ID: collapse the divergent derivations onto the ONE canonical formula.

    python3 scripts/ops/consolidate-short-doc-id-formula.py --check   # dry run, no writes
    python3 scripts/ops/consolidate-short-doc-id-formula.py --apply   # all-or-nothing rewrite

*** APPLYING THIS CHANGES REPO FILES ONLY. It takes effect on the live stack only after
*** `bbox n8n push`. Do not apply and walk away — an unpushed blueprint edit is a repo/live
*** divergence, and this one changes duplicate ADJUDICATION (see BEHAVIOUR CHANGE below).

════════════════════════════════════════════════════════════════════════════════
THE CANONICAL FORMULA — indoxIdentity01 "Compute Identity" is the single identity owner,
and its line 47 is the definition every other site must match:

    String(seed == null ? '' : seed).replace(/[^a-zA-Z0-9]/g, '').slice(-5).padStart(5, '0')

Its SQL twin (used by the data migrations) is
    lpad(right(regexp_replace(seed, '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')

════════════════════════════════════════════════════════════════════════════════
THE DIVERGENCES, measured 2026-08-06 by reading every `slice(-5)` site under
apps/indox/blueprint/n8n/. Three distinct derivations were in use:

  A. canonical — strip, last 5, zero-pad.
     indoxIdentity01, indoxV2Driver01, indoxV2ActionsGDoc01/Ship01 (both the bw1/bw2 write
     nodes and their lookup filters), indoxV2ActionsBS01's bw11 WRITE node. Not touched.

  B. NO PUNCTUATION STRIP — `(line.id ?? '').toString().slice(-5).padStart(5, '0')`
     indoxV2ActionsBS01, 2 sites, BOTH on the LOOKUP/filter path (the GET filter and the
     match-in-memory filter).

     *** THIS IS THE ONE THAT ACTUALLY BITES. *** In the SAME workflow, the WRITE node
     (bw11) uses the canonical form. So the BS lane STORES a stripped label and then
     SEARCHES for an unstripped one. Any balance-sheet line whose id contains punctuation
     is written as one label and looked up as another, the lookup misses, and the lane
     creates a second row for a document it already has. A formula that disagrees with
     itself inside one workflow is not a style difference — it is a duplicate factory.

  C. NO STRIP AND NO PAD — `$('Process Document').item.json.invoice_id.toString().slice(-5)`
     indoxGmailLinkDownloader01, 1 site, the SHORT_DOC_ID write. Also throws on a null
     invoice_id (`.toString()` on undefined), where the canonical form yields ''.

════════════════════════════════════════════════════════════════════════════════
BEHAVIOUR CHANGE — read before pushing.

Fixing B makes the BS lookups start MATCHING rows they previously missed. That is the
point, but it means documents that used to be created as fresh rows may now be adjudicated
as matches/duplicates instead. It changes dedupe outcomes on a live pipeline; it is not a
cosmetic edit. Push it deliberately and watch the BS lane's DOUBLE rate afterwards.

════════════════════════════════════════════════════════════════════════════════
NOT FIXED HERE, AND IT NEEDS AN OWNER DECISION — the '00000' placeholder.

`padStart(5,'0')` maps an EMPTY seed to the literal label '00000', and (COMPANY_ID,
SHORT_DOC_ID) is used as a match key. So every document of one company with no usable id
collapses into a single '00000' bucket and matches every other one.

PROVEN LIVE, from the rows' own audit column, 2026-08-06 — 11 rows carry
    DOUBLE_LINE_CONTEXT = {"idMatch":false,"hashMatch":false,"compShortDocMatch":"<other row>","match":true}
i.e. neither the id nor the content hash matched and the ONLY thing that made them DOUBLE
was the '00000' label: 10 rows on COMPANY_ID 516511375 and 1 on 513825943, all
SOURCE_TYPE='BALANCE_SHEET' with no COMPANY_DOC_ID, no DOC_ID and no HASH.

The fix is one line — make the canonical formula return '' rather than '00000' when the
stripped seed is empty:

    const s = String(seed == null ? '' : seed).replace(/[^a-zA-Z0-9]/g, '');
    return s === '' ? '' : s.slice(-5).padStart(5, '0');

It is NOT applied here because it is a semantic ruling, not a formula unification: it
changes what a label MEANS for id-less documents, and the 11 rows already adjudicated
DOUBLE on the bogus key would need re-adjudication (a STATUS change on live rows, which
indoxDataGateway01's LEGAL_TRANSITIONS governs). Owner decision.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
STRIP = r".replace(/[^a-zA-Z0-9]/g, '')"

#: (relative path, exact old substring, exact new substring, expected occurrences)
PATCHES: list[tuple[str, str, str, int]] = [
    # ---- B: indoxV2ActionsBS01 lookup paths — add the missing strip ------------------
    ("apps/indox/blueprint/n8n/indoxV2ActionsBS01.json",
     "SHORT_DOC_ID: (line.id ?? '').toString().slice(-5).padStart(5, '0')",
     "SHORT_DOC_ID: (line.id ?? '').toString()" + STRIP + ".slice(-5).padStart(5, '0')",
     2),
    # ---- C: indoxGmailLinkDownloader01 write — add the strip AND the pad -------------
    ("apps/indox/blueprint/n8n/indoxGmailLinkDownloader01.json",
     "$('Process Document').item.json.invoice_id.toString().slice(-5)",
     "String($('Process Document').item.json.invoice_id ?? '')" + STRIP
     + ".slice(-5).padStart(5, '0')",
     1),
]


def node_positions(path: pathlib.Path) -> list:
    """Every node's name+position, in file order. `position` decides execution order, so it
    must come out of this patch byte-identical."""
    wf = json.loads(path.read_text(encoding="utf-8"))
    return [(n.get("name"), n.get("position")) for n in wf.get("nodes", [])]


def scan() -> tuple[list[tuple[str, str, int, int]], list[str]]:
    rows, problems = [], []
    for rel, old, _new, want in PATCHES:
        p = REPO / rel
        if not p.exists():
            problems.append(f"MISSING: {rel}")
            continue
        have = p.read_text(encoding="utf-8").count(old)
        rows.append((rel, old[:56] + "…", want, have))
        if have == 0:
            problems.append(f"ALREADY CONSOLIDATED or drifted: {rel} (wanted {want})")
        elif have != want:
            problems.append(f"DRIFT: {rel} has {have} occurrence(s), manifest says {want} "
                            f"— re-review before applying")
    return rows, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.check or a.apply):
        ap.error("pass --check or --apply")

    rows, problems = scan()
    print(f"{'file':<58} {'want':>5} {'have':>5}")
    print("-" * 72)
    for rel, _snip, want, have in rows:
        print(f"{rel:<58} {want:>5} {have:>5}")
    print("-" * 72)
    print(f"{'TOTAL sites':<58} {sum(r[2] for r in rows):>5} {sum(r[3] for r in rows):>5}")

    if problems:
        print("\nPROBLEMS:")
        for pr in problems:
            print(f"  ! {pr}")

    if a.check:
        print("\nCHECK ONLY — nothing written.")
        return 1 if problems else 0
    if problems:
        print("\nREFUSING TO APPLY while problems are outstanding.")
        return 1

    # all-or-nothing: build every new body in memory, validate, then write
    staged: dict[pathlib.Path, str] = {}
    before_positions: dict[pathlib.Path, list] = {}
    for rel, old, new, want in PATCHES:
        p = REPO / rel
        before_positions[p] = node_positions(p)
        body = p.read_text(encoding="utf-8")
        body = body.replace(old, new)
        json.loads(body)                       # must still parse
        if body.count(old) != 0:
            raise RuntimeError(f"{rel}: old form survived the rewrite")
        staged[p] = body

    for p, body in staged.items():
        p.write_text(body, encoding="utf-8", newline="")

    # positions must be untouched — verify AFTER the write, against the real file
    for p, before in before_positions.items():
        if node_positions(p) != before:
            raise RuntimeError(f"{p}: node positions changed — REVERT THIS FILE")
    print(f"\nAPPLIED to {len(staged)} file(s). Node positions verified unchanged.")
    print("NOT DEPLOYED. The live stack still runs the old formula until `bbox n8n push`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
