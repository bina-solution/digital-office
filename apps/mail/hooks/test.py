#!/usr/bin/env python3
"""bbox mail test — run the mail app's E2E suite (the Mail Label Engine / organizer).

Moved here from the INDOX battery (owner decision 2026-08-06): the suite's one persistent red —
the label-registry split between `public.tag_rules` and mailapi `/organizer/settings`
(issues/mail-label-registry-split.yaml) — is a MAIL product defect, so the suite lives with the
code that owns the behaviour. That split is closed (N1, 2026-09-02): mailapi's organizer store is
the ONE rule store, and both this hook and the suite read it — nothing here touches `tag_rules`.
Blueprint: apps/mail/blueprint/n8n/mailOrgTest00001.workflow.ts.

What this suite uniquely proves: labelling of UNLABELLED mail. Every INDOX gmail lane injects
mail that already carries its to_sync label, so a totally broken label engine would leave those
green — this is the only lane that catches a labelling outage. The INDOX-side half of the story
(documents from labelled mail arrive in INDOX) stays in `bbox indox test` via sync_sources'
gmail-doc/gmail-bs/gmail-link and proc-gmail-* lanes.

Mechanics are the proven ones from apps/indox/hooks/test.py, scoped to one suite: REST login →
manual-run from the suite's manual trigger → poll → parse the 🏁 Test Summary straight from the
n8n DB (deflatten) → scorecard → non-zero exit on red. Not imported from the indox hook — an app
never reaches into another app (G9); the ~80 shared lines are the cost of the boundary.
"""
import sys, os, json, time, subprocess, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SUITE_ID, BUDGET_S = "mailOrgTest00001", 360
BASE, HOST_HDR = os.environ.get("INDOX_TEST_BASE", ""), os.environ.get("INDOX_TEST_HOST", "")


def env(k, d=""):
    for ln in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip()
    return d


def _require_test_instance():
    """Refuse to start unless the permanent `test` tenant exists and is enabled.

    The suite run is pinned to instance `test` (schema indox_test, registered in
    public.indox_instances with purpose='test') — production workflows THROW on a missing
    __instance, so without the registration the run dies cryptically inside n8n. There is no
    production mode and no override: "run against the live instance" is not something this CLI
    can be asked to do. Duplicated from apps/indox/hooks/test.py on purpose — an app never
    reaches into another app (G9), same as the rest of this file's shared mechanics.
    """
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    r = subprocess.run(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres",
                        "-d", "postgres", "-t", "-A", "-c",
                        "select 1 from public.indox_instances where id='test' and enabled;"],
                       capture_output=True)
    if r.returncode != 0:
        sys.exit("[mail-test] REFUSING TO RUN: cannot verify the test tenant in "
                 "public.indox_instances (%s) — is the stack up?"
                 % r.stderr.decode("utf-8", errors="replace").strip()[:200])
    if r.stdout.decode("utf-8", errors="replace").strip() != "1":
        sys.exit(
            "[mail-test] REFUSING TO RUN: no enabled 'test' instance in public.indox_instances.\n"
            "  The suite runs exclusively against the permanent test tenant (schema indox_test);\n"
            "  without it the pinned __instance='test' run throws inside n8n.\n"
            "  Provision it (apps/indox/hooks/apply-schema test) and re-run."
        )
    print("[mail-test] test tenant: 'test' registered and enabled in public.indox_instances",
          flush=True)


def _detect_endpoint():
    global BASE, HOST_HDR
    if BASE:
        return
    deadline = time.time() + 180
    while time.time() < deadline:
        for base, host in (("http://localhost:5678", ""), ("http://127.0.0.1", "n8n.localhost")):
            try:
                req = urllib.request.Request(base + "/rest/settings",
                                             headers={"Host": host} if host else {})
                with urllib.request.urlopen(req, timeout=5) as r:
                    if r.status == 200:
                        BASE, HOST_HDR = base, host
                        return
            except Exception:
                pass
        time.sleep(5)
    sys.exit("n8n unreachable for 180s")


def _req(path, method="GET", body=None, ck=None, timeout=120):
    h = {"Content-Type": "application/json"}
    if HOST_HDR:
        h["Host"] = HOST_HDR
    if ck:
        h["Cookie"] = ck
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getheaders(), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.headers.items(), e.read().decode()


def deflatten(arr):
    """n8n 'flatted' execution data — see apps/indox/hooks/test.py for the format notes."""
    def deref(v, seen):
        if isinstance(v, str) and v.isdigit() and int(v) < len(arr):
            i = int(v)
            if i in seen:
                return None
            t = arr[i]
            return t if isinstance(t, str) else walk(t, seen | {i})
        return v

    def walk(v, seen):
        if isinstance(v, list):
            return [deref(x, seen) for x in v]
        if isinstance(v, dict):
            return {k: deref(x, seen) for k, x in v.items()}
        return v
    return deref("0", set())


def ensure_labels():
    """Seed the LOCAL test mailbox's labels from the organizer store (GMAIL_IMAP_MODE=local only).

    This suite appends UNLABELLED mail and asserts the engine labels it, so the mailbox must hold
    the rule labels before the run. The names come from the ONE rule store — mailapi's
    `/organizer/settings` (N1, 2026-09-02: `indox_<tenant>.tag_rules` is retired), the same
    document the engine's `Load Settings (rules)` node reads — and are read inside the mailapi
    container, which is also where `/labels/create` is called. The selection mirrors the engine's
    own `Labels to create`: LABEL trimmed, blanks and `-LABEL` remove-rules skipped (the engine
    never creates those either), a rule the editor disabled (enabled === false) skipped. Bounded
    poll: mailapi seeds the store from its shipped fixture at boot, so an empty answer means
    mailapi is still coming up — if it never fills, run anyway and let the suite report the real
    failure.
    """
    if env("GMAIL_IMAP_MODE", "gmail") != "local":
        return
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    # /labels/create is a canonical op: it REFUSES a call that names no connection, so the labels
    # are seeded into the resolved LOCAL test mailbox explicitly. They used to be seeded into
    # whatever /data/active.json pointed at — the client's Gmail — which is where the label names
    # this suite asserts on were actually being created.
    cid = test_mail_connection()
    if not cid:
        print("[mail-test] no local test mailbox — skipping label seed", flush=True)
        return
    code = (
        "import json,time,urllib.request\n"
        "CID=%r\n"
        "rows=[]\n"
        "for _ in range(12):\n"                                                   # ~60s
        "    try:\n"
        "        d=json.load(urllib.request.urlopen('http://localhost:8970/organizer/settings',timeout=15))\n"
        "        rows=((d.get('gmail') or {}).get('rows')) or []\n"
        "    except Exception:\n"
        "        rows=[]\n"
        "    if rows: break\n"
        "    time.sleep(5)\n"
        "names=[]\n"
        "for r in rows:\n"
        "    if not isinstance(r,dict) or r.get('enabled') is False: continue\n"
        "    n=str(r.get('LABEL') or '').strip()\n"
        "    if not n or n.startswith('-') or n in names: continue\n"
        "    names.append(n)\n"
        "bad=[]\n"
        "for n in names:\n"
        "    q=urllib.request.Request('http://localhost:8970/labels/create',"
        "data=json.dumps({'name':n,'connection_id':CID}).encode(),"
        "headers={'Content-Type':'application/json'},method='POST')\n"
        "    try: urllib.request.urlopen(q,timeout=15)\n"
        "    except Exception as e: bad.append('%%s: %%s' %% (n, str(e)[:60]))\n"
        "print(json.dumps({'rows':len(rows),'names':len(names),'bad':bad},ensure_ascii=False))"
    ) % cid
    r = subprocess.run(["docker", "exec", f"mailapi-{dn}", "python", "-c", code], capture_output=True)
    out = r.stdout.decode("utf-8", errors="replace").strip().splitlines()
    try:
        res = json.loads(out[-1]) if out else {}
    except Exception:
        res = {}
    if not res.get("rows"):
        print("[mail-test] organizer store answered no rules — running anyway so the suite reports it "
              + r.stderr.decode("utf-8", errors="replace").strip()[:120], flush=True)
        return
    bad = res.get("bad") or []
    print(f"[mail-test] label seed from the organizer store: {res.get('names', 0)} labels into {cid}"
          + (f" — {len(bad)} FAILED: {bad[:3]}" if bad else " — ok"), flush=True)


def test_mail_connection():
    """The mailbox this suite is allowed to touch — resolved from the LOCAL mail engine, never
    inherited from mailapi's ambient pointer.

    mailapi now refuses a canonical op that names no connection. Before that guard, this suite's
    `append`/`search`/`listLabels` calls carried no `connection_id` and resolved to
    `/data/active.json` — the CLIENT's real Gmail — which is how two `mailorg_*` fixture messages
    (and 146 sync-v3 ones from the INDOX battery) landed in person9@example.com.

    A non-local id is REFUSED rather than used: seeding unlabelled fixture mail into a real account
    is the incident this closes. Returns "" if the engine is unreachable, so the suite fails loudly
    instead of falling back. Duplicated from apps/indox/hooks/test.py on purpose — an app never
    reaches into another app (G9), same as the rest of this file's shared mechanics.
    """
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    code = ("import json,urllib.request\n"
            "d=json.load(urllib.request.urlopen('http://localhost:8970/engine/profiles',timeout=15))\n"
            "ps=d.get('profiles') or []\n"
            "p=next((x for x in ps if x.get('is_admin') or x.get('admin')), None) or (ps[0] if ps else None)\n"
            "print('CID=' + ((p or {}).get('connection_id') or ''))")
    r = subprocess.run(["docker", "exec", f"mailapi-{dn}", "python", "-c", code],
                       capture_output=True)
    out = r.stdout.decode("utf-8", errors="replace")
    cid = next((l.split("=", 1)[1].strip() for l in out.splitlines()
                if l.startswith("CID=")), "")
    if cid and not cid.startswith("mail_imap_local-"):
        print(f"[mail-test] REFUSING mail connection {cid!r} — not a local test mailbox.",
              flush=True)
        cid = ""
    print(f"[mail-test] test mail connection: "
          f"{cid or 'UNRESOLVED (suite will fail loudly)'}", flush=True)
    return cid


def fetch_summary(eid):
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                        env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                        f'SELECT data FROM execution_data WHERE "executionId"={int(eid)};'],
                       capture_output=True)
    raw = o.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return None
    try:
        d = deflatten(json.loads(raw))
    except Exception as ex:
        return {"RESULT": "❌ SUMMARY PARSE ERROR", "passed": "0", "checks": [f"❌ {ex}"]}
    if not isinstance(d, dict):
        return {"RESULT": "❌ NO EXECUTION DATA", "passed": "0",
                "checks": ["❌ execution data is degenerate (stopped mid-flight?)"]}
    res = d.get("resultData") or {}
    for k, runs in (res.get("runData") or {}).items():
        if "🏁" in k or "Test Summary" in k:
            for run in runs:
                try:
                    return run["data"]["main"][0][0]["json"]
                except Exception:
                    pass
    err = res.get("error") or {}
    return {"RESULT": "❌ NO SUMMARY", "passed": "0",
            "checks": ["❌ died at node '%s': %s" % (res.get("lastNodeExecuted"),
                        str(err.get("message"))[:220])]}


def main():
    _require_test_instance()
    _detect_endpoint()
    ensure_labels()
    hdrs, _ = _req("/rest/login", "POST", {"emailOrLdapLoginId": env("N8N_OWNER_EMAIL"),
                                            "password": env("N8N_OWNER_PASSWORD")})
    ck = "; ".join(v.split(";")[0] for k, v in hdrs if k.lower() == "set-cookie")
    if not ck:
        sys.exit("n8n login failed (N8N_OWNER_* in .env; n8n up?)")
    _, b = _req("/rest/workflows/" + SUITE_ID, ck=ck)
    wf = json.loads(b).get("data")
    if not wf:
        sys.exit(f"workflow {SUITE_ID} not found: {b[:200]}")
    start = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.manualTrigger")["name"]
    # Pinned to the permanent `test` tenant — production workflows THROW on a missing
    # __instance. [2026-08-31] triggerToStartFrom must CARRY THE DATA on n8n 2.17: pins alone
    # are ignored for the start trigger (measured on the indox side twice); the trigger output
    # rides triggerToStartFrom.data as a full ITaskData, pins stay as the belt.
    inj = {"__instance": "test"}
    pin = {start: [{"json": inj}]}
    task_data = {"startTime": int(time.time() * 1000), "executionTime": 0,
                 "executionStatus": "success", "source": [],
                 "data": {"main": [[{"json": inj}]]}}
    t0 = time.time()
    _, rb = _req("/rest/workflows/" + SUITE_ID + "/run", "POST",
                 {"workflowData": {**wf, "pinData": {**(wf.get("pinData") or {}), **pin}},
                  "startNodes": [{"name": start}],
                  "triggerToStartFrom": {"name": start, "data": task_data}, "pinData": pin}, ck)
    try:
        eid = json.loads(rb)["data"]["executionId"]
    except Exception:
        sys.exit("trigger failed: " + rb[:200])
    print(f"[mail-test] mail_organizer: execution {eid} running…", flush=True)
    status = "timeout"
    while time.time() - t0 < BUDGET_S:
        time.sleep(10)
        _, eb = _req("/rest/executions/" + str(eid), ck=ck)
        try:
            j = json.loads(eb)["data"]
            if j.get("finished") or j.get("status") in ("success", "error", "crashed", "canceled"):
                status = j.get("status")
                break
        except Exception:
            pass
    s = fetch_summary(eid) or {}
    ok = status == "success" and str(s.get("RESULT", "")).startswith("✅")
    print("\n════════ MAIL E2E SCORECARD ════════")
    print(f"{'✅' if ok else '❌'} mail_organizer {s.get('RESULT', '(no summary)')} "
          f"{s.get('passed', '')}  exec={eid} {round(time.time() - t0)}s")
    for c in s.get("checks", []) or []:
        print(f"     {c}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
