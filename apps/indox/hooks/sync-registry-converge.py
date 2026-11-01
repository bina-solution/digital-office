#!/usr/bin/env python3
"""Converge `settings.sync_registry` toward the tracked fixture. Idempotent.

WHY THIS EXISTS
---------------
`settings.sync_registry` is the ONE source of truth for every sync pipe — which
folders INDOX watches, where it files successes, where it files failures. Until
2026-08-06 it had **no declarative source anywhere in the repo**:

  * `apps/indox/blueprint/fixtures/schema.sql` creates `public.settings` but never
    inserts a `sync_registry` row (the only occurrence of the string in that file
    is a comment).
  * `scripts/_reg.json` looked authoritative but was untracked, stale, and read by
    nothing. It has been retired.

So a fresh `git clone` + `./bbox run` produced a stack with **no sync_registry row
at all**, and every folder id for a deployment existed solely as live DB state on
one machine. Losing that machine lost the configuration. That is the gap this
closes.

THE HARD PART: THE BLOB MIXES CONFIG WITH LIVE RUNTIME STATE
------------------------------------------------------------
A registry entry carries both what an operator configured (`pairs`, `connection`,
`processor_wf`, `enabled`, `batch`) and what the engine wrote back (`last_run`,
`last_run_execution`, `last_run_url`). A naive seed that wrote whole entries would
reset run state on every `bbox run` — and on the production VPS it would overwrite
the client's live registry with whatever the fixture happened to say.

So convergence is a MERGE, and it is deliberately asymmetric:

  config keys   fixture wins   (that is what "declarative" means)
  RUNTIME_KEYS  live wins      (never written, never cleared, never seeded)
  extra entries live wins      (a pipe absent from the fixture is LEFT ALONE)

`RUNTIME_KEYS` is defined HERE and nowhere else. `--emit` regenerates the fixture
through the same constant, so the file this reads and the file it writes cannot
drift apart. Adding a runtime field means editing one line in one file.

WHY IT NEVER DELETES
--------------------
A deployment legitimately carries pipes the fixture does not know about — a pipe
authored through the Console, a per-site pipe, a load-test pipe mid-run. Deleting
"anything not in the fixture" would make `bbox run` destroy an operator's work.
Convergence adds and updates; removal stays a deliberate, human act through the
BFF's DELETE endpoint.

WHY IT WRITES THROUGH THE BFF AND NOT SQL
-----------------------------------------
`_write_sync_registry` runs `_normalise_entry`, which keeps the registry's TWO
folder vocabularies in step (`from`/`to_sync`, `to`/`synced`, `failed_to`/`failed`).
Raw SQL bypasses it, and a second normaliser is exactly how the two spellings drift
apart — the failure that once made "a pipe you configured" and "a pipe you could
see" disjoint sets. One normaliser, one write path.

USAGE
  sync-registry-converge.py --deployment-name <dn> [--dry-run]
  sync-registry-converge.py --deployment-name <dn> --emit   # live -> fixture
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

#: THE REAL REGISTRY LIVES OUT OF TREE, AND THAT IS DELIBERATE.
#:
#: The obvious home for this would be apps/indox/blueprint/fixtures/sync_registry.json.
#: It must not go there. Gate G40 (scripts/refactor/fixture-live-key-lint.py) bars
#: `sync_registry` from every blueprint fixture, after a 2026-08-05 incident in which a
#: fixture's registry row was upserted over a REAL client's live registry twice — deleting
#: two configured drive pipes and blanking `connection` on two more. And a tracked file of
#: real folder ids is worse than an overwrite risk: it points the NEXT deployment
#: bootstrapped from this repo at THIS client's Drive folders on its very first seed, which
#: is a cross-tenant leak.
#:
#: So the registry is treated exactly like `.env`: tenant-specific operational config,
#: gitignored, backed up alongside the deployment's other secrets. What IS tracked is the
#: tenant-neutral shape, for documentation only — never applied.
FIXTURE = os.environ.get("INDOX_SYNC_REGISTRY_FILE") or os.path.join(
    REPO, "data", "registry", "sync_registry.json")
EXAMPLE = os.path.join(HERE, "..", "blueprint", "fixtures", "sync_registry.example.json")

#: Written by the ENGINE, never by an operator. Live value always wins; `--emit`
#: strips these so they can never enter the tracked fixture. THE one definition.
RUNTIME_KEYS = frozenset({"last_run", "last_run_execution", "last_run_url"})

BFF_BASE = "http://127.0.0.1:8080/incomingDocuments"

#: SOURCE FEEDBACK — the pipe's answer to "what happened to the document you gave me?"
#:
#: The registry has always carried a FOUR-state destination model per pipe
#: (`to_sync` -> `in_progress` -> `synced` | `failed`, as folder ids for drive and as
#: tag_rules KEYs for gmail), but the state machine only ever wrote ONE of them: `failed`,
#: drive only, via `file_to_failed_folder`. `synced` was asserted BLINDLY at delivery time,
#: before any verdict existed — so a document that ended badly left a Drive file sitting in
#: a folder called "synced", which is the opposite of the truth.
#:
#: `feedback` is the switch that makes the other three states reachable, and — critically —
#: that lets a pipe say NO. Two of this deployment's seven pipes physically cannot express a
#: verdict (`drive-whatsapp-bot` has to_sync == synced == failed; `drive-bs` has
#: synced == failed), so for them feedback is pointless Drive traffic, not information.
#: Inferring "has a failed folder => wants feedback" would have had both shuffling files
#: into the folder they are already in, forever.
#:
#: THE DERIVATION LIVES HERE AND NOWHERE ELSE. Consumers (syncV3Main0001 -> the work item ->
#: syncDeliverGmail01 -> SOURCE_LIST[].required_feedback_type) read `feedback.mode` and treat
#: ABSENCE AS OFF. That direction is deliberate: a pipe predating this field, or authored
#: through the Console, does nothing until convergence materialises an explicit block for it,
#: rather than silently starting to move a client's files.
FEEDBACK_MODES = ("drive_move", "mail_tag", "off")

#: LEGACY OWNERSHIP — how a retired folder or a retired pipe name still finds its pipe.
#:
#: A document records where it came from; a registry records where things come from NOW. Those two
#: drift apart every time a pipe is repointed or pruned, and the drift is not small: measured
#: 2026-08-21, 23,940 of 25,795 rows carry a SYNC_NAME that no live entry answers to, because
#: `drive-gdoc-scanned-synced` / `drive-gdoc-scanned-failed` / `mail-private` were real entries once
#: and are not any more. Those documents still exist, their files still sit in Drive, and they still
#: need their verdict reported — so the pipe that owns them has to remain nameable.
#:
#:   legacy_folders     drive folder ids this pipe used to scan or file into. Folded into the same
#:                      folder -> pipe map the live `pairs` build, so a row resolves by WHERE IT
#:                      CAME FROM even when the folder is no longer configured.
#:   legacy_sync_names  pipe names this pipe used to be called. Only consulted when the folder
#:                      lookup fails, because the folder is the stronger key (87% vs 7.2%).
#:
#: A retired pipe that owns no live folders keeps its own entry with `enabled: false` — the scanner
#: skips those everywhere (syncV3Main0001: `if(s.enabled===false){ skipped.disabled++; continue; }`)
#: so it never ingests again, while remaining a resolvable owner for the rows it already produced.
#: `feedback_for` deliberately does NOT consult `enabled`: a retired pipe's documents still need
#: their verdict filed, and that is the entire reason the entry is kept.
LEGACY_KEYS = ("legacy_folders", "legacy_sync_names")


def _feedback_off(why):
    return {"mode": "off", "on_success": False, "on_failure": False, "_derived": why}


def feedback_for(entry):
    """The `feedback` block for one registry entry — explicit if set, else derived.

    An operator's explicit block always wins and is only normalised (unknown mode -> off,
    flags coerced to bool, `_derived` dropped because it is no longer derived). Everything
    else is read off the folder/label vocabulary the entry already declares, so turning
    feedback on for a pipe is a matter of GIVING IT SOMEWHERE TO FILE, not of setting a flag
    in a second place.
    """
    explicit = entry.get("feedback")
    if isinstance(explicit, dict) and explicit.get("mode"):
        mode = str(explicit.get("mode"))
        if mode not in FEEDBACK_MODES:
            return _feedback_off(f"unknown mode {mode!r} — refusing to guess")
        if mode == "off":
            return {"mode": "off", "on_success": False, "on_failure": False}
        return {"mode": mode,
                "on_success": bool(explicit.get("on_success", True)),
                "on_failure": bool(explicit.get("on_failure", True))}

    source = str(entry.get("source") or "").lower()

    if source == "gmail":
        labels = entry.get("labels") or {}
        ok, bad = labels.get("synced"), labels.get("failed")
        if not ok and not bad:
            return _feedback_off("pipe declares no `labels` vocabulary, so it has no way "
                                 "to say what happened — add labels.synced / labels.failed")
        return {"mode": "mail_tag", "on_success": bool(ok), "on_failure": bool(bad)}

    if source == "drive":
        pairs = entry.get("pairs") or []
        if not pairs:
            return _feedback_off("drive pipe declares no `pairs`")
        # TWO independent conditions, and the selftest exists because I got this wrong once:
        #   1. the pair must DISCRIMINATE — `synced` != `failed`. Landing both outcomes in one
        #      folder carries no information, so it is off, not "on but pointless".
        #   2. the direction must MOVE THE FILE — destination != `to_sync`, where the file
        #      already is. A pipe whose `synced` IS its `to_sync` says "success = leave it
        #      alone"; filing that as feedback is a Drive call that changes nothing.
        # Comparing `synced` against `failed` for (2) is the bug: on {to_sync:A, synced:A,
        # failed:C} it reported success feedback for a move from A to A.
        def _on(p, dest):
            return bool(p.get(dest)) and p.get("synced") != p.get("failed") \
                and p.get(dest) != p.get("to_sync")
        on_success = any(_on(p, "synced") for p in pairs)
        on_failure = any(_on(p, "failed") for p in pairs)
        if not on_success and not on_failure:
            return _feedback_off("`synced` and `failed` are the same folder on every pair — "
                                 "this pipe cannot express a verdict")
        return {"mode": "drive_move", "on_success": on_success, "on_failure": on_failure}

    return _feedback_off(f"source {source!r} has no feedback channel")


def with_feedback(entry):
    """Entry + its resolved `feedback` block. Idempotent."""
    out = dict(entry)
    out["feedback"] = feedback_for(entry)
    return out


def sh(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def psql(dn, sql):
    r = sh(["docker", "exec", "-i", f"supabase-db-{dn}", "psql", "-U", "postgres",
            "-d", "postgres", "-tAc", sql])
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr[:400]}")
    return r.stdout.strip()


#: `public.settings` is keyed (instance, key) — one registry row PER INSTANCE. An
#: unscoped read returns N rows on a multi-instance stack and `json.loads` then fails
#: on the concatenation, or worse succeeds on the first. Matches the column's DDL
#: default in blueprint/fixtures/schema.sql and the BFF's own `_instance()` fallback.
DEFAULT_INSTANCE = "incoming-documents-main"


#: [cutover 2026-08-31] the tenant SCHEMA (indox_<id>), resolved once per run. Explicit
#: --instance / INDOX_INSTANCE wins; else the sole enabled production tenant (purpose <> 'test')
#: — the registry carries purpose exactly so tools can skip the standing test tenant when
#: defaulting, and TWO production tenants is genuinely ambiguous, so it refuses.
_TENANT_SCHEMA = None


def resolve_tenant(dn, want=None):
    global _TENANT_SCHEMA
    if _TENANT_SCHEMA:
        return _TENANT_SCHEMA
    want = want or os.environ.get("INDOX_INSTANCE")
    rows = [r.split("|") for r in psql(
        dn, "select id, schema_name, coalesce(purpose,'') from public.indox_instances "
            "where enabled order by id").splitlines() if r.strip()]
    if want:
        hit = [r for r in rows if r[0] == want]
        if not hit:
            raise SystemExit(f"converge: instance '{want}' is not enabled/registered "
                             f"(have: {' '.join(r[0] for r in rows)})")
        print(f"converge: acting on instance '{want}'", file=sys.stderr)
        _TENANT_SCHEMA = hit[0][1]
        return _TENANT_SCHEMA
    prod = [r for r in rows if (r[2] if len(r) > 2 else '') != 'test']
    if len(prod) != 1:
        raise SystemExit(f"converge: {len(prod)} enabled production tenants "
                         f"({' '.join(r[0] for r in prod)}) — name one with --instance/INDOX_INSTANCE")
    print(f"converge: no instance named — defaulting to the sole production tenant "
          f"'{prod[0][0]}'", file=sys.stderr)
    _TENANT_SCHEMA = prod[0][1]
    return _TENANT_SCHEMA


def read_live(dn, instance=DEFAULT_INSTANCE):
    sch = resolve_tenant(dn)
    raw = psql(dn, f"select value from \"{sch}\".settings where key='sync_registry' "
                   f"and instance='{instance}'")
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except ValueError:
        return []
    return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []


def bff(dn, method, path, body=None):
    """Call the INDOX BFF from inside its own container.

    A read timeout is NOT a failed write. `_write_sync_registry` commits before the
    response is enriched, and the enrichment re-lists every pipe's Drive folders —
    which on a real deployment routinely exceeds any sane HTTP timeout. Verified
    live 2026-08-06: a PATCH that "timed out" had already landed. So every caller
    re-reads the DB and treats that, not the response, as the truth.
    """
    code = (
        "import json,urllib.request,urllib.error\n"
        f"body={body!r}\n"
        f"data=json.dumps(body).encode() if body is not None else None\n"
        f"req=urllib.request.Request({BFF_BASE + path!r},data=data,method={method!r},"
        "headers={'Content-Type':'application/json'})\n"
        "try:\n"
        "    r=urllib.request.urlopen(req,timeout=900)\n"
        "    print(json.dumps({'http':r.status,'body':json.loads(r.read())}))\n"
        "except urllib.error.HTTPError as e:\n"
        "    print(json.dumps({'http':e.code,'err':e.read()[:400].decode('utf-8','replace')}))\n"
        "except TimeoutError:\n"
        "    print(json.dumps({'http':599,'err':'read timeout after the write'}))\n"
    )
    r = sh(["docker", "exec", f"incoming-documents-{dn}", "python3", "-c", code], timeout=960)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"http": 0, "err": (r.stderr or r.stdout)[:400]}


def config_only(entry):
    return {k: v for k, v in entry.items() if k not in RUNTIME_KEYS}


def merge(live, seed):
    """Seed config over the live entry, runtime keys preserved from live."""
    merged = dict(live)
    merged.update(config_only(seed))
    for k in RUNTIME_KEYS:
        if k in live:
            merged[k] = live[k]
        else:
            merged.pop(k, None)
    return merged


def emit(dn):
    live = read_live(dn)
    fixture = [with_feedback(config_only(e))
               for e in sorted(live, key=lambda e: str(e.get("name") or ""))]
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)
        f.write("\n")
    stripped = sorted({k for e in live for k in e if k in RUNTIME_KEYS})
    print(f"[sync-registry] emitted {len(fixture)} config-only entries -> {FIXTURE}")
    print(f"[sync-registry] runtime keys stripped: {stripped or '(none present)'}")
    return 0


def load_fixture(path):
    """Read a registry file, dropping doc-only blocks.

    `__doc__` entries exist so the tracked example can explain itself in the file a
    reader actually opens. They are never pipes and must never reach the registry.

    Every seed is stamped with its resolved `feedback` block (see `feedback_for`). Doing it
    HERE rather than inside `merge()` keeps the merge honest: a live entry that predates the
    field plans exactly ONE update, after which it is a no-op forever, and an entry differing
    only in runtime state stays a no-op — which is what selftest section 2 asserts.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [with_feedback(e) for e in raw
            if isinstance(e, dict) and e.get("name") and "__doc__" not in e]


def converge(dn, dry_run):
    if not os.path.exists(FIXTURE):
        # SILENCE HERE WOULD BE THE BUG. A deployment with no registry file is not
        # converged — say so plainly rather than exiting 0 into a stack whose pipes
        # exist only in its database. Do NOT fall back to the example: seeding
        # PLACEHOLDER folder ids into a live registry is its own incident.
        print(f"[sync-registry] NO REGISTRY FILE at {FIXTURE} — nothing converged.")
        print(f"[sync-registry]   This deployment's pipes exist only as live DB state.")
        print(f"[sync-registry]   Create it from the running stack:")
        print(f"[sync-registry]     python3 {os.path.relpath(__file__, REPO)} "
              f"--deployment-name {dn} --emit")
        print(f"[sync-registry]   Shape reference: {os.path.relpath(EXAMPLE, REPO)}")
        return 0
    seeds = load_fixture(FIXTURE)
    live = read_live(dn)
    by_name = {str(e.get("name") or ""): e for e in live}

    creates, updates, noops = [], [], []
    for seed in seeds:
        name = str(seed.get("name") or "")
        if not name:
            continue
        cur = by_name.get(name)
        if cur is None:
            creates.append(seed)
        elif merge(cur, seed) != cur:
            updates.append((name, merge(cur, seed)))
        else:
            noops.append(name)

    extra = [n for n in by_name if n not in {str(s.get("name") or "") for s in seeds}]
    print(f"[sync-registry] fixture={len(seeds)} live={len(live)} | "
          f"create={len(creates)} update={len(updates)} unchanged={len(noops)} "
          f"| left alone (not in fixture): {extra or '(none)'}")

    if dry_run:
        for s in creates:
            print(f"[sync-registry] DRY-RUN would CREATE {s.get('name')}")
        for name, m in updates:
            diff = sorted(k for k in set(m) | set(by_name[name])
                          if m.get(k) != by_name[name].get(k))
            print(f"[sync-registry] DRY-RUN would UPDATE {name}: {diff}")
            leaked = [k for k in diff if k in RUNTIME_KEYS]
            if leaked:
                print(f"[sync-registry] ERROR: runtime keys in diff: {leaked}")
                return 1
        return 0

    rc = 0
    for s in creates:
        res = bff(dn, "POST", "/sync/registry", s)
        print(f"[sync-registry] create {s.get('name')} -> http {res.get('http')}"
              f"{' ' + str(res.get('err'))[:160] if res.get('err') else ''}")
    for name, m in updates:
        res = bff(dn, "PATCH", f"/sync/registry/{name}", config_only(m))
        print(f"[sync-registry] update {name} -> http {res.get('http')}"
              f"{' ' + str(res.get('err'))[:160] if res.get('err') else ''}")

    # VERIFY FROM THE DB, never from the write responses (see bff() docstring).
    after = {str(e.get("name") or ""): e for e in read_live(dn)}
    for seed in seeds:
        name = str(seed.get("name") or "")
        got = after.get(name)
        if got is None:
            print(f"[sync-registry] FAIL {name}: absent after converge")
            rc = 1
            continue
        for k, v in config_only(seed).items():
            if got.get(k) != v:
                print(f"[sync-registry] FAIL {name}: {k} is {got.get(k)!r}, fixture says {v!r}")
                rc = 1
        before = by_name.get(name)
        if before:
            for k in RUNTIME_KEYS:
                if before.get(k) != got.get(k):
                    print(f"[sync-registry] FAIL {name}: runtime key {k} changed "
                          f"{before.get(k)!r} -> {got.get(k)!r}")
                    rc = 1
    for n in extra:
        if n not in after:
            print(f"[sync-registry] FAIL: pre-existing pipe {n} disappeared")
            rc = 1
    print(f"[sync-registry] converge {'OK' if rc == 0 else 'FAILED'} — "
          f"{len(after)} entries, runtime state preserved")
    return rc


def plan(live, seeds):
    """Pure planning step — no DB, no HTTP. What converge() would do."""
    by_name = {str(e.get("name") or ""): e for e in live}
    creates, updates, noops = [], [], []
    for seed in seeds:
        name = str(seed.get("name") or "")
        cur = by_name.get(name)
        if cur is None:
            creates.append(name)
        elif merge(cur, seed) != cur:
            updates.append(name)
        else:
            noops.append(name)
    extra = [n for n in by_name if n not in {str(s.get("name") or "") for s in seeds}]
    return creates, updates, noops, extra


def selftest():
    """Prove the convergence contract with NO stack and NO database.

    `./bbox run` cannot be run from this lane, and re-running it to observe the
    fresh-clone path would rebuild a live production stack. The properties that
    matter are properties of the MERGE and the PLAN, so they are provable here —
    against synthetic registry states — which also makes them regression-tested
    rather than verified once by hand.
    """
    seeds = load_fixture(FIXTURE)
    fails = []

    def check(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    print("[selftest] 1. fresh clone: empty registry -> every fixture pipe is created")
    creates, updates, noops, extra = plan([], seeds)
    check(len(creates) == len(seeds) and not updates and not extra,
          f"empty registry plans {len(creates)} creates, 0 updates, 0 strays")
    for want in ("drive-gdoc-scanned", "drive-gdoc-chat-export"):
        e = next((s for s in seeds if s.get("name") == want), None)
        pairs = (e or {}).get("pairs") or [{}]
        both = all(pairs[0].get(k) for k in ("to_sync", "synced", "failed",
                                             "from", "to", "failed_to"))
        check(e is not None and both,
              f"{want} carries both folder vocabularies, all three states populated")

    print("[selftest] 2. runtime state is never seeded and never clobbered")
    live = [dict(seeds[0], last_run="2026-08-06T00:00:00Z",
                 last_run_execution="113201", last_run_url="http://n8n/x")]
    merged = merge(live[0], seeds[0])
    check(merged.get("last_run_execution") == "113201" and
          merged.get("last_run_url") == "http://n8n/x",
          "merge preserves last_run/last_run_execution/last_run_url from live")
    check(not any(k in s for s in seeds for k in RUNTIME_KEYS),
          "fixture contains no runtime keys at all")
    _, updates, noops, _ = plan(live, [seeds[0]])
    check(not updates and noops, "an entry differing ONLY in runtime state is a no-op")

    print("[selftest] 3. config drift is corrected")
    drifted = [dict(seeds[0], enabled=(not seeds[0].get("enabled")))]
    _, updates, _, _ = plan(drifted, [seeds[0]])
    check(updates == [seeds[0]["name"]], "a flipped `enabled` plans exactly one update")

    print("[selftest] 4. pipes absent from the fixture are never touched")
    _, _, _, extra = plan(list(seeds) + [{"name": "operator-authored-pipe"}], seeds)
    check(extra == ["operator-authored-pipe"], "an unknown pipe is reported and left alone")

    print("[selftest] 5. idempotency: converged state plans nothing")
    creates, updates, noops, extra = plan(seeds, seeds)
    check(not creates and not updates and len(noops) == len(seeds),
          "re-running against the converged state is a full no-op")

    # The create endpoint validates require_complete=True: it needs a non-empty
    # `connection`, and since the proc retirement (2026-08-31) a v3 entry naming a
    # `processor_wf` is REFUSED — every sync is thin, absence is the contract. An entry
    # that fails that cannot be reproduced on a fresh stack — report it here rather than
    # discovering it on the one machine where it matters.
    print("[selftest] 6. fresh-clone creatability (BFF create-endpoint completeness)")
    for s in seeds:
        ok = bool(str(s.get("connection") or "").strip()) and (
            s.get("engine") != "v3" or not str(s.get("processor_wf") or "").strip())
        note = "" if ok else "  <-- would be REJECTED by POST /sync/registry on a fresh stack"
        print(f"     {'ok  ' if ok else 'WARN'} {s.get('name')}{note}")
        if not ok and s.get("name") in ("drive-gdoc-scanned", "drive-gdoc-chat-export"):
            fails.append(f"production pipe {s.get('name')} is not creatable")

    print("[selftest] 7. source feedback is derived from the vocabulary, and can say NO")
    cases = [
        ({"name": "d-ok", "source": "drive",
          "pairs": [{"to_sync": "A", "synced": "B", "failed": "C"}]},
         "drive_move", True, True, "distinct synced/failed -> both directions"),
        ({"name": "d-same", "source": "drive",
          "pairs": [{"to_sync": "A", "synced": "A", "failed": "A"}]},
         "off", False, False, "synced == failed -> OFF (drive-whatsapp-bot's shape)"),
        ({"name": "d-bs", "source": "drive",
          "pairs": [{"to_sync": "A", "synced": "B", "failed": "B"}]},
         "off", False, False, "outcome folders identical -> OFF (drive-bs's shape)"),
        ({"name": "d-failonly", "source": "drive",
          "pairs": [{"to_sync": "A", "synced": "A", "failed": "C"}]},
         "drive_move", False, True, "only `failed` discriminates -> failure feedback only"),
        ({"name": "g-ok", "source": "gmail",
          "labels": {"synced": "SYNCED_DOC", "failed": "FAILED_DOC"}},
         "mail_tag", True, True, "labels.synced + labels.failed -> both (gmail-doc's shape)"),
        ({"name": "g-none", "source": "gmail"},
         "off", False, False, "no labels vocabulary -> OFF (mail-private's shape)"),
        ({"name": "x", "source": "whatsapp"},
         "off", False, False, "unknown source -> OFF"),
    ]
    for entry, mode, ok_s, ok_f, why in cases:
        f = feedback_for(entry)
        check(f["mode"] == mode and f["on_success"] == ok_s and f["on_failure"] == ok_f,
              f"{why} (got {f['mode']}/{f['on_success']}/{f['on_failure']})")
    explicit = feedback_for({"name": "e", "source": "drive", "feedback": {"mode": "off"},
                             "pairs": [{"to_sync": "A", "synced": "B", "failed": "C"}]})
    check(explicit["mode"] == "off" and "_derived" not in explicit,
          "an explicit block beats the derivation and carries no `_derived` note")
    check(feedback_for({"name": "e", "source": "drive", "feedback": {"mode": "teleport"}})
          ["mode"] == "off", "an unknown mode falls back to OFF rather than being guessed")
    once = with_feedback(cases[0][0])
    check(with_feedback(once) == once, "with_feedback is idempotent")
    retired = feedback_for({"name": "r", "source": "gmail", "enabled": False,
                            "labels": {"synced": "SYNCED_DOC", "failed": "FAILED_DOC"}})
    check(retired["mode"] == "mail_tag",
          "a RETIRED pipe (enabled=false) still resolves feedback — its documents still need "
          "their verdict filed, which is why the entry is kept at all")

    print("[selftest] 8. legacy ownership: retired folders and retired names still find their pipe")
    fmap, nmap = {}, {}
    for s in seeds:
        for fid in (s.get("legacy_folders") or []):
            fmap[fid] = s["name"]
        for p in (s.get("pairs") or []):
            for role in ("to_sync", "synced", "failed"):
                if p.get(role):
                    fmap.setdefault(p[role], s["name"])
        for old in (s.get("legacy_sync_names") or []):
            nmap[old] = s["name"]
    check(all(v in {s["name"] for s in seeds} for v in fmap.values()),
          f"every one of the {len(fmap)} mapped folders points at a pipe that exists")
    check(all(v in {s["name"] for s in seeds} for v in nmap.values()),
          f"every one of the {len(nmap)} legacy names points at a pipe that exists")
    # A legacy name must never collide with a LIVE pipe name — that would silently re-own rows.
    live_names = {s["name"] for s in seeds}
    collide = sorted(set(nmap) & live_names)
    check(not collide, f"no legacy name shadows a live pipe name (collisions: {collide or 'none'})")
    for s in seeds:
        if s.get("legacy_folders") or s.get("legacy_sync_names"):
            print(f"     {s['name']:<26} folders={s.get('legacy_folders') or []} "
                  f"names={s.get('legacy_sync_names') or []}")
    check(all(isinstance(s.get("feedback"), dict) for s in seeds),
          f"all {len(seeds)} fixture pipes carry a resolved feedback block")
    for s in seeds:
        fb = s["feedback"]
        print(f"     {s.get('name'):<26} {fb['mode']:<11} "
              f"success={str(fb['on_success']):<5} failure={str(fb['on_failure']):<5}"
              f"{'  # ' + fb['_derived'] if fb.get('_derived') else ''}")

    print(f"[selftest] {'PASSED' if not fails else 'FAILED: ' + '; '.join(fails)}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deployment-name")
    ap.add_argument("--instance", help="tenant id (default: the sole production tenant)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--emit", action="store_true",
                    help="regenerate the fixture FROM the live registry (config only)")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the convergence contract offline (no stack, no DB)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.deployment_name:
        ap.error("--deployment-name is required unless --selftest")
    if a.instance:
        resolve_tenant(a.deployment_name, a.instance)
    return emit(a.deployment_name) if a.emit else converge(a.deployment_name, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
