#!/usr/bin/env python3
"""
indox-demo — consolidated, blueprint-driven INDOX demo injection.

ONE declarative YAML per demo under apps/indox/blueprint/demo/<name>.yml is the single source:
  companies (seeded via indox API), ai_cache (seeded via indox API ai_extraction_cache),
  syncs (per-sync demo docs), settings (e.g. demo_inject_count).

Usage:
  bbox indox demo list                 # list available demo blueprints
  bbox indox demo run <name> --instance <id> [opts]   # push the blueprint's full context into the live system
      --instance <id> REQUIRED: which INDOX instance receives the demo — its data lives in the
                     tenant schema indox_<id> (the public fallback was removed at the 2026-08-31
                     cutover, so every write and read here must name its instance).
      --reset        LIGHT reset first: truncate indox_<id>.incoming_documents + clear doc_step locks.
                     Not the full "INDOX Reset + Setup" — this text used to claim that, but the
                     code has always called light_reset(), so no config was ever reseeded here.
                     For the full clear-to-initial + seed, run `bbox indox reset`.
      --wait         after inject, wait for gmail index + scan, poll until rest, print status
      --no-inject    seed companies + ai_cache only (skip doc placement)

Mechanism (all via the INDOX API layer + the n8n inject workflow):
  1) companies  -> indoxApiRouter01 INLINE_ACTION=TABLE_UPSERT table=companies
  2) ai_cache   -> indoxApiRouter01 INLINE_ACTION=TABLE_UPSERT table=ai_extraction_cache
  3) docs       -> trigger "INDOX Inject Demo Blueprint" (per_sync from the blueprint)
Default first-run settings live in n8n ("INDOX Reset + Setup"); everything demo-specific is in the YAML.
"""
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and
# dies with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")
import sys, os, re, json, glob, time, urllib.request, urllib.error
try:
    import yaml
except ImportError:
    sys.exit("pyyaml required: python -m pip install pyyaml")

# repo root = up THREE from apps/<id>/hooks/. This file used to live in scripts/, where up-two
# was right; the move left it pointing at apps/indox/, so it looked for apps/indox/.env and
# died before running a single test.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# `production/n8n/demo` has not existed since the three-layer refactor, so every `bbox indox demo
# run <name>` failed to find its blueprint. The corpus now lives with the app that owns it.
DEMO_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "demo")
BASE = "http://localhost:5678"

def _dn():
    try:
        for ln in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
            if ln.startswith("DEPLOYMENT_NAME="):
                return ln.split("=",1)[1].strip()
    except Exception:
        pass
    return os.getenv("DEPLOYMENT_NAME","bina-deployment")
DN = _dn()
INJECT_WF = "IndoxInjectDemo01"          # display name: "INDOX Inject Demo Blueprint"
# RESET_WF ("INDOX Reset + Setup") lived here too and was never read — demo's --reset calls the
# local light_reset(). The id now has exactly one definition, in hooks/reset, which is what runs it.
ROUTER_WF = "indoxApiRouter01"
# [v1 retirement 2026-08-25] The demo drives the SAME reconciler production runs. It used to call
# the v1 scanner (SyncScanner00001), which had been INACTIVE with zero retained executions for
# weeks while every real pass went through syncV3Main0001 — so the demo was exercising a lane the
# product no longer had. The v1 lane is deleted; this is its one live caller, repointed.
SCANNER_WF = "syncV3Main0001"


def env(k, d=""):
    for ln in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip()
    return d


def _req(path, method="GET", body=None, ck=None):
    h = {"Content-Type": "application/json"}
    if ck:
        h["Cookie"] = ck
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.getheaders(), resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.headers.items(), e.read().decode()


def login():
    hdrs, _ = _req("/rest/login", "POST", {"emailOrLdapLoginId": env("N8N_OWNER_EMAIL"),
                                            "password": env("N8N_OWNER_PASSWORD")})
    cks = [v.split(";")[0] for k, v in hdrs if k.lower() == "set-cookie"]
    return "; ".join(cks)


def run_wf(ck, wfid, pin_items=None, start_hint=None, timeout=120):
    """Run a workflow by id; optionally pin its trigger with pin_items. Returns final status."""
    _, b = _req("/rest/workflows/" + wfid, ck=ck)
    wf = json.loads(b)["data"]
    nodes = wf["nodes"]
    ewt = next((n for n in nodes if n["type"] == "n8n-nodes-base.executeWorkflowTrigger"), None)
    # executeWorkflowTrigger does NOT cascade the body via REST /run — it only runs when called by
    # another workflow. So START from a manual/schedule trigger (which DOES cascade), and PIN the
    # input on the executeWorkflowTrigger too, so $('When Called') still resolves to the blueprint.
    man = next((n for n in nodes if n["type"] in ("n8n-nodes-base.manualTrigger", "n8n-nodes-base.scheduleTrigger")), None)
    start = man or ewt or nodes[0]
    tn = start["name"]
    if pin_items is not None:
        if wf.get("pinData") is None:
            wf["pinData"] = {}
        # pin ONLY on the executeWorkflowTrigger (for $('When Called') refs). Do NOT pin the manual
        # start trigger — pinning it makes n8n treat it as already-run and skip cascading the body.
        pin_target = ewt["name"] if ewt else tn
        wf["pinData"][pin_target] = [{"json": it} for it in pin_items]
    _, rb = _req("/rest/workflows/" + wfid + "/run", "POST",
                 {"workflowData": wf, "startNodes": [{"name": tn}], "triggerToStartFrom": {"name": tn}}, ck)
    try:
        eid = json.loads(rb)["data"]["executionId"]
    except Exception:
        return "?", rb[:120]
    for _ in range(timeout):
        time.sleep(1)
        _, eb = _req("/rest/executions/" + eid, ck=ck)
        try:
            j = json.loads(eb)["data"]
        except Exception:
            continue
        if j and (j.get("finished") or j.get("status") in ("success", "error", "crashed")):
            return j.get("status"), eid
    return "timeout", eid


def load_blueprint(name):
    p = os.path.join(DEMO_DIR, name + ".yml")
    if not os.path.exists(p):
        sys.exit(f"no blueprint: {p}")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_list():
    print("Available demo blueprints (apps/indox/blueprint/demo/):")
    for p in sorted(glob.glob(os.path.join(DEMO_DIR, "*.yml"))):
        try:
            bp = yaml.safe_load(open(p, encoding="utf-8"))
            print(f"  {bp.get('name', os.path.basename(p)[:-4]):10s}  {bp.get('description', '')}")
        except Exception as e:
            print(f"  {os.path.basename(p)}  (parse error: {e})")


def companies_to_items(bp, instance):
    out = []
    for c in bp.get("companies", []) or ([bp["company"]] if bp.get("company") else []):
        # __instance = the tenant SCHEMA selector (indox_<id>); instance = the in-schema discriminator
        # column. indoxApi01 refuses a per-instance table write without BOTH since the 2026-08-31 cutover.
        it = {"INLINE_ACTION": "TABLE_UPSERT", "table": "companies",
              "instance": "incoming-documents-main", "__instance": instance,
              "שם חברה": c.get("name"), "מזהה 1": str(c.get("id"))}
        if c.get("email"):
            it["מייל 1"] = c["email"]
        out.append(it)
    return out


def load_ai_cache(bp):
    """ai_cache is part of the blueprint: inline `ai_cache:` OR `ai_cache_file:` -> demo/<path> JSON."""
    entries = bp.get("ai_cache") or []
    f = bp.get("ai_cache_file")
    if f:
        path = os.path.join(DEMO_DIR, f)
        if os.path.exists(path):
            entries = json.load(open(path, encoding="utf-8")) or []
    return entries


def cache_to_items(bp):
    out = []
    for e in load_ai_cache(bp):
        out.append({"INLINE_ACTION": "TABLE_UPSERT", "table": "ai_extraction_cache",
                    "cache_key": e["cache_key"], "kind": e.get("kind", "invoice"),
                    "value": e["value"] if isinstance(e["value"], str) else json.dumps(e["value"], ensure_ascii=False)})
    return out


def cmd_run(name, instance, reset=False, wait=False, no_inject=False):
    bp = load_blueprint(name)
    # Company emails come from the blueprint (demo/<name>.yml) — the single source of truth. gmail docs
    # resolve company BY SENDER, so each company that has gmail docs must carry an `email:` in the YAML.
    # The inject workflow (Build Companies / Build gmail-*) seeds it as 'מייל 1' and uses it as the From,
    # and falls back to a deterministic co<id>@demo.indox when a company has none (kept inside the WF).
    ck = login()
    if not ck:
        sys.exit("n8n login failed (check N8N_OWNER_* in .env, n8n up)")
    print(f"[demo:{name}] {bp.get('description', '')}")

    if reset:
        print(f"[demo] light reset (truncate indox_{instance}.incoming_documents + clear doc_step locks)…")
        light_reset(instance)

    # Seed companies + ai_extraction_cache via the API, ONE ITEM PER CALL. A multi-item TABLE_UPSERT
    # batch silently drops rows across the executeWorkflow hops (router -> supabase api), so a setup
    # seed is never batched — correctness over speed. The cache load is then verified explicitly below.
    comp = companies_to_items(bp, instance)
    if comp:
        ok = sum(1 for it in comp if run_wf(ck, ROUTER_WF, pin_items=[it])[0] == "success")
        print(f"[demo] seeded {ok}/{len(comp)} companies via API")

    if load_ai_cache(bp):
        ok, total = seed_cache_db(bp)
        print(f"[demo] seeded {ok}/{total} ai_extraction_cache entries (direct DB)")
        want = sorted({str(e["cache_key"]) for e in load_ai_cache(bp) if e.get("cache_key")})
        got = _cache_keys_in_db()
        missing = [k for k in want if k not in got]
        if missing:
            sys.exit(f"[demo] CACHE LOAD FAILED — {len(missing)}/{len(want)} keys not in ai_extraction_cache: {missing[:5]}")
        print(f"[demo] cache verified: {len(want)}/{len(want)} blueprint keys present in ai_extraction_cache")

    if not no_inject:
        per = (bp.get("settings", {}) or {}).get("demo_inject_count") or bp.get("per_sync") or 5
        inp = dict(bp)
        inp["per_sync"] = per
        inp["blueprint"] = name
        inp["instance"] = instance
        inp["ai_cache"] = load_ai_cache(bp)
        # Write the resolved blueprint to the mounted demo-docs folder so the n8n workflow READS it
        # (Read Blueprint node). REST /run + pinData does only a PARTIAL exec — it won't cascade the
        # body — so we trigger with NO pinData (full cascade) and the WF reads this file.
        active = os.path.join(ROOT, "apps", "indox", "blueprint", "demo-docs", "_active-blueprint.json")
        with open(active, "w", encoding="utf-8") as f:
            json.dump(inp, f, ensure_ascii=False)
        nfiles = sum(len(v or []) for v in (bp.get("syncs") or {}).values())
        print(f"[demo] injecting {nfiles} blueprint files (per_sync={per}) via INDOX Inject Demo Blueprint…")
        st, _ = run_wf(ck, INJECT_WF, timeout=240)   # no pinData -> full cascade; WF reads _active-blueprint.json
        print(f"[demo]   inject: {st}")

    if wait:
        print("[demo] waiting for gmail index + scanning until rest (this can take a few min)…")
        for i in range(1, 13):
            time.sleep(20)
            run_wf(ck, SCANNER_WF, timeout=60)
            ip = sb_count("\"STATUS\"='IN_PROGRESS'", instance)
            done = sb_count("\"STATUS\"='COMPLETED'", instance)
            tot = sb_count("1=1", instance)
            print(f"[demo]   scan {i}: total={tot} completed={done} in_progress={ip}")
            if tot > 0 and ip == 0 and i >= 3:
                break
        print("[demo] final:", sb_status(instance))


def _sb(sql, timeout=30):
    import subprocess
    # force UTF-8 decode: psql emits UTF-8 (Hebrew/binary cache values); without this, text=True
    # decodes with the Windows locale (cp1255) and dies on non-cp1255 bytes.
    return subprocess.run(["docker", "exec", f"supabase-db-{DN}", "psql", "-U", "postgres",
                           "-d", "postgres", "-tAc", sql], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _cache_keys_in_db():
    """Set of cache_keys currently in ai_extraction_cache (to verify a demo cache load)."""
    out = (_sb("select string_agg(cache_key, chr(10)) from ai_extraction_cache").stdout or "").strip()
    return set(out.split("\n")) if out else set()


def seed_cache_db(bp):
    """Seed ai_extraction_cache straight into Postgres (like light_reset does its truncate). The runtime
    AI extractor already writes the cache via a DIRECT postgres node; only the demo seed used the generic
    TABLE_UPSERT API, which silently drops rows. Direct DB is reliable + setup-time, so we use it here.
    Dollar-quoting ($IXQ$) avoids any value escaping; cache_key/value never contain that tag."""
    entries = load_ai_cache(bp)
    ok = 0
    for e in entries:
        key = str(e["cache_key"])
        kind = e.get("kind", "invoice")
        val = e["value"] if isinstance(e["value"], str) else json.dumps(e["value"], ensure_ascii=False)
        sql = ("insert into public.ai_extraction_cache (cache_key,kind,value) values "
               f"($IXQ${key}$IXQ$,$IXQ${kind}$IXQ$,$IXQ${val}$IXQ$) "
               "on conflict (cache_key) do update set value=excluded.value")
        r = _sb(sql)
        if r.returncode == 0 and not (r.stderr or "").strip():
            ok += 1
        else:
            print(f"[demo]   cache seed error for {key[:32]}: {(r.stderr or '').strip()[:120]}")
    return ok, len(entries)


def light_reset(instance):
    import subprocess
    _sb(f"truncate indox_{instance}.incoming_documents;")
    rp = env("REDIS_PASSWORD")
    subprocess.run(["docker", "exec", f"redis-{DN}", "sh", "-lc",
                    f"redis-cli -a '{rp}' --no-auth-warning --scan --pattern 'n8n.process_lock.doc_step.*' "
                    f"| xargs -r redis-cli -a '{rp}' --no-auth-warning del"], capture_output=True, text=True, timeout=30)


def sb_count(where, instance):
    import subprocess
    dn = DN
    try:
        o = subprocess.run(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres", "-d", "postgres",
                            "-tAc", f'select count(*) from indox_{instance}.incoming_documents where {where}'],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        return int((o.stdout or "0").strip() or 0)
    except Exception:
        return -1


def sb_status(instance):
    import subprocess
    dn = DN
    o = subprocess.run(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres", "-d", "postgres",
                        "-tAc", f'select "STATUS",count(*) from indox_{instance}.incoming_documents group by 1 order by 2 desc'],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    return (o.stdout or "").strip().replace("\n", " | ")


def main():
    a = sys.argv[1:]
    if not a or a[0] == "list":
        return cmd_list()
    if a[0] == "run":
        usage = "usage: bbox indox demo run <name> --instance <id> [--reset] [--wait] [--no-inject]"
        if len(a) < 2 or a[1].startswith("--"):
            sys.exit(usage)
        instance = ""
        if "--instance" in a:
            i = a.index("--instance")
            if i + 1 < len(a):
                instance = a[i + 1]
        if not re.match(r"^[a-z][a-z0-9_]*$", instance):
            sys.exit(usage + f"\n--instance is required and must match ^[a-z][a-z0-9_]*$ (got: {instance!r})"
                     " — demo data lives in the tenant schema indox_<id>")
        return cmd_run(a[1], instance, reset="--reset" in a, wait="--wait" in a, no_inject="--no-inject" in a)
    sys.exit(f"unknown: indox demo {a[0]}  (list|run)")


if __name__ == "__main__":
    main()
