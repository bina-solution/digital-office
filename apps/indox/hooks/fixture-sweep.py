#!/usr/bin/env python3
r"""fixture-sweep — remove every E2E fixture row from indox_test.incoming_documents, from the host.

    python3 apps/indox/hooks/fixture-sweep.py --dry-run       # count, delete nothing
    python3 apps/indox/hooks/fixture-sweep.py                 # sweep
    python3 apps/indox/hooks/fixture-sweep.py --self-test     # prove the SQL, no DB needed
    python3 apps/indox/hooks/fixture-sweep.py --print-exclusion   # the poll/backlog predicate

WHY THIS EXISTS — the half G58 cannot reach.

`scripts/refactor/fixture-delete-scope-lint.py` (gate G58) proves every cleanup query in every
blueprint is scoped to a registered prefix. That is a statement about PREDICATE SHAPE, and it is
worth exactly nothing if the cleanup never runs. Every suite's cleanup sits on its happy path:
`indoxV2 DOC BASE E2E Test` crashed at 17:21 on 2026-08-06 and its fixture rows were still in the
client's live table afterwards, because a crashed execution does not reach its own Cleanup node.

So there are two independent failure modes and they need two independent answers:

    the cleanup deletes too much   ->  G58, static, over the blueprints
    the cleanup never runs at all  ->  this, dynamic, from outside n8n

THIS SWEEP RUNS OUTSIDE THE THING THAT CRASHES. `apps/indox/hooks/test.py` calls it in a
`finally`, so it runs whether the battery passed, failed, timed out, stalled, raised, or was
interrupted — the n8n execution being dead is precisely when it matters. It also runs BEFORE the
battery, which is what covers the one case a `finally` cannot: the CLI process itself being
`SIGKILL`ed, or the machine losing power. Debris then survives until the next run and no further.

SINGLE SOURCE OF TRUTH. Every prefix, marker column and the pipeline carve-out come from
`scripts/test-fixture-prefixes.yaml` and are not restated here. That is the entire point: the
2026-08-06 incident happened in a fleet of fifteen cleanups where each one restated its own prefix
list inline, so being right fourteen times bought nothing.

`_` IS A LIKE WILDCARD. `'db_%'` matches `dbZanything`. Every pattern this builds escapes it.

THE BLAST-RADIUS CAP. A prefix registry is a promise, and this script is the one place that
executes an unattended, whole-table, multi-prefix DELETE against the live client table — the
exact shape that deleted thousands of rows. So it refuses to delete more than `--max` rows (300
by default, roughly 10x a full battery's fixtures) and prints the per-prefix breakdown instead.
If a suite ever seeds outside its prefix, or a registered prefix ever collides with real client
ids, this stops and says so rather than proceeding confidently. Requirement: escaping a prefix
must fail LOUDLY.

WHAT THIS DOES NOT DO — read before trusting a clean sweep.
  * `indox_test.incoming_documents` ONLY (the permanent test tenant's schema — the suites run
    nowhere else since the tenant cutover; the incident happened when they still shared
    `public`). `sync_ledger`, `sync_attempt`, `sync_cursor`, `drive_files`, `companies` and the
    stored FILES are left to the suites' own cleanups; this is the table the incident was about
    and the table B4's acceptance proof names.
  * It cannot un-write side effects that left the database — a Drive rename, a Gmail label, an
    outbound API call. Crash-safety here means "the client's document table is unchanged", not
    "the world is unchanged".
  * It is NOT transactional with the suite. A suite that crashes mid-write and a sweep that runs
    a second later are two statements, not one; a row written after the sweep begins survives it.
  * G58 does not police THIS file — G58 reads blueprint JSON. The predicate built here is
    covered by `--self-test` instead, which asserts the exact SQL string.
"""
from __future__ import annotations

import argparse
import re
import os
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML required (scripts/test-fixture-prefixes.yaml is the source of truth)")

ROOT = pathlib.Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "scripts" / "test-fixture-prefixes.yaml"
#: The permanent test tenant's document table. The suites run ONLY against instance `test`
#: (schema indox_test) since the tenant cutover, so that is the only table this sweep may
#: touch — pointing it at public.incoming_documents again would be aiming a multi-prefix
#: DELETE back at the client's live table.
TABLE = "indox_test.incoming_documents"


# ── the registry ─────────────────────────────────────────────────────────────────────────
def load_registry(text: str | None = None) -> dict:
    raw = text if text is not None else REGISTRY.read_text(encoding="utf-8")
    reg = yaml.safe_load(raw) or {}
    reg.setdefault("prefixes", [])
    reg.setdefault("live_poll_visible", [])
    return reg


def like_pattern(prefix: str) -> str:
    r"""`db_` -> `db\_%`. The backslash is a real character in the SQL literal; with
    standard_conforming_strings (on by default, and on here) LIKE reads it as its escape
    character, so `\_` matches one literal underscore instead of any one character."""
    return prefix.replace("\\", "\\\\").replace("_", "\\_") + "%"


#: Blueprint filename suffix. Two dots, which is the whole reason the naive strip below broke.
_BP_SUFFIX = ".workflow.ts"


def owner_stem(p: dict) -> str:
    """`apps/indox/blueprint/n8n/indoxV2DocBaseTest01.workflow.ts` -> `indoxV2DocBaseTest01`,
    which is also the n8n workflow id the runner drives. That equality is what lets a sweep be
    scoped to the suites a run actually ran.

    [2026-08-21] IT WAS `rsplit(".", 1)[0]`, WRITTEN WHEN OWNERS WERE `.json`. Blueprints became
    code in 52b32aa4 and every `owner` in the registry gained a SECOND dot, so the strip left
    `indoxV2DocBaseTest01.workflow` — which equals no workflow id the runner ever passes. The
    ownership filter in `pairs()` and `aux_entries()` therefore matched NOTHING, for every suite,
    on every run.

    Nothing failed loudly. The sweep printed

        [fixture-sweep:post] no registered prefix is owned by ['indoxV2PipelineTest01'] — nothing to sweep

    which reads like a correct no-op, and fixtures accumulated instead: 47 `doc_`, 40 `gdx_`, 28
    `sv3s_`, 20 `gdt_`, 14 `db_` rows still in the dispatch log when this was found. The pipeline
    suite then failed on its OWN leftovers — "update_status_missing_link already dispatched
    (ACTION_HISTORY, no restart after it)" — a suite blocked by the run before it.

    Strip the known blueprint suffix explicitly rather than guessing at dots, so a third dot
    would not quietly do this again."""
    name = str(p.get("owner", "")).rsplit("/", 1)[-1]
    if name.endswith(_BP_SUFFIX):
        return name[: -len(_BP_SUFFIX)]
    return name.rsplit(".", 1)[0]


def pairs(reg: dict, owners: list[str] | None = None) -> list[tuple[str, str]]:
    """[(column, prefix)] — every place a fixture row is allowed to be marked.

    `owners` RESTRICTS THE SWEEP TO THE SUITES THAT RAN, and it is not an optimisation — it is a
    correctness fix found the hard way. On 2026-08-06 this sweep, running from one lane's battery,
    deleted 7 `sv3s_` rows belonging to a DIFFERENT lane's in-flight `sync_sources` run: the
    predicate was global, so "clean up after my run" silently meant "clean up after everyone".
    The pre-sweep counted 6 and deleted 7 — the count and the delete disagreeing was the tell,
    and the rows in between were another agent's live fixtures.

    The registry already knew the answer: every prefix carries the blueprint that `owner`s it.
    Passing the workflow ids a run drove is therefore enough to make the sweep touch only what
    that run could possibly have created. With no owners given the sweep is global, which is
    still the right default for a deliberate manual clean -- but it now SAYS so.
    """
    out: list[tuple[str, str]] = []
    for p in reg["prefixes"]:
        if not isinstance(p, dict) or not p.get("prefix"):
            continue
        if owners is not None and owner_stem(p) not in owners:
            continue
        for col in (p.get("columns") or []):
            out.append((col, p["prefix"]))
    return sorted(set(out))


def fixture_predicate(reg: dict, owners: list[str] | None = None) -> str:
    """The OR of every (column, prefix) — 'this row belongs to a test suite I am allowed to
    clean up after'. See `pairs()` for why `owners` is a correctness argument, not a filter."""
    return " or ".join('"%s" like \'%s\'' % (c, like_pattern(p))
                       for c, p in pairs(reg, owners))


def aux_entries(reg: dict, owners: list[str] | None = None) -> list[dict]:
    """The `aux_tables` entries this run is allowed to clean up.

    Same ownership rule as `pairs()`: naming no owner means a deliberate global clean, naming an
    unknown one sweeps nothing rather than everything.
    """
    out = []
    for e in (reg.get("aux_tables") or []):
        if not isinstance(e, dict) or not e.get("table") or not e.get("key_column"):
            continue
        if owners is not None and owner_stem(e) not in owners:
            continue
        if not [k for k in (e.get("keys") or []) if str(k).strip()]:
            continue
        out.append(e)
    return out


def aux_delete_sql(entry: dict) -> str:
    r"""`delete from indox_test.tag_rules where "KEY" in ('a','b')` — EXACT keys, never a pattern.

    This is a DELETE against a client CONFIGURATION table, so the containment rule binds at its
    hardest: `"KEY" like 'sv3s%'` would be a pattern standing in for identity, which is the
    shape that removed 2,432 client documents. An enumerated `in (...)` list cannot over-match,
    and a suite that adds a label has to declare it in the registry to get it cleaned up.

    Keys are single-quote escaped the way the rest of this fleet does it; a key containing a
    quote would otherwise end the literal early.
    """
    keys = [str(k).strip() for k in (entry.get("keys") or []) if str(k).strip()]
    lits = ", ".join("'" + k.replace("'", "''") + "'" for k in keys)
    return 'delete from %s where "%s" in (%s);' % (
        entry["table"], entry["key_column"], lits)


def sweep_aux(reg: dict, dry_run: bool, label: str,
              owners: list[str] | None = None) -> int:
    """Remove the suite's rows from the non-document tables it had to write into."""
    entries = aux_entries(reg, owners)
    if not entries:
        return 0
    for e in entries:
        keys = [str(k).strip() for k in e["keys"] if str(k).strip()]
        n = psql('select count(*) from %s where "%s" in (%s);'
                 % (e["table"], e["key_column"],
                    ", ".join("'" + k.replace("'", "''") + "'" for k in keys)))
        print("[fixture-sweep:%s] %s: %s of %d registered key(s) present"
              % (label, e["table"], n, len(keys)), flush=True)
        if dry_run or n in ("0", "", None):
            continue
        psql(aux_delete_sql(e))
        print("[fixture-sweep:%s] %s: removed %s row(s) by exact key"
              % (label, e["table"], n), flush=True)
    return 0


def saved_settings_entries(reg: dict, owners: list[str] | None = None) -> list[dict]:
    """The `saved_settings` entries this run may restore. Same ownership rule as `pairs()`."""
    out = []
    for e in (reg.get("saved_settings") or []):
        if not isinstance(e, dict) or not e.get("table") or not e.get("key_column"):
            continue
        if owners is not None and owner_stem(e) not in owners:
            continue
        saves = [s for s in (e.get("saves") or [])
                 if isinstance(s, dict) and str(s.get("prior_key", "")).strip()
                 and str(s.get("target_key", "")).strip()]
        if not saves:
            continue
        out.append({**e, "saves": saves})
    return out


def _lit(v: str) -> str:
    """A single-quoted SQL literal. Doubling an embedded quote is what stops a key from ending
    the literal early and turning the rest of the statement into syntax the server will run."""
    return "'" + str(v).replace("'", "''") + "'"


def _value_of(entry: dict, key: str) -> str:
    return psql("select coalesce((select value from %s where %s = %s limit 1), '<absent>');"
                % (entry["table"], '"' + entry["key_column"] + '"', _lit(key)))


def restore_sql(entry: dict, save: dict) -> str:
    """RESTORE-then-delete. The order is the entire point, and the reverse is a data loss.

    A `<prefix>_prior_<key>` row is where a suite parked the client's real value before writing
    a test value over the live one. `aux_delete_sql` would simply DELETE it -- which discards the
    only surviving copy of the original and makes the test's value PERMANENT. So this writes the
    parked value back FIRST and only then removes the parking slot.

    Both statements go to one `psql -c`, so they run in a single implicit transaction: there is
    no window in which the parked value has been dropped and not yet written back.

    Joined ON `instance`, not pinned to one. The suites hardcode 'incoming-documents-main', but a
    prior row that leaked under some other instance belongs to THAT instance's target -- pinning
    would restore it to the wrong row, or (worse) delete it having restored nothing.
    """
    tbl = entry["table"]
    kc = '"' + entry["key_column"] + '"'
    return (
        "update {t} s set value = p.value from {t} p "
        "where p.instance = s.instance and p.{k} = {pk} and s.{k} = {tk}; "
        "delete from {t} where {k} = {pk};"
    ).format(t=tbl, k=kc, pk=_lit(save["prior_key"]), tk=_lit(save["target_key"]))


def sweep_saved_settings(reg: dict, dry_run: bool, label: str,
                         owners: list[str] | None = None) -> int:
    """Put back any client setting a suite parked and never collected.

    This is the crash half of the AI-toggle contract. Each suite also self-heals ON ENTRY, which
    repairs the leak at the start of the next run of THAT suite; this repairs it at the end of
    the battery, for every suite, including ones that will not run again.
    """
    entries = saved_settings_entries(reg, owners)
    if not entries:
        return 0
    for e in entries:
        kc = '"' + e["key_column"] + '"'
        for s in e["saves"]:
            n = psql("select count(*) from %s where %s = %s;"
                     % (e["table"], kc, _lit(s["prior_key"])))
            if n in ("0", "", None):
                continue
            # A leak is worth a line even though it is about to be repaired: it is the only
            # evidence anywhere that a suite died before reaching its own restore.
            print("[fixture-sweep:%s] %s: LEAKED %s -- %s is now %s, parked value is %s%s"
                  % (label, e["table"], s["prior_key"], s["target_key"],
                     _value_of(e, s["target_key"]), _value_of(e, s["prior_key"]),
                     " (dry-run, left alone)" if dry_run else " -- restoring"), flush=True)
            if dry_run:
                continue
            psql(restore_sql(e, s))
            print("[fixture-sweep:%s] %s: %s restored to %s"
                  % (label, e["table"], s["target_key"], _value_of(e, s["target_key"])),
                  flush=True)
    return 0


def sync_table_entries(reg: dict) -> list[dict]:
    """Every prefix-matched state table: `sync_tables` (the four the v3 engine writes as a pipe
    runs, keyed by pipe) plus `doc_state_tables` (per-DOCUMENT state living outside
    incoming_documents, keyed by document id).

    Two registry keys, one mechanism, because they are two different things and naming a dispatch
    log a "sync table" is the kind of small lie that costs the next reader an hour."""
    entries = (reg.get("sync_tables") or []) + (reg.get("doc_state_tables") or [])
    return [e for e in entries
            if isinstance(e, dict) and e.get("table") and e.get("match_expr")]


def sync_predicate(reg: dict, entry: dict, owners: list[str] | None = None) -> str:
    r"""`regexp_replace(source,'^[^/]*/','') like 'sv3s\_%' or … ` — 'this state row belongs to a
    pipe owned by a suite I am allowed to clean up after'.

    PREFIXES ARE NOT RESTATED. They come from the same `prefixes` list the document sweep uses, so
    a suite that registers a prefix gets its sync state swept with no second declaration to drift
    out of step — which is the failure mode the whole registry exists to remove.

    The prefix set is DISTINCT-ed across columns: `prefixes` is keyed by (column, prefix) because a
    document row can be marked in several columns, but a pipe has exactly one name, so
    `sv3s_` appearing under both `SYNC_NAME` and `ID` must produce one term, not two.
    """
    pres = sorted({p for _c, p in pairs(reg, owners)})
    return " or ".join("%s like '%s'" % (entry["match_expr"], like_pattern(p)) for p in pres)


def sweep_sync_tables(reg: dict, dry_run: bool, label: str,
                      owners: list[str] | None = None) -> int:
    """Remove the per-pipe state a test run left in the sync engine's own tables.

    Every suite already deletes from these four in its pre-run `Cleanup SQL`. That is the START of
    a run, so it cleans up after the PREVIOUS one and leaves the current one's rows behind whenever
    the current one dies — the same crash hole this whole script exists to close for the document
    table. Doing it here means it happens from `test.py`'s `finally`, outside the thing that
    crashed.

    Never raises: a missing table (an older schema, a partial stack) is reported and skipped. A
    sweep that cannot clean one table must still clean the others, and must never be what turns a
    battery red.
    """
    entries = sync_table_entries(reg)
    if not entries or not pairs(reg, owners):
        return 0
    for e in entries:
        pred = sync_predicate(reg, e, owners)
        try:
            n = int(psql("select count(*) from %s where %s;" % (e["table"], pred)) or 0)
        except Exception as ex:                      # noqa: BLE001 — reported, never fatal
            print("[fixture-sweep:%s] %s: SKIPPED (%s)"
                  % (label, e["table"], str(ex).splitlines()[0][:120]), flush=True)
            continue
        if not n:
            continue
        print("[fixture-sweep:%s] %s: %d fixture state row(s)" % (label, e["table"], n),
              flush=True)
        if dry_run:
            continue
        try:
            got = psql("with d as (delete from %s where %s returning 1) select count(*) from d;"
                       % (e["table"], pred))
            print("[fixture-sweep:%s] %s: deleted %s row(s)" % (label, e["table"], got),
                  flush=True)
        except Exception as ex:                      # noqa: BLE001
            print("[fixture-sweep:%s] %s: DELETE FAILED (%s)"
                  % (label, e["table"], str(ex).splitlines()[0][:120]), flush=True)
    return 0


def exclusion_predicate(reg: dict) -> str:
    r"""REQUIREMENT 4, in one place: 'not a test row — except pipeline's, which must stay visible'.

    For the live poll's pickup, the MISSING_COMPANY_ID backlog population and dashboard counts.
    The `pipeline` suite is DESIGNED so the live poll picks its documents up; that is the only
    thing that suite proves. A blanket "hide all test prefixes" would make it assert nothing and
    pass anyway — this repo's dominant defect class. So the exception is `live_poll_visible`, and
    it lives in the same file as the list it excepts so the two cannot drift.

    `coalesce()` IS LOad-BEARING, not defensive habit. `not ("SYNC_NAME" like '…')` is NULL when
    `SYNC_NAME` is NULL, and NULL is not true, so a `where not (…)` filter SILENTLY DROPS EVERY
    NULL ROW. `SYNC_NAME` is NULL across this deployment's entire historical corpus; the same
    mistake in a classifier returned 10 rows instead of 2,403 on 2026-08-06.
    """
    keep = set(reg["live_poll_visible"] or [])
    terms = ["coalesce(\"%s\", '') like '%s'" % (c, like_pattern(p))
             for c, p in pairs(reg) if p not in keep]
    return "not (" + " or ".join(terms) + ")"


# ── the database ─────────────────────────────────────────────────────────────────────────
def env(key: str, default: str = "") -> str:
    try:
        for ln in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get(key, default)


def _docker_env() -> dict:
    """bbox exports DOCKER_HOST (scripts/lib.sh bbox_select_engine) before dispatching a hook, so
    a bare `docker` is already pointed at the project engine. Run standalone there is nothing to
    inherit, and a bare `docker` then hits the WRONG engine and cheerfully reports the stack down.
    BBOX_DOCKER_SOCK is a bare PATH, not a URL — assigning it straight to DOCKER_HOST yields
    `tcp://localhost:2375/run/bbox-docker.sock`."""
    e = dict(os.environ)
    if not e.get("DOCKER_HOST"):
        e["DOCKER_HOST"] = "unix://" + e.get("BBOX_DOCKER_SOCK", "/run/bbox-docker.sock")
    return e


def psql(sql: str, timeout: int = 120) -> str:
    dn = env("DEPLOYMENT_NAME", "bina-deployment")
    cmd = ["docker", "exec", "supabase-db-" + dn,
           "psql", "-U", "postgres", "-d", "postgres", "-tA", "-c", sql]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=_docker_env())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace").strip()[:600])
    return r.stdout.decode("utf-8", errors="replace").strip()


# ── the sweep ────────────────────────────────────────────────────────────────────────────
def counts(reg: dict, owners: list[str] | None = None) -> list[tuple[str, str, int]]:
    """Per (column, prefix) row count. Reported before anything is deleted, so an over-broad
    prefix is visible as a number rather than discovered as a missing client document."""
    out = []
    for col, pre in pairs(reg, owners):
        n = psql('select count(*) from %s where "%s" like \'%s\';'
                 % (TABLE, col, like_pattern(pre)))
        out.append((col, pre, int(n or 0)))
    return out


def sweep(reg: dict, dry_run: bool, cap: int, label: str,
          owners: list[str] | None = None) -> int:
    scoped = pairs(reg, owners)
    # Restore before ANY early return. A parked client setting is the one thing here that is
    # actively harmful while it sits — the live extraction path reads it — and it can be the
    # ONLY thing a run left behind, so gating it on the document table having rows (or on the
    # owner having a registered prefix at all) would be a sweep that reports success without
    # having looked. That is the shape this whole file exists to prevent.
    sweep_saved_settings(reg, dry_run, label, owners)
    if not scoped:
        print("[fixture-sweep:%s] no registered prefix is owned by %s — nothing more to sweep"
              % (label, owners), flush=True)
        return 0
    if owners is None:
        print("[fixture-sweep:%s] GLOBAL sweep — every registered prefix. If another lane is "
              "running a suite right now, this will delete its in-flight fixtures."
              % label, flush=True)
    else:
        print("[fixture-sweep:%s] scoped to %s (%d prefix/column pair(s)); every other "
              "registered prefix is left alone" % (label, ",".join(owners), len(scoped)),
              flush=True)

    # Non-document tables first, and unconditionally: they are swept even when the document
    # table is already clean, because a run can leave a registry row behind having written no
    # documents at all.
    sweep_aux(reg, dry_run, label, owners)
    # The sync engine's own state tables, for the same reason and with the same timing: a suite
    # that dies never reaches its own cleanup, and a stranded `sync_cursor` row makes the NEXT
    # run of that pipe resume from a fixture's position.
    sweep_sync_tables(reg, dry_run, label, owners)

    pred = fixture_predicate(reg, owners)
    total = int(psql("select count(*) from %s where %s;" % (TABLE, pred)) or 0)
    print("[fixture-sweep:%s] %d fixture row(s) in %s" % (label, total, TABLE), flush=True)
    if total == 0:
        return 0

    for col, pre, n in counts(reg, owners):
        if n:
            print("[fixture-sweep:%s]   %-12s %-10s %d" % (label, col, pre, n), flush=True)

    if total > cap:
        print("[fixture-sweep:%s] REFUSING TO DELETE — %d rows exceeds the --max cap of %d.\n"
              "    A registered prefix is matching far more than a battery seeds. Either a suite\n"
              "    is writing outside its prefix, or a prefix in scripts/test-fixture-prefixes.yaml\n"
              "    collides with real client ids. Both are the thing this cap exists to catch, and\n"
              "    both need a human before a DELETE runs. Re-run with --max once you know which."
              % (label, total, cap), file=sys.stderr, flush=True)
        return 2

    if dry_run:
        print("[fixture-sweep:%s] --dry-run: nothing deleted" % label, flush=True)
        return 0

    got = psql("with d as (delete from %s where %s returning 1) "
               "select count(*) from d;" % (TABLE, pred))
    print("[fixture-sweep:%s] deleted %s row(s)" % (label, got), flush=True)
    return 0


# ── self-test ────────────────────────────────────────────────────────────────────────────
_REG = """
version: 1
prefixes:
  - {prefix: "db_",      owner: apps/indox/blueprint/n8n/indoxV2DocBaseTest01.workflow.ts, columns: [ID]}
  - {prefix: "plx_",     owner: apps/indox/blueprint/n8n/indoxV2PipelineTest01.workflow.ts, columns: [ID, LINKED_BS]}
  - {prefix: "sv3khash", owner: apps/indox/blueprint/n8n/syncItemApiTest01.workflow.ts, columns: [HASH]}
  - {prefix: "sv3s_",    owner: apps/indox/blueprint/n8n/syncSourcesTest01.workflow.ts, columns: [SYNC_NAME]}
live_poll_visible: ["plx_"]
aux_tables:
  - table: indox_test.tag_rules
    key_column: KEY
    owner: apps/indox/blueprint/n8n/syncSourcesTest01.json
    keys: ["sv3s_synced", "sv3s_pb_synced", "o'brien"]
  - table: indox_test.tag_rules
    key_column: KEY
    owner: apps/indox/blueprint/n8n/indoxV2GDocTest01.json
    keys: []
saved_settings:
  - table: indox_test.settings
    key_column: key
    owner: apps/indox/blueprint/n8n/indoxV2PipelineTest01.json
    saves:
      - {prior_key: plt_prior_extraction_ai_enabled, target_key: extraction_ai_enabled}
      - {prior_key: plt_prior_incomplete}
  - table: indox_test.settings
    key_column: key
    owner: apps/indox/blueprint/n8n/indoxV2GDocTest01.json
    saves: []
doc_state_tables:
  - {table: indox_test.indox_action_execution_log, match_expr: '"ID"'}
sync_tables:
  - {table: indox_test.sync_ledger, match_expr: "regexp_replace(source,'^[^/]*/','')"}
  - {table: public.drive_files, match_expr: "folder"}
"""


def self_test() -> int:
    reg = load_registry(_REG)
    _ss = restore_sql({"table": "indox_test.settings", "key_column": "key"}, {"prior_key": "plt_prior_extraction_ai_enabled", "target_key": "extraction_ai_enabled"})
    cases = [
        # [2026-08-21] owner_stem was `rsplit(".", 1)[0]`, written when owners were `.json`.
        # `.workflow.ts` has TWO dots, so it returned "...Test01.workflow" and the ownership
        # filter matched nothing on every run — silently, printing "nothing to sweep". The
        # registry above now uses the real suffix, which is what makes the next three cases bite.
        ("owner_stem strips the two-dot blueprint suffix",
         owner_stem({"owner": "apps/indox/blueprint/n8n/indoxV2DocBaseTest01.workflow.ts"}),
         "indoxV2DocBaseTest01"),
        ("owner_stem still handles a single-extension owner",
         owner_stem({"owner": "apps/indox/blueprint/n8n/indoxV2DocBaseTest01.json"}),
         "indoxV2DocBaseTest01"),
        ("scoping to a suite yields ITS pairs, not none",
         pairs(reg, ["indoxV2PipelineTest01"]),
         [("ID", "plx_"), ("LINKED_BS", "plx_")]),
        ("scoping to an unknown suite still yields none",
         pairs(reg, ["noSuchWorkflow01"]), []),

        # ── saved_settings [2026-08-23] ───────────────────────────────────────────────
        # These rows are the ONLY ones in this file that must not simply be deleted. A
        # `<prefix>_prior_<key>` row holds the client's real value, parked while a suite ran a
        # test value over the live setting; deleting it discards the only surviving copy and
        # makes the test's value permanent. Measured: plt_prior_extraction_ai_enabled sat at
        # 'true' after pipeline hit its 1080s timeout and never reached its own restore node,
        # which silently moved the whole deployment onto the AI extraction path.
        ("a registered save is picked up",
         [s["prior_key"] for e in saved_settings_entries(reg) for s in e["saves"]],
         ["plt_prior_extraction_ai_enabled"]),
        ("a save missing its target_key is DROPPED, not half-applied",
         [s for e in saved_settings_entries(reg) for s in e["saves"]
          if s["prior_key"] == "plt_prior_incomplete"],
         []),
        ("an entry whose saves list is empty registers nothing",
         saved_settings_entries(reg, ["indoxV2GDocTest01"]), []),
        ("scoping to an unknown suite restores nothing",
         saved_settings_entries(reg, ["noSuchWorkflow01"]), []),
        # The ORDER is the invariant. Reversed, this is the data loss it exists to prevent.
        ("the restore runs BEFORE the delete",
         _ss.index("update ") < _ss.index("delete from "), True),
        # Compared as the WHOLE literal, not as a substring: the live key is a suffix of the
        # parked key ("..._prior_extraction_ai_enabled"), so a containment test passes on the
        # very statement it is supposed to reject.
        ("the DELETE names the parked key, never the live one",
         re.findall(r"'([^']*)'", _ss.split("delete from")[1]),
         ["plt_prior_extraction_ai_enabled"]),
        ("the restore is joined on instance, not pinned to one",
         "p.instance = s.instance" in _ss, True),
        ("a quote in a key is doubled, not left to end the literal",
         _lit("o'brien"), "'o''brien'"),
        ("underscore is escaped, not left as a wildcard",
         like_pattern("db_"), "db\\_%"),
        ("a prefix with no underscore is untouched",
         like_pattern("sv3khash"), "sv3khash%"),
        ("an internal underscore is escaped too",
         like_pattern("C_GDTEST"), "C\\_GDTEST%"),
        ("the fixture predicate covers every (column, prefix) pair",
         fixture_predicate(reg),
         '"HASH" like \'sv3khash%\' or "ID" like \'db\\_%\' or "ID" like \'plx\\_%\' '
         'or "LINKED_BS" like \'plx\\_%\' or "SYNC_NAME" like \'sv3s\\_%\''),
        # REQUIREMENT 4. plx_ must NOT appear in the exclusion, or the pipeline suite stops
        # proving the one thing it exists to prove; everything else MUST appear, or fixtures
        # keep landing in the client's backlog.
        ("the exclusion keeps pipeline visible and hides the rest",
         exclusion_predicate(reg),
         'not (coalesce("HASH", \'\') like \'sv3khash%\' or coalesce("ID", \'\') like \'db\\_%\' '
         'or coalesce("SYNC_NAME", \'\') like \'sv3s\\_%\')'),
    ]
    bad = 0
    for label, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s" % ("ok " if ok else "FAIL", label))
        if not ok:
            print("        got : %s" % got)
            print("        want: %s" % want)

    # ── OWNERSHIP SCOPING ────────────────────────────────────────────────────────────────
    # THE REGRESSION TEST FOR THE REAL INCIDENT. On 2026-08-06 a doc_base/gdoc/pipeline battery
    # swept 7 `sv3s_` rows out from under a DIFFERENT lane's live `sync_sources` run. The
    # assertion that matters is the NEGATIVE one: sv3s_ must be absent when sync_sources did not
    # run. A test that only checked "db_ is present" would have passed against the broken code.
    ran = ["indoxV2DocBaseTest01", "indoxV2PipelineTest01"]
    scoped = fixture_predicate(reg, ran)
    for prop, ok in (
        ("a scoped sweep includes the prefixes of the suites that ran", 'db\\_%' in scoped),
        ("a scoped sweep EXCLUDES another lane's sv3s_ (the actual incident)",
         "sv3s" not in scoped),
        ("a scoped sweep excludes sv3khash too", "sv3khash" not in scoped),
        ("an unscoped sweep is still global (the deliberate manual clean)",
         "sv3s" in fixture_predicate(reg, None)),
        ("owner path -> workflow id",
         owner_stem({"owner": "apps/indox/blueprint/n8n/indoxV2DocBaseTest01.json"})
         == "indoxV2DocBaseTest01"),
        ("a run naming no known suite sweeps NOTHING, rather than everything",
         pairs(reg, ["someOtherLaneWorkflow"]) == []),
    ):
        bad += 0 if ok else 1
        cases.append((prop, "", ""))
        print("  [%s] %s" % ("ok " if ok else "FAIL", prop))

    # ── AUX TABLES (2026-08-07) ──────────────────────────────────────────────────────────
    # These are DELETEs against a client CONFIGURATION table, so the assertions that matter are
    # the negative ones: no pattern, no over-match, and nothing at all when the run does not own
    # the entry. A test that only checked "the right keys appear" would pass against a `like`.
    sv3s = aux_entries(reg, ["syncSourcesTest01"])
    sql = aux_delete_sql(sv3s[0]) if sv3s else ""
    for prop, ok in (
        ("aux sweep is scoped to the owning suite", len(sv3s) == 1),
        ("a run that owns no aux entry sweeps none",
         aux_entries(reg, ["someOtherLaneWorkflow"]) == []),
        ("an entry with an EMPTY key list is skipped, not turned into a bare delete",
         aux_entries(reg, ["indoxV2GDocTest01"]) == []),
        ("the delete is exact-match `in (...)`, never a LIKE",
         " in (" in sql and "like" not in sql.lower() and "%" not in sql),
        ("every registered key appears as its own quoted literal",
         "'sv3s_synced'" in sql and "'sv3s_pb_synced'" in sql),
        ("a key containing a quote is escaped, not left to end the literal early",
         "'o''brien'" in sql),
        ("the key column is quoted (KEY is a reserved word in some engines)",
         '"KEY"' in sql),
    ):
        bad += 0 if ok else 1
        cases.append((prop, "", ""))
        print("  [%s] %s" % ("ok " if ok else "FAIL", prop))

    # ── SYNC STATE TABLES (2026-08-09) ───────────────────────────────────────────────────
    # The claims that matter are again the negative ones: the ledger predicate must be scoped to
    # the suites that ran, must strip the `<instance>/` ledger identity before testing the prefix,
    # and must escape `_`. `sv3s_` is registered under two document columns in the real registry,
    # so the de-duplication is asserted too — a pipe has one name, and emitting the same term
    # twice would be a predicate that reads as if it checked two things.
    led = [e for e in sync_table_entries(reg) if e["table"] == "indox_test.sync_ledger"][0]
    scoped_led = sync_predicate(reg, led, ["syncSourcesTest01"])
    dup_reg = load_registry(_REG.replace(
        '  - {prefix: "sv3s_",    owner: apps/indox/blueprint/n8n/syncSourcesTest01.workflow.ts, columns: [SYNC_NAME]}',
        '  - {prefix: "sv3s_",    owner: apps/indox/blueprint/n8n/syncSourcesTest01.workflow.ts, columns: [SYNC_NAME, ID]}'))
    for prop, ok in (
        # doc_state_tables is where ACTION_HISTORY lives. A suite blocked by its OWN previous
        # run is what its absence looked like, so both the wiring and the predicate are asserted.
        # `drive_files` is the one PLATFORM table in the set (public on purpose — the drive
        # service owns it deployment-wide); the tenant tables live in the test schema.
        ("doc_state_tables are swept alongside sync_tables",
         sorted(e["table"] for e in sync_table_entries(reg))
         == ["indox_test.indox_action_execution_log", "indox_test.sync_ledger",
             "public.drive_files"]),
        ("the action log is matched on the document id column, scoped to the suite",
         sync_predicate(reg, {"match_expr": '"ID"'}, ["indoxV2PipelineTest01"])
         == '"ID" like \'plx\\_%\''),
        ("every prefix-matched table comes from the registry, not restated in code",
         [e["table"] for e in sync_table_entries(reg)]
         == ["indox_test.sync_ledger", "public.drive_files",
             "indox_test.indox_action_execution_log"]),
        ("the ledger predicate strips the <instance>/ identity before matching",
         scoped_led == "regexp_replace(source,'^[^/]*/','') like 'sv3s\\_%'"),
        ("the ledger predicate escapes `_`, so sv3sZ… is not a match",
         "sv3s\\_%" in scoped_led and "'sv3s_%'" not in scoped_led),
        ("a scoped sync sweep EXCLUDES another lane's prefixes",
         "db\\_%" not in scoped_led and "plx" not in scoped_led),
        ("drive_files matches on `folder`, not on a source column",
         sync_predicate(reg, [e for e in sync_table_entries(reg)
                              if e["table"] == "public.drive_files"][0],
                        ["syncSourcesTest01"]) == "folder like 'sv3s\\_%'"),
        ("a run naming no known suite produces NO sync predicate at all",
         sync_predicate(reg, led, ["someOtherLaneWorkflow"]) == ""),
        ("one prefix registered under two document columns yields ONE ledger term",
         sync_predicate(dup_reg, led, ["syncSourcesTest01"]).count(" like ") == 1),
    ):
        bad += 0 if ok else 1
        cases.append((prop, "", ""))
        print("  [%s] %s" % ("ok " if ok else "FAIL", prop))

    # Two properties asserted directly rather than by string comparison, because they are the
    # claims a reader actually cares about and a typo in the expected string above would hide.
    excl = exclusion_predicate(reg)
    for prop, ok in (("plx_ (live_poll_visible) is absent from the exclusion", "plx" not in excl),
                     ("db_ (not visible) IS present in the exclusion", "db\\_%" in excl),
                     ("every exclusion term is coalesce()-wrapped against NULL",
                      excl.count("coalesce(") == excl.count(" like "))):
        bad += 0 if ok else 1
        print("  [%s] %s" % ("ok " if ok else "FAIL", prop))

    n = len(cases) + 3
    print("\nfixture-sweep self-test: %d/%d passed" % (n - bad, n))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--print-exclusion", action="store_true",
                    help="print the poll/backlog exclusion predicate and exit")
    ap.add_argument("--max", type=int, default=300, help="blast-radius cap (default 300)")
    ap.add_argument("--label", default="manual", help="tag for the log lines (pre/post/manual)")
    ap.add_argument("--workflows", default="",
                    help="comma-separated n8n workflow ids whose fixtures this run may delete "
                         "(e.g. indoxV2DocBaseTest01,indoxV2GDocTest01). Omit for a GLOBAL "
                         "sweep — which will destroy another lane's in-flight fixtures.")
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    reg = load_registry()
    if a.print_exclusion:
        print(exclusion_predicate(reg))
        return 0
    owners = [w.strip() for w in a.workflows.split(",") if w.strip()] or None
    try:
        return sweep(reg, a.dry_run, a.max, a.label, owners)
    except Exception as ex:  # a sweep failure must be loud, never a silent no-op
        print("[fixture-sweep:%s] FAILED: %s" % (a.label, ex), file=sys.stderr, flush=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
