"""THE single point of logic for "what data does this deployment own".

    Imported by app.py (the HTTP API) and by nothing else. The CLI does NOT import this — it calls
    the API. That is the whole point: one implementation, reachable two ways.

WHY THIS IS A MODULE AND NOT A SCRIPT

    Before this existed the inventory lived in a CLI script, and the frontend would have needed its
    own copy to render a page. Two copies of "what data exists" is exactly how a store goes missing
    from an archive nobody opens until the old machine is gone. So: the logic is here, the API
    exposes it, and both the web UI and `bbox data view` are clients of that API.

WHAT IT READS

    - every app.json under apps/ and platform-base/ (the declared inventory, gate G26 keeps it honest)
    - docker: volumes for THIS compose project, their sizes and users
    - docker: every postgres/redis container in THIS project, their databases and table row estimates
    - scripts/deployment-archive.py: stateful_binds()/SECRET_PATHS, so "what the archive takes" is
      read from the archiver itself rather than guessed at

COVERAGE VERDICTS (the reason anyone runs this)

    covered (hook)          the owning app ships hooks/backup — it dumps itself properly
    covered (generic tar)   no hook, the archiver tars the volume
    covered (bind tar)      a writable bind holding untracked files, tarred by the archiver
    covered (dormant tar)   declared by an app that is installed but DISABLED. The platform keeps a
                            disabled app's data on purpose, so the export carries it too (cmd_export
                            step 2b). Until that step existed these volumes were silently dropped —
                            this verdict was "NOT BACKED UP (app disabled)" and it was correct.
    UNCLAIMED               on the host, no app.json declares it. Would not be in a backup at all.
                            The ONLY remaining way for live data to miss an archive.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess

REPO = pathlib.Path(os.environ.get("DEPLOYMENT_PATH", "/deployment"))


def _load_archiver():
    """Import scripts/deployment-archive.py (hyphenated, so importlib rather than import).

    Imported for its FUNCTIONS, not its CLI; its argparse sits behind __main__ so nothing runs.
    If it is absent we degrade rather than die — an inventory that shows volumes and databases is
    still worth serving even when the bind/secret lists are unavailable.
    """
    p = REPO / "scripts" / "deployment-archive.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("deployment_archive", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                     # noqa: BLE001
        return None


ARCHIVER = _load_archiver()


def _docker(args, timeout=90):
    r = subprocess.run(["docker"] + args, capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace").strip(), r.returncode


def project_name() -> str:
    if ARCHIVER and hasattr(ARCHIVER, "project_name"):
        try:
            return ARCHIVER.project_name()
        except Exception:                                 # noqa: BLE001
            pass
    return os.environ.get("COMPOSE_PROJECT_NAME", "deployment-hacohen")


def deployment_name() -> str:
    return os.environ.get("DEPLOYMENT_NAME", "?")


# ── app manifests ───────────────────────────────────────────────────────────────────────────────

def all_apps():
    """EVERY app on disk with its enabled flag, declared volumes and hook presence.

    Deliberately every app, not just enabled ones: a disabled app's volumes still hold data, and
    reporting them as UNCLAIMED (they are declared) or hiding them (they exist) both lose the fact
    that the export will skip them.
    """
    enabled = set()
    if ARCHIVER and hasattr(ARCHIVER, "enabled_apps"):
        try:
            enabled = {aid for _r, aid in ARCHIVER.enabled_apps()}
        except Exception:                                 # noqa: BLE001
            pass

    out = []
    for root in ("apps", "platform-base"):
        base = REPO / root
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            man_p = d / "app.json"
            if not man_p.is_file():
                continue
            try:
                man = json.loads(man_p.read_text(encoding="utf-8"))
            except Exception:                             # noqa: BLE001
                continue
            hooks = d / "hooks"
            out.append({
                "root": root,
                "id": man.get("id", d.name),
                "title": (man.get("title") or {}).get("he") or (man.get("title") or {}).get("en") or d.name,
                "layer": man.get("layer"),
                "kind": man.get("kind"),
                "enabled": (man.get("id", d.name) in enabled) if enabled else None,
                "volumes": ((man.get("data") or {}).get("volumes") or []),
                # The rest of the app's declared ownership. `volumes` alone was never the whole
                # story: apitools keeps 17.8GB in a bind and 730MB of tables, and declared neither.
                "paths": ((man.get("data") or {}).get("paths") or []),
                "sql": ((man.get("data") or {}).get("sql") or []),
                "kv": ((man.get("data") or {}).get("kv") or []),
                "on_uninstall": ((man.get("data") or {}).get("on_uninstall") or "prompt"),
                "backup_hook": any((hooks / f"backup{e}").is_file() for e in ("", ".sh", ".py", ".mjs")),
                "restore_hook": any((hooks / f"restore{e}").is_file() for e in ("", ".sh", ".py", ".mjs")),
            })
    return out


# ── live docker state ───────────────────────────────────────────────────────────────────────────

def project_containers(project):
    out, _ = _docker(["ps", "--format", "{{.Names}}",
                      "--filter", f"label=com.docker.compose.project={project}"])
    return [c for c in out.splitlines() if c]


_SIZE_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12,
               "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}
_SIZE_RE = re.compile(r"^([\d.]+)\s*([A-Za-z]+)$")


def size_to_bytes(s):
    """'89.09MB' -> 89090000. docker reports volume sizes only as formatted strings, so a caller
    that wants to TOTAL them has to parse. Returns None when it cannot, never a wrong number: a
    summary that silently treats an unparsed size as 0 understates exactly the thing it is for."""
    if not s:
        return None
    m = _SIZE_RE.match(s.strip())
    if not m:
        return None
    mult = _SIZE_UNITS.get(m.group(2).upper())
    return int(float(m.group(1)) * mult) if mult else None


def live_volumes(project):
    out, _ = _docker(["volume", "ls", "--format", "{{.Name}}"])
    vols = [v for v in out.splitlines() if v.startswith(project + "_")]
    sizes = {}
    df, rc = _docker(["system", "df", "-v"], timeout=240)
    if rc == 0:
        for line in df.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] in vols:
                sizes[parts[0]] = parts[2]
    rows = []
    for v in sorted(vols):
        u, _ = _docker(["ps", "-a", "--filter", f"volume={v}", "--format", "{{.Names}}"], timeout=40)
        rows.append({"name": v, "short": v[len(project) + 1:], "size": sizes.get(v),
                     "bytes": size_to_bytes(sizes.get(v)),
                     "used_by": [x for x in u.splitlines() if x]})
    return rows


# ── store discovery: by TECHNOLOGY, never by app ────────────────────────────────────────────────
#
# THE COUPLING RULE. data-management is chassis: it must work on a deployment whose apps it has
# never heard of, and installing an app must not require editing it. So the only proper nouns
# allowed in this file are storage technologies it has to speak in order to dump them — postgres,
# redis, docker. Never n8n, authentik, glitchtip, indox.
#
# This list used to be a table of (user, database) logins: supabase_admin/postgres, hacohen/n8n,
# authentik/authentik, glitchtip/glitchtip. Every one of those pairs is an app's private
# credential, and a new app with its own database was simply invisible until someone remembered to
# come back here. Each of them is also recoverable from the container itself — POSTGRES_USER and
# POSTGRES_DB are how the official image was told to initialise — so asking the container is both
# decoupled AND more accurate than a list that can go stale.
PG_IMAGE_HINTS = ("postgres", "pgvector", "timescale")
KV_IMAGE_HINTS = ("redis", "valkey", "keydb")

# The -d is load-bearing: postgres defaults dbname to the username, so a bare `psql -U hacohen`
# fails with "database hacohen does not exist" and that store renders as an error, not an inventory.
PG_FALLBACK_LOGINS = (("postgres", "postgres"),)


def containers_with_images(project):
    """[(name, image)] for this compose project."""
    out, rc = _docker(["ps", "--format", "{{.Names}}\t{{.Image}}",
                       "--filter", f"label=com.docker.compose.project={project}"])
    rows = []
    if rc == 0:
        for line in out.splitlines():
            if "\t" in line:
                n, i = line.split("\t", 1)
                rows.append((n.strip(), i.strip()))
    return rows


def containers_by_tech(project, hints):
    return [n for n, img in containers_with_images(project) if any(h in img.lower() for h in hints)]


def container_env(name, keys, timeout=30):
    """Read env vars from inside a container. The image's own configuration is the most reliable
    statement of how to connect to it."""
    got = {}
    for k in keys:
        o, rc = _docker(["exec", "-i", name, "printenv", k], timeout=timeout)
        if rc == 0 and o.strip():
            got[k] = o.strip()
    return got


def live_databases(project, table_limit=40):
    """Row counts are pg_stat_user_tables.n_live_tup — the planner's estimate, not count(*).

    An exact count across four instances takes minutes and locks nothing useful. The estimate
    answers "is this table empty or does it hold the business", which is the question asked.
    """
    result = []
    for c in containers_by_tech(project, PG_IMAGE_HINTS):
        entry = {"container": c, "user": None, "databases": [], "error": None}
        # The container's own init variables first, then the universal default. An image that
        # merely CONTAINS postgres (postgres-meta, postgrest) has neither and answers no psql, so
        # it drops out here without needing to be named — which is the point: the probe validates
        # the candidate instead of a hand-written exclusion list doing it.
        env = container_env(c, ("POSTGRES_USER", "POSTGRES_DB"))
        logins = []
        if env.get("POSTGRES_USER"):
            logins.append((env["POSTGRES_USER"], env.get("POSTGRES_DB") or env["POSTGRES_USER"]))
        logins.extend(PG_FALLBACK_LOGINS)
        for user, mdb in logins:
            q = ("select datname||'|'||pg_database_size(datname) from pg_database "
                 "where datistemplate=false order by pg_database_size(datname) desc")
            o, rc = _docker(["exec", "-i", c, "psql", "-U", user, "-d", mdb, "-t", "-A", "-c", q], timeout=60)
            if rc != 0 or not o:
                continue
            entry["user"] = user
            for line in o.splitlines():
                if "|" not in line:
                    continue
                dbname, size = line.rsplit("|", 1)
                db = {"name": dbname, "bytes": int(size) if size.isdigit() else None, "tables": []}
                # EVERY table, not a top-N. This list is what attributes tables to apps, and a
                # truncated list would report the tail as unclaimed — inventing a data-loss warning
                # out of a display limit. table_limit now bounds only what the UI shows.
                tq = ("select schemaname||'.'||relname||'|'||n_live_tup||'|'"
                      "||pg_total_relation_size(relid) from pg_stat_user_tables "
                      "order by pg_total_relation_size(relid) desc limit 5000")
                to, trc = _docker(["exec", "-i", c, "psql", "-U", user, "-d", dbname,
                                   "-t", "-A", "-c", tq], timeout=90)
                if trc == 0:
                    for tl in to.splitlines():
                        parts = tl.split("|")
                        if len(parts) < 3:
                            continue
                        nm, rows, nbytes = parts[0], parts[1].strip(), parts[2].strip()
                        db["tables"].append({
                            "name": nm,
                            "schema": nm.split(".", 1)[0] if "." in nm else None,
                            "table": nm.split(".", 1)[1] if "." in nm else nm,
                            "rows": int(rows) if rows.lstrip("-").isdigit() else None,
                            "bytes": int(nbytes) if nbytes.isdigit() else None})
                entry["databases"].append(db)
            break
        if entry["user"] is None:
            # Not an error worth surfacing when the image merely embeds postgres client libraries
            # (postgres-meta, postgrest): those answer no psql and own no data. A container that
            # advertised POSTGRES_USER and still refused IS worth reporting.
            if not env.get("POSTGRES_USER"):
                continue
            entry["error"] = ("no psql login worked (tried %s)"
                              % ", ".join(u for u, _ in logins))
        result.append(entry)
    return result


def live_redis(project):
    result = []
    pw = ""
    if ARCHIVER and hasattr(ARCHIVER, "read_env"):
        try:
            pw = ARCHIVER.read_env("REDIS_PASSWORD", "")
        except Exception:                                 # noqa: BLE001
            pw = ""
    for c in containers_by_tech(project, KV_IMAGE_HINTS):
        # Per-container password first (its own env), then the deployment-wide one. Matching on
        # container NAME here meant an instance not called *redis*/*valkey* was skipped entirely.
        cpw = container_env(c, ("REDIS_PASSWORD",)).get("REDIS_PASSWORD") or pw
        base = ["exec", "-i", c, "redis-cli"]
        if cpw:
            base += ["-a", cpw, "--no-auth-warning"]
        o, rc = _docker(base + ["dbsize"], timeout=40)
        info, _ = _docker(base + ["info", "keyspace"], timeout=40)
        result.append({"container": c, "keys": o.strip() if rc == 0 else None,
                       "keyspace": [l for l in info.splitlines() if l.startswith("db")],
                       "error": None if rc == 0 else "redis-cli failed (auth?)"})
    return result


def stateful_binds():
    if not (ARCHIVER and hasattr(ARCHIVER, "stateful_binds")):
        return [], "archiver unavailable — bind inventory not read"
    try:
        cfg = ARCHIVER.compose_config()
        return ([{"path": k, "bytes": v, "coverage": "covered (bind tar)"}
                 for k, v in sorted(ARCHIVER.stateful_binds(cfg).items())], None)
    except Exception as e:                                # noqa: BLE001
        return [], f"could not read compose config: {e}"


def secret_paths():
    rows = []
    for rel in (getattr(ARCHIVER, "SECRET_PATHS", []) if ARCHIVER else []):
        p = REPO / rel
        exists = p.exists()
        size = None
        if exists:
            try:
                size = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                        if p.is_dir() else p.stat().st_size)
            except Exception:                             # noqa: BLE001
                size = None
        # cmd_export copies every SECRET_PATH that exists (deployment-archive.py:608) — directories
        # tarred through a container because acme.json is root-owned 0600. So presence alone decides
        # coverage here. "absent" is a statement of fact, not a warning: a deployment that never
        # enabled portainer has no portainer_password.txt to lose.
        rows.append({"path": rel, "exists": exists, "bytes": size,
                     "coverage": "covered (secrets)" if exists else "absent"})
    return rows


# ── the join ────────────────────────────────────────────────────────────────────────────────────

# Cheap first, expensive last — the order the UI reveals them in. Measured on shlomo-laptop
# 2026-08-12: apps 1.6s, volumes 9.6s, databases 8.3s, redis 1.1s, secrets 0.2s, binds 91.6s.
# Binds dominate by an order of magnitude (compose config + walking a 16.5GB tree over /mnt/c),
# so a view that waits for everything shows a blank page for ~110s. Hence the generator.
SECTION_ORDER = ["apps", "volumes", "databases", "redis", "secrets", "binds", "attribution"]


# ── attribution: every store on this host, under the app that owns it ───────────────────────────
#
# THE MODEL, and why it is this one. Three prior arts, one conclusion:
#
#   Windows VSS      each application registers a writer whose metadata document declares its
#                    components. The backup engine enumerates writers; it does not guess.
#   Android Backup   auto-includes app data BY DEFAULT, and the manifest's extraction rules only
#                    refine it. Safe default, declaration for precision.
#   Cloudron         the PLATFORM imposes the layout (one data dir + one database per app), which is
#                    what makes a per-app tarball restorable into a different server at all.
#
# Declaration alone loses whatever an app forgets to mention. Discovery alone can back everything up
# but can never restore ONE app, because nothing says which bytes are whose. So both, with the
# disagreement made loud: every store found on the host must be claimed by exactly one app, and
# what nothing claims is reported as unclaimed rather than quietly swept into a host-wide tar.
#
# Discovery is also allowed to attribute by LOCATION (a bind under apps/<id>/ belongs to <id>) —
# marked provenance "discovered" so it is visibly weaker evidence than a declaration.

def _match_table(patterns, table):
    """Exact name, or a trailing-* prefix. Deliberately not a regex: `chat_*` should be readable by
    whoever writes the manifest, and a manifest that can express `^(?!x)` is a manifest nobody can
    review."""
    for p in patterns or ():
        if p.endswith("*"):
            if table.startswith(p[:-1]):
                return True
        elif p == table:
            return True
    return False


PLATFORM_OWNER = {"id": "_platform", "title": "פלטפורמה (מפתחות וקונפיגורציה)", "layer": 0}


def attribute(o):
    """Group every discovered store under its owning app. Returns (by_app, unclaimed)."""
    apps = o["apps"]
    by_id = {a["id"]: a for a in apps}
    stores = {a["id"]: [] for a in apps}
    stores[PLATFORM_OWNER["id"]] = []
    unclaimed = []

    def add(aid, store):
        stores.setdefault(aid, []).append(store)

    # 1. volumes — declared in data.volumes, the one channel that already existed.
    for v in o["volumes"]:
        owners = v.get("declared_by") or []
        if owners:
            add(owners[0], {"kind": "volume", "name": v["short"], "bytes": v.get("bytes"),
                            "size": v.get("size"), "coverage": v["coverage"],
                            "provenance": "declared",
                            "shared_with": owners[1:]})
        else:
            unclaimed.append({"kind": "volume", "name": v["short"], "bytes": v.get("bytes"),
                              "size": v.get("size"),
                              "why": "no app.json declares this volume in data.volumes"})

    # 2. binds — data.paths is authoritative; otherwise attribute by where the path lives.
    for b in o["binds"]:
        path = b["path"]
        owner, prov = None, None
        for a in apps:
            if path in (a.get("paths") or []):
                owner, prov = a["id"], "declared"
                break
        if not owner:
            for root in ("apps/", "platform-base/"):
                if path.startswith(root):
                    cand = path[len(root):].split("/", 1)[0]
                    if cand in by_id:
                        owner, prov = cand, "discovered"
                    break
        if owner:
            add(owner, {"kind": "path", "name": path, "bytes": b.get("bytes"),
                        "coverage": b.get("coverage"), "provenance": prov})
        else:
            unclaimed.append({"kind": "path", "name": path, "bytes": b.get("bytes"),
                              "why": "not declared in any app's data.paths and not under an app directory"})

    # 3. sql — the shared `public` schema is the whole reason this exists. Without data.sql the
    #    tables of indox, apitools, drive and chat are one commons that can only move as a lump.
    for inst in o["databases"]:
        for db in inst.get("databases") or []:
            for t in db.get("tables") or []:
                schema, table = t.get("schema"), t.get("table")
                owner, prov = None, None
                for a in apps:
                    for decl in (a.get("sql") or []):
                        if decl.get("database") not in (None, db["name"]):
                            continue
                        # `postgres` is a database in EVERY instance, so the instance prefix is what
                        # keeps indox's claim on supabase-db's `postgres` from also claiming the
                        # (empty) maintenance database inside n8n-postgres and authentik-postgres.
                        inst_pat = decl.get("instance")
                        if inst_pat and not inst["container"].startswith(inst_pat):
                            continue
                        if schema and schema in (decl.get("schemas") or []):
                            owner, prov = a["id"], "declared"
                            break
                        if _match_table(decl.get("tables"), table):
                            owner, prov = a["id"], "declared"
                            break
                        # Neither schemas nor tables = the WHOLE database. This is the correct
                        # declaration for an app with its own postgres instance; enumerating
                        # glitchtip's 614 tables by hand would be a list that rots on first upgrade.
                        if not decl.get("schemas") and not decl.get("tables"):
                            owner, prov = a["id"], "declared"
                            break
                    if owner:
                        break
                rec = {"kind": "sql", "name": f"{db['name']}.{t['name']}", "bytes": t.get("bytes"),
                       "rows": t.get("rows"), "container": inst["container"],
                       "coverage": "covered (sql dump)", "provenance": prov}
                if owner:
                    add(owner, rec)
                else:
                    rec["why"] = ("no app declares this table in data.sql — it is dumped with the "
                                  "shared database but cannot be exported or restored per app")
                    rec.pop("provenance", None)
                    unclaimed.append(rec)

    # 4. redis logical databases.
    for r in o["redis"]:
        for ks in (r.get("keyspace") or []):
            name = ks.split(":", 1)[0]
            keys = None
            for part in ks.split(","):
                if part.strip().startswith("keys="):
                    keys = part.split("=", 1)[1]
            idx = name[2:] if name.startswith("db") and name[2:].isdigit() else None
            owner = None
            for a in apps:
                for decl in (a.get("kv") or []):
                    if idx is not None and str(decl.get("db")) == idx:
                        owner = a["id"]
                        break
                if owner:
                    break
            rec = {"kind": "kv", "name": f"{r['container']}/{name}", "keys": keys, "bytes": None,
                   "coverage": "covered (volume tar)", "provenance": "declared" if owner else None}
            if owner:
                add(owner, rec)
            else:
                rec["why"] = "no app declares this redis database in data.kv"
                unclaimed.append(rec)

    # 5. secrets belong to the platform itself, not to any one app.
    for s in o["secret_paths"]:
        if s.get("exists"):
            add(PLATFORM_OWNER["id"], {"kind": "secret", "name": s["path"], "bytes": s.get("bytes"),
                                       "coverage": s.get("coverage"), "provenance": "platform"})

    rows = []
    for a in apps:
        st = stores.get(a["id"]) or []
        rows.append({**{k: a[k] for k in ("id", "title", "layer", "kind", "enabled",
                                          "backup_hook", "restore_hook", "on_uninstall")},
                     "stores": st,
                     "store_count": len(st),
                     "bytes": sum(s.get("bytes") or 0 for s in st),
                     "declared": sum(1 for s in st if s.get("provenance") == "declared"),
                     "discovered": sum(1 for s in st if s.get("provenance") == "discovered")})
    plat = stores.get(PLATFORM_OWNER["id"]) or []
    if plat:
        rows.append({**PLATFORM_OWNER, "kind": "platform", "enabled": True, "backup_hook": False,
                     "restore_hook": False, "on_uninstall": "keep", "stores": plat,
                     "store_count": len(plat), "bytes": sum(s.get("bytes") or 0 for s in plat),
                     "declared": 0, "discovered": 0})
    rows.sort(key=lambda r: (-r["bytes"], r["id"]))
    return rows, unclaimed


def _summary(o):
    """Summary over WHATEVER is present. Called after every section so a partial view still has
    honest totals — the counts only ever grow as sections land."""
    vols, binds, dbs, apps = o["volumes"], o["binds"], o["databases"], o["apps"]
    at_risk = [v for v in vols if v["coverage"].startswith(("UNCLAIMED", "NOT BACKED UP"))]
    return {
        "volumes": len(vols),
        # Volumes + binds is what an archive actually CONTAINS. Databases are deliberately not added
        # to it: every postgres store lives inside one of these volumes, so summing the two would
        # count the same 7.7GB twice and quote a restore size ~15% larger than the real one.
        "volume_bytes": sum(v.get("bytes") or 0 for v in vols),
        "volume_bytes_unknown": sum(1 for v in vols if v.get("bytes") is None),
        "volumes_at_risk": len(at_risk),
        "at_risk": [{"volume": v["short"], "size": v["size"], "why": v["coverage"],
                     "declared_by": v["declared_by"]} for v in at_risk],
        "binds": len(binds),
        "bind_bytes": sum(b["bytes"] or 0 for b in binds),
        "databases": sum(len(i["databases"]) for i in dbs),
        "db_bytes": sum((d["bytes"] or 0) for i in dbs for d in i["databases"]),
        "secrets": len([s for s in o["secret_paths"] if s.get("exists")]),
        # The headline number of the whole app-centric model: stores that exist on this host and
        # belong to no app. They still travel in a whole-host archive, but they cannot be exported
        # or restored per app — and if one is genuinely orphaned, nothing will notice it is gone.
        "unclaimed": len(o["unclaimed"]),
        "unclaimed_bytes": sum(u.get("bytes") or 0 for u in o["unclaimed"]),
        "apps_with_data": sum(1 for a in o["by_app"] if a["store_count"]),
        "apps_total": len(apps),
        "apps_enabled": sum(1 for a in apps if a["enabled"]),
        "apps_with_hooks": sum(1 for a in apps if a["backup_hook"]),
    }


def inventory_steps(table_limit=40):
    """Yield (section, snapshot) after each section completes, cheapest first.

    inventory() below is this generator drained to the end, so the console's progressive view and
    `bbox data view` run the SAME traversal. A second implementation for "the fast version" is
    exactly how two answers about what is backed up start to disagree.
    """
    o = {
        "deployment": deployment_name(), "project": None,
        "apps": [], "volumes": [], "declared_absent": [], "binds": [], "bind_error": None,
        "databases": [], "redis": [], "secret_paths": [],
        "by_app": [], "unclaimed": [],
        "ready": [], "summary": {},
    }

    def emit(name):
        o["ready"] = o["ready"] + [name]
        o["summary"] = _summary(o)
        return name, o

    o["project"] = project = project_name()

    # apps first: every later verdict needs the declaration map, and it is the cheapest call.
    o["apps"] = apps = all_apps()
    declared, hooks, enabled_of = {}, {}, {}
    for a in apps:
        enabled_of[a["id"]] = a["enabled"]
        hooks[a["id"]] = a["backup_hook"]
        for v in a["volumes"]:
            declared.setdefault(v, []).append(a["id"])
    yield emit("apps")

    vols = live_volumes(project)
    for v in vols:
        owners = declared.get(v["short"], [])
        v["declared_by"] = owners
        if not owners:
            v["coverage"] = "UNCLAIMED"
        elif not any(enabled_of.get(o_) for o_ in owners):
            # Step 2b of cmd_export. Declared by an installed-but-disabled app, so the data is kept
            # by the platform's own promise and the export tars it generically. Before that step
            # existed this read "NOT BACKED UP (app disabled)" and was accurate.
            v["coverage"] = "covered (dormant tar)"
        else:
            owner = next(o_ for o_ in owners if enabled_of.get(o_))
            v["coverage"] = "covered (hook)" if hooks.get(owner) else "covered (generic tar)"
    o["volumes"] = vols
    live_short = {v["short"] for v in vols}
    o["declared_absent"] = [{"volume": d, "declared_by": ow} for d, ow in sorted(declared.items())
                            if d not in live_short]
    yield emit("volumes")

    o["databases"] = live_databases(project, table_limit=table_limit)
    yield emit("databases")

    o["redis"] = live_redis(project)
    yield emit("redis")

    o["secret_paths"] = secret_paths()
    yield emit("secrets")

    o["binds"], o["bind_error"] = stateful_binds()
    yield emit("binds")

    # Pure computation over what the sections above collected — no docker, no psql, milliseconds.
    # It runs last because it needs all of them, not because it is expensive.
    o["by_app"], o["unclaimed"] = attribute(o)
    yield emit("attribution")


def inventory(table_limit=40):
    """The complete view. Identical to the last snapshot the generator yields, by construction."""
    out = None
    for _section, out in inventory_steps(table_limit=table_limit):
        pass
    return out


def archive_inventory(path: str):
    """The same shape, read from an archive manifest — answers 'what is IN this backup' without
    unpacking 50GB."""
    d = pathlib.Path(path).expanduser()
    man = d / "manifest.json"
    if not man.is_file():
        raise FileNotFoundError(f"no manifest.json in {d} — not an archive")
    return json.loads(man.read_text(encoding="utf-8"))
