#!/usr/bin/env python3
r"""published-drift-lint — gate G61: an ACTIVE workflow must run the body you can read.

    python3 scripts/refactor/published-drift-lint.py [--self-test]

    Requires a live n8n database. It FAILS LOUDLY when it cannot reach one — see below.

WHY THIS GATE EXISTS

n8n 2.17 keeps two copies of every workflow: the draft in `workflow_entity.nodes`, and the
published body in `workflow_history.nodes` selected by `workflow_entity."activeVersionId"`. An
ACTIVE workflow executes the PUBLISHED copy. Every structural check anyone has run against this
deployment — "is the fix live?", "does the query still say X?" — reads `workflow_entity.nodes`,
which is the draft. A `PATCH` that updates a workflow without activating it leaves code that
reads back correctly over the API and never executes.

Measured 2026-08-07: 68 active workflows, 68 identical, 0 drifted. So `bbox n8n push` publishes
correctly and no claim made that night was reading stale code. This gate exists to keep that
true, because the failure is invisible: nothing errors, the API agrees with you, and the
behaviour is simply the old one.

Inactive workflows are deliberately NOT compared. An inactive workflow has no published version,
and the suites are driven by manual REST run against the editor state — so for them the draft IS
what executes, and flagging them would be noise.

COMPARISON SHAPE

Node NAME + TYPE + PARAMETERS, sorted, hashed. Positions are EXCLUDED: a layout nudge is not a
behavioural change, and a gate that reported one would cry wolf on every canvas tidy — which is
how a gate gets switched off.

LOUD ON NO DATABASE — the point of this paragraph

A gate that quietly passes when it cannot check anything is a check whose evidence is an absence,
which is the defect family this repo has spent a day cataloguing. So: no database, no verdict.
This exits non-zero with a message saying it could not look, and never prints PASS. `--self-test`
runs without a database on purpose, and tests exactly that behaviour.

LOUD ON AN EMPTY INSTANCE — the same paragraph, one step further in

The database can be reached and still hold nothing to compare. hp-laptop's did on 2026-10-07: an
n8n that was up and healthy with 0 workflows (24 credentials, one owner) — the blueprints had
never been imported there — and this gate said "PASS — all 0 active workflow(s) run the body
stored against them". Every office ships the central blueprint, and four of its workflows are
active (the error handler 79 others name as theirs among them), so an instance with no active
workflow is not a clean one: it is one nothing was imported into. That is a FAIL that says so.

WHAT THIS GATE DOES NOT COVER
  * It compares what n8n stores, not what n8n executes. A worker running stale code in memory
    after a partial restart is outside its reach.
  * It says two bodies differ; it does not say which is correct.
  * Credentials, settings and pinned data are not compared — only the node graph's behaviour.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]


def env(key: str, default: str = "") -> str:
    try:
        for ln in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get(key, default)


def _docker_env() -> dict:
    e = dict(os.environ)
    if not e.get("DOCKER_HOST"):
        e["DOCKER_HOST"] = "unix://" + e.get("BBOX_DOCKER_SOCK", "/run/bbox-docker.sock")
    return e


def n8n_sql(sql: str, timeout: int = 120) -> str:
    dn = env("DEPLOYMENT_NAME", "bina-deployment")
    r = subprocess.run(
        ["docker", "exec", "n8n-postgres-" + dn, "psql", "-U", env("N8N_DB_USER", "hacohen"),
         "-d", env("N8N_DB_NAME", "n8n"), "-tA", "-c", sql],
        capture_output=True, timeout=timeout, env=_docker_env())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace").strip()[:400])
    return r.stdout.decode("utf-8", errors="replace").strip()


def signature(nodes) -> tuple[str, int]:
    """Behaviour only: name + type + parameters. Positions deliberately excluded."""
    items = sorted(
        (n.get("name", ""), n.get("type", ""),
         json.dumps(n.get("parameters") or {}, sort_keys=True, ensure_ascii=False))
        for n in nodes if isinstance(n, dict))
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode()).hexdigest()[:16], len(items)


def scan() -> tuple[list, int, list]:
    rows = n8n_sql(
        "select w.id || E'\\t' || w.nodes::text || E'\\t' || coalesce(h.nodes::text,'NULL') "
        "from workflow_entity w "
        "left join workflow_history h on h.\"versionId\" = w.\"activeVersionId\" "
        "where w.active order by w.id;")
    drift, same, unpublished = [], 0, []
    for line in rows.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        wid, draft_s, hist_s = parts
        if hist_s == "NULL":
            unpublished.append(wid)
            continue
        try:
            d_sig, d_n = signature(json.loads(draft_s))
            h_sig, h_n = signature(json.loads(hist_s))
        except ValueError:
            continue
        if d_sig != h_sig:
            drift.append((wid, d_n, h_n))
        else:
            same += 1
    return drift, same, unpublished


SELF_TEST = [
    ("positions are excluded from the signature",
     lambda: signature([{"name": "A", "type": "t", "parameters": {"q": 1}, "position": [0, 0]}])[0]
     == signature([{"name": "A", "type": "t", "parameters": {"q": 1}, "position": [9, 9]}])[0]),
    ("a parameter change DOES change the signature",
     lambda: signature([{"name": "A", "type": "t", "parameters": {"q": 1}}])[0]
     != signature([{"name": "A", "type": "t", "parameters": {"q": 2}}])[0]),
    ("node order does not change the signature",
     lambda: signature([{"name": "A", "type": "t"}, {"name": "B", "type": "t"}])[0]
     == signature([{"name": "B", "type": "t"}, {"name": "A", "type": "t"}])[0]),
    ("a renamed node DOES change the signature",
     lambda: signature([{"name": "A", "type": "t"}])[0]
     != signature([{"name": "A2", "type": "t"}])[0]),
    ("no database is reported as NO VERDICT, never as a pass",
     lambda: _no_db_is_loud()),
    ("a database with no active workflow is a FAIL, never a pass over zero",
     lambda: _empty_is_loud()),
]


def _no_db_is_loud() -> bool:
    """The property that matters most: an unreachable database must not read as green."""
    try:
        n8n_sql("select 1;", timeout=15)
        return True          # a DB is present; the loud path is unexercised but not violated
    except Exception:
        return main(_probe=True) != 0


def _empty_is_loud() -> bool:
    global scan
    real = scan
    scan = lambda: ([], 0, [])                                   # noqa: E731 — reachable, and empty
    try:
        return main(_probe=True) == 1
    finally:
        scan = real


def self_test() -> int:
    bad = 0
    for label, fn in SELF_TEST:
        try:
            ok = bool(fn())
        except Exception as ex:
            ok, label = False, label + "  (raised %s)" % type(ex).__name__
        bad += 0 if ok else 1
        print("  [%s] %s" % ("ok " if ok else "FAIL", label))
    print("\nG61 self-test: %d/%d passed" % (len(SELF_TEST) - bad, len(SELF_TEST)))
    return 1 if bad else 0


def main(_probe: bool = False) -> int:
    if not _probe:
        ap = argparse.ArgumentParser()
        ap.add_argument("--self-test", action="store_true")
        if ap.parse_args().self_test:
            return self_test()

    try:
        drift, same, unpublished = scan()
    except Exception as ex:
        if not _probe:
            print("G61 NO VERDICT — could not reach the n8n database, so nothing was checked.")
            print("  %s" % str(ex)[:300])
            print("  This is deliberately NOT a pass: a check that cannot fail is not a check.")
        return 2

    if not (drift or unpublished or same):
        if not _probe:
            print("G61 FAIL — this n8n holds NO active workflow, so there was nothing to compare.")
            print("  Every office ships the central blueprint (apps/n8n/blueprint/n8n), and its")
            print("  error handler, process lock and reporters are active — an instance without them")
            print("  was never imported into. `./bbox n8n push all` (or `./bbox run`) does it.")
        return 1

    if drift or unpublished:
        print("G61 FAIL — %d active workflow(s) do not run the body you can read:"
              % (len(drift) + len(unpublished)))
        for wid, d_n, h_n in drift:
            print("\n  %-30s draft %d node(s) / PUBLISHED %d node(s)" % (wid, d_n, h_n))
            print("      the draft reads back over the API; the published copy is what executes")
        for wid in unpublished:
            print("\n  %-30s ACTIVE but activeVersionId resolves to no published row" % wid)
        print("\n  A PATCH without activation produces exactly this: code that reads correctly")
        print("  and never runs. Re-publish, or reconcile with `bbox n8n pull`.")
        return 1

    print("G61 PASS — all %d active workflow(s) run the body stored against them "
          "(signature over name+type+parameters; positions excluded)." % same)
    return 0


if __name__ == "__main__":
    sys.exit(main())
