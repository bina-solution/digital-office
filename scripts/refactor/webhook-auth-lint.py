#!/usr/bin/env python3
"""webhook-auth-lint — gate G97: an ACTIVE webhook that the edge publishes either authenticates or
is closed to the internet.

    python3 scripts/refactor/webhook-auth-lint.py [--self-test]

WHY THIS EXISTS. Measured 2026-11-09 (DGO-1603) — on vps1, from its own n8n database, and on the
client office «examplef» the same day: the office's edge publishes `/webhook/*` on its PUBLIC host
through the `n8n-hooks` routers with no middleware in front, so a webhook whose `authentication` is
`none` answers the whole internet. On vps1 that was **eight active nodes over seven paths**: INDOX's
`incoming_document` (create and read), `mail-api/doc-context` (a client's document context, 21 runs
in 30 days), `meet-recordings` (1911 runs — it fetches an audio URL and writes Plane items), and the
three `sync-*-e2e-lane` suite runners. Anyone could call them without a password. That is strictly
worse than the n8n EDITOR, which at least had n8n's own login (DGO-1594).

WHAT THE GATE ASKS, in the order the item's plan set:
  * a workflow that is `active: false` registers no webhook at all — nothing to ask;
  * an active webhook with `authentication` other than `none` is the office's own answer — pass;
  * an active webhook with `authentication: none` must be CLOSED TO THE INTERNET: its
    `options.ipWhitelist` must be present and must name only private/loopback ranges. n8n enforces
    that list itself (measured behind the edge with `N8N_PROXY_HOPS=1`: 403 "IP is not allowed" to a
    public address, not 404 and not a run), which is what makes "internal only" true in practice.
  * …unless the path is DECLARED PUBLIC below, with the caller that needs it. A webhook that must
    take the internet is not a mistake — it is a decision, and a decision is written down.

`--live` ASKS THE SAME OF THE OFFICE'S OWN n8n (DGO-1603 step 3). The tree is what a push WOULD
publish; the database is what the edge publishes NOW — and the two drift: a workflow that exists only
there (INDOX's context-collection reference JSON has no blueprint in git), an office that imported
a tree from before the batch that closed the twelve, a hand edit in the editor. So `--live` reads
every row of `workflow_entity` with the body n8n RUNS for it — the published copy that
`activeVersionId` names (G61's distinction: the draft is what you read, the published copy is what
executes), the draft only when no published copy exists — and applies `findings()` to those rows,
unchanged: the same rule, the same PUBLIC, on both sides. It is in run-gates' LIVE_SET with G61,
and it is loud the way G61 is: no database is NO VERDICT (exit 2, never a pass), and a database
that holds no workflow at all is a FAIL (an office nothing was imported into is not a clean one).

WHAT IT DOES NOT DO. It does not judge whether the allow-list is the right one. It reads what n8n
stores, not what the running process registered (a worker on stale code after a partial restart is
G61's limit too). It also does not replace G67, which asks the different question of what an open
webhook can REACH.
"""
import argparse
import importlib.util
import ipaddress
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "refactor"))

#: path -> why it may answer the internet without authentication. Each is a caller OUTSIDE the
#: office that cannot be given a secret: a third party's webhook registration, a form a customer
#: fills. Empty by design until such a caller is named — an entry here is a decision, and the gate
#: FAILS when one of them stops existing (G31/G84's anti-rot rule).
PUBLIC = {}


def private_ranges(whitelist):
    """Is every entry of an `ipWhitelist` a private or loopback range? -> (ok, [bad entries])"""
    bad = []
    for part in str(whitelist or "").split(","):
        item = part.strip()
        if not item:
            continue
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            bad.append(item)                      # a name is not an address the edge can trust
            continue
        # `is_private` covers 10/8, 172.16/12, 192.168/16 and IPv6's fc00::/7; loopback and
        # link-local are named separately because a public address is what must be refused.
        if not (net.is_private or net.is_loopback or net.is_link_local):
            bad.append(item)
    return (len(bad) == 0 and bool(str(whitelist or "").strip())), bad


def findings(wfs):
    """[(workflow, path, why)] over {wid: loaded blueprint}."""
    out = []
    for wid, wf in wfs.items():
        if wf.get("_unreadable"):
            out.append((wid, "?", f"unreadable blueprint: {wf['_unreadable']}"))
            continue
        if not wf.get("active"):
            continue                              # inactive: no webhook is registered by n8n
        for n in wf.get("nodes") or []:
            if not str(n.get("type", "")).endswith("webhook") or n.get("disabled"):
                continue                          # a disabled node: n8n registers no webhook for it either
            p = n.get("parameters") or {}
            if (p.get("authentication") or "none") != "none":
                continue
            path = p.get("path") or "?"
            if path in PUBLIC:
                continue
            whitelist = ((p.get("options") or {}).get("ipWhitelist") or "")
            ok, bad = private_ranges(whitelist)
            if not ok:
                why = ("no ipWhitelist" if not whitelist.strip()
                       else f"ipWhitelist names a public entry: {', '.join(bad)}")
                out.append((wid, path, why))
    return out


def stale_public(wfs):
    """Paths declared PUBLIC that no active open webhook carries any more."""
    live = set()
    for wf in wfs.values():
        if not wf.get("active"):
            continue
        for n in wf.get("nodes") or []:
            p = n.get("parameters") or {}
            if str(n.get("type", "")).endswith("webhook") and not n.get("disabled") \
                    and (p.get("authentication") or "none") == "none":
                live.add(p.get("path") or "?")
    return [p for p in sorted(PUBLIC) if p not in live]


def load_all(paths):
    from n8n_blueprint import load
    wfs = {}
    for wid, f in paths.items():
        try:
            wfs[wid] = load(str(f))
        except Exception as e:                    # noqa: BLE001 — a blueprint this gate cannot read is
            wfs[wid] = {"_unreadable": str(e), "nodes": []}   # not a pass; it is a finding
    return wfs


def blueprints():
    out = {}
    for d in sorted(REPO.glob("apps/*/blueprint/n8n")):
        for f in sorted(d.glob("*.workflow.ts")):
            out[f.name[:-len(".workflow.ts")]] = f
    return out


#: Every ACTIVE row with both of its bodies — chosen in Python, not in SQL, so the self-test can prove
#: the choice: the published copy when `activeVersionId` names one, else the draft (and that is said).
LIVE_SQL = (
    "select json_build_object('total', (select count(*) from workflow_entity), 'rows', coalesce(("
    "select json_agg(json_build_object('id', w.id, 'published', h.nodes, 'draft', w.nodes)) "
    "from workflow_entity w left join workflow_history h on h.\"versionId\" = w.\"activeVersionId\" "
    "where w.active), '[]'::json));")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "refactor" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _n8n_sql():
    """G61's reader of the office's n8n database — one way to reach it, not two."""
    return _load("published_drift_lint", "published-drift-lint.py").n8n_sql


def scan_live(sql=None):
    """-> (workflows in the database, {wid: {active, nodes}} of the ACTIVE ones, [wids run from the draft])"""
    data = json.loads((sql or _n8n_sql())(LIVE_SQL) or "null")
    if not isinstance(data, dict):
        raise RuntimeError("the n8n database did not answer with the expected JSON object")
    wfs, from_draft = {}, []
    for r in data.get("rows") or []:
        wid = str(r.get("id"))
        body = r.get("published")
        if body is None:
            body = r.get("draft")
            from_draft.append(wid)
        if isinstance(body, str):                 # a json column handed over as text
            body = json.loads(body)
        # a body that is not a list of nodes is not a pass — it is a finding, as an unreadable blueprint is
        wfs[wid] = ({"active": True, "nodes": body} if isinstance(body, list)
                    else {"_unreadable": f"its body is {type(body).__name__}, not a list of nodes", "nodes": []})
    return int(data.get("total") or 0), wfs, from_draft


def main_live(sql=None, say=print):
    try:
        total, wfs, from_draft = scan_live(sql)
    except Exception as ex:                       # noqa: BLE001 — any failure to look is NO VERDICT
        say("G97 --live NO VERDICT — could not read the office's n8n database, so nothing was checked.")
        say(f"  {str(ex)[:300]}")
        say("  This is deliberately NOT a pass: a check that cannot fail is not a check (G61's rule).")
        return 2
    if total == 0:
        say("G97 --live FAIL — this n8n holds NO workflow at all, so there was nothing to ask. An office ships")
        say("  the central blueprint; an instance without it was never imported into (`./bbox n8n push all`).")
        return 1
    found = findings(wfs)
    nodes = sum(1 for wf in wfs.values() for n in wf["nodes"]
                if str(n.get("type", "")).endswith("webhook") and not n.get("disabled"))
    scope = (f"{len(wfs)} active of {total} workflow(s) in this office's n8n, {nodes} enabled webhook node(s); "
             f"{len(wfs) - len(from_draft)} judged by the published body, {len(from_draft)} by the draft")
    if found:
        say("A WEBHOOK THIS OFFICE'S EDGE PUBLISHES NOW THAT ANSWERS THE INTERNET WITHOUT A PASSWORD")
        say("-" * 78)
        for wid, path, why in found:
            say(f"  {wid:28} /webhook/{path}  — {why}" + ("  (no published copy: the draft)" if wid in from_draft
                                                            else ""))
        say("-" * 78)
        say("  -> close it in the app's blueprint (options.ipWhitelist with the private ranges, or\n"
            "     `active: false`) and push it; `bbox n8n push` refuses a push that would re-open one\n"
            "     this database has closed. A workflow with no blueprint is closed in the editor.")
        say(f"\nG97 --live FAIL — {len(found)} active webhook(s) open ({scope}).")
        return 1
    say(f"G97 --live PASS — every active webhook in this office's n8n authenticates or is closed ({scope}).")
    return 0


def self_test():
    ok = 0
    base = lambda active, params: {"active": active,          # noqa: E731
                                   "nodes": [{"type": "n8n-nodes-base.webhook", "parameters": params}]}
    private = {"path": "x", "options": {"ipWhitelist": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1,::1"}}
    cases = [
        ("an active open webhook with no allow-list", [("w", "x", "no ipWhitelist")],
         {"w": base(True, {"path": "x"})}),
        ("a public address in the allow-list", [("w", "x", "ipWhitelist names a public entry: 8.8.8.8")],
         {"w": base(True, {"path": "x", "options": {"ipWhitelist": "10.0.0.0/8,8.8.8.8"}})}),
        ("a private allow-list passes", [], {"w": base(True, private)}),
        ("a deactivated workflow is not asked", [], {"w": base(False, {"path": "x"})}),
        ("a disabled webhook node registers nothing — not asked", [],
         {"w": {"active": True, "nodes": [{"type": "n8n-nodes-base.webhook", "disabled": True,
                                           "parameters": {"path": "x"}}]}}),
        ("basicAuth needs no allow-list", [], {"w": base(True, {"path": "x", "authentication": "basicAuth"})}),
        ("a declared-public path passes", [], {"w": base(True, {"path": "public-hook"})}),
        ("an unreadable blueprint is a finding", [("w", "?", "unreadable blueprint: boom")],
         {"w": {"_unreadable": "boom", "nodes": []}}),
    ]
    real_public = dict(PUBLIC)
    try:
        PUBLIC.clear()
        for label, want, wfs in cases[:6]:          # the declared-public case needs the declaration
            got = findings(wfs)
            if got != want:
                raise SystemExit(f"self-test FAILED ({label}): {got!r}, want {want!r}")
            ok += 1
        got = findings(cases[7][2])
        if got != cases[7][1]:
            raise SystemExit(f"self-test FAILED (unreadable): {got!r}")
        ok += 1
        PUBLIC["public-hook"] = "self-test"
        if findings(cases[6][2]) != cases[6][1]:
            raise SystemExit(f"self-test FAILED (a declared-public path passes): {findings(cases[6][2])!r}")
        ok += 1
        if stale_public({"w": base(False, {"path": "public-hook"})}) != ["public-hook"]:
            raise SystemExit("self-test FAILED: a declaration that matches nothing must be stale")
        ok += 1
    finally:
        PUBLIC.clear()
        PUBLIC.update(real_public)
    # --live: the same rule on the office's own rows, read through a stand-in for the database
    hush = lambda *a: None                                                          # noqa: E731
    db = lambda rows, total=None: (lambda sql: json.dumps(                          # noqa: E731
        {"total": len(rows) if total is None else total, "rows": rows}))
    open_n, closed_n = base(True, {"path": "x"})["nodes"], base(True, private)["nodes"]

    def boom(sql):
        raise RuntimeError("no such container")
    for label, want, sql in (
            ("live: the PUBLISHED body is what runs — a draft closed in the editor and never published is "
             "still open", 1, db([{"id": "w", "published": open_n, "draft": closed_n}])),
            ("live: a published body that is closed passes, whatever the draft says", 0,
             db([{"id": "w", "published": closed_n, "draft": open_n}])),
            ("live: an active row with no published copy is asked by its draft", 1,
             db([{"id": "w", "published": None, "draft": json.dumps(open_n)}])),
            ("live: no database is NO VERDICT (2), never a pass", 2, boom),
            ("live: a database with no workflow at all is a FAIL, never a pass over zero", 1, db([], total=0)),
            ("live: workflows, none active — nothing registered, a pass", 0, db([], total=5)),
            ("live: a body that is not a list of nodes is a finding, never a silent pass", 1,
             db([{"id": "w", "published": {"nodes": open_n}, "draft": None}]))):
        PUBLIC.clear()                              # the live cases judge "x" as undeclared, whatever PUBLIC holds
        try:
            got = main_live(sql, say=hush)
        finally:
            PUBLIC.clear()
            PUBLIC.update(real_public)
        if got != want:
            raise SystemExit(f"self-test FAILED ({label}): exit {got}, want {want}")
        ok += 1
    rg = _load("run_gates", "run-gates.py")
    if "webhook-auth-lint" not in rg.LIVE_SET or "--live" not in rg.LIVE_ARGS.get("webhook-auth-lint", []):
        raise SystemExit("self-test FAILED: run-gates' live lane does not ask this gate with --live — "
                         "a check nobody calls is not a check")
    ok += 1
    if "webhook-auth-lint" in rg.known_red_for(True):
        raise SystemExit("self-test FAILED: run-gates' live lane would call a red from --live «known» — the tree's "
                         "known-red reason would hide an office's open webhook and its NO VERDICT")
    ok += 1
    if not blueprints():
        raise SystemExit("self-test FAILED: no blueprint in this tree — a scan that finds nothing cannot pass")
    ok += 1
    print(f"self-test OK — {ok} checks")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="G97 — an active public webhook authenticates or is closed.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true",
                    help="ask the office's own n8n database (the bodies it runs), not the tree")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.live:
        return main_live()
    paths = blueprints()
    if not paths:
        print("G97 FAIL — no blueprint was read; a scan that finds nothing proves nothing.")
        return 1
    wfs = load_all(paths)
    found = findings(wfs)
    stale = stale_public(wfs)
    active_open = sum(1 for wf in wfs.values() if wf.get("active")
                      for n in (wf.get("nodes") or []) if str(n.get("type", "")).endswith("webhook"))
    if found or stale:
        print("A WEBHOOK THE EDGE PUBLISHES THAT ANSWERS THE INTERNET WITHOUT A PASSWORD")
        print("-" * 78)
        for wid, path, why in found:
            print(f"  {wid:28} /webhook/{path}  — {why}")
        for p in stale:
            print(f"  {p:28} declared PUBLIC, but no active open webhook carries it any more")
        print("-" * 78)
        print("  -> an internal caller: give the webhook node the office's own private ranges in\n"
              "     `options.ipWhitelist` (n8n enforces it behind the edge), or deactivate a workflow\n"
              "     nobody calls (`active: false`, so a push cannot bring it back).\n"
              "     an outside caller: `authentication: headerAuth` with a per-office secret.\n"
              "     A webhook that really must be public is declared in this gate's PUBLIC, with the\n"
              "     caller that needs it.")
        print(f"\nG97 FAIL — {len(found)} active webhook(s) open over {len(paths)} blueprint(s)"
              f" ({active_open} webhook node(s) in active workflows).")
        return 1
    print(f"G97 PASS — every active webhook either authenticates or is closed to the internet "
          f"({len(paths)} blueprint(s), {active_open} webhook node(s) in active workflows).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
