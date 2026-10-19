#!/usr/bin/env python3
"""fixture-delete-scope-lint — gate G58: an E2E cleanup may only mutate its own fixture rows.

    python3 scripts/refactor/fixture-delete-scope-lint.py [--self-test] [--warn-fail]

WHY THIS GATE EXISTS

On 2026-08-06 a test suite deleted **2,432 real client documents** from
`public.incoming_documents`. Not a dropped table, not a TRUNCATE — a cleanup query that looked
scoped. `syncV3SourcesTest01`'s "Cleanup SQL" node builds this:

    delete from public.incoming_documents d using public.sync_ledger l
     where <prefix guard bound to l.source>
       and position('#inbox/' || l.platform_id in coalesce(d."SOURCE_LINK", '')) > 0

Two independent defects, either of which alone is fatal:

  1. THE GUARD IS ON THE WRONG SIDE OF THE JOIN. `l.source like 'sv3s_pb_%'` constrains which
     LEDGER rows take part. The DELETED relation `d` — the live client table — carries no
     fixture predicate at all. Its blast radius is "whatever the join happens to reach".
  2. THE JOIN CONDITION IS AN UNANCHORED SUBSTRING TEST ON AN IMAP UID. `platform_id` is an
     IMAP uid; the shortest one in this deployment's `sync_ledger` is **one character long**.
     `position('#inbox/1' in "SOURCE_LINK") > 0` therefore matches `#inbox/1b`,
     `#inbox/187`, `#inbox/195add2e3d872d82`… Measured read-only against the live database on
     2026-08-06, `platform_id = '1'` alone still matches 12 of the 12 surviving `#inbox/`
     documents. Before the incident there were 586.

Fourteen sibling cleanups in the same fleet were correctly prefix-scoped. That is the point:
they differ from the fifteenth only in having been written correctly, and each one restates
its own prefix list inline, so nothing mechanical stood between the fleet and this incident —
and nothing would stand between it and the next one. `scripts/test-fixture-prefixes.yaml` is
the single registry of what a fixture row looks like; this gate is what makes it binding.

THE RULES

Applied to every `delete ... from ... incoming_documents` inside `apps/*/blueprint/n8n/*.workflow.ts`
— bare, `public.`-qualified, or qualified with ANY `indox_*` tenant schema (`indox_test.` is where
Phase 4 moves the suites; a cleanup aimed at `indox_hacohen.` is scanned too, not excused) —
except (file, node) pairs named in the registry's `delete_allowlist`:

  F1  UNREGISTERED SCOPE. Every literal a marker-column predicate compares against must begin
      with a prefix registered in `test-fixture-prefixes.yaml`. This is what catches
      `"ID" LIKE 'db%'` and `"ID" LIKE 'pl%'`: the registered prefixes are `db_`/`dbf_`/`dbe_`
      and `plb_`/`plc_`/`plx_`, so `db%` and `pl%` are each strictly BROADER than anything the
      suite is allowed to own. Production document ids in this deployment really do share that
      two-character namespace (`do` 450 rows, `pt` 67 rows, measured live), so "no real row
      starts with db today" is a coincidence, not a guarantee.

  F2  UNGUARDED JOIN — THE INCIDENT. A delete with a `using` clause (or any second relation)
      must carry at least one literal, registered-prefix predicate bound to the DELETED
      relation's own alias. A guard on the join partner is not a guard.

  F3  CONTAINMENT IS NOT SCOPE. A delete may not be scoped by an unanchored containment test —
      `position(x in y)`, `strpos`, `like '%…'` — against the deleted relation. Containment
      says "this row mentions something of ours somewhere", which is not the same claim as
      "this row is ours", and the difference is 2,432 documents.

  F4  NO SCOPE AT ALL. A delete whose statement never names a marker column is unscoped.

  W1  UNESCAPED `_` (reported, does not fail by default). `_` is a LIKE wildcard, so
      `"ID" like 'sv3k_%'` also matches `sv3kZ…`. Every guard in the fleet except
      `mailOrgTest00001`'s `'mailorg\\_%'` is written this way. It is the same defect class as
      the incident — a match broader than intended — but strictly smaller in blast radius, and
      fixing all of them at once is a fleet-wide edit to live suite SQL that needs its own
      push window. Reported here so it cannot be forgotten; `--warn-fail` promotes it.

  W2  RUNTIME-VALUED SCOPE (reported). `indoxV2BSTest01` scopes by interpolated expression
      (`"LINKED_BS"=$q${{ … }}$q$`) rather than by literal. Not statically provable either way,
      so this gate declines to claim it is safe and declines to claim it is broken. Named so a
      reader knows the green above does not cover it.

WHAT THIS GATE DOES NOT COVER — read this before trusting a green.
  * It is STATIC. It reads committed blueprint JSON. It cannot see what a workflow currently
    active in n8n contains, and `bbox n8n pull` is the only thing that reconciles the two.
  * It polices DELETE and UPDATE (UPDATE added 2026-08-07). It does NOT police INSERT — a
    fixture INSERT that writes a row carrying no registered marker is invisible here, and that
    is not hypothetical: the `proc-gdoc`/`proc-bs` lanes write documents into the client table
    under the PRODUCTION `SYNC_NAME`s (`drive-gdoc`, `drive-bs`) with the only fixture trace
    mid-string in a `SOURCE_LINK` URL, so neither their own cleanup nor `fixture-sweep` can
    remove them. Nothing in this gate would have caught that either.
  * It reads only `parameters.query` and `parameters.jsCode`. SQL assembled anywhere else in a
    node — or in the Python services — is outside its reach.
  * It proves a delete is prefix-SCOPED. It does not prove the suite actually seeded rows under
    that prefix, nor that a crash before the cleanup leaves nothing behind — crash-safety is a
    transaction-shape problem, not a predicate-shape problem.
  * It cannot police SQL assembled from values only known at runtime (W2).
"""
from __future__ import annotations

import argparse
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

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO / "scripts" / "test-fixture-prefixes.yaml"
BLUEPRINT_GLOB = "apps/*/blueprint/n8n/*.workflow.ts"

#: [2026-08-31] The optional schema qualifier, shared by every mutation head below. Phase 4 moves
#: the suites' SQL off `public.<table>` onto the dedicated tenant schema `indox_test.<table>`. A
#: census that recognised only `public.` would not turn red on that move — it would stop
#: MATCHING, skip the statement, and keep printing PASS having scanned nothing, which is this
#: file's own named failure mode (see the glob note above). The alternation deliberately accepts
#: ANY `indox_*` schema, not just `indox_test`: a cleanup pointed at `indox_hacohen.` must enter
#: the census and face F1–F4 like everything else, not slip past because the census only knew
#: the schema its author was SUPPOSED to use. Quotes are tolerated the same way they are on the
#: table name (`indox_test."incoming_documents"`, JSON-escaped `\"` included).
_SCHEMA_Q = r"(?:\\?\"?(?:public|indox_[a-z0-9_]+)\\?\"?\s*\.\s*)?"

#: A delete whose target is the live document table, in any of the spellings the fleet uses.
_DELETE = re.compile(
    r"delete\s+from\s+" + _SCHEMA_Q + r"\\?\"?incoming_documents\\?\"?", re.I)

#: An UPDATE of the same table. Added 2026-08-07 after the DELETE-only scope cost a live
#: over-match: `syncV3SourcesTest01`'s `PB Row` joined the client table to the ledger with the
#: incident's own unanchored-uid predicate and matched **2,385 of 2,390** `#inbox/` documents.
#: That one was a read, so nothing was destroyed. The identical predicate on an UPDATE would
#: rewrite client data across the whole corpus, and — unlike the DELETE — leave no row-count drop
#: to notice afterwards. An UPDATE that escapes its prefix is strictly worse than a DELETE that
#: does, because the evidence of it is a changed value rather than a missing row.
_UPDATE = re.compile(
    r"update\s+" + _SCHEMA_Q + r"\\?\"?incoming_documents\\?\"?", re.I)

#: Either mutation. `finditer` over the alternation keeps statement order, which matters because
#: the CTE-shaped cleanups chain several mutations inside one string.
_MUTATION = re.compile(_DELETE.pattern + r"|" + _UPDATE.pattern, re.I)

#: Where a statement stops. `returning` first, because every CTE-shaped cleanup here ends there
#: and the enclosing string continues with the NEXT cte's delete.
_END = re.compile(r"\breturning\b|;", re.I)

#: The alias immediately after the table name, if any. `where`/`using` are not aliases.
_ALIAS = re.compile(r"\A\s*(?:as\s+)?(?!where\b|using\b|returning\b|set\b)"
                    r"([a-zA-Z_][a-zA-Z0-9_]*)\b", re.I)

_CONTAINMENT = re.compile(r"\b(?:position|strpos)\s*\(", re.I)


def _pred_re(markers) -> re.Pattern:
    """`d."SOURCE_ID" like 'sv3s_%'` — alias optional, JSON-escaped quotes tolerated.

    A `coalesce(d."SYNC_NAME",'') like '…'` wrapper counts as the same predicate. Not
    cosmetic: that is exactly how the repaired `syncV3SourcesTest01` join binds its guard to
    the deleted relation, and a gate that could not see through `coalesce` would have called
    the FIXED query broken — a false positive on the one query everybody is watching is how a
    gate gets switched off.
    """
    cols = "|".join(re.escape(c) for c in markers)
    return re.compile(
        r"(?:coalesce\s*\(\s*)?"
        r"(?:(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*)?"
        r"\\?\"(?P<col>" + cols + r")\\?\""
        r"(?:\s*,\s*'[^']*'\s*\))?"
        r"\s*(?P<op>like|ilike|=)\s*'(?P<lit>[^']*)'", re.I)


#: A bare LIKE pattern literal (`'gdx_inv%'`) anywhere in a delete-bearing node. The gdoc
#: suite builds its scope inside an n8n `{{ }}` expression whose branches are a JS map of
#: exactly these, so the predicate regex above sees only `"ID" LIKE '{{ …` and learns nothing.
#: Deliberately narrow — one token, no spaces — so `'PL Co %'` (a company NAME pattern in the
#: same node, matching a different table) is not dragged in.
#:
#: BOTH QUOTE STYLES, and that is not cosmetic. `indoxV2GDocTest01`'s "Batch Cleanup Prior"
#: holds its three lane patterns in a JS object literal keyed by lane —
#: `{'batch:inv':"gdx_inv%", …}` — in DOUBLE quotes, and only the `||` default `'gdx_%'` is
#: single-quoted. A single-quote-only scan therefore checked one branch of four and reported a
#: confident verdict on the other three, which is the "a check that cannot fail on the real
#: thing" failure this repo keeps rediscovering. Requiring a trailing `%` and a leading letter
#: is what keeps `"ID"` and other double-quoted SQL identifiers out.
_BARE_PATTERN = re.compile(r"['\"]((?:\\.|[A-Za-z][A-Za-z0-9_\-])[A-Za-z0-9_\-\\]*%)['\"]")

#: An n8n expression opener. A "literal" containing this is not a literal — it is the first few
#: characters of a `{{ … }}` template that happened to sit between two apostrophes.
_EXPR_OPEN = re.compile(r"\{\{")


def _col_mentioned_re(markers) -> re.Pattern:
    cols = "|".join(re.escape(c) for c in markers)
    return re.compile(r"\\?\"(?P<col>" + cols + r")\\?\"")


#: A CREATION SITE, in the three shapes this fleet actually uses. Measured before it was written:
#: across 81 blueprints there is ONE literal `insert into incoming_documents` and 61
#: `executeWorkflow` calls into a writer workflow, and the node that caused the 2026-08-07
#: contamination is one of the 61. A creation gate built around the word INSERT would have scanned
#: past the incident and reported clean — the same "check that cannot fail on the real thing"
#: this file exists to prevent.
_INSERT = re.compile(
    r"insert\s+into\s+" + _SCHEMA_Q + r"\\?\"?incoming_documents", re.I)
_INSERT_MODE = re.compile(r"\A(insert|upsert|insertorupdate)\Z", re.I)


def load_registry(text: str | None = None) -> dict:
    raw = text if text is not None else REGISTRY.read_text(encoding="utf-8")
    reg = yaml.safe_load(raw) or {}
    reg.setdefault("marker_columns", [])
    reg.setdefault("prefixes", [])
    reg.setdefault("live_poll_visible", [])
    reg.setdefault("document_writers", [])
    reg.setdefault("fixture_marker_key", "fixture_marker")
    reg.setdefault("insert_allowlist", [])
    reg.setdefault("insert_known_unmarked", [])
    # `delete_allowlist` was the name while this gate policed DELETE only. It covers UPDATE too
    # since 2026-08-07, so `mutation_allowlist` is the accurate name — both are read and merged
    # rather than one renamed, because a registry key that silently stops being honoured is how
    # an allowlist becomes a blindfold.
    reg["delete_allowlist"] = (reg.get("delete_allowlist") or []) + \
                              (reg.get("mutation_allowlist") or [])
    return reg


def registered_prefixes(reg: dict) -> list[str]:
    return [p["prefix"] for p in reg["prefixes"] if isinstance(p, dict) and p.get("prefix")]


def _unescape_like(lit: str) -> tuple[str, bool]:
    """Return (literal with LIKE escapes removed, whether every `_` in it was escaped).

    `\\\\` collapses to `\\` first. A `jsCode` node's value is JS SOURCE, so the SQL it emits
    has one fewer backslash level than the string stored in the blueprint — `'sv3s\\\\_%'` in
    the node is `sv3s\\_%` in the query. A `query` node has no doubled backslashes left after
    JSON decoding, so the collapse is a no-op there.
    """
    lit = lit.replace("\\\\", "\\")
    out, all_escaped, i = [], True, 0
    while i < len(lit):
        c = lit[i]
        if c == "\\" and i + 1 < len(lit):
            out.append(lit[i + 1])
            i += 2
            continue
        if c == "_":
            all_escaped = False
        out.append(c)
        i += 1
    return "".join(out), all_escaped


def _statement_end(text: str, start: int) -> int:
    """End of the SQL statement beginning at `start`.

    A statement ends at `;` or `returning` — but ONLY at one that is really SQL. Two things in
    these blueprints put those tokens somewhere they do not terminate anything, and both occur
    in one live node, indoxV2ActionsGlobal01 :: 'Record Base Doc Failure':

        UPDATE incoming_documents SET ...
          "REQUIRED_ACTION" = 'base extraction produced no answer (see ERROR) - fix the
                               file/link; ACTION_RESTART re-attempts once',
                                        ^ (1) inside a SQL string literal
          "ERROR" = LEFT('extract_base_doc: {{ ... .replace(/[...]/g, ';') }} ...', 500)
                                                                     ^ (2) inside an n8n expression
        WHERE "ID" = '{{ $json.ID }}' AND "STATUS" NOT IN ('COMPLETED','OLD');
                                                                              ^ the real end

    Splitting at (1) dropped the WHERE clause out of the slice, and the gate then reported its
    loudest finding — "UPDATE OF THE LIVE DOCUMENT TABLE WITH NO WHERE CLAUSE ... rewrites every
    row in the table" — about a statement scoped to a single "ID". A false positive on THAT
    message is expensive: it is indistinguishable from a real data-loss bug until somebody opens
    the node, and it trains readers to discount the gate.

    So this walks the text instead of regex-searching it, tracking two states:

      * `{{ ... }}` n8n expression — arbitrary JavaScript, checked FIRST because expressions are
        routinely interpolated INSIDE a SQL string (the LEFT(...) above), so "am I in a string"
        cannot be answered before "am I in an expression";
      * `'...'` SQL string literal, with `''` doubling handled as the escape it is.

    Only a terminator in neither state ends the statement.
    """
    i, n = start, len(text)
    in_expr = in_str = False
    while i < n:
        if text.startswith("{{", i):
            in_expr = True
            i += 2
            continue
        if in_expr:
            if text.startswith("}}", i):
                in_expr = False
                i += 2
            else:
                i += 1
            continue
        if text[i] == "'":
            if in_str and i + 1 < n and text[i + 1] == "'":
                i += 2                      # '' is an escaped quote, not a close
            else:
                in_str = not in_str
                i += 1
            continue
        if not in_str:
            if text[i] == ";":
                return i
            m = _END.match(text, i)
            if m and m.group(0).lower() != ";":
                return i
        i += 1
    return n


def _statements(text: str):
    """Yield (kind, start, tbl_end, end, statement_text) for each mutation of the table.

    `kind` is 'delete' or 'update'. They differ in three ways that matter to the rules below and
    in no other way:

      * the join keyword is `using` for DELETE and `from` for UPDATE;
      * an UPDATE has a `set` clause, and the columns assigned there are NOT scope. `update …
        set "SYNC_NAME" = 'sv3s_x'` mentions a marker column and scopes by nothing — reading the
        whole statement would let the SET clause satisfy the "names a marker column" test and
        turn F4 into a rubber stamp. So scope analysis starts at `where`;
      * an UPDATE with no `where` at all rewrites every row in the table.
    """
    for m in _MUTATION.finditer(text):
        end = _statement_end(text, m.end())
        kind = "delete" if m.group(0).lower().lstrip().startswith("delete") else "update"
        yield kind, m.start(), m.end(), end, text[m.start():end]


def _scope_part(kind: str, stmt: str) -> str | None:
    """The part of `stmt` that can carry scope. None means 'there is no WHERE clause'.

    For a DELETE the whole statement qualifies. For an UPDATE only the text from the first
    top-level `where` onward does — see `_statements`.
    """
    if kind == "delete":
        return stmt
    m = re.search(r"\bwhere\b", stmt, re.I)
    return stmt[m.start():] if m else None


def scan_node(rel: str, node: str, text: str, reg: dict) -> list[dict]:
    """Findings for one node's string. `text` is the DECODED JSON string, not the raw file."""
    markers = reg["marker_columns"]
    prefixes = registered_prefixes(reg)
    PRED = _pred_re(markers)
    MENTION = _col_mentioned_re(markers)
    findings: list[dict] = []

    def add(code, sev, msg, detail=""):
        findings.append({"file": rel, "node": node, "code": code,
                         "severity": sev, "msg": msg, "detail": detail})

    stmts = list(_statements(text))
    if not stmts:
        return findings

    # ── F1 / W1: every marker-column literal in this node must be a registered prefix ────
    # Node-wide, not statement-local: the sync suites hold their predicates in a JS object
    # literal (`docs:"\"SYNC_NAME\" like 'sv3f_mx_%'"`) and splice the VARIABLE into the SQL,
    # so a statement-local scan would see `"+S.docs+"` and find nothing to check. Checking the
    # node is what makes those suites analysable at all.
    expr_valued = False
    for pm in PRED.finditer(text):
        lit, op = pm.group("lit"), pm.group("op").lower()
        if lit in ("", "false", "true"):
            continue
        if _EXPR_OPEN.search(lit):
            # `"ID" LIKE '{{ (() => { let l='` — the regex closed on the apostrophe INSIDE an
            # n8n expression, so `lit` is template source, not a pattern. Reporting it as an
            # unregistered prefix is a false positive, and a gate that cries wolf on the one
            # node everybody is looking at is a gate that gets switched off. The scope is real
            # but arrives from the expression's branches, so it is checked below instead.
            expr_valued = True
            continue
        core = lit[:-1] if (op != "=" and lit.endswith("%")) else lit
        plain, all_escaped = _unescape_like(core)
        hit = next((p for p in prefixes if plain.startswith(p)), None)
        if hit is None:
            add("F1", "fail",
                f"predicate {pm.group(0).strip()} scopes by {lit!r}, which is not any prefix "
                f"registered in scripts/test-fixture-prefixes.yaml",
                f"registered: {sorted(prefixes)}")
        elif op != "=" and not all_escaped:
            add("W1", "warn",
                f"LIKE pattern {lit!r} leaves `_` unescaped — `_` is a LIKE wildcard, so this "
                f"also matches {plain[:len(hit)-1] + 'X'!r}...",
                f"write it as {core.replace('_', chr(92) + '_')!r} (or use starts_with())")

    # ── F1 (expression-valued form): the branches of the `{{ }}` must themselves be registered ──
    # When the pattern is chosen at runtime, the CHOICES are still committed source. `gdx_inv%`,
    # `gdx_ord%`, `gdx_shp%` and the `||` default `gdx_%` are all right there in the node, so the
    # node is fully analysable — just not through a predicate regex. Every one of them must be a
    # registered prefix; a node that interpolates and offers NO inspectable choices is the
    # genuinely opaque case, and that is W2's job, not a silent pass.
    if expr_valued:
        bare = {m.group(1) for m in _BARE_PATTERN.finditer(text)}
        if not bare:
            add("W2", "warn",
                "delete pattern is chosen by an n8n expression and the node offers no "
                "inspectable pattern literal — the gate can neither prove nor disprove that "
                "it stays inside its prefixes")
        for pat in sorted(bare):
            plain, all_escaped = _unescape_like(pat[:-1])
            hit = next((p for p in prefixes if plain.startswith(p)), None)
            if hit is None:
                add("F1", "fail",
                    f"expression-chosen delete pattern {pat!r} is not any prefix registered in "
                    f"scripts/test-fixture-prefixes.yaml",
                    f"registered: {sorted(prefixes)}")
            elif not all_escaped:
                add("W1", "warn",
                    f"expression-chosen LIKE pattern {pat!r} leaves `_` unescaped — `_` is a "
                    f"LIKE wildcard, so this also matches {plain[:len(hit)-1] + 'X'!r}...",
                    f"write it as {pat[:-1].replace('_', chr(92) + '_')!r}")

    # Does this NODE hold any literal marker-column predicate at all? The sync suites keep
    # theirs in a JS object literal and splice the variable into the SQL, so a statement that
    # reads `where "+S.docs+"` is still analysable — via the F1 pass above, which already
    # checked every one of those literals. A node with NO literal predicate anywhere is the
    # genuinely opaque case, and that is what W2 names.
    node_has_literal_pred = bool(list(PRED.finditer(text)))
    _INTERP = re.compile(r"\{\{|\$q\$|\"\s*\+|\+\s*\"")

    # ── per-statement rules ───────────────────────────────────────────────────────────────
    for kind, start, tbl_end, end, stmt in stmts:
        VERB = kind.upper()
        after = text[tbl_end:end]
        am = _ALIAS.match(after)
        alias = am.group(1).lower() if am else None
        # DELETE joins with `using`, UPDATE with `from`. Same rule, different keyword.
        joined = bool(re.search(r"\busing\b" if kind == "delete" else r"\bfrom\b", stmt, re.I))

        # An UPDATE with no WHERE rewrites the entire client table. There is no narrower way to
        # say this and no legitimate instance of it in a fixture cleanup, so it is reported
        # before anything else and the statement needs no further analysis.
        scope = _scope_part(kind, stmt)
        if scope is None:
            add("F4", "fail",
                "UPDATE OF THE LIVE DOCUMENT TABLE WITH NO WHERE CLAUSE — this rewrites every "
                "row in the table. Unlike a delete, it leaves no row-count drop behind to "
                "notice.", stmt[:220])
            continue
        stmt = scope

        if joined:
            guarded = False
            for pm in PRED.finditer(stmt):
                if (pm.group("alias") or "").lower() != (alias or ""):
                    continue
                lit, op = pm.group("lit"), pm.group("op").lower()
                core = lit[:-1] if (op != "=" and lit.endswith("%")) else lit
                plain, _ = _unescape_like(core)
                if any(plain.startswith(p) for p in prefixes):
                    guarded = True
                    break
            if not guarded:
                add("F2", "fail",
                    f"JOIN-SHAPED {VERB} WITH NO GUARD ON THE MUTATED RELATION"
                    f"{f' ({alias})' if alias else ''} — every prefix predicate here binds to "
                    f"the join partner, so the blast radius is whatever the join reaches. "
                    f"This is the shape that deleted 2,432 client documents on 2026-08-06"
                    + ("; on an UPDATE it rewrites them instead, leaving no missing rows to "
                       "notice." if kind == "update" else "."),
                    stmt[:400])
            if _CONTAINMENT.search(stmt):
                add("F3", "fail",
                    f"{kind} is joined by an unanchored containment test "
                    "(position/strpos) — 'mentions something of ours' is not 'is ours'",
                    stmt[:400])
            continue

        # ── single-table mutation ─────────────────────────────────────────────────────
        in_stmt = list(PRED.finditer(stmt))
        for pm in in_stmt:
            if pm.group("lit").startswith("%"):
                add("F3", "fail",
                    f"{kind} scoped by a leading-wildcard pattern "
                    f"{pm.group('lit')!r} — that is containment, not scope",
                    stmt[:300])
        if in_stmt:
            continue

        if _INTERP.search(stmt):
            # Scope arrives at runtime. Either the node's own literals carry it (checked by
            # F1 above), or nothing in this repo does.
            if not node_has_literal_pred:
                add("W2", "warn",
                    f"{kind} scope comes entirely from runtime-interpolated values, and this "
                    "node holds no literal prefix predicate anywhere — the gate can neither "
                    "prove nor disprove that it stays inside its prefixes",
                    stmt[:260])
        elif not MENTION.search(stmt):
            add("F4", "fail",
                f"{kind} names no marker column at all — it is unscoped",
                stmt[:220])

    return findings


def _allowed(reg: dict, rel: str, node: str) -> bool:
    for e in reg["delete_allowlist"]:
        if isinstance(e, dict) and e.get("file") == rel and e.get("node") == node:
            return True
    return False


# ── CREATION (INSERT) ─────────────────────────────────────────────────────────────────────────
# The invariant here is NOT scope. An INSERT has no WHERE, so there is nothing to over-match. What
# the 2026-08-07 contamination showed is that scope is unenforceable downstream when the row was
# born anonymous: `syncV3SourcesTest01`'s cleanup said `"SOURCE_ID" = 'sv3s_pg_src'` and matched 0
# rows for months, not because the predicate was wrong but because nothing had ever written that
# value. The cleanup could not be fixed at the query — GATES.md, "a read may reason from
# containment; a write may not" — so the obligation moves to the writer:
#
#     A ROW CREATED ON A PATH A FIXTURE CAN DRIVE MUST BE IDENTIFIABLE, AT BIRTH, BY AN ANCHORED
#     MATCH ON A REGISTERED MARKER COLUMN.
#
# "A path a fixture can drive" is DERIVED, never listed by hand. `syncV3Deliver0001` runs whatever
# a delivery names in `processor_wf`, unchanged, so the reachable set is exactly the `processor_wf`
# literals appearing inside blueprints that own a registered prefix. A hand-kept list would drift
# the first time a suite added a lane — and two lists that silently disagree is the failure this
# registry was created to end.


def fixture_owners(reg: dict) -> set[str]:
    """Blueprint stems that OWN a registered prefix — i.e. the suites."""
    return {str(p.get("owner", "")).rsplit("/", 1)[-1].rsplit(".", 1)[0]
            for p in reg["prefixes"] if isinstance(p, dict) and p.get("owner")}


def owner_prefixes(reg: dict, stem: str) -> list[str]:
    return [p["prefix"] for p in reg["prefixes"]
            if isinstance(p, dict) and p.get("prefix")
            and str(p.get("owner", "")).rsplit("/", 1)[-1].rsplit(".", 1)[0] == stem]


_PROC_WF = re.compile(r"processor_wf\s*:\s*['\"]([A-Za-z0-9_]+)['\"]")


def reachable_processors(reg: dict, files: dict[str, dict] | None = None) -> dict[str, set[str]]:
    """{processor workflow id: {suites that drive it}} — read out of the suites' own source."""
    files = files if files is not None else _load_blueprints()
    owners = fixture_owners(reg)
    out: dict[str, set[str]] = {}
    for rel, data in files.items():
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem not in owners:
            continue
        for n in data.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            for wf in _PROC_WF.findall(json.dumps(n.get("parameters") or {}, ensure_ascii=False)):
                out.setdefault(wf, set()).add(stem)
    return out


def creation_sites(data: dict, reg: dict):
    """Yield (node_name, kind, columns) for every place this blueprint can create a document row.

    `columns` maps column -> the value expression written to it. For a SQL insert there is no
    column map to read, so the whole statement is handed back under the key `_sql` and the rules
    fall back to substring tests — stated plainly rather than pretended otherwise.
    """
    writers = set(reg["document_writers"])
    for n in data.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        name, ntype = n.get("name", "?"), str(n.get("type", ""))
        params = n.get("parameters") or {}

        for key in ("query", "jsCode"):
            v = params.get(key)
            if isinstance(v, str) and _INSERT.search(v):
                yield name, "sql-insert", {"_sql": v}

        if ntype.endswith("executeWorkflow"):
            wid = params.get("workflowId")
            wid = wid.get("value") if isinstance(wid, dict) else wid
            cols = ((params.get("workflowInputs") or {}).get("value") or {})
            # An EMPTY column map is a passthrough (a node delegating its own input unchanged),
            # not a place where column values are decided. Nothing there can carry a marker, and
            # flagging it would push the reader toward stamping one at a node that has no values.
            if isinstance(wid, str) and wid in writers and isinstance(cols, dict) and cols:
                yield name, "writer-call:" + wid, dict(cols)

        if ("postgres" in ntype or "supabase" in ntype) and \
                _INSERT_MODE.match(str(params.get("operation", ""))) and \
                re.search(r"incoming_documents", json.dumps(params, ensure_ascii=False), re.I):
            yield name, "node-insert", {"_sql": json.dumps(params, ensure_ascii=False)}


def _ledger_entry(reg: dict, key: str, rel: str, node: str) -> dict | None:
    for e in reg[key]:
        if isinstance(e, dict) and e.get("file") == rel and e.get("node") == node:
            return e
    return None


def scan_creation(rel: str, data: dict, reg: dict,
                  reachable: dict[str, set[str]]) -> list[dict]:
    markers = set(reg["marker_columns"])
    prefixes = registered_prefixes(reg)
    mkey = reg["fixture_marker_key"]
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    owners = fixture_owners(reg)
    is_suite = stem in owners
    drivers = reachable.get(stem)
    findings: list[dict] = []

    if not (is_suite or drivers):
        return findings          # neither a suite nor anything a suite can drive

    for node, kind, cols in creation_sites(data, reg):
        if _ledger_entry(reg, "insert_allowlist", rel, node):
            continue
        known = _ledger_entry(reg, "insert_known_unmarked", rel, node)
        sev = "known" if known else "fail"

        def add(code, msg, detail=""):
            findings.append({"file": rel, "node": node, "code": code, "severity": sev,
                             "msg": msg,
                             "detail": (detail + ("\n      LEDGERED: " + " ".join(
                                 str(known.get("reason", "")).split())[:300]) if known else detail)})

        sql = cols.get("_sql")
        written = sorted(c for c in cols if c in markers)

        # ── I3: the site names no marker column at all ────────────────────────────────────
        if sql is not None:
            named = [m for m in markers if re.search(r"\b%s\b" % re.escape(m), sql)]
        else:
            named = written
        if not named:
            add("I3", "creation site writes NO registered marker column — a row it makes cannot "
                      "be identified as a fixture row by any anchored predicate, so no cleanup "
                      "and no sweep can ever find it")
            continue

        # ── I1: fixture-reachable production writer must keep a marker PATH ───────────────
        if drivers:
            routed = [c for c in written
                      if isinstance(cols.get(c), str) and mkey in cols[c]] \
                if sql is None else ([mkey] if mkey in sql else [])
            if not routed:
                add("I1",
                    "this workflow is driven by %s as a `processor_wf`, so a suite run creates "
                    "rows here under PRODUCTION identifiers, and no marker column routes through "
                    "`%s` — the rows are indistinguishable from client documents and neither the "
                    "suite's cleanup nor fixture-sweep can remove them. This is the 2026-08-07 "
                    "contamination exactly."
                    % (", ".join(sorted(drivers)), mkey),
                    "marker columns written: %s" % ", ".join(written or named))

        # ── I2: a suite seeding its own rows must stamp a prefix IT owns ──────────────────
        if is_suite:
            own = owner_prefixes(reg, stem)
            vals = [sql] if sql is not None else [v for v in cols.values() if isinstance(v, str)]
            hit = any(any(p in v for p in own) for v in vals)
            if not hit:
                add("I2",
                    "a suite that seeds document rows must stamp a prefix it OWNS (%s); this "
                    "creation site carries none, so its own cleanup cannot match what it created"
                    % ", ".join(own) or "(none registered)",
                    "marker columns written: %s" % ", ".join(written or named))

        # A SQL insert is analysed by substring, which is weaker than the column map. Say so
        # rather than let a green here read as the same strength as a green above.
        if sql is not None and (drivers or is_suite):
            findings.append({"file": rel, "node": node, "code": "I4", "severity": "warn",
                             "msg": "creation site is raw SQL, so the checks above are substring "
                                    "tests over the statement rather than reads of a column map — "
                                    "weaker evidence than a writer-call site gives",
                             "detail": ""})
    return findings


_BLUEPRINT_CACHE: dict[str, dict] | None = None


def _load_blueprints() -> dict[str, dict]:
    global _BLUEPRINT_CACHE
    if _BLUEPRINT_CACHE is None:
        out = {}
        for p in sorted(REPO.glob(BLUEPRINT_GLOB)):
            try:
                out[str(p.relative_to(REPO)).replace("\\", "/")] = load_blueprint(str(p))
            except (OSError, ValueError, CompileError):
                continue
        _BLUEPRINT_CACHE = out
    return _BLUEPRINT_CACHE


def scan(reg: dict | None = None) -> list[dict]:
    reg = reg or load_registry()
    out: list[dict] = []
    files = _load_blueprints()
    reachable = reachable_processors(reg, files)
    for rel, data in files.items():
        out.extend(scan_creation(rel, data, reg, reachable))
    for p in sorted(REPO.glob(BLUEPRINT_GLOB)):
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        try:
            data = load_blueprint(str(p))
        except (OSError, ValueError, CompileError):
            continue
        nodes = data.get("nodes") if isinstance(data, dict) else None
        if not isinstance(nodes, list):
            continue
        for n in nodes:
            if not isinstance(n, dict):
                continue
            name = n.get("name", "?")
            if _allowed(reg, rel, name):
                continue
            params = n.get("parameters") or {}
            for key in ("query", "jsCode"):
                v = params.get(key)
                if isinstance(v, str) and _MUTATION.search(v):
                    out.extend(scan_node(rel, name, v, reg))
    return out


# ── self-test ────────────────────────────────────────────────────────────────────────────
_REG = """
version: 1
marker_columns: [ID, SYNC_NAME, SOURCE_ID, HASH, LINKED_BS, COMPANY_ID]
prefixes:
  - {prefix: "db_",  owner: x, columns: [ID]}
  - {prefix: "plb_", owner: x, columns: [ID]}
  - {prefix: "gdx_", owner: x, columns: [ID]}
  - {prefix: "sv3s_", owner: x, columns: [SYNC_NAME, SOURCE_ID]}
  - {prefix: "mailorg_", owner: x, columns: [SYNC_NAME]}
live_poll_visible: ["plb_"]
delete_allowlist:
  - {file: apps/x/blueprint/n8n/Reset01.json, node: Clear Table, reason: reset tool}
"""

#: THE INCIDENT, VERBATIM. Copied out of syncV3SourcesTest01's "Cleanup SQL" node as it stands
#: in the working tree, with the JS concatenation collapsed the way the node emits it. A gate
#: that has only ever been watched passing has not been tested; this is the thing it must catch.
_INCIDENT = (
    'with j as (delete from public.incoming_documents d using public.sync_ledger l'
    ' where regexp_replace(l.source,\'^[^/]*/\',\'\') like \'sv3s_pb_%\''
    ' and position(\'#inbox/\'||l.platform_id in coalesce(d."SOURCE_LINK",\'\'))>0 returning 1)'
)

SELF_TEST = [
    # [2026-08-23] A `;` that does not end a statement. Both of these are one live node,
    # indoxV2ActionsGlobal01 :: 'Record Base Doc Failure'. Splitting on either dropped the
    # WHERE clause out of the slice and produced the F4 "rewrites every row in the table"
    # finding against a statement scoped to a single ID. Expect NO findings.
    ("semicolon inside a SQL string literal does not end the statement",
     'UPDATE incoming_documents SET "STATUS" = \'X\', "REQUIRED_ACTION" = \'no answer - fix the link; ACTION_RESTART re-attempts once\' WHERE "ID" = \'db_1\';', set()),
    ("semicolon inside an n8n {{ }} expression does not end the statement",
     'UPDATE incoming_documents SET "ERROR" = \'{{ String($json.R).replace(/[,]/g, \'\';\'\') }}\' WHERE "ID" = \'db_1\';', set()),
    # ── must catch ────────────────────────────────────────────────────────────────────
    ("THE INCIDENT: guard on the join partner, unanchored uid containment",
     _INCIDENT, {"F2", "F3"}),
    ("under-anchored prefix: 'db%' is broader than the registered 'db_'",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE 'db%';", {"F1"}),
    ("a prefix nobody registered",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE 'wat_%';", {"F1"}),
    # both findings are true of this one: `%db_` is neither a registered prefix (F1) nor a
    # scope (F3). A gate that reported only one of them would be understating it.
    ("leading-wildcard containment on a single-table delete",
     "DELETE FROM incoming_documents WHERE \"NAME\" LIKE '%db_x%' AND \"ID\" LIKE '%db_';",
     {"F1", "F3"}),
    ("no marker column at all",
     "DELETE FROM public.incoming_documents WHERE \"STATUS\" = 'IN_PROGRESS';", {"F4"}),
    ("join guarded on the partner only, even without containment",
     'delete from public.incoming_documents d using public.sync_ledger l'
     ' where l.source like \'sv3s_%\' and d."HASH" = l.platform_id returning 1', {"F2"}),

    # ── the Phase-4 tenant schema (2026-08-31) ────────────────────────────────────────────
    # The suites' SQL is moving from `public.` onto `indox_test.`. Each census regex extended
    # for that move gets a case here, because a census regex does not fail by giving a wrong
    # verdict — it fails by giving NO verdict: a mutation the census cannot match is never
    # scanned, and unscanned is indistinguishable from clean.
    ("THE INCIDENT respelled onto the tenant schema — the census must still see it (_DELETE)",
     _INCIDENT.replace("public.", "indox_test."), {"F2", "F3"}),
    ("unscoped delete on indox_test.incoming_documents is scanned and fails",
     "DELETE FROM indox_test.incoming_documents WHERE \"STATUS\" = 'IN_PROGRESS';", {"F4"}),
    ("correctly scoped delete on the tenant schema stays clean — no false positive",
     "DELETE FROM indox_test.incoming_documents WHERE \"ID\" LIKE 'plb\\_%';", set()),
    ("UPDATE with no WHERE is caught on the tenant schema too (_UPDATE)",
     'update indox_test.incoming_documents set "STATUS" = \'COMPLETED\'', {"F4"}),
    # The alternation accepts ANY indox_* schema on purpose: a suite whose cleanup aims at a
    # REAL tenant must face the same rules, not slip past a census that only knew the schema
    # the author was supposed to use.
    ("a cleanup pointed at ANOTHER tenant's schema is scanned, not slipped past",
     "DELETE FROM indox_hacohen.incoming_documents WHERE \"STATUS\" = 'OLD';", {"F4"}),

    # THE FALSE POSITIVE, VERBATIM. `indoxV2GDocTest01`'s "Batch Cleanup Prior" as it stands in
    # the tree. Every branch is registered (`gdx_`), so the honest verdict is clean — but the
    # predicate regex closes on the apostrophe inside `{{`, and the first version of this gate
    # reported `'{{ (() => { let l='` as an unregistered prefix. Kept as a self-test because a
    # false positive on a live suite is how a gate gets ignored, and because the double-quoted
    # branches are the part a single-quote-only scan never saw.
    ("expression-chosen pattern whose every branch is registered",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE '{{ (() => { let l='all';\n"
     "const m={'batch:inv':\"gdx_inv%\",'batch:ord':\"gdx_ord%\",'batch:shp':\"gdx_shp%\"};\n"
     "return m[l] || 'gdx_%'; })() }}';", {"W1"}),
    # …and the same shape with ONE branch outside the registry still fails. This is the check
    # that makes the case above a real pass rather than a blind spot: without it, "contains {{"
    # would be an unconditional amnesty.
    ("expression-chosen pattern with one unregistered branch",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE '{{ (() => { let l='all';\n"
     "const m={'batch:inv':\"gdx\\\\_inv%\",'batch:ord':\"nope\\\\_ord%\"};\n"
     "return m[l] || 'gdx\\\\_%'; })() }}';", {"F1"}),
    ("expression-chosen scope with no inspectable pattern at all",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE '{{ $json.pat }}';", {"W2"}),

    # ── UPDATE (added 2026-08-07) ──────────────────────────────────────────────────────
    # THE READ-SIDE TWIN, PROMOTED TO A WRITE. `syncV3SourcesTest01`'s `PB Row` carried exactly
    # this join and matched 2,385 of 2,390 `#inbox/` documents. It was a SELECT, so nothing was
    # destroyed. As an UPDATE it rewrites the same 2,385 client rows and — unlike a DELETE —
    # leaves no row-count drop behind. This is the case that motivated extending the gate.
    ("unanchored-uid UPDATE joined to the ledger, guard on the partner only",
     'update public.incoming_documents d set "STATUS" = \'X\' from public.sync_ledger l'
     ' where l.source like \'sv3s\\_pb\\_%\''
     ' and position(\'#inbox/\'||l.platform_id in coalesce(d."SOURCE_LINK",\'\'))>0',
     {"F2", "F3"}),
    # An UPDATE with no WHERE is the worst statement in the file and must never be a warning.
    ("UPDATE with no WHERE clause at all",
     'update public.incoming_documents set "STATUS" = \'COMPLETED\'', {"F4"}),
    # THE SET-CLAUSE TRAP. `set "SYNC_NAME" = 'sv3s_x'` MENTIONS a marker column and assigns a
    # registered-looking prefix, but assigning a value is not scoping a row. Analysing the whole
    # statement would let the SET clause satisfy F4 and turn it into a rubber stamp; scope
    # analysis therefore starts at `where`. Without this narrowing the case below reads clean.
    ("UPDATE whose only marker column is in the SET clause, not the WHERE",
     'update public.incoming_documents set "SYNC_NAME" = \'sv3s\\_x\' where "STATUS" = \'OLD\'',
     {"F4"}),
    ("UPDATE scoped by an unregistered prefix",
     'update public.incoming_documents set "STATUS" = \'X\' where "ID" like \'wat\\_%\'', {"F1"}),
    ("correctly scoped single-table UPDATE",
     'update public.incoming_documents set "STATUS" = \'X\' where "ID" like \'plb\\_%\'', set()),
    ("an UPDATE join that IS guarded on the mutated relation",
     'update public.incoming_documents d set "STATUS" = \'X\' from public.sync_ledger l'
     ' where l.source like \'sv3s\\_%\' and d."SYNC_NAME" like \'sv3s\\_%\'', set()),

    # ── must allow ────────────────────────────────────────────────────────────────────
    ("correctly scoped single-table delete",
     "DELETE FROM incoming_documents WHERE \"ID\" LIKE 'plb\\_%';", set()),
    ("correctly escaped, the way mailOrgTest00001 writes it",
     "delete from public.incoming_documents where \"SYNC_NAME\" like 'mailorg\\_%' returning 1",
     set()),
    # equality has no wildcards, so the unescaped `_` in `sv3s_` is not a widening here
    ("equality on a registered prefix",
     "DELETE FROM incoming_documents WHERE \"SYNC_NAME\" = 'sv3s_drive-gdoc';", set()),
    ("a join that IS guarded on the deleted relation",
     'delete from public.incoming_documents d using public.sync_ledger l'
     ' where l.source like \'sv3s\\_%\' and d."SYNC_NAME" like \'sv3s\\_%\' returning 1', set()),
    ("the JS-builder shape: predicate lives in an object literal, spliced as a variable",
     'const S={a:{docs:"\\"SYNC_NAME\\" like \'sv3s\\\\_%\'"}};'
     'const sql="delete from public.incoming_documents where "+S.docs+" returning 1";', set()),
    # `docs:"false"` deletes nothing, but the gate cannot see that through the splice and says
    # so (W2) rather than claiming a green it has not earned.
    ("a `false` no-op predicate is reported, not failed",
     'const S={a:{docs:"false"}};'
     'const sql="delete from public.incoming_documents where "+S.docs+" returning 1";',
     {"W2"}),
]


#: A registry for the CREATION self-tests: one suite that owns `sv3s_`, one writer workflow, one
#: allowlisted site and one ledgered site.
_REG_CREATE = """
version: 1
marker_columns: [ID, SYNC_NAME, SOURCE_ID, HASH, COMPANY_ID]
prefixes:
  - {prefix: "sv3s_", owner: apps/x/blueprint/n8n/Suite01.json, columns: [SOURCE_ID]}
document_writers: [Writer01]
fixture_marker_key: fixture_marker
insert_allowlist:
  - {file: apps/x/blueprint/n8n/CentralWriter01.json, node: Build Deliver, reason: the writer itself}
insert_known_unmarked:
  - {file: apps/x/blueprint/n8n/ProcLedgered01.json, node: Upsert, reason: known broken, task: T}
"""


def _wf(*nodes):
    return {"nodes": list(nodes)}


def _call(name, cols, wid="Writer01"):
    return {"name": name, "type": "n8n-nodes-base.executeWorkflow",
            "parameters": {"workflowId": {"value": wid},
                           "workflowInputs": {"value": cols}}}


def _suite(*procs):
    """A suite node that names processors, which is how reachability is derived."""
    return {"name": "Unit Req", "type": "n8n-nodes-base.code",
            "parameters": {"jsCode": "return [{json:{" + ",".join(
                "processor_wf:'%s'" % p for p in procs) + "}}];"}}


MARKED = "={{ ($json.ctx||{}).fixture_marker || $json.id }}"
SELF_TEST_CREATE = [
    # ── the incident, and its repair ─────────────────────────────────────────────────────
    ("THE HOLE: a fixture-reachable processor writes production identifiers, no marker path",
     "Proc01", _wf(_call("Upsert", {"SOURCE_ID": "={{ $json.id }}", "SYNC_NAME": "drive-gdoc"})),
     {"I1"}),
    ("THE REPAIR: same node, marker routed through the ctx key",
     "Proc01", _wf(_call("Upsert", {"SOURCE_ID": MARKED, "SYNC_NAME": "drive-gdoc"})), set()),
    ("a fixture-reachable creation site naming NO marker column at all",
     "Proc01", _wf(_call("Upsert", {"NAME": "x", "STATUS": "IN_PROGRESS"})), {"I3"}),
    # ── scope: only suites and what suites drive ─────────────────────────────────────────
    ("an unreachable production workflow is out of scope entirely",
     "Unrelated01", _wf(_call("Upsert", {"SOURCE_ID": "={{ $json.id }}"})), set()),
    ("an EMPTY column map is a passthrough, not a creation site",
     "Proc01", _wf(_call("Delegate", {})), set()),
    ("a writer call to a workflow that is not a registered document writer is ignored",
     "Proc01", _wf(_call("Upsert", {"SOURCE_ID": "={{ $json.id }}"}, wid="SomethingElse01")),
     set()),
    # ── suites seeding their own rows ────────────────────────────────────────────────────
    ("a suite seeding with a prefix it owns",
     "Suite01", _wf(_call("Seed", {"SOURCE_ID": "sv3s_pg_src"})), set()),
    ("a suite seeding with NO owned prefix anywhere in the site",
     "Suite01", _wf(_call("Seed", {"SOURCE_ID": "={{ $json.driveFileId }}"})), {"I2"}),
    # ── the two ledgers ──────────────────────────────────────────────────────────────────
    ("insert_allowlist suppresses the central writer",
     "CentralWriter01", _wf({"name": "Build Deliver", "type": "n8n-nodes-base.code",
                             "parameters": {"jsCode": "insert into incoming_documents (a) ..."}}),
     set()),
    # ── raw SQL is analysable, but more weakly, and says so ──────────────────────────────
    ("raw SQL in a suite: prefix present, but flagged as substring-only evidence",
     "Suite01", _wf({"name": "Seed SQL", "type": "n8n-nodes-base.code",
                     "parameters": {"jsCode": "insert into public.incoming_documents "
                                              "(\"SOURCE_ID\") values ('sv3s_pg_src')"}}),
     {"I4"}),
    # Phase-4 tenant schema (2026-08-31): the _INSERT census must keep seeing creation sites
    # after the suites' SQL moves onto `indox_test.` — an unmatched insert is not a clean
    # insert, it is an unscanned one.
    ("raw SQL insert respelled onto the tenant schema is still a creation site (_INSERT)",
     "Suite01", _wf({"name": "Seed SQL", "type": "n8n-nodes-base.code",
                     "parameters": {"jsCode": "insert into indox_test.incoming_documents "
                                              "(\"SOURCE_ID\") values ('sv3s_pg_src')"}}),
     {"I4"}),
]


def self_test_create(reg: dict) -> tuple[int, int]:
    """Each case is a whole synthetic blueprint set, because reachability is DERIVED from the
    suite's own nodes — testing `scan_creation` on one file in isolation would test a different
    function than the one that runs."""
    bad = 0
    for label, stem, wf, expect in SELF_TEST_CREATE:
        rel = "apps/x/blueprint/n8n/%s.json" % stem
        files = {rel: wf,
                 "apps/x/blueprint/n8n/Suite01.json": _wf(_suite("Proc01", "ProcLedgered01"))}
        if stem == "Suite01":                       # the suite under test IS the suite file
            files["apps/x/blueprint/n8n/Suite01.json"] = _wf(_suite("Proc01"), *wf["nodes"])
        reach = reachable_processors(reg, files)
        got = {f["code"] for f in scan_creation(rel, files[rel], reg, reach)}
        ok = got == expect
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] expected {sorted(expect) or '(clean)'}, "
              f"got {sorted(got) or '(clean)'}: {label}")
    # the defect ledger must downgrade severity WITHOUT hiding the finding — both halves asserted,
    # because an exemption that also silenced the message would be indistinguishable from a pass.
    rel = "apps/x/blueprint/n8n/ProcLedgered01.json"
    files = {rel: _wf(_call("Upsert", {"SOURCE_ID": "={{ $json.id }}"})),
             "apps/x/blueprint/n8n/Suite01.json": _wf(_suite("ProcLedgered01"))}
    f = scan_creation(rel, files[rel], reg, reachable_processors(reg, files))
    for prop, ok in (("a ledgered site is still REPORTED", len(f) == 1 and f[0]["code"] == "I1"),
                     ("a ledgered site does not FAIL the build",
                      len(f) == 1 and f[0]["severity"] == "known"),
                     ("a ledgered site carries its reason into the output",
                      len(f) == 1 and "LEDGERED" in f[0]["detail"])):
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {prop}")
    return len(SELF_TEST_CREATE) + 3, bad


def self_test(warn_fail: bool = False) -> int:
    reg = load_registry(_REG)
    bad = 0
    for label, text, expect in SELF_TEST:
        got = {f["code"] for f in scan_node("apps/x/blueprint/n8n/T.json", "N", text, reg)}
        ok = got == expect
        if not ok:
            bad += 1
        print(f"  [{'ok ' if ok else 'FAIL'}] expected {sorted(expect) or '(clean)'}, "
              f"got {sorted(got) or '(clean)'}: {label}")
    print("\n  — creation (INSERT) rules —")
    n_create, bad_create = self_test_create(load_registry(_REG_CREATE))
    total = len(SELF_TEST) + n_create
    bad += bad_create
    print(f"\nG58 self-test: {total - bad}/{total} passed "
          f"({len(SELF_TEST)} mutation, {n_create} creation)")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--warn-fail", action="store_true",
                    help="promote W1/W2 to failures (the end state, not today's)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    reg = load_registry()
    findings = scan(reg)
    fails = [f for f in findings if f["severity"] == "fail"]
    warns = [f for f in findings if f["severity"] == "warn"]
    known = [f for f in findings if f["severity"] == "known"]
    n_files = len(list(REPO.glob(BLUEPRINT_GLOB)))
    # [2026-08-23 G66/C] AN EMPTY SCAN IS A RED, NEVER A PASS. This repo has already lived the
    # other way: twelve gates globbed apps/*/blueprint/n8n/*.json after blueprints became
    # .workflow.ts in 52b32aa4, matched nothing, looped over nothing, and printed their success
    # line for weeks. Green and blind are indistinguishable from OUTSIDE, so nothing surfaced it.
    # The glob is right today; this guard is what makes it stay honest if the layout moves again.
    if not n_files:
        print("G61 FAIL - scanned 0 blueprint(s) via %s. That is not a clean run, it is no run:"
              " a measurement over zero inputs is not a low score, it is no score." % BLUEPRINT_GLOB)
        return 1
    reach = reachable_processors(reg)

    def show(group, head):
        print(head)
        for f in group:
            print(f"\n  {f['file']}  node={f['node']!r}  [{f['code']}]")
            print(f"      {f['msg']}")
            if f["detail"]:
                print(f"      {f['detail'][:400]}")

    if fails:
        show(fails, f"G58 FAIL — {len(fails)} unsafe fixture mutation(s)/creation(s):")
    if known:
        # A DEFECT LEDGER, NOT AN ALLOWLIST. These are true positives the gate can see and that are
        # not fixed yet. Printing them every run, with the reason, is what stops an exemption
        # becoming silence — the failure mode of every allowlist that ever went stale.
        show(known, f"\nG58 KNOWN DEFECTS — {len(known)} creation site(s) exempted from failing "
                    f"by `insert_known_unmarked`, and still broken:")
    if warns:
        show(warns, f"\nG58 reported (non-blocking) — {len(warns)} warning(s):")
    if fails or warns or known:
        print("\n  Prefix registry: scripts/test-fixture-prefixes.yaml")
        print("  Scope of this gate's verdict is in its module docstring — read it before")
        print("  treating a green here as 'the suites cannot touch production'.")

    if fails or (a.warn_fail and warns):
        return 1
    print(f"G58 PASS — across {n_files} blueprint(s): every delete/update against "
          f"incoming_documents is scoped to a registered prefix, and every creation site on a "
          f"fixture-reachable path carries a registered marker."
          + (f" ({len(warns)} non-blocking warning(s) above)" if warns else ""))
    print(f"  creation scope: {len(reach)} production workflow(s) are reachable as a "
          f"`processor_wf` from a fixture-owning blueprint — "
          + ", ".join(f"{k} (via {','.join(sorted(v))})" for k, v in sorted(reach.items())))
    if known:
        print(f"  {len(known)} KNOWN DEFECT(S) above are exempted, not fixed — a green here does "
              f"NOT mean every creation site is marked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
