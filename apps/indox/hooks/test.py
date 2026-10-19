#!/usr/bin/env python3
"""
indox-test — ONE entrypoint for the INDOX v2 E2E suites (bbox indox test).

Usage:
  bbox indox test [all | decide | doc_base | bs | gdoc | pipeline] [--junit <path>]

Runs each n8n suite headlessly (REST manual-run from its manual trigger — the proven
mechanism; the generic start-node regex in indox-trigger-wf misses the '▶ Run …' triggers),
waits for the execution, parses the '🏁 Test Summary' node output, prints a scorecard and
exits non-zero on any red. --junit emits JUnit XML (one <testsuite> per suite, one
<testcase> per summary check).

The suites are FULLY SELF-PREPARING: each one starts by calling the "indox-v2 Test
Fixtures" workflow (bucket + committed fixtures via the indox api) — this CLI only
triggers, waits, parses and reports. FULLY ISOLATED: every run is pinned to the permanent
`test` tenant (schema indox_test; {"__instance": "test"} on every trigger and lane body) —
the battery refuses to start without that instance, and resets it before every run. FULLY LOCAL: apitools with Tesseract
(OCR_ENGINE=local), AI extraction from committed fixtures — no Google Vision/Gemini
anywhere; with DRIVE_BACKEND=local, no Google at all. CI runs this same CLI
(INDOX_TEST_BASE/INDOX_TEST_HOST route it through traefik).

Consolidates the scattered test entrypoints; the static v1==v2 parity checks remain
available as apps/indox/hooks/v2-actions-test.mjs / indox-v2-decide-test.mjs (stack-free,
run via node directly — they need no live stack and no orchestration).
"""
import sys, os, re, json, time, subprocess, urllib.request, urllib.error
from xml.sax.saxutils import escape

# repo root = up THREE from apps/<id>/hooks/. This file used to live in scripts/, where up-two
# was right; the move left it pointing at apps/indox/, so it looked for apps/indox/.env and
# died before running a single test.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# n8n endpoint autodetect — no special env needed anywhere (CI included):
#   1. INDOX_TEST_BASE/INDOX_TEST_HOST override (escape hatch)
#   2. http://localhost:5678 (local dev publish)
#   3. http://127.0.0.1 with Host: n8n.localhost (traefik — the CI shape)
BASE = os.environ.get("INDOX_TEST_BASE", "")
HOST_HDR = os.environ.get("INDOX_TEST_HOST", "")


def _detect_endpoint():
    """Retry up to ~3 min: n8n-push restarts n8n right before this runs (CI does not wait)."""
    global BASE, HOST_HDR
    if BASE:
        return
    import urllib.request as _u
    deadline = time.time() + 180
    while time.time() < deadline:
        for base, host in (("http://localhost:5678", ""), ("http://127.0.0.1", "n8n.localhost")):
            try:
                req = _u.Request(base + "/rest/settings", headers={"Host": host} if host else {})
                with _u.urlopen(req, timeout=5) as r:
                    if r.status == 200:
                        BASE, HOST_HDR = base, host
                        print(f"[indox-test] n8n endpoint: {base}" + (f" (Host: {host})" if host else ""), flush=True)
                        return
            except Exception:
                pass
        time.sleep(5)
    sys.exit("n8n unreachable for 180s (tried localhost:5678 and traefik n8n.localhost)")

# suite key -> (workflow id, expected max runtime seconds)
SUITES = {
    # [wired in 2026-08-21] indoxV2DecideTest01 has 48 assertions on the decide ladder and
    # NOTHING RAN IT. It was not in SUITES, so `bbox indox test` could not reach it and CI
    # never has. It had been carrying the same broken extract_base_doc seed doc_base died
    # on — asserting a branch it could not reach — and reported nothing, for as long as the
    # seed had been wrong. The cheapest coverage in the estate, unwired.
    # First in ORDER on purpose: it is pure decide logic with no stack dependency, so it is
    # the fastest possible signal that the state machine still chooses the right action.
    "decide": ("indoxV2DecideTest01", 240),
    "sync_kernel": ("syncItemApiTest01", 360),   # the Sync Item API (2026-09-02): every ledger op
                                                  # proven on the test tenant — cheap fail-fast, first
    "sync_sources": ("syncSourcesTest01", 900),   # per-source E2E on the sync item (2026-09-02):
                                                  # injector -> real pass -> ledger + documents
                                                  # (polls the ledger until every item settles; the
                                                  # budget must stay ABOVE the workflow's own
                                                  # executionTimeout or the CLI gives up first and
                                                  # reports a wedge instead of the suite's own red)
    "sync_full": ("syncFullTest01", 600),  # the sync PASS itself (2026-09-02): gate / lock / registry
    "sealed_inv": ("indoxV2SealedInv01", 1600),
    "sealed_ship": ("indoxV2SealedShip01", 1600),
    # ALL sealed budgets exceed the suites' own 600s ledger-watch + 1500s executionTimeout head-
    # room: in-battery the router digests the PREVIOUS sealed suite's 100-wide groups while the
    # next one fires, so a watch that closes in seconds standalone legitimately polls minutes
    # under queue contention. A 600 budget re-created the sync_full lesson exactly -- the HARNESS
    # expired first and discarded verdicts the workflow then computed (ord/rcp, battery 16:46).
    "sealed_bs": ("indoxV2SealedBS01", 1600),
    "sealed_ord": ("indoxV2SealedOrd01", 1600),
    "sealed_rcp": ("indoxV2SealedRcp01", 1600),  # per-action sealed lanes, batch 1+100 (505 docs);
                                                  # workflow executionTimeout 1500 + harness slack
    "doc_base": ("indoxV2DocBaseTest01", 360),
    "bs":       ("indoxV2BSTest01", 480),   # 42s typical, but 2-vCPU + doc_base tail-churn
                                            # was ALIVE at 306s (run 28911280222) — headroom
    "gdoc":     ("indoxV2GDocTest01", 900),   # CI-measured: healthy at 729s on the 2-vCPU runner
    "pipeline": ("indoxV2PipelineTest01", 1900),  # in-battery the batch runs right after gdoc's
                                                  # 15 extractions and shares the OCR slots --
                                                  # internal watch is 66x20s=1320, harness above it
                                                  # (the sync_full lesson, third application)  # slowest suite under 4-way parallel:
                                                   # cold-OCR runs measured 748-902s+ (healthy
                                                   # at the old 900 cap — budget-timeout, not wedge)
}
# mail_organizer moved to the mail app (owner decision 2026-08-06): its one persistent red — the
# label-registry split between public.tag_rules and mailapi /organizer/settings — is a MAIL
# product defect (issues/mail-label-registry-split.yaml), so the suite now lives with the code
# that owns the behaviour: blueprint apps/mail/blueprint/n8n/mailOrgTest00001.json, runner
# `bbox mail test` (apps/mail/hooks/test). What it uniquely proved — labelling of UNLABELLED
# mail — is a mail concern; the INDOX-side half (documents from labelled mail arrive in INDOX)
# stays covered here by sync_sources' gmail-doc/gmail-bs/gmail-link + proc-gmail-* lanes.
ORDER = ["decide", "sync_kernel", "sync_sources", "sync_full",
         "sealed_inv", "sealed_ship", "sealed_bs", "sealed_ord", "sealed_rcp",
         "doc_base", "bs", "gdoc", "pipeline"]

# --lanes: suite-internal lane parallelism. Each lane is an independent n8n execution
# (webhook-triggered — the only cross-worker parallelism in queue mode) running ONE of
# the suite's flows; the CLI is the manager that fires lanes concurrently and merges
# verdicts. Slowest flow first so it anchors the wall-clock.
LANES = {"gdoc": ["batch:inv", "batch:ord", "batch:shp", "lc", "extract", "cov", "perr"],
         "pipeline": ["bare", "batch", "cov"],
         "sync_kernel": ["upsert", "take", "record", "fail", "reset", "reap", "cursor", "gate"],
         # [thin-only 2026-08-31, owner order] The five proc-* lanes are GONE: they exercised the
         # v1 processor path (indoxProcessDocument01 / SyncProc* / the gmail downloaders), which
         # the owner retired outright — "the syncs must be thin; there must be no more runs of
         # indoxProcessDocument01 at all". The battery now also ASSERTS zero legacy executions
         # (see _assert_no_legacy_runs). Thin delivery → state-machine completion is proven by
         # these five thin lanes plus the pipeline suite's bare/batch (thin row → COMPLETED).
         "sync_sources": ["drive-gdoc", "drive-bs", "gmail-doc", "gmail-bs", "gmail-link"],
         "sync_full": ["gate", "lock", "registry"]}  # the sync pass: gate / mutex / registry key
                                                       # (asserts live loop-2 pickup latency;
                                                       # contention-flaky under lane concurrency)
LANE_PATHS = {"gdoc": "gdoc-e2e-lane", "pipeline": "pipeline-e2e-lane",
              "sync_kernel": "sync-kernel-e2e-lane",
              "sync_sources": "sync-sources-e2e-lane",
              "sync_full": "sync-full-e2e-lane"}
LANES_ON = False

#: The suite keys this process actually drove. Set by _run_battery once the suite list is
#: resolved, read by main()'s finally so the post-run sweep can be scoped to them. Empty until
#: then, and an empty scope sweeps NOTHING — a run that has not chosen its suites has not
#: seeded anything, and a global fallback here is precisely the cross-lane delete this fixes.
RAN_KEYS = []


def env(k, d=""):
    for ln in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip()
    return d


def _supabase_sql(sql, timeout=60):
    """One statement against the platform Postgres, via the supabase-db container — the same
    convention every other DB touch in this file uses. Returns stripped stdout; raises on a
    non-zero psql exit so callers cannot mistake a broken query for an empty result."""
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    r = subprocess.run(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres",
                        "-d", "postgres", "-t", "-A", "-c", sql],
                       capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace").strip()[:400])
    return r.stdout.decode("utf-8", errors="replace").strip()


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


def login():
    hdrs, _ = _req("/rest/login", "POST", {"emailOrLdapLoginId": env("N8N_OWNER_EMAIL"),
                                            "password": env("N8N_OWNER_PASSWORD")})
    cks = [v.split(";")[0] for k, v in hdrs if k.lower() == "set-cookie"]
    return "; ".join(cks)


def deflatten(arr):
    """n8n execution_data.data is 'flatted': index 0 is the root; every string INSIDE a
    container is an index reference. A referenced STRING is the value itself (deref exactly
    once — re-dereferencing numeric-string VALUES like "06146" corrupts them)."""
    def deref(v, seen):
        if isinstance(v, str) and v.isdigit() and int(v) < len(arr):
            i = int(v)
            if i in seen:
                return None
            t = arr[i]
            if isinstance(t, str):
                return t                     # a string target IS the value — stop
            return walk(t, seen | {i})
        return v                             # non-index primitive (num/bool/null)
    def walk(v, seen):
        if isinstance(v, list):
            return [deref(x, seen) for x in v]
        if isinstance(v, dict):
            return {k: deref(x, seen) for k, x in v.items()}
        return v
    return deref("0", set())


#: [thin-only 2026-08-31, owner order] The retired v1 processor path. A battery is green only
#: if NONE of these executed inside its window — the positive proof that syncs stay thin and
#: the state machine owns all processing. Deactivation alone is not proof; this is.
LEGACY_RETIRED = ("indoxProcessDocument01", "SyncProcGDoc0001", "SyncProcBS000001",
                  "indoxGmailDocDownloader01", "indoxGmailBSDownloader01",
                  "indoxGmailLinkDownloader01")


def _max_exec_id():
    """Highest n8n execution id right now — the battery-window fence for the legacy guard."""
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                        env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                        "SELECT coalesce(max(id),0) FROM execution_entity;"],
                       capture_output=True)
    try:
        return int(o.stdout.decode().strip() or 0)
    except ValueError:
        return 0


def _legacy_runs_since(start_id):
    """[(workflowId, count)] of retired-processor executions after the fence. Empty = proof."""
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    wfs = ",".join("'%s'" % w for w in LEGACY_RETIRED)
    o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                        env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                        'SELECT "workflowId"||\'|\'||count(*) FROM execution_entity '
                        f'WHERE id>{int(start_id)} AND "workflowId" IN ({wfs}) GROUP BY 1;'],
                       capture_output=True)
    out = []
    for line in o.stdout.decode().strip().splitlines():
        if "|" in line:
            w, n = line.rsplit("|", 1)
            out.append((w, int(n)))
    return out


def fetch_summary(eid):
    """Read the 🏁 Test Summary output (or the failure detail) straight from the n8n DB."""
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
    if not isinstance(d, dict):   # stopped/killed executions can leave degenerate flatted data
        return {"RESULT": "❌ NO EXECUTION DATA", "passed": "0",
                "checks": ["❌ execution data is degenerate (stopped mid-flight?)"]}
    res = d.get("resultData") or {}
    rd = res.get("runData") or {}
    for k, runs in rd.items():
        if "🏁" in k or "Test Summary" in k:
            for run in runs:
                try:
                    return run["data"]["main"][0][0]["json"]
                except Exception:
                    pass
    # no summary -> surface WHERE it died so a remote (CI) failure is traceable from the log alone
    err = res.get("error") or {}
    return {"RESULT": "❌ NO SUMMARY", "passed": "0",
            "checks": ["❌ died at node '%s': %s" % (res.get("lastNodeExecuted"),
                        str(err.get("message"))[:220])]}


def dump_state(reason):
    """Self-diagnosis when a suite hangs or dies without a summary: queued/running executions,
    redis queue depth, worker log tail. Works locally and in CI (docker exec; no SSH needed)."""
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    print(f"[indox-test] ── state dump ({reason}) ──", flush=True)
    o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                        env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-F", " | ", "-c",
                        'SELECT e.id, w.name, e.status, e."startedAt" FROM execution_entity e '
                        'JOIN workflow_entity w ON w.id=e."workflowId" ORDER BY e.id DESC LIMIT 25;'],
                       capture_output=True)
    print("[executions]", flush=True)
    print(o.stdout.decode("utf-8", errors="replace"), flush=True)
    rp = env("REDIS_PASSWORD")
    o = subprocess.run(["docker", "exec", f"redis-{dn}", "sh", "-lc",
                        f"redis-cli -a '{rp}' --no-auth-warning eval \"local ks=redis.call('keys','bull:*'); local out={{}}; for i,k in ipairs(ks) do local t=redis.call('type',k)['ok']; if t=='list' or t=='zset' then out[#out+1]=k..'='..(t=='list' and redis.call('llen',k) or redis.call('zcard',k)) end end return out\" 0"],
                       capture_output=True)
    print("[redis queues]", flush=True)
    print(o.stdout.decode("utf-8", errors="replace"), flush=True)
    for c in (f"n8n-worker-1-{dn}", f"n8n-{dn}", f"n8n-task-runners-{dn}"):
        o = subprocess.run(["docker", "logs", "--tail", "12", c], capture_output=True)
        print(f"[logs {c}]", flush=True)
        print((o.stdout.decode(errors="replace") + o.stderr.decode(errors="replace"))[-1500:], flush=True)


_LOCALMAIL_DONE = False


def bootstrap_localmail():
    """When the deployment runs GMAIL_IMAP_MODE=local, seed mailapi's label registry
    from tag_rules so label-name search resolution works. The registry lives in mailapi's own
    /data volume, so it survives a restart — but a FRESH stack (down -v) starts with none, which is
    the case this covers. No-op in gmail mode / on any failure.

    NB the old reason given here — "GreenMail is in-memory, a mailserver restart empties it" — was
    wrong twice over once the real MTA landed: the registry was never in the mail server, and mail
    now persists across restarts anyway. The seeding is still needed; the justification was not.

    Called once up front AND again before each suite, because on a fresh database the first call
    has nothing to read: `tag_rules` is seeded by the suites themselves ("indox-v2 Test Fixtures"),
    so the up-front call printed "no tag_rules labels yet (skipping)" and never ran again. The
    mail_organizer suite then found an empty label registry and failed 0/2 — 22 labels never
    created, DOC_TO_SYNC never applied — on a system whose label engine was fine.

    The retry costs one cheap query per suite and fixes the `all` path, where mail_organizer runs
    second and sync_kernel has already seeded the fixtures. It does NOT fix a single-suite run
    against a virgin database (`bbox indox test mail_organizer` on a stack that has never run
    anything): that suite seeds its own fixtures AFTER this call, so the registry is still empty
    when it appends. Closing that would mean triggering the fixture workflow from here before
    bootstrapping — worth doing if anyone starts running this suite in isolation, and deliberately
    not done now.
    """
    global _LOCALMAIL_DONE
    if _LOCALMAIL_DONE:
        return
    if env("GMAIL_IMAP_MODE", "gmail") != "local":
        _LOCALMAIL_DONE = True
        return
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    # [one rules store 2026-09-03, owner Decision N1] the label vocabulary is the mail app's
    # organizer settings — the same store the engine evaluates and mailapi's search resolves
    # through. Read it from inside the mailapi container (the harness has no network edge of its own).
    o = subprocess.run(["docker", "exec", f"mailapi-{dn}", "python3", "-c",
                        "import json,urllib.request;"
                        "d=json.loads(urllib.request.urlopen('http://127.0.0.1:8970/organizer/settings',timeout=30).read().decode());"
                        "L=((d.get('gmail') or {}).get('labels') or {});"
                        "print('\\n'.join(sorted({str(v.get('name')).strip() for v in L.values() if isinstance(v,dict) and v.get('name')})))"],
                       capture_output=True)
    labels = [l.strip() for l in o.stdout.decode("utf-8", errors="replace").splitlines() if l.strip()]
    if not labels:
        print("[indox-test] localmail bootstrap: the organizer store carries no labels yet (skipping)", flush=True)
        return
    payload = json.dumps(labels, ensure_ascii=False)
    # /labels/create is a canonical op and now REFUSES an unnamed connection. Seed the registry
    # into the resolved LOCAL test mailbox explicitly — it used to go to /data/active.json, i.e.
    # the client's Gmail.
    cid = test_mail_connection()
    if not cid:
        print("[indox-test] localmail bootstrap: no local test mailbox — skipping", flush=True)
        return
    code = ("import json,urllib.request\n"
            "CID=%r\n"
            "for n in json.loads(open('/tmp/_lm_labels.json',encoding='utf-8').read()):\n"
            "    r=urllib.request.Request('http://localhost:8970/labels/create',"
            "data=json.dumps({'name':n,'connection_id':CID}).encode(),"
            "headers={'Content-Type':'application/json'},method='POST')\n"
            "    urllib.request.urlopen(r,timeout=15)\n"
            "print('ok')" % cid)
    import tempfile
    # [tmp-collision 2026-08-24] UNIQUE host temp name, not a fixed /tmp/_lm_labels.json.
    # bbox.cmd runs this as root (`wsl -u root`), but a file left in /tmp by an earlier
    # non-root run is owned by that user, and the kernel's fs.protected_regular=1 refuses an
    # O_CREAT open of another user's file in a sticky world-writable dir -- FOR ROOT TOO. The
    # result was an unhandled PermissionError that killed the whole battery in bootstrap,
    # before a single suite ran, on a stack that was perfectly healthy. The container-side
    # path stays fixed: inside mailapi there is no such collision.
    fd, tf = tempfile.mkstemp(prefix="_lm_labels_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        # container is `mailapi-<deployment>` — the mail API service was renamed from `inbox` to
        # `mailapi` when the three mail apps merged into one. The old name silently no-op'd this
        # bootstrap (docker cp/exec both fail on a missing container, and only `ok` is checked), so the
        # label registry stayed empty and mail_organizer failed 0/2 on a system whose engine was fine.
        subprocess.run(["docker", "cp", tf, f"mailapi-{dn}:/tmp/_lm_labels.json"], capture_output=True)
        r = subprocess.run(["docker", "exec", f"mailapi-{dn}", "python", "-c", code], capture_output=True)
    finally:
        try:
            os.unlink(tf)
        except OSError:
            pass
    ok = b"ok" in r.stdout
    err = r.stderr.decode("utf-8", errors="replace")[:120]
    if ok:
        _LOCALMAIL_DONE = True
    print(f"[indox-test] localmail bootstrap: {len(labels)} labels "
          f"{'registered' if ok else 'FAILED: ' + err}", flush=True)


#: Resolved once per process by test_mail_connection(); "" until then.
_TEST_MAIL_CID = None


def test_mail_connection():
    """The mailbox this battery is allowed to touch — resolved, never assumed.

    mailapi's canonical ops now REFUSE a call that names no connection
    (`_explicit_connection_required`). Before that guard, a suite mail op with no `connection_id`
    fell through to mailapi's ambient pointer `/data/active.json`, which on this deployment is the
    CLIENT's real Gmail: that is how 148 fixture messages (`sv3s_`/`sv3f_`/`mailorg`, all addressed
    to @demo.indox) ended up in person9@example.com between 2026-08-05 and 2026-08-09.

    So the id is resolved from the LOCAL mail engine's own profiles — the same source
    scripts/ops/e2e-loadtest/provision.py already uses — and anything that is not a
    `mail_imap_local-*` connection is REFUSED rather than used. Two independent things then have to
    go wrong before a suite can reach a real account: the engine would have to hand back a
    non-local id AND this check would have to pass it.

    Deliberately not hardcoded: `mail_imap_local-1c058b0d` is a vault-instance hash and differs per
    deployment, so the literal that `ztestGmailApi01` and `demo/loadtest.yml` carry is itself a
    portability bug. Returns "" if the engine cannot be reached; callers then send "" and mailapi
    fails the op LOUDLY, which is the correct outcome — never a silent fallback.
    """
    global _TEST_MAIL_CID
    if _TEST_MAIL_CID is not None:
        return _TEST_MAIL_CID
    _TEST_MAIL_CID = ""
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
        # The whole point of this function. A non-local id here means the mail engine is bound to a
        # real account; seeding fixtures into it is the incident, not a fallback worth taking.
        print(f"[indox-test] REFUSING mail connection {cid!r} — not a local test mailbox. "
              f"Mail lanes will fail loudly rather than seed a real account.", flush=True)
        cid = ""
    _TEST_MAIL_CID = cid
    print(f"[indox-test] test mail connection: {cid or 'UNRESOLVED (mail lanes will fail loudly)'}",
          flush=True)
    return cid


def wait_for_webhooks():
    """Fresh-instance startup race: n8n retries failed activations in ~128s waves, so
    production webhooks (BS extractor bs_ex_2_dev, invoice_extractor) may register minutes
    after /healthz is green. Wait for them before running suites."""
    need = {"bs_ex_2_dev", "invoice_extractor"}
    if LANES_ON:
        need |= {p for k in LANES for p in [LANE_PATHS[k]]}
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    deadline = time.time() + 300
    while time.time() < deadline:
        o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                            env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                            'SELECT "webhookPath" FROM webhook_entity;'], capture_output=True)
        have = set(o.stdout.decode(errors="replace").split())
        missing = need - have
        if not missing:
            print("[indox-test] webhooks registered:", ", ".join(sorted(need)), flush=True)
            return
        print(f"[indox-test] waiting for webhooks: {sorted(missing)}", flush=True)
        time.sleep(10)
    sys.exit("required webhooks never registered: " + ", ".join(sorted(missing)))


# ensure_labels_for() (poll tag_rules, then bootstrap) moved to apps/mail/hooks/test.py with the
# mail_organizer suite — it existed solely for that suite's unlabelled-mail lane. The up-front
# bootstrap_localmail() call above stays: the sync gmail lanes still search the local-mail
# registry by label name, so on a fresh volume it must be seeded before the battery.


def ensure_fresh_corpus():
    """Keep the fixture corpus inside the OLD window before any suite seeds from it.

    INDOX terminalises documents older than settings.OldDocumentMonthsBack as STATUS=OLD.
    That is wall-clock relative; demo-docs is a fixed 2025 snapshot. Lanes that assert
    COMPLETED (pipeline's `bare`, and the batch lane's per-doc status) therefore rot on a
    calendar, not on a code change — which is exactly how they failed on 2026-08-06, the
    day the fixture stopped force-seeding OldDocumentMonthsBack=1200 over the operator's 6.

    So the corpus is re-stamped FROM THE DB CLOCK at seed time rather than pinned to a
    wider window for the suite's own run: widening the window would re-hide the product
    rule the suite exists to exercise. scripts/refresh-corpus-dates.py owns the stamping;
    this is only the trigger. Set INDOX_TEST_SKIP_CORPUS_REFRESH=1 to opt out (e.g. when
    bisecting a corpus change).
    """
    if os.environ.get("INDOX_TEST_SKIP_CORPUS_REFRESH"):
        print("[indox-test] corpus date refresh: skipped (INDOX_TEST_SKIP_CORPUS_REFRESH)", flush=True)
        return
    gen = os.path.join(ROOT, "scripts", "refresh-corpus-dates.py")
    if not os.path.exists(gen):
        return
    chk = subprocess.run([sys.executable, gen, "--check"], capture_output=True)
    out = (chk.stdout.decode(errors="replace") + chk.stderr.decode(errors="replace")).strip()
    if chk.returncode == 0:
        print("[indox-test] " + (out.splitlines() or ["corpus dates fresh"])[-1], flush=True)
        return
    print("[indox-test] fixture corpus is outside the OLD window — re-stamping before the "
          "battery:\n" + out, flush=True)
    r = subprocess.run([sys.executable, gen, "--purge-uploads"], capture_output=True)
    print((r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")).strip(), flush=True)
    if r.returncode != 0:
        # Loud, not fatal: the suites still run and will report the real STATUS:OLD reds.
        # A green that depended on a refresh that did not happen would be the worse outcome.
        print("[indox-test] ⚠ corpus refresh FAILED — suites will run against the stale "
              "corpus and any COMPLETED assertion may report OLD", flush=True)
    else:
        print("[indox-test] ⚠ tracked fixture files under apps/indox/blueprint/ were "
              "regenerated — commit them (`git status`)", flush=True)


def run_suite(ck, key):
    wfid, budget = SUITES[key]
    _, b = _req("/rest/workflows/" + wfid, ck=ck)
    wf = json.loads(b).get("data")
    if not wf:
        return {"suite": key, "status": "missing", "summary": None, "eid": None, "elapsed": 0,
                "detail": f"GET /rest/workflows/{wfid} returned no workflow: {b[:200]}"}
    start = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.manualTrigger")["name"]
    # Every manual suite runs pinned to the permanent `test` tenant (schema indox_test) —
    # production workflows THROW on a missing __instance, so this injection IS the run.
    # [2026-08-31] triggerToStartFrom must CARRY THE DATA on n8n 2.17: pins alone are ignored
    # for the start trigger (measured twice — IndoxResetFull01 exec 3734995 saw {} at When
    # Called, then doc_base exec 3735677 seeded schema `undefined` for exactly the same reason).
    # The trigger output rides triggerToStartFrom.data as a full ITaskData; the pins stay in
    # BOTH body.pinData and workflowData.pinData as the belt for other run semantics.
    inj = {"__instance": "test"}
    pin = {start: [{"json": inj}]}
    task_data = {"startTime": int(time.time() * 1000), "executionTime": 0,
                 "executionStatus": "success", "source": [],
                 "data": {"main": [[{"json": inj}]]}}
    t0 = time.time()
    _, rb = _req("/rest/workflows/" + wfid + "/run", "POST",
                 {"workflowData": {**wf, "pinData": {**(wf.get("pinData") or {}), **pin}},
                  "startNodes": [{"name": start}],
                  "triggerToStartFrom": {"name": start, "data": task_data}, "pinData": pin}, ck)
    try:
        eid = json.loads(rb)["data"]["executionId"]
    except Exception:
        return {"suite": key, "status": "trigger-failed", "summary": None, "eid": None,
                "elapsed": 0, "detail": rb[:200]}
    print(f"[indox-test] {key}: execution {eid} running…", flush=True)
    status = "timeout"
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    beats = 0
    last_max, last_progress = "", time.time()
    last_err = -1
    while time.time() - t0 < budget:
        time.sleep(10)
        beats += 1
        st = "?"
        _, eb = _req("/rest/executions/" + str(eid), ck=ck)
        try:
            j = json.loads(eb)["data"]
            st = j.get("status")
            if j.get("finished") or st in ("success", "error", "crashed", "canceled"):
                status = st
                break
        except Exception:
            pass
        # stall detector: a healthy suite spawns sub-executions constantly. If the max
        # execution id hasn't moved in 120s, the environment is wedged (e.g. task-runner
        # broker not dispatching) — fail LOUDLY now instead of burning the whole budget.
        o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                            env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                            "SELECT max(id) FROM execution_entity;"], capture_output=True)
        cur_max = o.stdout.decode(errors="replace").strip()
        if cur_max != last_max:
            last_max, last_progress = cur_max, time.time()
        elif time.time() - last_progress > 120:
            print(f"[indox-test] {key}: STALLED — no new executions for 120s (exec {eid} still {st})",
                  flush=True)
            dump_state(f"{key}: stalled")
            _req("/rest/executions/" + str(eid) + "/stop", "POST", {}, ck)
            status = "stalled"
            break
        if beats % 3 == 0:  # live heartbeat every ~30s: shows WHERE the run is, so hangs are visible
            # (cur_max vs the previous heartbeat = sub-executions completed since — movement =健)
            o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                                env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-F", "|", "-c",
                                "SELECT status||' '||count(*)||'x '||string_agg(DISTINCT w.name, ',') "
                                "FROM execution_entity e JOIN workflow_entity w ON w.id=e.\"workflowId\" "
                                "WHERE e.status IN ('running','new') GROUP BY status;"],
                               capture_output=True)
            act = " ; ".join(x for x in o.stdout.decode(errors="replace").splitlines() if x.strip()) if o.stdout else ""
            oe = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                                 env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                                 "SELECT count(*) FROM execution_entity WHERE status='error';"],
                                capture_output=True)
            try:
                err_now = int(oe.stdout.decode().strip() or 0)
            except ValueError:
                err_now = -1
            delta = (err_now - last_err) if (last_err >= 0 and err_now >= 0) else 0
            last_err = err_now
            warn = f" ⚠ errors={err_now}(+{delta})" if delta else f" errors={err_now}"
            print(f"[indox-test] {key}: {round(time.time()-t0)}s elapsed, exec {eid}={st}, "
                  f"total-execs={cur_max};{warn}; active: {act.strip() or 'none'}", flush=True)
    summary = fetch_summary(eid)
    ok = status == "success" and str((summary or {}).get("RESULT", "")).startswith("✅")
    print(f"[indox-test] {key}: {'✅' if ok else '❌'} {(summary or {}).get('RESULT', status)} "
          f"({(summary or {}).get('passed', '?')}) in {round(time.time() - t0)}s", flush=True)
    if not ok:   # a red verdict must be self-explanatory from the log alone (CI runner is gone later)
        for c in (summary or {}).get("checks", []) or []:
            print(f"[indox-test] {key}:   {c}", flush=True)
    if not ok:   # any red verdict dumps state — the NO-SUMMARY fallback dict is truthy,
                 # so gating on `not summary` silently skipped the dump (seen on CI)
        dump_state(f"{key}: status={status}, result={(summary or {}).get('RESULT', '?')}")
    return {"suite": key, "status": status, "eid": eid,
            "elapsed": round(time.time() - t0), "summary": summary}


def run_lane(key, lane, budget):
    """One lane = one webhook-triggered execution of the suite workflow, routed by the
    Lane Switch to a single flow. The webhook response IS the lane verdict (the lane's
    Assert node items, via Respond Lane). Verdict printed immediately — a later lane
    failure can't lose it."""
    t0 = time.time()
    try:
        # connection_id is part of the lane request, not something the suite infers: mailapi
        # refuses an unnamed mail op, and an omitted id used to mean "the client's Gmail".
        # __instance likewise: webhook lanes bypass the pinned manual trigger, so the tenant
        # rides in the lane body itself — production workflows THROW on a missing __instance.
        _, b = _req("/webhook/" + LANE_PATHS[key], "POST",
                    {"lane": lane, "connection_id": test_mail_connection(),
                     "__instance": "test"},
                    timeout=budget + 30)
        items = json.loads(b) if b.strip() else []
        if isinstance(items, dict):
            items = [items]
    except Exception as ex:
        print(f"[indox-test] {key}/{lane}: ❌ lane transport failed: {ex}", flush=True)
        return {"lane": lane, "ok": False, "detail": f"transport: {ex}",
                "elapsed": round(time.time() - t0)}
    results = [str((i.get("json", i) or {}).get("result", "")) for i in items
               if isinstance(i, dict) and (i.get("json", i) or {}).get("result") is not None]
    ok = bool(results) and all("PASS" in r for r in results)
    detail = "; ".join(r[:120] for r in results) or f"lane execution failed: {b[:160]}"
    print(f"[indox-test] {key}/{lane}: {'✅' if ok else '❌'} {detail} "
          f"in {round(time.time() - t0)}s", flush=True)
    return {"lane": lane, "ok": ok, "detail": detail, "elapsed": round(time.time() - t0)}


def run_suite_lanes(ck, key):
    """Lane-parallel replacement for run_suite: fire all lanes concurrently, merge into
    one scorecard entry. Wall-clock ≈ slowest lane instead of sum(flows)."""
    import concurrent.futures
    _, budget = SUITES[key]
    lanes = LANES[key]
    t0 = time.time()
    print(f"[indox-test] {key}: LANE mode — {len(lanes)} lanes: {' + '.join(lanes)}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(lanes)) as ex:
        futs = {ex.submit(run_lane, key, ln, budget): ln for ln in lanes}
        lr = [f.result() for f in futs]
    lr.sort(key=lambda r: lanes.index(r["lane"]))
    n_ok = sum(1 for r in lr if r["ok"])
    all_ok = n_ok == len(lanes)
    summary = {"RESULT": "✅ ALL LANES PASS" if all_ok else "❌ LANES FAILED",
               "passed": f"{n_ok}/{len(lanes)}",
               "checks": [f"{'✅' if r['ok'] else '❌'} lane {r['lane']} — {r['detail']} "
                          f"({r['elapsed']}s)" for r in lr]}
    status = "success" if all_ok else "error"
    print(f"[indox-test] {key}: {'✅' if all_ok else '❌'} {summary['RESULT']} "
          f"({summary['passed']}) in {round(time.time() - t0)}s", flush=True)
    if not all_ok:
        dump_state(f"{key}: lanes failed ({summary['passed']})")
    return {"suite": key, "status": status, "eid": "lanes",
            "elapsed": round(time.time() - t0), "summary": summary}


def junit(results, path):
    ts = []
    for r in results:
        checks = (r["summary"] or {}).get("checks") or []
        cases, fails = [], 0
        for c in checks:
            name = escape(c.lstrip("✅❌ ").split(" — ")[0])
            if c.startswith("✅"):
                cases.append(f'    <testcase name="{name}"/>')
            else:
                fails += 1
                cases.append(f'    <testcase name="{name}"><failure message="{escape(c)}"/></testcase>')
        if not checks:  # no summary at all = suite-level failure
            fails += 1
            cases.append(f'    <testcase name="run"><failure message="status={r["status"]}, no summary"/></testcase>')
        ts.append(f'  <testsuite name="indox-{r["suite"]}" tests="{max(len(checks),1)}" failures="{fails}" time="{r["elapsed"]}">\n'
                  + "\n".join(cases) + "\n  </testsuite>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n' + "\n".join(ts) + "\n</testsuites>\n"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    open(path, "w", encoding="utf-8").write(xml)
    print(f"[indox-test] junit written: {path}")


def _fixture_sweep(label, keys=None):
    """Run apps/indox/hooks/fixture-sweep.py. Never raises — a sweep that blows up must not be
    what makes the battery red, and must not swallow the battery's own verdict either.

    `keys` are the suite keys THIS run drove, and passing them is a correctness fix, not
    tidiness. This sweep used to be global: on 2026-08-06 a doc_base/gdoc/pipeline battery
    deleted 7 `sv3s_` rows belonging to another lane's in-flight `sync_sources` run, because
    "clean up after my run" was implemented as "clean up after everybody". The registry knows
    which blueprint owns which prefix, so naming the workflows this run touched is enough to
    make the sweep incapable of reaching another lane's fixtures.

    Set INDOX_TEST_NO_SWEEP=1 to skip (for deliberately inspecting what a crash left behind —
    which is exactly how the 92 stranded fixture rows were found on 2026-08-06)."""
    if os.environ.get("INDOX_TEST_NO_SWEEP") == "1":
        print(f"[indox-test] fixture sweep ({label}) SKIPPED — INDOX_TEST_NO_SWEEP=1", flush=True)
        return
    cmd = [sys.executable, os.path.join(ROOT, "apps", "indox", "hooks", "fixture-sweep.py"),
           "--label", label,
           # [sealed 2026-08-31] the sealed suites legitimately seed 505 rows per run (5 lanes
           # x batch 1+100; FIVE of them in a full battery = 1,414 rows + the rest = 1,525 measured),
           # over the sweep's default 300-row cap. 2000 keeps the cap's
           # purpose (a prefix matching THOUSANDS still refuses) while letting a sealed battery
           # sweep itself.
           "--max", "2000"]
    if keys:
        cmd += ["--workflows", ",".join(SUITES[k][0] for k in keys if k in SUITES)]
    try:
        subprocess.run(cmd, timeout=300)
    except Exception as ex:
        # Loud, but not fatal. A failed sweep leaves fixtures in the client's table, which is bad;
        # turning a green battery red because psql was slow is a different kind of bad, and the
        # next run's pre-sweep gets another go at it.
        print(f"[indox-test] fixture sweep ({label}) FAILED: {ex}", flush=True)


def _registry_scope_gate():
    """G64, run BEFORE the battery: refuse to start if any suite can still reach the live registry.

    This is a pre-flight, not a CI nicety, and the ordering is the whole point. The failure it
    guards against is not "a test went red" — it is `sv3Inject3x001` appending fixture mail into the
    client's production mailbox and applying the client's real `to_sync` labels to it, which puts
    fixtures into the live pipeline as genuine client documents. There is no cleanup for that: the
    sweep can delete a row from a table, it cannot un-send a message or un-label a thread. So the
    check has to be a gate on STARTING, not a verdict at the end.

    Static, and fast (no stack needed). Non-zero exits the battery before a single lane fires.
    """
    lint = os.path.join(ROOT, "scripts", "refactor", "test-registry-scope-lint.py")
    if not os.path.exists(lint):
        print("[indox-test] G64 gate MISSING at %s — refusing to run the battery blind" % lint,
              flush=True)
        sys.exit(2)
    r = subprocess.run([sys.executable, lint], capture_output=True, timeout=120)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
    if r.returncode != 0:
        print(out, flush=True)
        sys.exit("[indox-test] REFUSING TO RUN: a test blueprint can still reach the live sync "
                 "registry or emit a mail op with no connection_id. Fix the findings above — a "
                 "battery started in this state seeds the client's real mailbox, and nothing "
                 "cleans that up.")
    print("[indox-test] G64 test-registry scope gate: %s"
          % (out.splitlines()[-1] if out else "PASS"), flush=True)


def _reset_test_instance():
    """Per-run reset of the permanent `test` tenant, and a hard gate on starting without one.

    IndoxResetFull01 with {"instance":"test","setup":true,"kill_execs":false} is clear-to-initial
    plus config reseed, scoped to the pinned instance; kill_execs stays false because another
    lane's executions are not this battery's to kill. Triggered via apps/indox/hooks/trigger-wf
    (the proven executeWorkflowTrigger pin mechanism), then WAITED on through the n8n DB — the
    same execution_entity polling the rest of this file uses — because at this point in the
    bring-up neither the endpoint nor a login cookie exists yet.

    Failure is a refusal, not a warning: a battery started on a half-reset tenant reports the
    previous run's leftovers as product reds, which is worse than no run at all."""
    # confirm names the instance ON PURPOSE (Reset Scope's guard): a token you could paste from
    # another deployment's runbook is not a confirmation.
    payload = json.dumps({"instance": "test", "confirm": "RESET-INSTANCE:test",
                          "setup": True, "kill_execs": False})
    tw = os.path.join(ROOT, "apps", "indox", "hooks", "trigger-wf")
    try:
        r = subprocess.run(["bash", tw, "IndoxResetFull01", payload],
                           capture_output=True, timeout=120)
    except Exception as ex:
        sys.exit(f"[indox-test] REFUSING TO RUN: could not invoke {tw}: {ex}")
    out = (r.stdout.decode("utf-8", errors="replace")
           + r.stderr.decode("utf-8", errors="replace")).strip()
    print(f"[indox-test] test-instance reset: {out or '(no output)'}", flush=True)
    m = re.search(r"execution (\d+)", out)
    if r.returncode != 0 or not m:
        sys.exit("[indox-test] REFUSING TO RUN: IndoxResetFull01 did not start (see above) — "
                 "the battery must not run on an un-reset test tenant.")
    eid = int(m.group(1))
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(5)
        o = subprocess.run(["docker", "exec", f"n8n-postgres-{dn}", "psql", "-U",
                            env("POSTGRES_USER", "hacohen"), "-d", "n8n", "-t", "-A", "-c",
                            f"SELECT status FROM execution_entity WHERE id={eid};"],
                           capture_output=True)
        st = o.stdout.decode("utf-8", errors="replace").strip()
        if st == "success":
            print(f"[indox-test] test-instance reset: execution {eid} success", flush=True)
            return
        if st in ("error", "crashed", "canceled"):
            sys.exit(f"[indox-test] REFUSING TO RUN: IndoxResetFull01 execution {eid} ended "
                     f"'{st}' — the test tenant is in an unknown state; fix the reset first.")
    sys.exit(f"[indox-test] REFUSING TO RUN: IndoxResetFull01 execution {eid} did not finish "
             f"within 600s — the test tenant is in an unknown state.")


def _seed_test_connections():
    """Mint the test tenant's connection bindings for THIS deployment, after the reset.

    Both ids are vault-instance hashes that differ per deployment, so the fixture can never
    carry them — they are resolved live and REQUIRED to be local-engine ids. A non-local id
    here is the 2026-08-05 incident (fixtures into a real account), not a fallback:

      * settings.test_connections — the drive_local admin connection + the local IMAP mailbox
        (upsert: runtime-minted per deployment, re-asserted every run).
      * settings.sync_registry    — '[]', insert-only, so the scheduled per-instance sync pass
        over the test tenant is a loud no-op instead of an error (suites install their own).
    """
    dn = env("DEPLOYMENT_NAME", "shlomo-laptop")
    # (a) drive: admin profile's connection — read from the drive service the same way this
    # file reaches mailapi: python/urllib INSIDE the container (no curl there), localhost port.
    code = ("import json,urllib.request\n"
            "d=json.load(urllib.request.urlopen('http://localhost:8975/connections',timeout=15))\n"
            "c=next((c for c in (d.get('connections') or []) if c.get('profile_id')=='admin'),{})\n"
            "print('DCID=' + (c.get('connection_id') or c.get('id') or ''))")
    r = subprocess.run(["docker", "exec", f"drive-{dn}", "python", "-c", code],
                       capture_output=True)
    out = r.stdout.decode("utf-8", errors="replace")
    dcid = next((l.split("=", 1)[1].strip() for l in out.splitlines()
                 if l.startswith("DCID=")), "")
    if not dcid.startswith("drive_local-"):
        sys.exit(f"[indox-test] REFUSING TO RUN: drive admin connection is {dcid!r}, not a "
                 f"drive_local-* id — tests never run against a real Google connection.")
    # (b) mail: the same resolution (and the same refusal) the battery already uses.
    mcid = test_mail_connection()
    if not mcid.startswith("mail_imap_local-"):
        sys.exit("[indox-test] REFUSING TO RUN: no mail_imap_local-* test mailbox resolved — "
                 "tests never run against a real mail account.")
    val = json.dumps({"drive_connection_id": dcid, "mail_connection_id": mcid,
                      "drive_profile_id": "admin"}).replace("'", "''")
    try:
        # `instance` is the column's DDL default — the SCHEMA is the tenant boundary; the
        # column kept its historic constant (see sync-registry-converge.py DEFAULT_INSTANCE).
        _supabase_sql(
            "insert into indox_test.settings (instance, key, value) "
            "values ('incoming-documents-main', 'test_connections', '%s') "
            "on conflict (instance, key) do update "
            "set value = excluded.value, updated_at = now();" % val)
        _supabase_sql(
            "insert into indox_test.settings (instance, key, value) "
            "values ('incoming-documents-main', 'sync_registry', '[]') "
            "on conflict (instance, key) do nothing;")
    except Exception as ex:
        sys.exit(f"[indox-test] REFUSING TO RUN: could not seed indox_test.settings: {ex}")
    print(f"[indox-test] test connections seeded: drive={dcid} mail={mcid}", flush=True)


def _run_battery():
    a = [x for x in sys.argv[1:]]
    jpath = None
    if "--junit" in a:
        i = a.index("--junit")
        jpath = a[i + 1] if i + 1 < len(a) else "ci-artifacts/indox-e2e.xml"
    if "--budget-scale" in a:   # parallel on few cores: same work, shared CPU — scale budgets
        i = a.index("--budget-scale")
        scale = float(a[i + 1])
        for k in SUITES:
            SUITES[k] = (SUITES[k][0], int(SUITES[k][1] * scale))
        a = a[:i] + a[i + 2:]
    pos = [x for x in a if not x.startswith("--") and x != jpath]
    # multiple suites allowed: `bbox indox test doc_base pipeline` (was silently running only the first)
    keys = ORDER if (not pos or "all" in pos) else pos
    for k in keys:
        if k not in SUITES:
            sys.exit(f"unknown suite: {k}  (all|{'|'.join(ORDER)})")

    global LANES_ON
    if "--lanes" in a:
        LANES_ON = True
        a.remove("--lanes")

    if "--cold-ocr" in a:
        # honest speed measurement: wipe apitools' OCR cache so Tesseract REALLY runs
        # (clean-machine parity; the AI-extraction cache stays per ruling U3)
        r = subprocess.run(["docker", "exec", "apitools", "sh", "-c",
                            "rm -f /app/.storage/ocr_cache/*.json && echo cleared"],
                           capture_output=True)
        print(f"[indox-test] COLD-OCR: apitools ocr_cache wiped "
              f"({r.stdout.decode().strip() or r.stderr.decode().strip()[:80]})", flush=True)

    # ── CRASH-SAFETY: the battery is bracketed by a fixture sweep ────────────────────────
    # Every suite cleans up on its HAPPY PATH, inside n8n, in a node the execution only reaches
    # if it got that far. `indoxV2 DOC BASE E2E Test` crashed at 17:21 on 2026-08-06 and its
    # 32 fixture rows were still in the client's live table hours later — measured, not assumed.
    #
    # So the sweep runs from OUT HERE, where the thing that crashed cannot take it down with it:
    #   * `finally` (below) — covers a suite that failed, timed out, stalled, raised, or was
    #     Ctrl-C'd. This is the case the in-workflow cleanups cannot cover, because the workflow
    #     is what died.
    #   * this pre-sweep — covers the one case `finally` cannot: this PROCESS being SIGKILLed, or
    #     the host losing power. Debris then survives until the next run and no further.
    # Prefixes come from scripts/test-fixture-prefixes.yaml, never restated here, and the sweep
    # is scoped to the suites THIS run drives so it cannot reach another lane's fixtures.
    global RAN_KEYS
    RAN_KEYS = list(keys)
    # BEFORE the sweep and before any lane: a suite that can still reach the live registry must not
    # start. See _registry_scope_gate() — the damage it prevents is not cleanable afterwards.
    _registry_scope_gate()
    _fixture_sweep("pre", RAN_KEYS)
    # The permanent test tenant is reset EVERY run (clear-to-initial + config reseed), and only
    # then re-seeded with this deployment's local connection ids — in that order, because the
    # reset is what wipes the settings the seed writes. Both refuse the battery on failure.
    _reset_test_instance()
    _seed_test_connections()

    t_batt0 = time.time()
    _detect_endpoint()
    ensure_fresh_corpus()      # before ANY suite seeds fixtures from demo-docs
    bootstrap_localmail()
    wait_for_webhooks()
    ck = login()
    if not ck:
        sys.exit("n8n login failed (N8N_OWNER_* in .env; n8n up?)")
    t_start_eid = _max_exec_id()

    if "--parallel" in a:
        # TRUE all-parallel: corpora are content-unique per suite (scripts/gen-unique-corpus.py),
        # so suites can no longer dedup-collide. Wall-clock ≈ max(suite). No wedge fail-fast —
        # each suite has its own budget and stall detector.
        import concurrent.futures
        print(f"[indox-test] PARALLEL mode: {' + '.join(keys)}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as ex:
            futs = [ex.submit(run_suite_lanes if (LANES_ON and k in LANES) else run_suite,
                              ck, k) for k in keys]
            results = [f.result() for f in futs]
        results.sort(key=lambda r: keys.index(r["suite"]))
    else:
        results = []
        for k in keys:
            r = (run_suite_lanes if (LANES_ON and k in LANES) else run_suite)(ck, k)
            results.append(r)
            # [per-suite sweep 2026-08-31] The battery used to sweep ONCE at the end, so every
            # suite ran against the residue of all its predecessors — a semantics standalone runs
            # never have (each CLI run sweeps). Three interference bugs came from that gap in one
            # day, all of the same class: cross-suite rows clustering in the doubles detector
            # (sealed identity collisions ×2, then gdoc's gdx_ord5 hash-twinning pipeline's
            # plx_ord1 — same corpus file, same md5 — into no_action_merge_blocked, batteries
            # 2/4/5, always exactly 1/17). Sweeping each suite's own registered prefixes right
            # after it reports makes battery semantics IDENTICAL to standalone semantics, and
            # turns the seed-uniqueness measures into belt-and-braces instead of load-bearing.
            _fixture_sweep("post-" + k, [k])
            # A TIMEOUT IS NOT A WEDGE. `stalled` means the stall detector proved no new execution
            # appeared for 120s — the broker really has stopped dispatching, and running on is
            # pointless. `timeout` only means one suite outran its budget, which under contention
            # (a busy driver poll, a cold OCR cache) says nothing about the next suite.
            #
            # Conflating them cost us real data: battery 6, doc_base hit 366s of a 360s budget
            # while the live poll held 130+ concurrent extractions, and the run skipped bs, gdoc
            # AND pipeline — including the only measurement of that push's gdoc extractor fixes.
            # One starved suite became three unmeasured ones and a 1/7 that meant less than it
            # looked like. So: skip the rest ONLY on a proven stall; on a timeout, say so and
            # keep going — a red we measured beats a blank we assumed.
            if r["status"] == "stalled":
                print(f"[indox-test] ENVIRONMENT WEDGED ({k}: stalled — no new executions for "
                      f"120s) — skipping remaining suites, they would hit the same wall.",
                      flush=True)
                for rest in keys[keys.index(k) + 1:]:
                    results.append({"suite": rest, "status": "skipped-env-wedged", "eid": None,
                                    "elapsed": 0, "summary": None})
                break
            if r["status"] == "timeout":
                print(f"[indox-test] {k}: TIMED OUT at its {SUITES[k][1]}s budget — continuing; "
                      f"a budget overrun under load is not evidence about the next suite.",
                      flush=True)

    # concurrency report over the battery window — profiling-effectiveness review
    try:
        hrs = max(0.2, round((time.time() - t_batt0) / 3600 + 0.02, 2))
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ci-concurrency-report"),
                        env("DEPLOYMENT_NAME", "shlomo-laptop"), "ci-artifacts", str(hrs)], timeout=300)
    except Exception as ex:
        print(f"[indox-test] concurrency report skipped: {ex}")

    # ── THE THIN-SYNC PROOF (owner order 2026-08-31) ────────────────────────────────────
    # "There must be no more runs of indoxProcessDocument01 at all." The v1 processor path is
    # retired; syncs deliver THIN rows and the state machine completes them. A battery is only
    # green if the retired workflows produced ZERO executions across its whole window — a
    # positive proof of the migration, not an absence of a test.
    legacy = _legacy_runs_since(t_start_eid)
    if legacy:
        detail = ", ".join(f"{w}×{n}" for w, n in legacy)
        print(f"[indox-test] ❌ LEGACY PROCESSOR RAN: {detail} — the thin-sync migration is "
              f"not holding (owner order: zero indoxProcessDocument01/proc-path runs).",
              flush=True)
        results.append({"suite": "thin_only", "status": "error", "eid": None, "elapsed": 0,
                        "summary": {"RESULT": "❌ LEGACY PROCESSOR RAN", "passed": "0/1",
                                    "checks": [f"❌ retired workflow executed: {detail}"]}})
    else:
        results.append({"suite": "thin_only", "status": "success", "eid": None, "elapsed": 0,
                        "summary": {"RESULT": "✅ ALL TESTS PASS", "passed": "1/1",
                                    "checks": ["✅ zero executions of the retired v1 processor "
                                               "path across the battery window"]}})

    print("\n════════ INDOX E2E SCORECARD ════════")
    red = False
    for r in results:
        s = r["summary"] or {}
        ok = r["status"] == "success" and str(s.get("RESULT", "")).startswith("✅")
        red = red or not ok
        print(f"{'✅' if ok else '❌'} {r['suite']:<9} {s.get('RESULT','(no summary)'):<22} "
              f"{s.get('passed','')}  exec={r['eid']} {r['elapsed']}s")
        # a suite that never STARTED (missing workflow / rejected /run) has no summary and no
        # checks, so the scorecard used to render it as a bare `exec=None 0s` — indistinguishable
        # from a product failure and unactionable. The trigger response is the only evidence there
        # is; print it.
        if r.get("detail"):
            print(f"     ❌ {r['status']}: {r['detail']}")
        for c in s.get("checks", []):
            print(f"     {c}")
    if jpath:
        junit(results, jpath)
    sys.exit(1 if red else 0)


def _require_test_instance():
    """Refuse to start unless the permanent `test` tenant exists and is enabled.

    This replaces _refuse_unguarded_production_run() and its INDOX_TEST_ON_PRODUCTION=i-know
    escape hatch. The hatch existed because there WAS no separate test instance — the only
    boundary between a test run and a client's documents was a deliberate keystroke. Now every
    suite run is pinned to instance `test` (schema indox_test, registered in
    public.indox_instances with purpose='test'), so "run against production" is no longer a
    mode this CLI has, and an override that means "yes, use production" has nothing legitimate
    left to authorize. It is deleted, not renamed.

    What remains to check is that the tenant is actually there: production workflows THROW on a
    missing __instance, so without the registration every suite would die one by one inside n8n
    — eight cryptic reds instead of one sentence with the fix in it. A registry that cannot be
    read is the same refusal (cannot verify == must not run), not a pass.
    """
    try:
        ok = _supabase_sql(
            "select 1 from public.indox_instances where id='test' and enabled;")
    except Exception as ex:
        sys.exit("[indox-test] REFUSING TO RUN: cannot verify the test tenant in "
                 f"public.indox_instances ({ex}) — is the stack up?")
    if ok != "1":
        sys.exit(
            "[indox-test] REFUSING TO RUN: no enabled 'test' instance in public.indox_instances.\n"
            "  The E2E suites run exclusively against the permanent test tenant (schema\n"
            "  indox_test); without it every pinned __instance='test' run throws inside n8n.\n"
            "  Provision it (apps/indox/hooks/apply-schema test) and re-run."
        )
    print("[indox-test] test tenant: 'test' registered and enabled in public.indox_instances",
          flush=True)


def main():
    """The battery, bracketed by the post-run fixture sweep.

    `finally` rather than a call after `_run_battery()` — because `_run_battery` ENDS in
    `sys.exit(1 if red else 0)`, so a trailing statement would be unreachable on every single
    run, red or green. It is also unreachable on the two early `sys.exit`s, on any exception a
    suite raises, and on Ctrl-C. `finally` catches all five, which is the whole point: the runs
    that leave fixtures behind are precisely the runs that do not finish normally.

    The exit status is untouched — SystemExit propagates through the `finally` unchanged, so the
    sweep can never turn a red battery green or a green one red."""
    _require_test_instance()
    try:
        return _run_battery()
    finally:
        # RAN_KEYS is set by _run_battery as soon as the suite list is known. If it died before
        # that (bad arguments), it seeded nothing, so sweeping nothing is the correct answer —
        # NOT falling back to a global sweep, which is the bug this scoping exists to fix.
        _fixture_sweep("post", RAN_KEYS)


if __name__ == "__main__":
    main()
