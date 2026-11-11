#!/usr/bin/env python3
"""drain.py — `bbox indox main` and `bbox indox decide`: run the state machine from the shell (DGO-231).

    bbox indox main   --instance <id> [--id <ID> …] [--company <COMPANY_ID>] [--status <S>|--changed] [--dry] [--force] [--no-follow]
    bbox indox decide --instance <id> [the same filters | --sweep]                         (decide only: acts on nothing)
    bbox indox main   --instance <id> --alive                                  (only list the instance's live drains)

The owner (2026-08-10): «implment bbox cli to enable bbox indox main (dose sweep, excepts id, company for selecting
only some, runs the driver». Both verbs are THIN over INDOX's one drain API — indoxV2BaseDrain01's webhook,
POST /webhook/indox-drain {mode, ids?, status?, dry?, __instance}, basic auth with the «Incoming Documents» credential
(BS_WEBHOOK_USER / BS_WEBHOOK_PASS, as apps/n8n/blueprint.yml fills it). They print the drain execution it answers
with, follow it to its end, and finish with the drain's own verdict (its Summarize node): exit 0 only when the drain
ended `success` AND Summarize said OK.

`decide` is the drain with `dry: true`. In the driver, a dry lane runs decide, the duplicate guard and the action
filter, then parks before the lock: no lock, no dispatch, no action. What it still does, said rather than hidden:
  - the drain's 'Reap Stale Dispatches' closes stale dispatch rows (ENDED_AT) in every mode, dry included;
  - a duplicate-guard hit still raises 'Double Blocked' into errorHandler01;
  - while it runs, this instance's scheduled drains may stand aside — so a dry FULL sweep takes its own --sweep.

Before starting, the CLI looks for a drain of this instance already alive and refuses to start a second one unless
--force (the webhook skips the drain's own solo check; "the supervisor does its own alive-check before firing"). It
reads the drain's `__instance` from its stored data, and a database it cannot read counts as "maybe alive".
`--alive` is that look alone: it starts nothing.

Following reads n8n's own tables, not its REST API: the drain's row in execution_entity, and the driver lanes THIS
drain fired — each lane carries DRAINER_ID "drain:<id>" (Fire Lanes), matched once per lane, then followed by id.
One progress line, rewritten in place on a terminal; elsewhere a line only when the counts change. Every 15 s.
Credentials come from .env and are never printed.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
BASE = os.environ.get("INDOX_N8N_BASE", "http://localhost:5678")
INSTANCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DONE = ("success", "error", "crashed", "canceled", "unknown")
LANE_RUNNING = ("new", "running", "waiting")
LANE_FAILED = ("error", "crashed", "canceled", "unknown")
EVERY = 15.0


def env(key: str, default: str = "") -> str:
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get(key, default)


def editor_base() -> str:
    """n8n's public editor address — the same rule n8n's compose uses for N8N_EDITOR_BASE_URL."""
    if env("N8N_OAUTH_BASE"):
        return env("N8N_OAUTH_BASE").rstrip("/")
    host = env("N8N_BASE_URL") or "n8n." + (env("DEPLOYMENT_DOMAIN") or "localhost")
    return f"{env('N8N_PROTOCOL') or 'https'}://{host}"


def body_for(verb: str, a) -> dict:
    """The drain API's request body for these arguments: one of four modes, decide always dry."""
    if not INSTANCE_RE.match(a.instance or ""):
        raise SystemExit("indox: --instance <id> is required (the instance's id, as `bbox indox` uses it)")
    if a.status and a.changed:
        raise SystemExit("indox: --status and --changed are two modes; choose one")
    body: dict = {"__instance": a.instance, "dry": verb == "decide" or bool(a.dry)}
    if a.ids:
        if a.status or a.changed:
            raise SystemExit("indox: --id/--company select rows by id; --status/--changed select by state — choose one")
        body.update(mode="ids", ids=a.ids)
    elif a.status:
        body.update(mode="status", status=a.status)
    elif a.changed:
        body.update(mode="changed")
    else:
        body.update(mode="all")
    return body


def _psql(container: str, user: str, db: str, q: str, run=subprocess.run):
    return run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tA", "-F", "|", "-c", q],
               capture_output=True, text=True)


def n8n_sql(q: str, run=subprocess.run):
    """One read of n8n's own database. Returns rows (lists of fields), or None when it could not be read.
    Rows split on "\\n" only: JSON keeps U+2028 / U+2029 raw, and str.splitlines() would cut a row there."""
    r = _psql(f"n8n-postgres-{env('DEPLOYMENT_NAME', 'bina-deployment')}", env("POSTGRES_USER", "root"),
              env("POSTGRES_DB", "n8n"), q, run)
    if r.returncode != 0:
        return None
    return [ln.split("|") for ln in (r.stdout or "").split("\n") if ln.strip()]


def company_ids(instance: str, company: str, run=subprocess.run) -> list:
    """The instance's row ids for one COMPANY_ID — a read of its own schema, nothing else."""
    q = ('select "ID" from indox_%s.incoming_documents where "COMPANY_ID" = \'%s\' order by "ID"'
         % (instance, company.replace("'", "''")))
    r = _psql(f"supabase-db-{env('DEPLOYMENT_NAME', 'bina-deployment')}", "postgres", "postgres", q, run)
    if r.returncode != 0:
        raise SystemExit(f"indox: could not read instance «{instance}»'s documents: {(r.stderr or '').strip()[:200]}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def names_instance(text: str, instance: str) -> bool:
    """Whether a drain's flatted data carries `__instance` = this instance. In flatted form the value is an INDEX
    into the list, so a bare string match would also hit keys and common words — every execution holds "main"."""
    try:
        vals = json.loads(text)
    except ValueError:
        return True                                        # unreadable: assume it is this instance's (fail closed)
    for v in vals if isinstance(vals, list) else []:
        if isinstance(v, dict) and "__instance" in v:
            x = v["__instance"]
            if isinstance(x, str) and x.isdigit() and int(x) < len(vals) and vals[int(x)] == instance:
                return True
    return False


def alive_drains(instance: str, run=subprocess.run):
    """Drains of this instance already alive (their ids), or None when n8n's database could not be read. Alive drains
    are few and their stored data is their small request (save-on-progress is off), so each is read and decided."""
    rows = n8n_sql("select e.id, coalesce(d.data, '') from execution_entity e left join execution_data d "
                   "on d.\"executionId\" = e.id where e.\"workflowId\" = 'indoxV2BaseDrain01' "
                   "and e.status in ('running','waiting','new') order by e.id", run)
    if rows is None:
        return None
    return [r[0] for r in rows if not "|".join(r[1:]) or names_instance("|".join(r[1:]), instance)]


def _http(path: str, method: str = "GET", body=None, headers=None, timeout: float = 90):
    """(code, headers, text); code 0 = no answer at all (refused, timed out, cut) — said, never a traceback."""
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        return 0, {}, f"{type(e).__name__}: {e}"


def start(body: dict, http=_http) -> str:
    """POST the drain API; return the drain execution id it answers with."""
    auth = base64.b64encode(f"{env('BS_WEBHOOK_USER')}:{env('BS_WEBHOOK_PASS')}".encode()).decode()
    code, _h, text = http("/webhook/indox-drain", "POST", body, {"Authorization": "Basic " + auth})
    if code == 0:
        raise SystemExit("indox: n8n did not answer the drain webhook (" + text[:160] + "). Whether a drain started is "
                         "UNKNOWN — look before retrying: `bbox indox main --instance <id> --alive` lists this "
                         "instance's live drains and starts nothing")
    try:
        got = json.loads(text)
    except ValueError:
        got = {}
    if code != 200 or not got.get("accepted") or not got.get("drain_execution"):
        why = " (the webhook's credentials: BS_WEBHOOK_USER / BS_WEBHOOK_PASS in .env)" if code == 401 else ""
        raise SystemExit(f"indox: the drain did not accept the run (HTTP {code}){why}: {text[:200]}")
    return str(got["drain_execution"])


def drain_row(eid: str, run=subprocess.run):
    """(status, createdAt) of the drain execution, None when it could not be read, () when the row is gone."""
    if not eid.isdigit():
        return ()
    rows = n8n_sql('select status, "createdAt" from execution_entity where id = %s' % eid, run)
    if rows is None:
        return None
    return tuple(rows[0][:2]) if rows else ()


class Lanes:
    """The driver lanes THIS drain fired: matched once each by DRAINER_ID "drain:<id>", then followed by id."""

    def __init__(self, eid: str, run=subprocess.run):
        self.eid, self.run, self.mine, self.last_id = eid, run, [], int(eid) if eid.isdigit() else 0

    def poll(self, since: str) -> dict:
        if not re.match(r"^[0-9T:.\-+Z ]+$", since or ""):
            return {}
        # every new driver run is read ONCE, soon after it is created — while its stored data is still the small
        # request, not the run's full output — and the cursor moves past it whether it is this drain's or not;
        # it stops at the first run whose data is not written yet, to read that one next time
        rows = n8n_sql("select e.id, (d.data is not null), coalesce(d.data like '%%\"drain:%s\"%%', false) "
                       "from execution_entity e left join execution_data d on d.\"executionId\" = e.id "
                       "where e.\"workflowId\" = 'indoxV2Driver01' and e.id > %d and e.\"createdAt\" >= '%s' "
                       "order by e.id" % (self.eid, self.last_id, since), self.run) or []
        for lane, written, mine in (r[:3] for r in rows if len(r) >= 3):
            if written != "t":
                break
            self.last_id = int(lane)
            if mine == "t":
                self.mine.append(lane)
        if not self.mine:
            return {}
        rows = n8n_sql("select status, count(*) from execution_entity where id in (%s) group by status"
                       % ",".join(self.mine), self.run) or []
        return {r[0]: int(r[1]) for r in rows}


def line(state: str, secs: int, lanes: dict) -> str:
    running = sum(v for k, v in lanes.items() if k in LANE_RUNNING)
    done = lanes.get("success", 0)
    failed = sum(v for k, v in lanes.items() if k in LANE_FAILED)
    total = running + done + failed
    width = 20
    filled = int(width * done / total) if total else 0
    return (f"[indox] drain {state:<8} {secs // 60:02d}:{secs % 60:02d}  "
            f"[{'#' * filled}{'.' * (width - filled)}] lanes {done}/{total} done"
            + (f", {failed} failed" if failed else "") + (f", {running} running" if running else ""))


def follow(eid: str, row=drain_row, lanes=None, sleep=time.sleep, out=sys.stderr, every: float = EVERY,
           tty=None, limit_s: int = 36000, misses_max: int = 8) -> str:
    """Follow the drain to its end. Returns its final status ('gone' / 'unreadable' / 'running' when it stops early)."""
    lanes = lanes or Lanes(eid)
    tty = out.isatty() if tty is None else tty
    t0, misses, shown = time.time(), 0, None
    while True:
        r = row(eid)
        if r is None:
            misses += 1
            if misses >= misses_max:
                out.write(f"\n[indox] n8n's database did not answer {misses} times in a row — stopped following "
                          f"(the drain runs on)\n")
                return "unreadable"
        elif r == ():
            out.write(f"\n[indox] drain {eid} is no longer in n8n's executions (deleted or pruned)\n")
            return "gone"
        else:
            misses = 0
            state, since = r[0], r[1]
            text = line(state, int(time.time() - t0), lanes.poll(since))
            if tty:
                out.write("\r" + text)
            elif text.split(" lanes ")[-1] != (shown or "").split(" lanes ")[-1] or state in DONE:
                out.write(text + "\n")
            shown = text
            out.flush()
            if state in DONE:
                if tty:
                    out.write("\n")
                return state
        if time.time() - t0 > limit_s:
            out.write("\n[indox] still running after the drain's own timeout — stopped following (it runs on)\n")
            return "running"
        sleep(every)


# The drain's Summarize output, walked IN POSTGRES along its one path through the flatted data (root → resultData →
# runData → Summarize → the last run → data → main → [0] → [0] → json), each field's index resolved there. A long
# drain stores its state on every tick, hundreds of MB; reading all of it into Python to keep ten fields would not do.
SUMMARY_SQL = """with a as (select data::jsonb j from execution_data where "executionId" = %s),
b as (select j, j -> ((j -> 0) ->> 'resultData')::int v from a),
c as (select j, j -> (v ->> 'runData')::int v from b),
d as (select j, j -> (v ->> 'Summarize')::int v from c),
e as (select j, j -> (v ->> (jsonb_array_length(v) - 1))::int v from d),
f as (select j, j -> (v ->> 'data')::int v from e),
g as (select j, j -> (v ->> 'main')::int v from f),
h as (select j, j -> (v ->> 0)::int v from g),
i as (select j, j -> (v ->> 0)::int v from h),
k as (select j, j -> (v ->> 'json')::int v from i)
select jsonb_object_agg(kv.key, case when jsonb_typeof(kv.value) = 'string' then k.j -> (kv.value #>> '{}')::int
                                     else kv.value end)::text
from k, jsonb_each(k.v) kv"""


def verdict(eid: str, run=subprocess.run, sleep=time.sleep):
    """The drain's own Summarize output (its scalar fields), or None when it cannot be read. Read twice at most: the
    execution's status can be written a moment before its data."""
    if not eid.isdigit():
        return None
    for attempt in (0, 1):
        rows = n8n_sql(SUMMARY_SQL % eid, run)
        try:
            got = json.loads("|".join(rows[0])) if rows else None
        except ValueError:
            got = None
        if isinstance(got, dict) and got.get("RESULT"):
            return got
        if attempt == 0:
            sleep(5)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bbox indox main|decide")
    ap.add_argument("verb", choices=("main", "decide"))
    ap.add_argument("--instance", "-i", default="")
    ap.add_argument("--id", dest="ids", action="append", default=[], help="a document ID (repeatable, or comma-separated)")
    ap.add_argument("--company", help="every row of this COMPANY_ID in the instance")
    ap.add_argument("--status", help="rows in this STATUS (mode=status)")
    ap.add_argument("--changed", action="store_true", help="what changed recently (mode=changed)")
    ap.add_argument("--dry", action="store_true", help="main only: decide without acting (decide always is)")
    ap.add_argument("--sweep", action="store_true", help="decide over EVERY line of the instance (a dry full sweep)")
    ap.add_argument("--force", action="store_true", help="start even while a drain of this instance is alive")
    ap.add_argument("--alive", action="store_true", help="only list this instance's live drains; start nothing")
    ap.add_argument("--no-follow", action="store_true", help="print the drain execution id and return")
    a = ap.parse_args(argv)
    a.ids = [i.strip() for chunk in a.ids for i in chunk.split(",") if i.strip()]
    if not INSTANCE_RE.match(a.instance or ""):
        raise SystemExit("indox: --instance <id> is required (the instance's id, as `bbox indox` uses it)")
    if a.alive:                                            # a look, nothing more
        alive = alive_drains(a.instance)
        if alive is None:
            raise SystemExit("indox: n8n's database could not be read — whether a drain is alive is unknown")
        print(f"[indox] «{a.instance}»: " + (f"drain(s) alive: {', '.join(alive)}" if alive else "no drain alive"))
        return 0
    if a.company:
        found = company_ids(a.instance, a.company)
        if not found:
            print(f"[indox] instance «{a.instance}» has no documents of company {a.company} — nothing to run")
            return 0
        a.ids += found
        print(f"[indox] company {a.company}: {len(found)} document(s)")
    body = body_for(a.verb, a)
    if body["dry"] and body["mode"] == "all" and not a.sweep:
        print("[indox] a dry FULL sweep decides over every line of the instance; while it runs, the instance's "
              "scheduled drains may stand aside. Narrow it (--status/--changed/--id/--company) or pass --sweep.")
        return 2
    alive = alive_drains(a.instance)
    if alive is None and not a.force:
        raise SystemExit("indox: n8n's database could not be read, so whether a drain of «%s» is alive is unknown — "
                         "--force starts anyway" % a.instance)
    if alive and not a.force:
        raise SystemExit(f"indox: a drain of «{a.instance}» is already alive (execution {', '.join(alive)}) — wait for "
                         f"it, or --force to start another beside it")
    eid = start(body)
    what = "decide only (dry: no lock, no action)" if body["dry"] else "the driver, acting"
    sel = {"ids": f"{len(body.get('ids', []))} id(s)", "status": f"STATUS={body.get('status')}",
           "changed": "changed rows", "all": "a full sweep"}[body["mode"]]
    print(f"[indox] drain execution {eid} — {what}, {sel}, instance «{a.instance}»")
    print(f"[indox]   {editor_base()}/workflow/indoxV2BaseDrain01/executions/{eid}")
    if a.no_follow:
        return 0
    state = follow(eid)
    v = verdict(eid) if state in DONE else None
    if v:
        print(f"[indox] drain {eid}: {state}, {v.get('RESULT')} — selected {v.get('documentsSelected')}, "
              f"dispatched {v.get('documentsDispatched')}, batches {v.get('batchesCompleted')}/{v.get('batchesTotal')}"
              + (f", {v.get('nonSuccess')} not successful: {v.get('nonSuccessDetail')}" if v.get("nonSuccess") else ""))
    else:
        print(f"[indox] drain {eid} ended: {state} (its summary could not be read)")
    return 0 if state == "success" and (v or {}).get("RESULT") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
