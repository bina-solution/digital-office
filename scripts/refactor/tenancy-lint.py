#!/usr/bin/env python3
"""tenancy-lint — gate G28: a query against a tenant-scoped table must name its discriminator.

(This had no number of its own and ran in CI as "G22", which is profile-gate-lint.py's number.
Registry: scripts/refactor/GATES.md.)

THREE SCANS, ONE RULE (was two — see 2026-07-31 below)
  * n8n workflows — `settings`, `companies` and `tag_rules` carry an `instance`
    discriminator column (indox-final-plan phase 6.2).
  * n8n workflows AGAIN — `drive_files` carries a `profile` discriminator (added
    2026-07-31). Added after `apps/indox/blueprint/n8n/syncV3FullTest01.json`'s
    "CH Bad Seed" node shipped a raw `insert into drive_files` with no `profile`,
    and this gate — which already existed and already enforced `profile` on the
    Python side — printed OK the whole time, because its n8n scanner only ever
    knew about `settings`/`companies`/`tag_rules`. The bug and the gate lived in
    the same file family and never met. Not a hypothetical: this is the exact
    claim K-series review work (`ai/context/review-claims-verdicts.md`) would
    have called CONFIRMED had anyone asked it about n8n JSON instead of only
    `apps/drive/**/*.py`.
  * drive's own source — same `drive_files` -> `profile` rule, applied to the
    Python queries. Drive's PRODUCTION queries live here, not in workflow JSON —
    n8n calls `driveApi01`, which calls this code. Kept exactly as it was.

`settings`, `companies` and `tag_rules` carry an `instance` discriminator column
(indox-final-plan phase 6.2). Documents stay table-per-instance; these three do
not, because they are small, uniformly shaped, and read on every request.

A discriminator column has exactly one failure mode, and it is silent:

    select value from public.settings where key='sync_registry'

That is a perfectly good query. It parses, it runs, it returns a row. With one
instance it returns the right row, so it passes every test anyone writes today.
With two, it returns whichever instance sorts first — and the pipeline that ran
it proceeds to reconcile one client's documents against another client's
registry. Nothing raises. Nothing looks wrong. The only evidence is documents
arriving in a table they do not belong to.

The write side is worse: an INSERT without `instance` lands on the column
default, which means it OVERWRITES the first instance's configuration and
reports success.

Neither is catchable by review — the missing thing is absent, and absence does
not show up in a diff. So it is caught here instead.

WHAT COUNTS AS SAFE
  * an `instance` predicate in the SQL, or an `instance` key in the request the
    chokepoint builds SQL from
  * `instance:'*'` — reading deliberately ACROSS instances. The scanner needs
    this: it must see every instance's registry in order to fan out to them.
    Spelled explicitly so that reading everything is always a decision.
  * the chokepoint nodes themselves (`Build Table Get` / `Build Table Upsert`),
    which are where the predicate is added

Exit 1 listing every workflow node that names a tenant table without one.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
# [2026-08-23] Blueprints are code (.workflow.ts) since 52b32aa4. This gate globbed *.json,
# matched zero files on disk, and reported PASS while checking nothing. n8n_blueprint is the
# ONE reader — see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

# This gate PRINTS the offending SQL when it finds a violation, and the SQL it lints contains Hebrew
# column values. On Windows stdout defaults to the ANSI codepage (cp1255 here), so printing that line
# raises UnicodeEncodeError — the gate would crash precisely when it had something to report, and the
# crash would read as a broken tool rather than a found defect. G10 (portability-lint) flags exactly
# this shape; it was flagging this file.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TENANT_TABLES = ("settings", "companies", "tag_rules")

#: n8n's OWN copy of drive_files's discriminator (scan_source(), below, is the Python copy). The
#: same table, the same rule, checked where n8n workflows can ALSO write raw SQL against it — which
#: is exactly how "CH Bad Seed" shipped uncaught: it is Python-only in name, JSON-blind in fact.
N8N_TENANT_TABLES = {"instance": TENANT_TABLES, "profile": ("drive_files",)}

#: the chokepoints — they ADD the predicate, so they legitimately mention the
#: tables without carrying one themselves
EXEMPT_NODES = {"Build Table Get", "Build Table Upsert"}

#: `sync_pipe_state`, `sync_ledger` etc. are scoped by `source` (the pipe name),
#: not by `instance` — do not flag them for a missing instance. Irrelevant to the `profile` scan
#: (drive_files is not in this set), kept as one rule so it is not silently reinterpreted per table.
NOT_TENANT = re.compile(r"\b(sync_ledger|sync_cursor|sync_attempt|sync_pipe_state)\b")

# The blob being searched is `json.dumps(parameters)`, so a SQL identifier written `"instance"` in
# the workflow arrives here as `\"instance\"`. Allowing the escape is not cosmetic — without it the
# lint reports the nodes that DID scope themselves and stays quiet about nothing, which is the one
# way to make a linter get switched off.
_Q = r"""\\?["']?"""


def _has_discriminator(text: str, discriminator: str) -> bool:
    pat = re.compile(
        _Q + discriminator + _Q + r"\s*[:=]"       # instance: 'x'  /  "profile" = 'x'
        r"|\b" + discriminator + r"\b\s*=\s*\$"     # instance = $1  (parameterised)
        r"|" + _Q + discriminator + _Q + r"\s*,"    # ("instance", "שם חברה", …) — an INSERT column list
        r"|" + _Q + discriminator + _Q + r"\s*\)"   # "...values (..., (select id ... limit 1))" — the
    )                                                # discriminator NAME appears in the column list,
    return bool(pat.search(text))                    # its VALUE may be a subquery, not a literal


def scan(path: pathlib.Path, tables: tuple[str, ...], discriminator: str) -> list[tuple[str, str, str]]:
    try:
        doc = load_blueprint(str(path))
    except (OSError, ValueError, CompileError):
        return []
    # public.<table>  — the qualified SQL form
    sql_ref = re.compile(r"\bpublic\.(%s)\b" % "|".join(tables))
    # …and the BARE form. Not a nicety: `INSERT INTO companies` and `select … from settings` both
    # appear in shipped workflows, so a lint that only knows the qualified spelling prints OK over
    # exactly the queries that are wrong. Anchored to statement keywords so the word "settings" in
    # prose or in a node name does not trip it.
    sql_bare = re.compile(
        r"\b(?:from|into|update|join)\s+(?:public\.)?(%s)\b" % "|".join(tables), re.IGNORECASE,
    )
    # table: 'settings' — the chokepoint-request form (instance scan only; no drive_files chokepoint
    # exists in n8n today — production drive access goes through driveApi01, not a raw {table:} req)
    req_ref = re.compile(r"""["']?table["']?\s*[:=]\s*["'](%s)["']""" % "|".join(tables))

    out = []
    for node in doc.get("nodes", []) or []:
        name = str(node.get("name") or "?")
        if name in EXEMPT_NODES:
            continue
        params = node.get("parameters", {}) or {}
        blob = json.dumps(params, ensure_ascii=False)

        # SQL patterns are matched against the SQL FIELD ONLY, never the whole node. A code node
        # whose comment reads "// keep the name the resolver resolved (from settings)" is English
        # prose, not a query — and a lint that reports it teaches people to ignore the lint. The
        # field split is the honest discriminator: SQL lives in `query`, JavaScript in `jsCode`.
        sql = params.get("query")
        sql = sql if isinstance(sql, str) else ""
        hit = sql_bare.search(sql) or sql_ref.search(sql) or req_ref.search(blob)
        if not hit:
            continue
        # a node that only touches the source-scoped sync tables is not in scope
        if NOT_TENANT.search(blob) and not req_ref.search(blob):
            continue
        if _has_discriminator(sql if sql else blob, discriminator) or _has_discriminator(blob, discriminator):
            continue
        out.append((path.name, name, hit.group(1)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE SCANNER — the same rule, applied to SQL written in Python.
#
# drive's index table `drive_files` is scoped by `profile`. Every read and every
# write in apps/drive must name it; a query that does not returns (or overwrites)
# another profile's files, silently, and returns a perfectly good-looking row
# while doing it.
#
# The SQL is reconstructed from the AST rather than grepped, because the queries
# are built by concatenating a module-level column list with a WHERE clause
# (`SELECT_COLS + "WHERE profile=%s ..."`). A line-based grep sees the half
# without the predicate and reports the file that is correct.
# ─────────────────────────────────────────────────────────────────────────────
SOURCE_TABLES = {"drive_files": "profile"}
SOURCE_ROOTS = ("apps/drive/**/*.py",)

#: DDL and catalogue reads are not tenant queries — they are about the table, not about rows in it.
_DDL = re.compile(r"^\s*(create|alter|drop)\b", re.IGNORECASE)
_CATALOG = re.compile(r"information_schema", re.IGNORECASE)

#: What makes a string a QUERY rather than a log line that happens to name the table. Either the
#: call is the database chokepoint, or the text reads as DML. Without this the scanner flags
#: `print(f"[drive] migrated drive_files.{col}")`, and a lint that reports prose gets switched off.
_SQL_CALLEES = {"q", "execute", "executemany"}
_DML = re.compile(r"\b(select|insert|update|delete|from|into|join)\b", re.IGNORECASE)


def _callee(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""

#: The one deliberate exemption, spelled on the line(s) above the call so that reading
#: across every profile is always a decision somebody wrote down.
_ALLOW = "tenancy-lint: allow-unscoped"


def _flatten(node: ast.AST, consts: dict[str, str]) -> str:
    """Best-effort literal text of a SQL expression: constants, module-level string names, `+`
    concatenation and f-strings. An interpolated value becomes `?`, which is the honest answer —
    the lint cannot see through it, and a WHERE clause hidden behind one is exactly what it is
    here to refuse."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.Name):
        return consts.get(node.id, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten(node.left, consts) + _flatten(node.right, consts)
    if isinstance(node, ast.JoinedStr):
        return "".join(_flatten(v, consts) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return " ? "
    return ""


def scan_source(path: pathlib.Path) -> list[tuple[str, str, str]]:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return []
    lines = src.splitlines()
    consts: dict[str, str] = {}
    for node in tree.body:                       # module-level string constants only
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Constant, ast.BinOp)):
            text = _flatten(node.value, consts)
            for t in node.targets:
                if isinstance(t, ast.Name) and text:
                    consts[t.id] = text

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        sql = _flatten(node.args[0], consts)
        if not sql:
            continue
        if _callee(node) not in _SQL_CALLEES and not _DML.search(sql):
            continue
        for table, col in SOURCE_TABLES.items():
            if not re.search(r"\b%s\b" % table, sql):
                continue
            if _DDL.search(sql) or _CATALOG.search(sql):
                continue
            if re.search(r"\b%s\b" % col, sql):
                continue
            # an explicit, written-down exemption in the three lines above the call
            lo = max(0, (node.lineno or 1) - 4)
            if _ALLOW in "\n".join(lines[lo:(node.lineno or 1)]):
                continue
            out.append((str(path.name), f"line {node.lineno}", table))
    return out


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    findings: list[tuple[str, str, str]] = []
    profile_findings: list[tuple[str, str, str]] = []
    # BOTH trees. `apps/n8n/blueprint/n8n` holds the shared Settings loader, which reads
    # `settings` and `tag_rules` on behalf of every app — the single highest-traffic reader of the
    # tenant tables in the deployment. A lint scoped to apps/ alone declares victory while the
    # busiest offender sits one directory over.
    for pattern in ("apps/*/blueprint/n8n/*.workflow.ts",):
        for wf in sorted(root.glob(pattern)):
            findings.extend(scan(wf, N8N_TENANT_TABLES["instance"], "instance"))
            profile_findings.extend(scan(wf, N8N_TENANT_TABLES["profile"], "profile"))

    src_findings: list[tuple[str, str, str]] = []
    for pattern in SOURCE_ROOTS:
        for py in sorted(root.glob(pattern)):
            src_findings.extend(scan_source(py))

    if not findings and not profile_findings and not src_findings:
        print("tenancy-lint: OK — every tenant-table access names its discriminator")
        print("  n8n workflows: %s -> `instance`" % ", ".join(TENANT_TABLES))
        print("  n8n workflows: %s -> `profile`" % ", ".join(N8N_TENANT_TABLES["profile"]))
        print("  source:        %s" % ", ".join(f"{t} -> `{c}`" for t, c in SOURCE_TABLES.items()))
        return 0

    if findings:
        print("tenancy-lint: %d node(s) touch a tenant-scoped table without an "
              "`instance`:\n" % len(findings))
        for wf, node, table in findings:
            print(f"  {wf}  ::  {node}   -> public.{table}")
        print(
            "\nAdd `instance: <name>` to the request (or `instance:'*'` if this caller\n"
            "genuinely reads across every instance, as the scanner does). Without it the\n"
            "query silently returns — or overwrites — another instance's configuration."
        )
    if profile_findings:
        print("\ntenancy-lint: %d node(s) touch drive_files without a `profile` "
              "(this is the class 'CH Bad Seed' shipped as — see the module docstring):\n"
              % len(profile_findings))
        for wf, node, table in profile_findings:
            print(f"  {wf}  ::  {node}   -> public.{table}")
        print(
            "\nName `profile` in the query — a subquery resolving the default active profile is\n"
            "fine (`select id from drive_profiles where is_admin and status='active' order by\n"
            "created_at, id limit 1`), a literal is fine, `null` is NOT: the column is NOT NULL.\n"
            "Production code should call driveApi01 instead of raw SQL — this scan exists for the\n"
            "cases (chaos/fixture rows) where raw SQL is the point."
        )
    if src_findings:
        print("\ntenancy-lint: %d SQL statement(s) touch a tenant-scoped table without its "
              "discriminator:\n" % len(src_findings))
        for f, where, table in src_findings:
            print(f"  {f}  ::  {where}   -> {table} (needs `{SOURCE_TABLES[table]}`)")
        print(
            "\nName the discriminator in the statement. If this read genuinely must cross\n"
            "profiles (the public /file/d/<id>/view byte-serve is the only one that does),\n"
            "write `# tenancy-lint: allow-unscoped — <reason>` on the line above the call, so\n"
            "that reading across every profile is always a decision somebody wrote down."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
