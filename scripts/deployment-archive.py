#!/usr/bin/env python3
"""deployment-archive — move a whole deployment to another machine, and prove it arrived.

    bbox export [--mode config|full] [--out DIR] [--quiesce] [--force]
    bbox import [DIR] [--force]
    bbox export --verify DIR          # re-read the live estate and diff it against DIR's manifest

THE PROBLEM THIS EXISTS FOR. `zip -r deployment.zip digital-office/` looks like a backup and is
not one. Every database, every n8n workflow and credential, every document, every auth user and
every sync cursor lives in DOCKER NAMED VOLUMES under /var/lib/docker — outside the folder. Measured
on this host: the repo folder is 7.3 GB and the volumes are another ~6.2 GB, and the 6.2 GB is the
part that cannot be regenerated. A zip restores a deployment that boots perfectly and knows nothing.

WHAT OWNS WHAT (the repo's one-owner rule, applied here)

  what state exists .......... each app's `data.volumes` in its app.json, policed by gate G26.
                               This driver reads that inventory rather than keeping its own list, so
                               adding an app adds it to the backup with no edit here.
  how to snapshot a store .... the app, at <root>/<id>/hooks/backup (and hooks/restore). An app with
                               a live database cannot be backed up by copying its data directory —
                               that is a torn snapshot — so the app that owns the database owns the
                               dump. Apps without those hooks get the generic volume tar below.
  the archive format ......... this file, and only this file. export and import must agree on the
                               manifest byte-for-byte, so they are one program with two verbs rather
                               than two programs with a shared convention that can drift.

HOOK DISCOVERY IS BY FILE EXISTENCE, NOT BY THE EXECUTABLE BIT — deliberately different from
run_app_hooks, which tests `-x`. On a /mnt/c checkout every file reports mode 755 while git may have
recorded 644, and `run_app_hooks` SILENTLY SKIPS a non-executable hook. A silently skipped `prepare`
is a bootstrap that did not run; a silently skipped `backup` is a store that is missing from an
archive nobody will open until the day the old machine is gone. So this driver tests `-f` and names
the interpreter itself, and a hook that fails FAILS THE EXPORT rather than being stepped over.

CONSISTENCY. Each Postgres store is dumped with `pg_dump`, which takes a REPEATABLE READ snapshot,
so a store's dump is internally consistent as of the moment it started even while n8n workers write.
CROSS-store consistency is NOT free: an execution recorded in n8n's database a millisecond after
supabase's dump began is in one artifact and not the other. `--quiesce` stops the writers (each app's
`data.writers`: n8n's main, workers and runners, INDOX's poller, mail's) for the duration and restarts them afterwards, which is
the right choice for a MIGRATION (you are leaving this machine anyway) and the wrong one for a
routine backup of a live system. Default is off; the manifest records which was used, so a restore
can never silently assume the stronger guarantee.

RESUMABLE. Every artifact is written to `<name>.part` and renamed only after it is complete, and a
re-run skips any artifact already present with a matching size in `manifest.json`. Interrupting a
multi-GB export costs the artifact in flight and nothing else.

SECRETS. The archive necessarily contains key material — an n8n credential dump restored without the
same N8N_ENCRYPTION_KEY yields rows that look fine and cannot be decrypted, which is a restore that
appears to succeed. So `.env` and friends travel in the archive, and this driver REFUSES to write to
any path git does not ignore. See _assert_gitignored().
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "platform" / "manager"))
import datamoves  # noqa: E402 — the data move's ledger (DGO-2019): which old volumes a store still runs from
ROOTS = ("apps", "platform-base")
FORMAT_VERSION = 1

# There is deliberately NO skip-list of volumes here.
#
# The first draft had one — four postgres data directories and redis_data, each with a comment
# explaining why the driver would not tar it. That is a second owner of a fact each app already
# states: the app's hooks/backup emits `SKIPVOL <volume>` for anything it handled itself, and the
# redis app's hook emits it for a volume it deliberately does not carry (and re-proves that decision
# on every run). Two places recording "this volume is special" is exactly how §1-§3 of
# ai/context/platform-os-consolidation.md happened. A volume the driver does not see a SKIPVOL for
# is tarred, full stop.

# Files that a `git clone` does not bring and a restore cannot work without. Gitignored by design,
# so they travel in the archive rather than in the repo. Missing entries are not an error — a
# deployment that never issued a certificate has no acme.json.
SECRET_PATHS = [
    ".env",
    "secrets",
    ".catalog-signing-key.json",
    "portainer_password.txt",
    # Where portainer's compose actually keeps it (gitignored there). The root entry above found
    # nothing on any office measured, and the inventory reported the password "absent" while the
    # file sat in apps/portainer/ (DGO-1510, MacBook 2026-11-09). Both stay: an older checkout may
    # still have the root one.
    "apps/portainer/portainer_password.txt",
    "platform-base/traefik/config/acme.json",
    "apps/n8n/.credentials-state",
]

# What a clone does not bring and is the office's own DECLARATION rather than its secret. Carried
# ALWAYS, tracked or not:
#   platform.state.yaml   the apps the owner chose. Gitignored on the public copy (.gitignore), so on
#                         a client's office it was in NO archive: the volumes restored, and the office
#                         came up with the default apps. Tracked on an office branch, it still holds
#                         the edits since the last commit (`M platform.state.yaml` on mac-dgo), which
#                         the commit's copy would drop.
#   .state/outbox         the work-item writes project-pln has not sent yet (apps/project-pln/outbox.py).
# Never `.dgo/`: .gitignore says it is this machine's rendering of the link, re-rendered from the
# dgo-extend volumes, and a copy would carry another machine's keys.
DECLARATION_PATHS = [
    "platform.state.yaml",
    ".state/outbox",
]
# The declaration an import puts in place BEFORE it renders the compose config (cmd_import).
STATE_FIRST = {"platform.state.yaml"}

# Bind-mount subtrees excluded in `config` mode, with the cost of excluding each.
# apitools' store is the DGO folder's data/apitools/ since DGO-2019 (its source tree's ./storage and ./logs before, and
# still there on an office whose move waits): both spellings, so a config export leaves them out either way.
CONFIG_MODE_BIND_EXCLUDES = {
    "data/apitools/logs": "logs; regenerated by running",
    "data/apitools/storage/ocr_pdf_images": "rendered page images; re-derived by re-OCR (paid)",
    "data/apitools/storage/ocr_drawings": "overlay drawings; re-derived by re-OCR (paid)",
    "apps/apitools/logs": "logs; regenerated by running",
    "apps/apitools/storage/ocr_pdf_images": "rendered page images; re-derived by re-OCR (paid)",
    "apps/apitools/storage/ocr_drawings": "overlay drawings; re-derived by re-OCR (paid)",
}

SKIP_BIND_PREFIX = ("/var/run", "/run/", "/proc", "/sys", "/dev", "/etc/localtime", "/etc/timezone")


# ── plumbing ────────────────────────────────────────────────────────────────────────────────────

def run(cmd, **kw):
    """subprocess with a REAL return code. Never `$?` through a shell relay — see AGENTS.md."""
    kw.setdefault("cwd", REPO)
    kw.setdefault("capture_output", True)
    return subprocess.run(cmd, **kw)


def sh(cmd, **kw):
    r = run(cmd, **kw)
    if r.returncode != 0:
        raise RuntimeError(
            f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n"
            f"{(r.stderr or b'').decode('utf-8', 'replace')[-2000:]}")
    return (r.stdout or b"").decode("utf-8", "replace")


def say(msg):
    print(f"[archive] {msg}", flush=True)


def read_env(name, default=""):
    """The .env value, with ${VAR} references resolved the way scripts/lib.sh read_env does."""
    envf = REPO / ".env"
    if not envf.exists():
        return default
    raw = {}
    for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m and m.group(1) not in raw:
            raw[m.group(1)] = m.group(2).rstrip("\r")
    v = raw.get(name, default)
    for _ in range(20):
        m = re.search(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}", v or "")
        if not m:
            break
        v = v[:m.start()] + (raw.get(m.group(1)) or m.group(2) or "") + v[m.end():]
    return v


def docker_env():
    """The PROJECT engine, never Docker Desktop's — the same decision scripts/lib.sh makes."""
    e = dict(os.environ)
    e.setdefault("DOCKER_HOST", f"unix://{os.environ.get('BBOX_DOCKER_SOCK', '/run/bbox-docker.sock')}")
    return e


def project_name():
    """The compose project name, which is what prefixes every volume.

    This is NOT DEPLOYMENT_NAME. DEPLOYMENT_NAME suffixes CONTAINER names; the volume prefix is the
    basename of the clone directory (scripts/lib.sh compose_args passes `--project-directory .`).
    The distinction is the single biggest trap in restoring onto a machine that already runs this
    stack: two deployments in directories of the same name share volumes no matter how differently
    they are named, and two deployments in differently-named directories share nothing even if
    DEPLOYMENT_NAME matches.
    """
    return os.environ.get("COMPOSE_PROJECT_NAME") or REPO.name.lower()


def engine_id():
    """The docker engine's own id, or "" when it cannot be read.

    Volumes live in an ENGINE, so this is what "the deployment this archive came from" means for the
    one refusal that depends on it (cmd_import). The compose project name alone could not say: it is
    the clone directory's basename, and two offices cloned into same-named directories on two
    machines — the normal case — look identical by it.
    """
    r = run(["docker", "info", "--format", "{{.ID}}"], env=docker_env(), timeout=60)
    return (r.stdout or b"").decode("utf-8", "replace").strip() if r.returncode == 0 else ""


def enabled_apps():
    """[(root, id)] from the compiler — the same source run_app_hooks uses."""
    out = sh([sys.executable, "platform/manager/reconcile.py", "enabled-apps"])
    return [tuple(l.split()[:2]) for l in out.splitlines() if len(l.split()) >= 2]


# ── store discovery, by TECHNOLOGY rather than by app ───────────────────────────────────────────
#
# See scripts/refactor/app-coupling-lint.py (G33). The archiver may know postgres and redis — it
# cannot dump them otherwise — but it must not know which APPS run them, or an app installed
# tomorrow is silently left out of the backup. These live here rather than in the data-management
# service so the inventory and the export agree by construction: what the view lists is what the
# export walks.
PG_IMAGE_HINTS = ("postgres", "pgvector", "timescale")
KV_IMAGE_HINTS = ("redis", "valkey", "keydb")


def containers_with_images():
    r = run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}",
             "--filter", f"label=com.docker.compose.project={project_name()}"], env=docker_env())
    rows = []
    if r.returncode == 0:
        for line in (r.stdout or b"").decode("utf-8", "replace").splitlines():
            if "\t" in line:
                n, i = line.split("\t", 1)
                rows.append((n.strip(), i.strip()))
    return rows


def containers_by_tech(hints):
    return [n for n, img in containers_with_images() if any(h in img.lower() for h in hints)]


def container_env(name, keys, timeout=30):
    """How the image was told to initialise itself is the most reliable statement of how to reach
    it — and it stays correct when a password rotates or a new instance appears."""
    got = {}
    for k in keys:
        r = run(["docker", "exec", "-i", name, "printenv", k], env=docker_env(), timeout=timeout)
        if r.returncode == 0:
            v = (r.stdout or b"").decode("utf-8", "replace").strip()
            if v:
                got[k] = v
    return got


def pg_instances():
    """[(container, user, maintenance_db)] for every postgres that actually answers.

    A container whose image merely embeds postgres (postgres-meta, postgrest) has no POSTGRES_USER
    and is skipped, so no exclusion list has to name it.
    """
    out = []
    for c in containers_by_tech(PG_IMAGE_HINTS):
        env = container_env(c, ("POSTGRES_USER", "POSTGRES_DB"))
        u = env.get("POSTGRES_USER")
        if not u:
            continue
        out.append((c, u, env.get("POSTGRES_DB") or u))
    return out


def _live_tables(container, user, db):
    r = run(["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-tA", "-c",
             "select schemaname||'.'||relname from pg_stat_user_tables"],
            env=docker_env(), timeout=90)
    if r.returncode != 0:
        return []
    return [l.strip() for l in (r.stdout or b"").decode("utf-8", "replace").splitlines() if l.strip()]


# Functions an app's tables DEPEND on. `pg_dump -t table` carries the table AND its trigger
# definitions, but NOT the functions those triggers call — they live in the schema, not the table.
# Observed on a real round-trip of indox: the data restored and pg_restore then failed to create
# four triggers because incdoc_sync_doc_date_norm(), touch_updated_at() and two mirror functions did
# not exist in the target. That restore looks successful, holds every row, and has lost the
# behaviour that keeps those rows correct. So the functions travel with the tables.
_FN_DEPS_SQL = """
with tabs as (
  select c.oid from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind = 'r' and n.nspname||'.'||c.relname in (%s)
), fns as (
  select distinct p.oid from pg_trigger t join tabs on tabs.oid = t.tgrelid
    join pg_proc p on p.oid = t.tgfoid where not t.tgisinternal
  union
  select distinct d.refobjid from pg_attrdef ad join tabs on tabs.oid = ad.adrelid
    join pg_depend d on d.objid = ad.oid and d.refclassid = 'pg_proc'::regclass
)
select pg_get_functiondef(p.oid) || E';\\n'
from fns join pg_proc p on p.oid = fns.oid
join pg_namespace n on n.oid = p.pronamespace
where n.nspname not in ('pg_catalog','information_schema')
"""


def dump_table_functions(container, user, dbname, tables, dest: pathlib.Path):
    """Write CREATE OR REPLACE for every function `tables` depend on. Returns how many, or 0."""
    if not tables:
        return 0
    lst = ", ".join("'" + t.replace("'", "''") + "'" for t in sorted(tables))
    r = run(["docker", "exec", "-i", container, "psql", "-U", user, "-d", dbname, "-tA",
             "-c", _FN_DEPS_SQL % lst], env=docker_env(), timeout=120)
    if r.returncode != 0:
        return 0
    body = (r.stdout or b"").decode("utf-8", "replace").strip()
    if not body:
        return 0
    dest.write_text(body + "\n", encoding="utf-8")
    return body.count("CREATE OR REPLACE FUNCTION") + body.count("CREATE FUNCTION")


def dump_app_sql(aid, decl, dest: pathlib.Path):
    """pg_dump exactly what one app declared, into dest. Returns a note, or None if nothing matched.

    This is what data.sql buys. The shared `public` schema holds several apps' tables at once, so a
    per-app dump has to name them: -n for whole schemas, -t for individual tables, and neither means
    the app owns the whole database. Table patterns are expanded against the LIVE table list so a
    declaration of `chat_*` picks up a table added since the manifest was written.
    """
    inst_pat, dbname = decl.get("instance"), decl.get("database")
    cands = [(c, u, m) for c, u, m in pg_instances()
             if not inst_pat or c.startswith(inst_pat)]
    for container, user, _maint in cands:
        r = run(["docker", "exec", "-i", container, "psql", "-U", user, "-d", dbname, "-tAc",
                 "select 1"], env=docker_env(), timeout=60)
        if r.returncode != 0:
            continue                                  # this instance has no such database
        args = ["docker", "exec", "-i", container, "pg_dump", "-U", user, "-d", dbname, "-Fc"]
        what, picked = [], []
        for s in (decl.get("schemas") or []):
            args += ["-n", s]
            what.append(f"schema {s}")
        pats = decl.get("tables") or []
        if pats:
            live = _live_tables(container, user, dbname)
            picked = []
            for full in live:
                schema, _, tbl = full.partition(".")
                for p in pats:
                    if (tbl.startswith(p[:-1]) if p.endswith("*") else tbl == p):
                        picked.append(full)
                        break
            if not picked:
                continue
            for t in sorted(picked):
                args += ["-t", t]
            what.append(f"{len(picked)} table(s)")
        if not what:
            what.append("whole database")
        part = dest.with_suffix(dest.suffix + ".part")
        with open(part, "wb") as fh:
            r = subprocess.run(args, cwd=REPO, stdout=fh, stderr=subprocess.PIPE, env=docker_env())
        if r.returncode != 0:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump for {aid} failed: "
                               f"{(r.stderr or b'').decode('utf-8', 'replace')[-400:]}")
        part.rename(dest)
        return {"note": f"{aid}: {container}/{dbname} — {', '.join(what)}",
                "container": container, "user": user, "db": dbname, "tables": picked}
    return None


def path_owner_map():
    """{repo-relative bind path: app_id}. data.paths is authoritative; otherwise the directory's
    location decides, since a bind under apps/<id>/ is that app's by construction.

    Lives here so the inventory and the export attribute a path the same way. Two implementations of
    "whose directory is this" is how a view says an app owns 17.8GB and an export files it elsewhere.
    """
    owner, located = {}, {}
    for root, aid in installed_apps():
        for p in ((app_manifest(root, aid).get("data") or {}).get("paths") or []):
            owner[p.strip("/")] = aid
        located[f"{root}/{aid}"] = aid
    return owner, located


def owner_of_path(relpath, owner, located):
    p = relpath.strip("/")
    if p in owner:
        return owner[p], "declared"
    for prefix, aid in located.items():
        if p == prefix or p.startswith(prefix + "/"):
            return aid, "discovered"
    return None, None


def app_sql_decls(apps):
    """[(app_id, decl)] from every app's data.sql — the declared ownership the per-app dump uses."""
    out = []
    for root, aid in apps:
        for decl in ((app_manifest(root, aid).get("data") or {}).get("sql") or []):
            out.append((aid, decl))
    return out


def installed_apps():
    """[(root, id)] for EVERY app with a manifest on disk, enabled or not.

    Needed because "enabled" is a runtime disposition while a volume is durable state.
    app.schema.json is explicit that disabling an app "ALWAYS keeps data (that is what makes the
    toggle stateful)" — only `bbox apps uninstall --purge` deletes it. So the set of apps whose data
    must survive a machine move is the INSTALLED set, not the enabled one.
    """
    out = []
    # instances/ (DGO-1920): an app's further copies keep their data in volumes of their own, which a move
    # carries like any app's; their folders come back from platform.state.yaml (the render writes them).
    for root in ("apps", "platform-base", "instances"):
        base = REPO / root
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if (d / "app.json").is_file():
                out.append((root, app_manifest(root, d.name).get("id", d.name)))
    return out


def app_manifest(root, aid):
    p = REPO / root / aid / "app.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def app_hook(root, aid, verb):
    """The app's hook for `verb`, or None. Existence, not the executable bit — see module docstring."""
    for ext in ("", ".sh", ".py"):
        p = REPO / root / aid / "hooks" / f"{verb}{ext}"
        if p.is_file():
            return p
    return None


def tracked_paths():
    raw = run(["git", "ls-files", "-z"]).stdout or b""
    return {p for p in raw.decode("utf-8", "surrogateescape").split("\0") if p}


def _assert_gitignored(path: pathlib.Path):
    """Refuse to write an archive anywhere git would pick it up.

    A check that cannot fail is not a check. This one fails closed: if the path is inside the repo
    and `git check-ignore` does not claim it, the export STOPS rather than writing credentials into
    a tree somebody will later `git add -A`.
    """
    try:
        rel = path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return                                    # outside the repo: git cannot pick it up
    r = run(["git", "check-ignore", "-q", rel])
    if r.returncode != 0:
        raise SystemExit(
            f"[archive] REFUSING to write to {rel}: git does not ignore it, and this archive "
            f"contains .env, the n8n encryption key and the connections vault.\n"
            f"          Add a line to .gitignore (the default output path `exports/` already is), "
            f"or pass --out to a path outside the repo.")


def carried_source(rel):
    """The path to read for a carried file or tree `rel` (SECRET_PATHS, DECLARATION_PATHS), or None
    when the office has none.

    A symlink is read at its TARGET. On a packaged office `.env` is a link to /etc/binaos/binaos.env
    (packaging/linux/header.sh), and a link whose target this process cannot see is REFUSED, never
    stepped over. `exists()` follows the link, so the old `if not src.exists(): continue` read a
    dangling `.env` as "no .env here". Inside data-management, which does not mount /etc/binaos, that
    produced an archive with no .env, i.e. no key to any credential in it, under a green export
    (DGO-1510).
    """
    p = REPO / rel
    if p.is_symlink():
        real = pathlib.Path(os.path.realpath(p))
        if not real.exists():
            raise RuntimeError(
                f"{rel} is a link to {real}, which this process cannot see, so the archive would be "
                f"written without it. Run the export where {real} is visible, or mount it here.")
        return real
    return p if p.exists() else None


def undeclared_volumes(listing, declared, project):
    """Pure. What on this engine no installed app declares, so no archive carries it.

    listing:  [(volume name, its compose project label or "", its size or None)]
    declared: the short names every INSTALLED app declares (data.volumes)
    Returns ([{name, project, ours, size}], anonymous): `ours` is a volume of THIS project
    (`<project>_<short>`) whose short name nobody declares; the rest belong to another project or to
    none (a `docker volume create`, an earlier office's leftovers). Every one is named: the inventory's
    UNCLAIMED list saw only this project's prefix, and 26 volumes on the MacBook (2026-11-09) were in
    no list at all. Anonymous volumes (64 hex) are counted, not named.
    """
    rows, anonymous = [], {"count": 0, "sizes": []}
    for name, label, size in listing:
        size = None if str(size or "").strip().upper() in ("", "N/A") else size
        if re.fullmatch(r"[0-9a-f]{64}", name or ""):
            anonymous["count"] += 1
            anonymous["sizes"].append(size)
            continue
        # A declared volume is carried by its NAME, `<project>_<short>` (_tar_volume), whatever its
        # label says — so it is never named as left out (DGO-1510, the second reader).
        if name.startswith(project + "_") and name[len(project) + 1:] in declared:
            continue
        # Otherwise the compose label decides whose a volume is, when there is one: a project `p_x`
        # would otherwise read `p_x_data` as a volume of `p`. With no label, the name's prefix is all
        # there is to go by.
        ours = (label == project) if label else name.startswith(project + "_")
        rows.append({"name": name, "project": label or (project if ours else None), "ours": ours,
                     "size": size})
    return rows, anonymous


def engine_volumes():
    """[(name, compose project label, size)] of every volume on the project engine. The size is
    docker's own (`system df -v`), or None where it did not answer: a missing size is said, never
    guessed."""
    r = run(["docker", "volume", "ls", "--format", '{{.Name}}\t{{.Label "com.docker.compose.project"}}'],
            env=docker_env(), timeout=90)
    if r.returncode != 0:
        raise RuntimeError("docker volume ls failed: "
                           + (r.stderr or b"").decode("utf-8", "replace")[-300:])
    sizes = {}
    try:                                   # sizes are a nicety: their timeout must not lose the names
        df = run(["docker", "system", "df", "-v", "--format",
                  "{{range .Volumes}}{{.Name}}\t{{.Size}}\n{{end}}"], env=docker_env(), timeout=240)
    except subprocess.TimeoutExpired:
        df = None
    if df is not None and df.returncode == 0:
        for line in (df.stdout or b"").decode("utf-8", "replace").splitlines():
            n, _, s = line.partition("\t")
            if n:
                sizes[n.strip()] = s.strip() or None
    out = []
    for line in (r.stdout or b"").decode("utf-8", "replace").splitlines():
        n, _, label = line.partition("\t")
        if n.strip():
            out.append((n.strip(), label.strip(), sizes.get(n.strip())))
    return out


def sha256_size(p: pathlib.Path):
    h = hashlib.sha256()
    n = 0
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


# ── the state inventory ─────────────────────────────────────────────────────────────────────────

def declared_volumes(apps):
    """{volume_short_name: app_id} from every enabled app's `data.volumes`.

    Gate G26 asserts this inventory is complete and grounded against each app's compose, which is
    what makes it safe to derive a backup from. Its docstring says so in as many words: "a backup
    derived from it would silently skip every volume the manifest forgot".
    """
    out = {}
    for root, aid in apps:
        m = app_manifest(root, aid)
        # …and the old volume of a store whose move into data/<app>/ is not proven yet (DGO-2019): the store still
        # runs from it on an office that waits (drvfs, a share), so it is what the backup must carry
        for v in ((m.get("data") or {}).get("volumes") or []) + datamoves.carried_volumes(REPO, aid, m):
            out[v] = aid
    return out


def app_shares(aid):
    """The volumes app `aid` mounts but another app owns (`data.shares`, DGO-1510): carried, restored and purged with
    their owner, never in `aid`'s own scope."""
    root = next((r for r, i in installed_apps() if i == aid), None)
    return set(((app_manifest(root, aid).get("data") or {}).get("shares") or [])) if root else set()


def volume_of(rel, e):
    """The volume a volume artifact restores (`volumes/<v>.tar.gz`, parsed as the restore parses it), or ""."""
    p = pathlib.PurePosixPath(rel)
    if e.get("kind") in ("volume", "volume-dormant") and p.parent.as_posix() == "volumes" \
            and p.name.endswith(".tar.gz"):
        return p.name[:-len(".tar.gz")]
    return ""


def shared_entries(scope_app):
    """{`volumes/<v>.SHARED`: entry} for each volume `scope_app` only shares (DGO-1510): what an export scoped to it
    records instead of the volume. Filed under the app like any artifact of its scope, so that app's own `--app`
    import of the archive finds it (an app move: export here, `import --app` there)."""
    owners = declared_volumes(installed_apps())
    out = {}
    for vol in sorted(app_shares(scope_app)):
        owner = owners.get(vol, "another app")
        out[f"volumes/{vol}.SHARED"] = {
            "kind": "skipped", "bytes": 0, "sha256": "", "app": scope_app,
            "note": f"{owner}'s volume, which {scope_app} shares: `export --app {owner}` carries it"}
    return out


def volume_owners():
    """{volume: the app that owns it} of every installed app — its `data.volumes`, and the old volumes its stores moved
    from (`data.moved_from`, DGO-2019): n8n owns n8n_storage after its move as before it, whoever read it."""
    out = {}
    for root, aid in installed_apps():
        m = app_manifest(root, aid)
        for v in ((m.get("data") or {}).get("volumes") or []) + datamoves.old_volumes(m):
            out.setdefault(v, aid)
    return out


def drop_shares(scope, artifacts):
    """(artifacts without another app's volumes, [(artifact, owner)]) — what an import scoped to `scope` must never
    write: a volume `scope` only shares (data.shares), or one another app OWNS (volume_owners) — an archive made before
    data.shares filed n8n_storage under any-concurrency, which reads n8n's store and declares none of it since n8n's
    move (G26 holds each volume to one owner)."""
    shares = app_shares(scope)
    owners = volume_owners()
    keep, dropped = {}, []
    for rel, e in artifacts.items():
        vol = volume_of(rel, e)
        if vol and (vol in shares or owners.get(vol, scope) != scope):
            dropped.append((rel, owners.get(vol, "another app")))
        else:
            keep[rel] = e
    return keep, dropped


def compose_config():
    dc = REPO / "scripts" / "dc"
    out = sh(["bash", str(dc), "config", "--format", "json"], env=docker_env())
    return json.loads(out)


def _network_owners(net):
    """{alias: [container names]} and {container: project} for one existing docker network."""
    r = run(["docker", "network", "inspect", net, "--format", "{{json .Containers}}"],
            env=docker_env())
    if r.returncode != 0:
        return {}, {}
    try:
        members = json.loads((r.stdout or b"{}").decode() or "{}") or {}
    except json.JSONDecodeError:
        return {}, {}
    aliases, owners = {}, {}
    for info in members.values():
        name = info.get("Name")
        if not name:
            continue
        insp = run(["docker", "inspect", name, "--format",
                    "{{json .NetworkSettings.Networks}}|{{index .Config.Labels \"com.docker.compose.project\"}}"],
                   env=docker_env())
        if insp.returncode != 0:
            continue
        raw = (insp.stdout or b"").decode().strip()
        nets_json, _, proj = raw.rpartition("|")
        owners[name] = proj.strip() or "<no project>"
        try:
            nets = json.loads(nets_json) or {}
        except json.JSONDecodeError:
            continue
        for a in (nets.get(net) or {}).get("Aliases") or []:
            aliases.setdefault(a, []).append(name)
    return aliases, owners


def assert_network_isolation(cfg, allow_shared=False, services=None):
    """REFUSE to restore if this project would claim a network alias another project already holds.

    ── THE INCIDENT THIS EXISTS FOR (2026-08-06, caused by this very feature's first test) ────────
    Restoring into a second deployment on the same host brought up `supabase-db-restore-test`,
    `n8n-postgres-restore-test` and `authentik-postgres-restore-test`, and compose attached them to
    the EXTERNAL, SHARED `traefik-network` — where compose also gave each one the bare SERVICE NAME
    as a network alias: `db`, `supabase-db`, `n8n-postgres`.

    Those are the names the LIVE stack resolves its databases by. Docker's embedded DNS round-robins
    an alias across every container holding it, so roughly half of every database connection from
    n8n, its workers and every Postgres node was answered by an EMPTY restore database. Measured on
    the E2E lane: the error rate went from 2.3% to 32.5%, and one minute recorded 0 successes and 12
    errors. The symptoms read as catastrophic product failure — `relation "public.execution_entity"
    does not exist`, `public.incoming_documents` missing, `public.touch_updated_at()` missing — and
    both real databases were perfectly intact the whole time. It also invalidated a full E2E
    verification run.

    On the VPS the identical collision would silently route LIVE WRITES into a restored database.

    ── WHY archive-lib.sh WAS NOT ENOUGH ─────────────────────────────────────────────────────────
    scripts/archive-lib.sh already guards the sibling hazard: `cn`'s regex widening onto another
    deployment's CONTAINER. Someone had already seen the class. But a container name is not the only
    name a container answers to, and nothing guarded the NETWORK ALIAS — which is the one the rest
    of the estate actually dials. The guard that existed is the proof the class was known and this
    instance uncovered.

    ── THE RULE ──────────────────────────────────────────────────────────────────────────────────
    An alias collision is refused unconditionally: there is no correct reason to answer to a name
    another deployment's clients are already dialling. Merely sharing a network with another project
    is refused too, but with an escape hatch, because a single-deployment host legitimately has one
    project on `traefik-network` — and that case does not trip this at all, since the colliding
    containers would be its own.

    ── AN APP-SCOPED RESTORE ASKS ABOUT THAT APP'S SERVICES (`services`) ─────────────────────────
    The shared-network refusal is a precaution about what a restore will start LATER: on a
    whole-deployment restore that is every service there is, so one foreign project on the network
    is reason enough to stop. Restoring ONE app starts that app's services and nothing else, and
    for those the question can be answered now instead of feared: each name they answer to is
    looked up, and a single one held by another project is the unconditional refusal above. Past
    that there is nothing left for the precaution to guard — and keeping it would mean no office
    with a neighbour on its engine could ever take an app in (measured 2026-10-05: hp-laptop
    shares `traefik-network` with two containers of an older stack, which answer to
    `console-posnet`, `network-posnet` and `network`; a restore of project-pln, whose services are
    `project-pln`, `plane-db`, `plane-redis` and `plane-minio`, was refused for it).
    """
    ours = (cfg.get("name") or project_name()).strip()

    # Resolve each compose network KEY to the REAL docker network name. They are not the same thing
    # and confusing them makes this check answer about the wrong network: a project-local
    # `traefik-network` is `dh-restore_traefik-network` in docker, while an `external: true` one
    # keeps the bare name. The first version of this function looked up the KEY, found the SHARED
    # `traefik-network`, and reported 34 collisions for a deployment that was already isolated —
    # failing safe, but for the wrong reason, which is a check you cannot trust in either direction.
    netname = {}
    for key, spec in (cfg.get("networks") or {}).items():
        netname[key] = ((spec or {}).get("name") or key)

    want = {}                       # real docker network name -> {alias: service}
    for svc, spec in (cfg.get("services") or {}).items():
        if services is not None and svc not in services:
            continue
        nets = spec.get("networks") or {}
        names = list(nets) if isinstance(nets, dict) else list(nets or [])
        for key in names:
            n = netname.get(key, key)
            claims = {svc}
            cn_ = spec.get("container_name")
            if cn_:
                claims.add(cn_)
            if isinstance(nets, dict) and isinstance(nets.get(key), dict):
                claims.update((nets[key].get("aliases") or []))
            for a in claims:
                want.setdefault(n, {}).setdefault(a, svc)

    collisions, shared = [], {}
    for net, claims in sorted(want.items()):
        held, owners = _network_owners(net)
        foreign = {c: p for c, p in owners.items() if p != ours}
        if foreign:
            shared[net] = foreign
        for alias, svc in sorted(claims.items()):
            for holder in held.get(alias, []):
                if owners.get(holder) != ours:
                    collisions.append((net, alias, svc, holder, owners.get(holder)))

    if collisions:
        lines = [f"    {net}: alias '{alias}' (our service '{svc}') is already held by "
                 f"{holder} of project '{proj}'" for net, alias, svc, holder, proj in collisions]
        raise SystemExit(
            "[archive] REFUSING TO RESTORE — network alias collision.\n"
            + "\n".join(lines) +
            "\n\n  Docker's DNS round-robins an alias across every container holding it. Bringing "
            "these up would\n  answer a share of the OTHER deployment's database traffic from THIS "
            "one — silently, and for\n  writes as well as reads. Measured on 2026-08-06: a restore "
            "that joined the shared network took\n  the live stack's error rate from 2.3% to 32.5%.\n"
            "\n  Fix: give this deployment its own networks. The compose project name is the CLONE "
            "DIRECTORY\n  BASENAME, so a second checkout already gets its own PROJECT networks — but "
            "any network declared\n  `external: true` (traefik-network) is shared by definition and "
            "must not be joined by two\n  deployments on one host.")

    if shared and not allow_shared and services is None:
        lines = [f"    {net}: also carries {len(cs)} container(s) from project(s) "
                 f"{sorted(set(cs.values()))}" for net, cs in sorted(shared.items())]
        raise SystemExit(
            "[archive] REFUSING TO RESTORE — this deployment joins a network another compose "
            "project is on.\n" + "\n".join(lines) +
            "\n\n  No alias collides RIGHT NOW, but every service this restore later starts claims "
            "its own service\n  name as an alias on these networks, and the collision appears the "
            "moment it does.\n"
            "\n  Pass --allow-shared-network only if you know this host runs exactly one deployment "
            "and the\n  other project is something unrelated that will never dial these names.")
    say("  network isolation OK — no alias "
        + (f"these {len(services)} service(s) claim" if services is not None else "this deployment claims")
        + " is held by another project")


def stateful_binds(cfg):
    """Writable host binds under the repo that hold files git does not track.

    G26 asks the same question and answers it at DIRECTORY granularity: tracked_paths() adds every
    parent directory of every tracked file, so a single `.gitkeep` marks a whole tree as "tracked,
    therefore not state". Measured on this estate, that hides N files (156 MB) under
    apps/apitools/storage and 8 more under apps/chat/data behind two `.gitkeep`s, and G26 still
    reports PASS. This function asks the question per FILE, so a sentinel file cannot hide a tree.
    """
    tracked = tracked_paths()
    found, walked = {}, set()
    for svc in (cfg.get("services") or {}).values():
        for m in svc.get("volumes") or []:
            if m.get("type") != "bind" or m.get("read_only"):
                continue
            src = (m.get("source") or "").replace("\\", "/")
            if not src or src.startswith(SKIP_BIND_PREFIX):
                continue
            try:
                rel = pathlib.Path(src).resolve().relative_to(REPO).as_posix()
            except ValueError:
                continue                          # outside the repo — not carried by a folder zip
            if rel in ("", "."):
                continue                          # the repo root itself (app-management's mount)
            # ONCE PER DIRECTORY, not once per service that mounts it. The browser's profile is
            # mounted by five services, so it was walked five times: 39 of the 54 seconds an
            # inventory sweep took on hp-laptop (2026-10-07), for N files.
            if rel in walked:
                continue
            walked.add(rel)
            p = REPO / rel
            if not p.is_dir():
                continue                          # single-file config injections
            # os.walk, not Path.rglob: one directory read per DIRECTORY, where rglob + is_file()
            # + stat() asked the file system about every entry twice — over a Windows mount each
            # question is a round trip (4 ms a file there; the same tree walks in 0.7 s this way).
            # A file that goes away between the listing and the stat (a live browser profile does
            # that all day) is simply not counted; it used to fail the whole inventory section.
            size = count = 0
            for cur, _dirs, files in os.walk(p):
                base = pathlib.Path(cur).relative_to(REPO).as_posix()
                for name in files:
                    if f"{base}/{name}" in tracked:
                        continue
                    try:
                        size += os.stat(os.path.join(cur, name)).st_size
                    except OSError:
                        continue                  # gone, or a link to nothing: not a file to carry
                    count += 1
            if count:
                found[rel] = size
    return found


# ── export ──────────────────────────────────────────────────────────────────────────────────────

def _tar_volume(vol, dest: pathlib.Path, exclude=()):
    """tar a named volume through a throwaway container — the only way to read one portably."""
    proj = project_name()
    full = f"{proj}_{vol}"
    ex = " ".join(f"--exclude ./{e}" for e in exclude)
    sh(["docker", "run", "--rm", "-v", f"{full}:/v:ro", "-v", f"{dest.parent}:/out", "alpine",
        "sh", "-c",
        f"tar czf /out/{dest.name} {ex} -C /v . && chown {os.getuid()}:{os.getgid()} /out/{dest.name}"],
       env=docker_env())


def _tar_dir_as_root(src: pathlib.Path, dest: pathlib.Path, exclude=()):
    """tar a host directory THROUGH A CONTAINER, not with the host's own tar.

    Found the hard way on the first real export. `apps/apitools/storage/ocr_cache/*.json` is written
    by the apitools container, which runs as root, so the six cache files are mode 600 root:root on
    the host — and the operator's `tar` exits 2 with "Cannot open: Permission denied" on every one.
    Six files out of 1,150 in one subtree of one bind, and the failure mode had two forms available
    to it: abort the export (what happened), or, had anyone reached for `|| true`, produce an archive
    that is missing files and reports success.

    A bind mount is state written by containers; it must be read the same way. This also preserves
    the uid/gid a container expects to find on restore, which a host-side tar run as an unprivileged
    user cannot do either.
    """
    ex = " ".join(f"--exclude ./{e}" for e in exclude)
    # chown back to the caller: a root-owned artifact in the operator's own archive is one the
    # operator cannot checksum, delete or ship.
    sh(["docker", "run", "--rm", "-v", f"{src}:/src:ro", "-v", f"{dest.parent}:/out", "alpine",
        "sh", "-c",
        f"tar czf /out/{dest.name} {ex} -C /src . && chown {os.getuid()}:{os.getgid()} /out/{dest.name}"],
       env=docker_env())


def _volume_exists(vol):
    r = run(["docker", "volume", "inspect", f"{project_name()}_{vol}"], env=docker_env())
    return r.returncode == 0


def _run_hook(path: pathlib.Path, args):
    """Run an app hook and parse its ARTIFACT / FACT / SKIPVOL lines."""
    interp = [sys.executable] if path.suffix == ".py" else ["bash"]
    r = run(interp + [str(path)] + list(args), env=docker_env())
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    parsed = {"artifacts": [], "facts": {}, "skipvols": []}
    for line in out.splitlines():
        w = line.split(None, 2)
        if not w:
            continue
        if w[0] == "ARTIFACT" and len(w) >= 2:
            parsed["artifacts"].append(w[1])
        elif w[0] == "FACT":
            # A FACT with no value is NOT a fact worth zero — it is a query that failed. Hooks route
            # psql's stderr to /dev/null (an expected table may not exist yet), so a broken query
            # emits `FACT users ` and, left alone, would be dropped on both sides of the diff and
            # compare equal by being absent twice. Measured: `\"user\"` written inside single quotes
            # reached psql with literal backslashes and produced exactly that. Absence of a
            # measurement is not evidence of a good one — fail.
            if len(w) < 3 or not w[2].strip():
                raise RuntimeError(
                    f"{path.name} emitted an EMPTY fact: '{line.strip()}'. The underlying query "
                    f"failed; a silently missing fact makes the restore diff vacuous.")
            parsed["facts"][w[1]] = w[2].strip()
        elif w[0] == "SKIPVOL" and len(w) >= 2:
            parsed["skipvols"].append(w[1])
        else:
            print(f"    {line}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"{path.relative_to(REPO).as_posix()} failed ({r.returncode})\n{err[-3000:]}\n{out[-2000:]}")
    if err.strip():
        for line in err.strip().splitlines()[-10:]:
            print(f"    ! {line}", flush=True)
    return parsed


def _writers(apps):
    """Container names of the RUNNING services that `apps` declare as writing to their stores (`data.writers`), in
    declaration order — what a quiesced export stops (it passes every installed app: one app's service may write
    another app's store, and a disabled app's may still run). Read from the declarations (DGO-1510): it used to pick
    containers by name (n8n-*, incoming-documents, mailboxd, mailapi), which no new app could join without an edit
    here, and whose suffix match also hit another deployment's `n8n-x-<name>`. G26 holds each declared writer to a
    service of the app's compose whose container is `<service>-${DEPLOYMENT_NAME}`, and never a database."""
    dn = read_env("DEPLOYMENT_NAME") or "bina-deployment"
    running = set(sh(["docker", "ps", "--format", "{{.Names}}"], env=docker_env()).split())
    out = []
    for root, aid in apps:
        for svc in ((app_manifest(root, aid).get("data") or {}).get("writers") or []):
            name = f"{svc}-{dn}"
            if name in running and name not in out:
                out.append(name)
    return out


def cmd_export(a):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dn = read_env("DEPLOYMENT_NAME") or "bina-deployment"
    out = pathlib.Path(a.out) if a.out else REPO / "exports" / f"{dn}-{a.mode}-{stamp}"
    out = out.resolve()
    _assert_gitignored(out)
    out.mkdir(parents=True, exist_ok=True)

    mpath = out / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() and not a.force else {}
    # A run resumes only an archive of its own scope: resuming another's (an `--app n8n` directory with
    # `--app any-concurrency`, or a whole-office one) mixed two scopes in one manifest — and a sharer's run then
    # removed the owner's tarball from that other backup (DGO-1510, the third reader).
    if "scope" in man and (man.get("scope") or {}).get("app") != (getattr(a, "app", None) or None):
        raise SystemExit(f"[archive] {out} holds an archive of {(man.get('scope') or {}).get('app') or 'the whole office'}"
                         f", not of {getattr(a, 'app', None) or 'the whole office'}: resume it with the same scope, "
                         "or export into another directory (--force starts this one again)")
    man.setdefault("format_version", FORMAT_VERSION)
    man.setdefault("artifacts", {})
    man.setdefault("facts", {})
    man.update({
        "deployment_name": dn,
        "compose_project": project_name(),
        "engine": engine_id(),
        "repo_dir_basename": REPO.name,
        "mode": a.mode,
        "quiesced": bool(a.quiesce),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    def save():
        mpath.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")

    def record(rel, kind, note="", app=None, **extra):
        p = out / rel
        digest, size = sha256_size(p)
        # `app` is what makes per-app restore possible: it is the manifest's index of who owns each
        # artifact. `note` stayed free text (it also carries exclusion reasons), so the owner needed
        # its own field rather than a convention about how to parse a sentence — and `extra` exists
        # for the same reason: the SQL restore needs the instance and database, and recovering those
        # by splitting a human sentence on ':' and '/' is a parser waiting to meet a container whose
        # name contains a dash in the wrong place.
        man["artifacts"][rel] = {"kind": kind, "sha256": digest, "bytes": size, "note": note,
                                 "app": app, **extra}
        say(f"  + {rel}  {size/1e6:.1f} MB")
        save()

    def done(rel):
        """Resumability: an artifact already present at its recorded size is not redone."""
        e = man["artifacts"].get(rel)
        p = out / rel
        return bool(e) and p.exists() and p.stat().st_size == e["bytes"] and not a.force

    # SCOPE. A whole-deployment export walks the enabled apps; --app narrows to one app's declared
    # stores and produces an archive that stands on its own — the unit you move when you want THIS
    # app on another machine, not this machine on another machine.
    #
    # installed_apps(), not enabled_apps(), for the --app lookup: a disabled app still holds data
    # (the platform promises that), and "export the thing I just turned off, before I wipe the
    # laptop" is exactly when a per-app export earns its keep.
    scope_app = getattr(a, "app", None)
    if scope_app:
        match = [(r, i) for r, i in installed_apps() if i == scope_app]
        if not match:
            raise SystemExit(f"[archive] no app '{scope_app}' is installed "
                             f"({', '.join(sorted(i for _r, i in installed_apps()))})")
        apps = match
    else:
        apps = enabled_apps()
    man["scope"] = {"app": scope_app}
    say(f"deployment={dn}  project={project_name()}  mode={a.mode}  out={out}")
    say(f"scope: {'app ' + scope_app if scope_app else str(len(apps)) + ' enabled app(s)'}")

    # Every carried path is asked FIRST. A `.env` link this process cannot follow (a packaged office,
    # run from data-management, which does not mount /etc/binaos) refuses in carried_source. Asked at
    # step 4, that refusal came after every volume had been tarred, hours into a large office.
    if not scope_app:
        for rel in SECRET_PATHS + DECLARATION_PATHS:
            carried_source(rel)

    stopped = []
    try:
        if a.quiesce:
            # every INSTALLED app's running writers, whatever the scope: n8n writes INDOX's tables (its workflows'
            # upserts), so an export of INDOX alone that stopped only INDOX's service was not quiet (the second
            # reader, DGO-1510); and a disabled app's volumes are exported too (2b, and `--app` of a disabled app),
            # while its containers may still run — a state written before its render (the third reader). Only
            # running ones are stopped, and exactly those are started again.
            stopped = _writers(installed_apps())
            if stopped:
                say(f"quiescing {len(stopped)} writer(s): {' '.join(stopped)}")
                sh(["docker", "stop"] + stopped, env=docker_env())

        # 1. apps that own their own snapshot
        (out / "apps").mkdir(exist_ok=True)
        handled = set()
        for root, aid in apps:
            hook = app_hook(root, aid, "backup")
            if not hook:
                continue
            d = out / "apps" / aid
            d.mkdir(parents=True, exist_ok=True)
            say(f"app {aid}: {hook.relative_to(REPO).as_posix()}")
            res = _run_hook(hook, [str(d), a.mode])
            handled.update(res["skipvols"])
            man["facts"].setdefault(aid, {}).update(res["facts"])
            for rel in res["artifacts"]:
                record(f"apps/{aid}/{rel}", "app-backup", aid, app=aid)
            save()

        # 2. every other declared volume, generically
        (out / "volumes").mkdir(exist_ok=True)
        for vol, aid in sorted(declared_volumes(apps).items()):
            if vol in handled:
                man["artifacts"].setdefault(f"volumes/{vol}.HANDLED", {
                    "kind": "skipped", "bytes": 0, "sha256": "",
                    "note": f"claimed by {aid}'s own hooks/backup"})
                continue
            if not _volume_exists(vol):
                say(f"  - {vol}: does not exist on this engine (app never started) — skipped")
                continue
            rel = f"volumes/{vol}.tar.gz"
            if done(rel):
                say(f"  = {rel} (already complete)")
                continue
            part = out / (rel + ".part")
            _tar_volume(vol, part)
            part.rename(out / rel)
            record(rel, "volume", aid, app=aid)
        # a volume the scoped app only shares is its owner's (DGO-1510): not carried here, and said where it is.
        # A tarball of it an earlier run into this directory left (before the share was declared) goes too:
        # resumability keeps what is on disk, and this archive must not carry it.
        if scope_app:
            stale = []
            for rel, entry in shared_entries(scope_app).items():
                say(f"  - {rel[len('volumes/'):-len('.SHARED')]}: {entry['note']}")
                tar = rel[:-len(".SHARED")] + ".tar.gz"
                if man["artifacts"].pop(tar, None) is not None or (out / tar).exists():
                    stale.append(tar)
                man["artifacts"][rel] = entry
            save()                                         # the manifest first: it never names a file gone
            for tar in stale:                              # …even under --force, whose manifest began empty
                (out / tar).unlink(missing_ok=True)
                say(f"    {tar} of an earlier run removed: it is the owner's")

        # 2b. volumes belonging to apps that are INSTALLED BUT NOT ENABLED.
        #
        # Steps 1 and 2 both iterate enabled_apps(), so a disabled app's data was invisible to the
        # export. That is a real loss, not a tidy omission: the platform's own schema promises that
        # disabling keeps data, so the volume is live user state the operator was told is safe.
        # Export -> restore on a new machine -> enable the app again, and it comes back empty. On
        # owner-laptop 2026-08-12 this was 4 volumes / 89.6MB, including `cloakprofile`, which
        # holds a logged-in Google browser session that cannot be re-created from the repo.
        #
        # Tarred generically and never via hooks: a disabled app has no running container for a hook
        # to dump from. Volumes that do not exist are skipped exactly as in step 2 — an app that was
        # never started has nothing to carry.
        # 2c. per-app SQL, from data.sql. Only in --app scope: a whole-deployment export already
        # dumps these through the owning app's hooks/backup (which know about ACLs, --clean and
        # role handling), and dumping both would double the archive to no benefit. In app scope
        # there may be no hook at all — an app that only keeps tables in the SHARED database owns no
        # container to run one — and this is the only thing that carries its rows.
        if scope_app:
            (out / "sql").mkdir(exist_ok=True)
            for aid, decl in app_sql_decls(apps):
                rel = f"sql/{aid}.{decl.get('database')}.dump"
                if done(rel):
                    say(f"  = {rel} (already complete)")
                    continue
                res = dump_app_sql(aid, decl, out / rel)
                if not res:
                    say(f"  - {aid}: no live tables matched its data.sql declaration")
                    continue
                # Functions FIRST in the archive's ordering, because the restore needs them before
                # the dump's triggers can be created. Recorded as their own artifact so the import
                # can apply them ahead of pg_restore rather than relying on file naming.
                if res["tables"]:
                    frel = f"sql/{aid}.{decl.get('database')}.functions.sql"
                    n = dump_table_functions(res["container"], res["user"], res["db"],
                                             res["tables"], out / frel)
                    if n:
                        record(frel, "sql-functions",
                               f"{aid}: {n} function(s) its tables' triggers/defaults depend on",
                               app=aid, instance=res["container"], database=res["db"])
                record(rel, "sql", res["note"], app=aid,
                       instance=res["container"], database=res["db"])

        dormant = {}
        for root, aid in installed_apps():
            if scope_app or aid in {i for _r, i in apps}:
                continue
            m = app_manifest(root, aid)
            # …with the old volume of a store whose move is not proven (DGO-2019): a disabled app never ran the move
            for v in ((m.get("data") or {}).get("volumes") or []) + datamoves.carried_volumes(REPO, aid, m):
                dormant.setdefault(v, aid)
        for vol, aid in sorted(dormant.items()):
            if vol in handled or f"volumes/{vol}.tar.gz" in man["artifacts"]:
                continue
            if not _volume_exists(vol):
                continue
            rel = f"volumes/{vol}.tar.gz"
            if done(rel):
                say(f"  = {rel} (already complete)")
                continue
            say(f"  ~ {vol}: {aid} is installed but disabled — its data is kept, so it is archived")
            part = out / (rel + ".part")
            _tar_volume(vol, part)
            part.rename(out / rel)
            record(rel, "volume-dormant", aid, app=aid)

        # 3. stateful host binds (the part a folder zip DOES carry — recorded so a restore can
        #    verify it, and so `--out` outside the repo is still a complete archive)
        (out / "binds").mkdir(exist_ok=True)
        # ONCE. stateful_binds() walks every writable bind to size it — 91s here, most of it a
        # 16.5GB tree over /mnt/c — and this used to call it twice in two adjacent lines, doubling
        # the slowest step of the whole export to build a dict it then rebuilt.
        _decl_paths, _located = path_owner_map()
        if scope_app:
            # DECLARED paths only, and no compose config at all when there are none. An app-scoped
            # export of an app that owns no bind was otherwise paying the full discovery cost to
            # produce an empty list: `notifications` (one 88KB volume) sat in this step for minutes.
            # Declaration is the right contract for a per-app archive anyway — location-based
            # attribution is informative in the inventory, not a claim to move data on.
            binds_found = {p: None for p in (_decl_paths if _decl_paths else {})
                           if _decl_paths.get(p) == scope_app and (REPO / p).is_dir()}
            # …and a store that was a FOLDER (`path:`) whose move is not proven here still lives in that folder (an
            # office that waits: the HP's C:) — carried from there, as a store's old volume is (DGO-2019; the reader of
            # apitools': its signer would otherwise be left out of the archive without a word)
            for root_, aid_ in apps:
                if aid_ == scope_app:
                    for p in datamoves.carried_folders(REPO, aid_, app_manifest(root_, aid_)):
                        if (REPO / p).is_dir():
                            binds_found.setdefault(p, None)
            bind_owner = {p: scope_app for p in binds_found}
        else:
            cfg = compose_config()
            binds_found = stateful_binds(cfg)
            bind_owner = {p: owner_of_path(p, _decl_paths, _located)[0] for p in binds_found}
        # a store a hook claims (`SKIPVOL <its old volume>`): its own backup carries it — a database it dumps, a queue it
        # leaves out on purpose — so the folder the volume moved to (DGO-2019) is never tarred live beside the dump,
        # and said where it is, as its volume was (step 2)
        claimed = datamoves.claimed_folders({aid: app_manifest(root, aid) for root, aid in apps}, handled)
        for relpath, nbytes in sorted(binds_found.items()):
            if scope_app and bind_owner.get(relpath) != scope_app:
                continue
            claim = next((c for c in claimed if relpath == c or relpath.startswith(c + "/")), None)
            if claim:
                # a tarball of it an earlier run into this directory left (before the claim) goes: resumability
                # keeps what is on disk, and a restore would unpack it over the dump's database (its second reader)
                stale = "binds/" + relpath.replace("/", "__") + ".tar.gz"
                if man["artifacts"].pop(stale, None) is not None:
                    save()
                (out / stale).unlink(missing_ok=True)
                man["artifacts"].setdefault("binds/" + relpath.replace("/", "__") + ".HANDLED", {
                    "kind": "skipped", "bytes": 0, "sha256": "", "app": claimed[claim],
                    "note": f"{relpath}: claimed by {claimed[claim]}'s own hooks/backup"})
                save()
                say(f"  - {relpath}: claimed by {claimed[claim]}'s own hooks/backup — not tarred here")
                continue
            if a.mode == "config" and relpath in CONFIG_MODE_BIND_EXCLUDES:
                say(f"  - {relpath}: not carried in config mode "
                    f"({CONFIG_MODE_BIND_EXCLUDES[relpath]})")
                continue
            excl = ([e for e in CONFIG_MODE_BIND_EXCLUDES if e.startswith(relpath + "/")]
                    if a.mode == "config" else [])
            # …and a claimed store INSIDE a bind above it (data/<app> beside data/<app>/db) is left out of that one too
            excl += [c for c in claimed if c.startswith(relpath + "/")]
            rel = "binds/" + relpath.replace("/", "__") + ".tar.gz"
            if done(rel):
                say(f"  = {rel} (already complete)")
                continue
            part = out / (rel + ".part")
            _tar_dir_as_root(REPO / relpath, part,
                             [e[len(relpath) + 1:] for e in excl])
            part.rename(out / rel)
            record(rel, "bind", relpath + (f"  (excluded: {', '.join(excl)})" if excl else ""),
                   app=bind_owner.get(relpath))

        # 4. the key material a git clone does not carry.
        #
        # NOT in --app scope. These are the DEPLOYMENT's secrets — .env holds every password on the
        # host — and a per-app archive is the thing you hand to another deployment. Shipping the
        # whole estate's credentials inside "just the drive app" would be a leak disguised as a
        # convenience. The cost is stated at the end of the run rather than left to be discovered:
        # anything encrypted with a platform key travels unreadable without that key.
        carried = []
        if scope_app:
            say("secrets: NOT included in an app-scoped archive (they belong to the deployment, "
                "not the app). Data encrypted with a platform key needs that key carried "
                "separately and deliberately.")
        for rel in (SECRET_PATHS if not scope_app else []):
            sec = out / "secrets"
            sec.mkdir(exist_ok=True)
            os.chmod(sec, 0o700)
            src = carried_source(rel)          # a link is read at its target; a dangling one fails
            if src is None:
                continue
            dst = sec / rel.replace("/", "__")
            if src.is_dir():
                # APPEND, do not with_suffix(): `.credentials-state` looks like a suffix to pathlib,
                # so with_suffix() produced `platform-base__n8n__.tar.gz` — a name that collides with
                # any other dotted directory under the same app.
                dst = dst.parent / (dst.name + ".tar.gz")
                _tar_dir_as_root(src, dst)
            else:
                # Through a container, same reason as _tar_dir_as_root: traefik's acme.json is
                # root-owned 0600 (it must be — traefik REFUSES its ACME account otherwise and
                # silently falls back to a self-signed cert), so the operator's own process cannot
                # read the file at all. A host-side copy fails with EACCES on the one artifact that
                # carries every issued TLS private key.
                #
                # The copy is chowned back to the invoking user inside the same container. `cp -p`
                # alone reproduced the 0600 root:root mode in the archive, and then the export died
                # computing its own checksum — a backup this process could write and could not read.
                sh(["docker", "run", "--rm", "-v", f"{src.parent}:/src:ro", "-v", f"{dst.parent}:/out",
                    "alpine", "sh", "-c",
                    f"cp /src/{src.name} /out/{dst.name} && chmod 600 /out/{dst.name} && "
                    f"chown {os.getuid()}:{os.getgid()} /out/{dst.name}"], env=docker_env())
            # Best-effort: a tar produced through a container is owned by root, so an unprivileged
            # operator cannot chmod it. The confidentiality guarantee here is the 0700 on the
            # enclosing directory, not the mode of each file — and failing the whole export on a
            # cosmetic chmod would be the wrong trade.
            try:
                os.chmod(dst, 0o600)
            except PermissionError:
                pass
            carried.append(rel)
            record(f"secrets/{dst.name}", "secret", rel, app="_platform")
        man["secrets_carried"] = carried
        save()

        # 5. the office's own declarations a clone does not bring (DECLARATION_PATHS). The
        # deployment's, like the secrets, so not in --app scope. Read through a container like the
        # secrets: the outbox is written by project-pln, which runs as root.
        declared_carried = []
        for rel in (DECLARATION_PATHS if not scope_app else []):
            src = carried_source(rel)
            if src is None:
                continue
            ddir = out / "declarations"
            ddir.mkdir(exist_ok=True)
            dst = ddir / rel.replace("/", "__")
            if src.is_dir():
                dst = dst.parent / (dst.name + ".tar.gz")
            # Written whole under `.part` and renamed, like every other artifact (RESUMABLE above):
            # a run cut short never leaves half a state file recorded as the office's.
            part = dst.parent / (dst.name + ".part")
            if src.is_dir():
                _tar_dir_as_root(src, part)
            else:
                # `cp -p`: the mode travels with the file (a declaration keeps its mode on import).
                sh(["docker", "run", "--rm", "-v", f"{src.parent}:/src:ro", "-v", f"{dst.parent}:/out",
                    "alpine", "sh", "-c",
                    f"cp -p /src/{src.name} /out/{part.name} && "
                    f"chown {os.getuid()}:{os.getgid()} /out/{part.name}"], env=docker_env())
            part.rename(dst)
            declared_carried.append(rel)
            record(f"declarations/{dst.name}", "declaration", rel, app="_platform")
        man["declarations_carried"] = declared_carried
        save()

    finally:
        if stopped:
            say(f"restarting {len(stopped)} writer(s)")
            run(["docker", "start"] + stopped, env=docker_env())

    # 6. what on this engine NO installed app declares. Not carried (there is no owner to say what it
    # is or how to restore it), but named in the run and in the manifest, so an archive never reads as
    # "everything" while a volume of data sits beside it. After the writers are back (it adds up to
    # 330 s of docker questions, none of which a quiesced office should wait for), and a REPORT only:
    # a docker that does not answer it is said in the manifest and fails nothing that was carried.
    if not scope_app:
        try:
            rows, anon = undeclared_volumes(engine_volumes(), set(declared_volumes(installed_apps())),
                                            project_name())
            man["undeclared_volumes"] = rows
            man["anonymous_volumes"] = anon["count"]
            man.pop("undeclared_volumes_error", None)
            for row in rows:
                say(f"  ! {row['name']} ({row['size'] or 'size unknown'}, project "
                    f"{row['project'] or 'none'}): no installed app declares it — NOT in this archive")
            if anon["count"]:
                say(f"  ! {anon['count']} anonymous volume(s) — NOT in this archive")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            # a resumed run's earlier list is not this run's answer
            man.pop("undeclared_volumes", None)
            man.pop("anonymous_volumes", None)
            man["undeclared_volumes_error"] = f"{type(e).__name__}: {e}"[:300]
            say(f"  ! could not list this engine's volumes to name the undeclared ones: "
                f"{man['undeclared_volumes_error']}")
        save()

    # PRUNE entries whose file is not on disk.
    #
    # The manifest is carried across runs so an interrupted export can resume, and that memory has a
    # cost: an artifact this run no longer produces stays recorded forever. It happened immediately —
    # ownership of the auth/storage dump moved from platform-base/postgres to apps/supabase, and the
    # next `bbox import` failed with "missing artifact apps/postgres/supabase-auth-storage.dump"
    # against a perfectly complete archive.
    #
    # Pruning is safe here and only here: control reaches this line only after every phase completed,
    # so anything recorded-but-absent was NOT produced this run and does not belong in the archive.
    # It is still reported — a quietly shrinking backup is the thing this whole file exists to
    # prevent.
    gone = [rel for rel, e in man["artifacts"].items()
            if e["kind"] != "skipped" and not (out / rel).exists()]
    for rel in gone:
        del man["artifacts"][rel]
    if gone:
        say(f"pruned {len(gone)} stale manifest entr(ies) from an earlier run: {', '.join(gone)}")

    total = sum(e["bytes"] for e in man["artifacts"].values())
    man["total_bytes"] = total
    save()
    say(f"DONE  {len(man['artifacts'])} artifact(s), {total/1e6:.1f} MB total")
    say(f"      {out}")
    print()
    # The handling advice DIFFERS by scope, and getting it wrong is not cosmetic: an app-scoped
    # archive carries no .env, so telling the operator it "holds .env in clear" would have them
    # treat a shareable artifact as toxic — and, worse, the same sentence on the day they DO take a
    # full export would read as boilerplate they have already learned to ignore.
    if scope_app:
        print(f"  Scope                  : app '{scope_app}' only — its declared volumes, paths and tables")
        print("  NOT in this archive    : the deployment's secrets (.env, keys, certs). Anything")
        print("                           encrypted under a platform key restores unreadable unless")
        print("                           you carry that key across deliberately and separately.")
        print()
        print(f"  On the target machine:  ./bbox data import <dir> --app {scope_app}")
    else:
        print("  Travels IN the archive : " + ", ".join(carried + declared_carried))
        if man.get("undeclared_volumes") or man.get("anonymous_volumes"):
            print(f"  NOT in the archive     : {len(man.get('undeclared_volumes') or [])} volume(s) no app "
                  f"declares, {man.get('anonymous_volumes') or 0} anonymous (named above and in the manifest)")
        print("  Travels in the FOLDER  : source tree, apps/*/storage, apps/*/logs (also archived above)")
        print("  Must be carried by YOU : nothing — but the archive holds .env in clear. Move it over a")
        print("                           channel you trust, and delete it from the source machine when")
        print("                           the restore is verified.")
        print()
        print("  On the new machine:  unzip → ./bbox import <dir> → ./bbox run")
    return 0


# ── import ──────────────────────────────────────────────────────────────────────────────────────

def _untar_volume(vol, src: pathlib.Path):
    full = f"{project_name()}_{vol}"
    sh(["docker", "volume", "create", full], env=docker_env())
    sh(["docker", "run", "--rm", "-v", f"{full}:/v", "-v", f"{src.parent}:/in:ro",
        "alpine", "sh", "-c",
        f"rm -rf /v/* /v/.[!.]* 2>/dev/null; tar xzf /in/{src.name} -C /v"], env=docker_env())


def carried_artifact(kind, note):
    """The one artifact name the export gives a carried path: `secrets/<a__b>` or
    `declarations/<a__b>`, plus `.tar.gz` for a tree. Returns the two names a manifest may use."""
    base = ("secrets/" if kind == "secret" else "declarations/") + note.replace("/", "__")
    return {base, base + ".tar.gz"}


def carried_skips(artifacts):
    """{artifact: why} for the secrets and declarations that import must NOT write.

    `note` is the archive's word for where a carried file goes, and import writes REPO/<note>. An
    archive is also what a linked office hands this one (pull.py), so a note of `scripts/dc` or
    `../x` would have been written into the checkout. Only a path this archiver itself carries
    (SECRET_PATHS for a secret, DECLARATION_PATHS for a declaration), under the artifact name the
    export gives it, is a slot. Anything else is left out by name, never written. It is not a refusal
    of the whole archive: an archive from before a path moved (n8n's credential state lived under
    platform-base/ until DGO-477) still restores everything else.
    """
    allowed = {"secret": set(SECRET_PATHS), "declaration": set(DECLARATION_PATHS)}
    skips = {}
    for rel, e in artifacts.items():
        kind, note = e.get("kind"), e.get("note") or ""
        if kind not in allowed:
            continue
        if note not in allowed[kind]:
            skips[rel] = f"{note!r} is not a path this archiver carries as a {kind}"
        elif rel not in carried_artifact(kind, note):
            skips[rel] = f"a {kind} for {note!r} must be named {sorted(carried_artifact(kind, note))[0]}"
    return skips


#: a volume's short name as an app declares it — nothing that could leave docker's `-v <project>_<name>:/v`
#: or the helper's `tar xzf /in/<name>.tar.gz`
_VOLUME_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def writable_binds(cfg):
    """The checkout directories this office's compose mounts read-write — what an export carries as
    binds (stateful_binds), named without walking a single file."""
    out = set()
    for svc in (cfg.get("services") or {}).values():
        for m in svc.get("volumes") or []:
            if m.get("type") != "bind" or m.get("read_only"):
                continue
            src = (m.get("source") or "").replace("\\", "/")
            if not src or src.startswith(SKIP_BIND_PREFIX):
                continue
            try:
                rel = pathlib.Path(src).resolve().relative_to(REPO).as_posix()
            except ValueError:
                continue
            if rel not in ("", "."):
                out.add(rel)
    return out


def restore_skips(artifacts, cfg):
    """{artifact: why} for the binds and volumes import must NOT write (DGO-1510).

    carried_skips' rule, for the two kinds that are unpacked as ROOT: a bind's `note` is the directory
    REPO/<note> its tree is unpacked over (through a container), a volume's file name is the volume
    emptied and refilled. Both are the archive's words, and an archive is also what a linked office hands
    this one (pull.py): a note of `../../etc` or `apps/x/../../etc` (which a prefix match takes for app
    x's) would have been unpacked over the machine. So only what THIS office would carry itself is a
    slot: a directory its compose mounts read-write, or a path an installed app declares (data.paths),
    under the artifact name the export gives it; a volume an installed app here declares (data.volumes,
    enabled or not), by a plain name. Anything else is left out by name, never written — the rest of the
    archive still restores.

    The same for the SQL an app-scoped archive carries (`sql`, `sql-functions`: pg_restore --clean, and the
    archive's own SQL run by psql): only into a database the app it is filed under declares HERE (data.sql).

    Known limit: a bind of an app that is installed but NOT enabled here, and that no app declares in
    data.paths, is in no compose config this office renders, so it is skipped by name (DGO-1510 slice 2:
    data.paths as the bind contract, with its gate).
    """
    binds, volumes, sqls = None, None, None
    carried = SECRET_PATHS + DECLARATION_PATHS
    skips = {}
    for rel, e in artifacts.items():
        kind = e.get("kind")
        if kind == "bind":
            if binds is None:
                owner, _located = path_owner_map()
                binds = writable_binds(cfg) | set(owner)
                # the folder a store came from (`path:`, DGO-2019) is its app's own, as its old volume is: a backup of
                # an office that still ran from it carries it, and the next `bbox run` here moves it into the folder —
                # or, where the store moved here and was written since, decides a CONFLICT, as for an old volume
                for root, aid in installed_apps():
                    binds |= set(datamoves.old_folders(app_manifest(root, aid)))
            raw = (e.get("note") or "").split("  ")[0]
            p = pathlib.PurePosixPath(raw)
            norm = p.as_posix()
            if not raw or p.is_absolute() or ".." in p.parts or norm in ("", "."):
                skips[rel] = f"{raw!r} is not a path inside the checkout"
            elif norm not in binds:
                skips[rel] = f"{norm!r} is not a directory this office mounts read-write or an app declares"
            elif rel != "binds/" + norm.replace("/", "__") + ".tar.gz":
                skips[rel] = f"a bind for {norm!r} must be named binds/{norm.replace('/', '__')}.tar.gz"
            elif any(norm == c or norm.startswith(c + "/") for c in carried):
                skips[rel] = f"{norm!r} is a carried secret or declaration, installed by its own rule"
            elif (REPO / norm).exists() and not (REPO / norm).is_dir():
                # a single-file mount (a postgres init .sql, a password file): a tree is never unpacked over it
                skips[rel] = f"{norm!r} is a file here, not a directory"
        elif kind in ("sql", "sql-functions"):
            if sqls is None:
                sqls = {(aid, (decl or {}).get("database")) for aid, decl in app_sql_decls(installed_apps())}
            if (e.get("app"), e.get("database")) not in sqls:
                skips[rel] = (f"no app installed here declares the database {e.get('database')!r} "
                              f"for {e.get('app')!r} (data.sql)")
        elif kind in ("volume", "volume-dormant"):
            if volumes is None:
                volumes = set()
                for root, aid in installed_apps():
                    m = app_manifest(root, aid)
                    for v in ((m.get("data") or {}).get("volumes") or []):
                        volumes.add(v if isinstance(v, str) else (v or {}).get("name"))
                    # an old volume of a store now in data/<app>/ (DGO-2019): a backup of an office that still ran
                    # from it carries it, and the next `bbox run` moves it into the folder
                    volumes.update(datamoves.old_volumes(m))
            r = pathlib.PurePosixPath(rel)
            vol = r.name[:-len(".tar.gz")] if r.name.endswith(".tar.gz") else ""
            if r.parent.as_posix() != "volumes" or not _VOLUME_NAME_RE.fullmatch(vol):
                skips[rel] = "not a volume archive by the name the export gives one (volumes/<name>.tar.gz)"
            elif vol not in volumes:
                skips[rel] = f"no app installed here declares the volume {vol!r}"
    return skips


def _extract_as_root(src: pathlib.Path, dest: pathlib.Path):
    """Unpack a carried tree at `dest` (inside the checkout) through a container, as the binds are:
    a tree a root container wrote (the project-pln outbox) cannot be re-created by the operator's own
    tar, and a `.state/` the operator cannot write would fail the import halfway, after the secrets.
    Only the nearest directory that exists above `dest` is mounted, never the whole checkout. The
    path and the file name are the ones carried_skips() admits."""
    base = dest.parent
    while not base.exists() and base != REPO:
        base = base.parent
    rest = dest.relative_to(base).as_posix()
    sh(["docker", "run", "--rm", "-v", f"{base}:/p", "-v", f"{src.parent}:/in:ro", "alpine",
        "sh", "-c", f"mkdir -p '/p/{rest}' && tar xzf '/in/{src.name}' -C '/p/{rest}'"],
       env=docker_env())


def install_carried(src: pathlib.Path, note: str, secret: bool):
    """Put one carried file or tree (a secret or a declaration) at REPO/<note>.

    Into an EMPTY slot only. An occupied one is kept, and the archive's copy goes BESIDE it as
    `<name>.from-archive` (see cmd_import's secrets step for why it is never written over). Returns
    that side path, repo-relative, or None when the slot was empty and the copy is now in place. A
    secret file is left 0600. A declaration keeps its own mode: the console rewrites the state file,
    and a 0600 one it cannot read is an office that cannot change its apps. A secret tree is unpacked
    by the operator's tar, as it always was; a declaration tree through a container.
    """
    target = REPO / note
    target.parent.mkdir(parents=True, exist_ok=True)
    tree = src.name.endswith(".tar.gz")

    def unpack(dest):
        if secret:
            dest.mkdir(parents=True, exist_ok=True)
            sh(["tar", "xzf", str(src), "-C", str(dest)])
        else:
            _extract_as_root(src, dest)

    if target.exists() or target.is_symlink():
        side = target.parent / (target.name + ".from-archive")
        if tree:
            unpack(side)
        else:
            shutil.copy2(src, side)
        return side.relative_to(REPO).as_posix()
    if tree:
        unpack(target)
    else:
        shutil.copy2(src, target)
        if secret:
            os.chmod(target, 0o600)
    return None


def _assert_app_owns(aid, artifacts):
    """REFUSE an app-scoped restore that reaches outside what THIS office says the app owns.

    Every artifact names its own target — a volume in its file name, a directory in `note`, a
    database in `database` — and says which app it belongs to. Both are the ARCHIVE's words. An
    app-scoped archive is the thing one office hands another (a move pulls it over the link), so
    without this a manifest that filed `volumes/<the vault's volume>.tar.gz` under `drive` would
    have that volume emptied and replaced by `import --app drive`; a `bind` entry would be unpacked
    over any directory of the checkout it cared to name. The owner of "which stores are this app's"
    is the app's manifest HERE, by the same attribution the export uses.
    """
    root = next((r for r, i in installed_apps() if i == aid), None)
    if root is None:
        raise SystemExit(f"[archive] no app '{aid}' is installed here — nothing of it can be restored")
    m = app_manifest(root, aid)
    data = m.get("data") or {}
    volumes = {v if isinstance(v, str) else (v or {}).get("name") for v in data.get("volumes") or []}
    volumes |= set(datamoves.old_volumes(m))            # its stores' old volumes are its own too (DGO-2019)
    databases = {d.get("database") for d in data.get("sql") or []}
    owner, located = path_owner_map()
    foreign = []
    for rel, e in sorted(artifacts.items()):
        kind = e.get("kind")
        if kind in ("volume", "volume-dormant"):
            ok = (pathlib.PurePosixPath(rel).parent.as_posix() == "volumes"
                  and pathlib.PurePosixPath(rel).name[:-len(".tar.gz")] in volumes)
        elif kind == "bind":
            ok = owner_of_path((e.get("note") or "").split("  ")[0], owner, located)[0] == aid
        elif kind in ("sql", "sql-functions"):
            ok = e.get("database") in databases
        elif kind == "app-backup":
            ok = rel.startswith(f"apps/{aid}/") and ".." not in pathlib.PurePosixPath(rel).parts
        else:
            ok = kind == "skipped"
        if not ok:
            foreign.append(f"    {rel}  ({kind})")
    if foreign:
        raise SystemExit(
            f"[archive] REFUSING: this archive files things under '{aid}' that are not {aid}'s here.\n"
            + "\n".join(foreign) +
            f"\n  {aid} declares volumes {sorted(v for v in volumes if v) or 'none'} and databases "
            f"{sorted(d for d in databases if d) or 'none'} in its app.json on this office; an "
            "app-scoped restore writes to those and to nothing else.")


def cmd_import(a):
    d = pathlib.Path(a.dir) if a.dir else None
    if d is None:
        cands = sorted((REPO / "exports").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
        if not cands:
            raise SystemExit("[archive] no archive found under exports/ — pass a directory")
        d = cands[-1].parent
    d = d.resolve()
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man.get("format_version") != FORMAT_VERSION:
        raise SystemExit(f"[archive] manifest format {man.get('format_version')} != {FORMAT_VERSION}")

    # --app narrows the restore to one app's artifacts. It works on a whole-deployment archive too:
    # "put drive back the way it was last Tuesday" without touching anything else on the host.
    only = getattr(a, "app", None)
    if only:
        # what the archive files under the app — and, in a WHOLE-office archive, every volume the app OWNS here
        # whatever the archive filed it under: one made before data.shares filed a volume two apps declared under
        # either of them (cad_projects under cad-api), and the owner's restore must still find it (DGO-1510). Never
        # from an archive of ANOTHER app: its copy of the owner's volume came without the owner's database, and
        # restoring it alone would roll the owner back half-way. _assert_app_owns holds both to what X declares here.
        whole = not (man.get("scope") or {}).get("app")
        own_root = next((r for r, i in installed_apps() if i == only), None)
        own = app_manifest(own_root, only) if own_root else {}
        owned = (set(((own.get("data") or {}).get("volumes") or [])) | set(datamoves.old_volumes(own))) \
            if own_root and whole else set()                      # …and the old volumes its moved stores came from
        keep = {r: e for r, e in man["artifacts"].items()
                if e.get("app") == only or (volume_of(r, e) and volume_of(r, e) in owned)}
        if not keep:
            owners = sorted({e.get("app") for e in man["artifacts"].values() if e.get("app")})
            raise SystemExit(f"[archive] this archive holds nothing for '{only}'. It has: "
                             f"{', '.join(owners) or '(artifacts predate per-app tagging)'}")
        say(f"scope: app {only} — {len(keep)} of {len(man['artifacts'])} artifact(s)")
        man["artifacts"] = keep
    # a volume the scoped app only SHARES is its owner's, restored with its owner alone (DGO-1510): an archive made
    # before data.shares carried n8n_storage with any-concurrency, and importing it wrote n8n's data back to that day
    scoped_app = only or (man.get("scope") or {}).get("app")
    if scoped_app:
        man["artifacts"], dropped = drop_shares(scoped_app, man["artifacts"])
        for rel, owner in dropped:
            say(f"  ! {rel} NOT restored: {owner} owns it, not {scoped_app} — it comes back with "
                f"{owner}'s own restore (an archive of {owner}, or of the whole office)")
    # An archive whose every artifact of the app was a share restores nothing, and says so above — as the new
    # export of an app that only shares (a marker alone) does: an app move from an office on the code before
    # data.shares must not stop on what is the owner's to carry (the second reader).
    if only:
        _assert_app_owns(only, man["artifacts"])

    say(f"restoring {d}")
    say(f"  from deployment '{man['deployment_name']}' (project '{man['compose_project']}')"
        f" mode={man['mode']} quiesced={man['quiesced']}")
    say(f"  into  deployment '{read_env('DEPLOYMENT_NAME')}' (project '{project_name()}')")
    # "The deployment it came from" is the same project ON THE SAME ENGINE. An archive that names its
    # engine and names a different one came from another machine, where an equal project name is a
    # coincidence of two clone directories; one that names none (written before the field existed)
    # is judged by the project name alone, as before.
    here = engine_id()
    same_engine = not man.get("engine") or not here or man["engine"] == here
    if man["compose_project"] == project_name() and same_engine and not a.force:
        raise SystemExit(
            "[archive] REFUSING: this archive's compose project is the same as this checkout's "
            f"('{project_name()}'), so a restore would overwrite the volumes of the deployment it "
            "came from. The project name is the CLONE DIRECTORY BASENAME, not DEPLOYMENT_NAME — "
            "restore into a differently-named directory, or pass --force if you really mean to "
            "overwrite in place.")

    # Where carried files may go is decided before anything is written (carried_skips).
    skips = carried_skips(man["artifacts"])
    for rel, why in sorted(skips.items()):
        say(f"  ! {rel} NOT installed: {why}")

    # THE STATE FILE, before compose_config() below. On a clone with no `.generated/`, compose_config
    # renders it, and the render CREATES platform.state.yaml from the default. The archive's state file
    # would then always find its slot taken, land beside it, and the office would come up with the
    # default apps. So it is checked by its sha256 and put into its empty slot first. It writes into
    # THIS checkout only, so it cannot hurt another deployment (the one thing the isolation check
    # exists for), and the check then asks about the archive's own apps rather than the default's.
    # The other declarations (the outbox) wait for the checks: a refused import must leave no unsent
    # writes behind to be sent.
    def declarations(early):
        for rel, e in sorted(man["artifacts"].items()):
            if e["kind"] != "declaration" or rel in skips or (e["note"] in STATE_FIRST) != early:
                continue
            p = d / rel
            if not p.exists() or sha256_size(p)[0] != e["sha256"]:
                raise SystemExit(f"[archive] {'missing' if not p.exists() else 'checksum mismatch on'} "
                                 f"artifact {rel}")
            side = install_carried(p, e["note"], secret=False)
            if side:
                say(f"  declaration KEPT (target already has one) -> {side}")
            else:
                say(f"  declaration -> {e['note']}")
                if e["note"] == ".state/outbox":
                    say("    its unsent Plane writes are now THIS office's to send; if the office the "
                        "archive came from still runs, it sends them too")

    declarations(early=True)

    # NETWORK ISOLATION FIRST, before integrity, before secrets, before anything else is written.
    # This is the only check whose failure damages a deployment OTHER than the target, so it is the
    # only one that must run before the driver has done a single thing. See assert_network_isolation.
    scope = None
    if only:
        scope = set(sh([sys.executable, "platform/manager/reconcile.py", "compose-services",
                        "--app", only]).split())
    assert_network_isolation(compose_config(), allow_shared=a.allow_shared_network, services=scope)

    # integrity next: a restore that starts and then finds a truncated artifact has already
    # destroyed the target.
    for rel, e in sorted(man["artifacts"].items()):
        if e["kind"] == "skipped":
            continue
        p = d / rel
        if not p.exists():
            raise SystemExit(f"[archive] missing artifact {rel}")
        digest, size = sha256_size(p)
        if digest != e["sha256"]:
            raise SystemExit(f"[archive] checksum mismatch on {rel}")
    say(f"  {len([e for e in man['artifacts'].values() if e['kind'] != 'skipped'])} artifact(s) verified")

    # ── secrets ─────────────────────────────────────────────────────────────────────────────────
    # BEFORE anything else, because an n8n dump restored without the matching N8N_ENCRYPTION_KEY
    # produces credential rows that exist and cannot be decrypted — and because authentik cannot
    # decrypt its own provider secrets without AUTHENTIK_SECRET_KEY.
    #
    # AND NEVER OVER AN EXISTING FILE. `.env` does not only hold secrets; it holds this deployment's
    # IDENTITY — DEPLOYMENT_NAME, DEPLOYMENT_DOMAIN, COMPANY_SLUG. Overwriting it would rewrite the
    # target's DEPLOYMENT_NAME to the SOURCE's, and every app restore hook that runs a moment later
    # resolves its container as `<svc>-${DEPLOYMENT_NAME}` from that same file. On a host running the
    # source deployment, the next line executed would be `drop database` against the LIVE one.
    #
    # So: install into an empty slot (the fresh-machine case, which is the whole point), and beside
    # an occupied one (the restore-into-a-second-deployment case, which is how anyone tests this).
    #
    # (The office's declarations follow the same rule, and were put in place above, before the
    # compose config was rendered.)
    deferred = []
    for rel, e in sorted(man["artifacts"].items()):
        if e["kind"] != "secret" or rel in skips:
            continue
        side = install_carried(d / rel, e["note"], secret=True)
        if side:
            if e["note"] == ".env":            # what the key check below points the operator at
                deferred.append((e["note"], side))
            say(f"  secret KEPT (target already has one) -> {side}")
        else:
            say(f"  secret -> {e['note']}")
    declarations(early=False)

    # ── pre-flight: the keys the archive was encrypted under must be the keys in force here ──────
    # This is the single check that turns this feature's worst failure mode — a restore that reports
    # success and yields credentials nobody can decrypt — into a refusal. It runs AFTER the secrets
    # step (so a fresh machine has just been given the right .env) and BEFORE any app restore hook
    # (so nothing has been dropped yet).
    want = ((man.get("facts") or {}).get("n8n") or {}).get("encryption_key_fp")
    if want:
        have_key = read_env("N8N_ENCRYPTION_KEY")
        have = hashlib.sha256(have_key.encode()).hexdigest()[:16] if have_key else ""
        if have != want:
            msg = (f"[archive] N8N_ENCRYPTION_KEY MISMATCH — archive fp={want} target fp={have or 'absent'}.\n"
                   f"          Restoring now would give you all {man['facts']['n8n'].get('credentials')} "
                   f"credential rows and NOT ONE usable credential: n8n stores the secrets encrypted\n"
                   f"          under that key, and n8n reports the failure per-execution ('bad decrypt'), "
                   f"not at restore time.\n")
            if deferred:
                msg += ("          The archive's .env was NOT installed because this checkout already had "
                        "one. Take the key from\n          " +
                        ", ".join(s for _, s in deferred) + "\n")
            if not a.force:
                raise SystemExit(msg + "          Fix the key, or pass --force to restore anyway.")
            say(msg + "  --force given: continuing with a knowingly undecryptable credential set.")
        else:
            say(f"  encryption key fingerprint matches ({want}) — credentials will decrypt")

    # Where the binds, volumes and SQL may go is decided before any of them is written (restore_skips) —
    # against the compose config rendered NOW, with the archive's .env and state in place: a bind whose
    # source comes from .env (`${WHATSAPP_DATA_DIR:-./data}`) is judged by this office's value, not the default.
    rskips = restore_skips(man["artifacts"], compose_config())
    for rel, why in sorted(rskips.items()):
        say(f"  ! {rel} NOT restored: {why}")
    # …and each allowed bind's REAL directory is pinned before the first tree is unpacked: `docker -v` follows a
    # link, so a link one bind's tree planted where another bind goes would aim that one's root unpack elsewhere
    pinned = {rel: os.path.realpath(REPO / e["note"].split("  ")[0])
              for rel, e in man["artifacts"].items() if e["kind"] == "bind" and rel not in rskips}

    for rel, e in sorted(man["artifacts"].items()):
        if e["kind"] != "bind" or rel in rskips:
            continue
        relpath = e["note"].split("  ")[0]
        target = REPO / relpath
        if os.path.realpath(target) != pinned[rel]:
            say(f"  ! {rel} NOT restored: {relpath} now leads to {os.path.realpath(target)} "
                f"(a link appeared there during this restore)")
            continue
        target.mkdir(parents=True, exist_ok=True)
        # Through a container, for the mirror of the reason _tar_dir_as_root exists: these trees
        # contain root-owned files, and an unprivileged host `tar -x` cannot restore their ownership
        # — it would hand apitools a cache it can read and a directory it cannot write.
        sh(["docker", "run", "--rm", "-v", f"{target}:/dst", "-v", f"{(d / rel).parent}:/in:ro",
            "alpine", "tar", "xzf", f"/in/{pathlib.Path(rel).name}", "-C", "/dst"],
           env=docker_env())
        say(f"  bind -> {relpath}")

    # BOTH kinds. `volume-dormant` is the same tar of the same volume; the kind exists only to record
    # that its owning app was disabled when the archive was taken. Matching on "volume" alone here
    # would have exported those volumes faithfully and then silently declined to restore them —
    # a backup that passes every check and quietly drops the data of every disabled app.
    for rel, e in sorted(man["artifacts"].items()):
        if e["kind"] not in ("volume", "volume-dormant") or rel in rskips:
            continue
        vol = pathlib.Path(rel).name[:-len(".tar.gz")]
        _untar_volume(vol, d / rel)
        say(f"  volume -> {project_name()}_{vol}"
            + ("   (app was disabled at export; data restored)" if e["kind"] == "volume-dormant" else ""))

    # per-app SQL, written only by an --app export. pg_restore --clean so a re-import is idempotent;
    # --if-exists so the first import into an empty database does not fail on the drops.
    #
    # sql-functions BEFORE sql, hence the sort key rather than plain name order: the dump's CREATE
    # TRIGGER statements reference these functions, and postgres will not create a trigger whose
    # function is absent. Getting this order wrong yields a restore that holds every row and has
    # lost every trigger — and says nothing about it beyond a line of pg_restore noise.
    def _sql_first(item):
        return (0 if item[1]["kind"] == "sql-functions" else 1, item[0])

    for rel, e in sorted(man["artifacts"].items(), key=_sql_first):
        if e["kind"] not in ("sql", "sql-functions") or rel in rskips:
            continue
        container, dbname = e.get("instance") or "", e.get("database") or ""
        # The SOURCE container name will not exist on the target — DEPLOYMENT_NAME suffixes it — so
        # match on the service prefix (`supabase-db-oldhost` -> `supabase-db-newhost`), which is
        # what stays the same across machines.
        prefix = container.rsplit("-", 1)[0] if "-" in container else container
        cands = [(c, u) for c, u, _m in pg_instances() if c == container or c.startswith(prefix)]
        if not cands:
            raise SystemExit(f"[archive] {rel}: no postgres instance here matches '{container}'. "
                             f"Present: {', '.join(c for c, _u, _m in pg_instances()) or 'none'}")
        c, u = cands[0]
        if e["kind"] == "sql-functions":
            with open(d / rel, "rb") as fh:
                r = subprocess.run(["docker", "exec", "-i", c, "psql", "-U", u, "-d", dbname,
                                    "-v", "ON_ERROR_STOP=1", "-f", "-"],
                                   stdin=fh, capture_output=True, cwd=REPO, env=docker_env())
            if r.returncode != 0:
                raise SystemExit(f"[archive] restoring {rel} failed:\n"
                                 + (r.stderr or b"").decode("utf-8", "replace")[-800:])
            say(f"  sql-functions -> {c}/{dbname}  ({e.get('note')})")
            continue
        with open(d / rel, "rb") as fh:
            r = subprocess.run(["docker", "exec", "-i", c, "pg_restore", "-U", u, "-d", dbname,
                                "--clean", "--if-exists", "--no-owner"],
                               stdin=fh, capture_output=True, cwd=REPO, env=docker_env())
        # pg_restore exits non-zero on benign "does not exist" noise from --clean on a fresh target,
        # so the error text decides, not the code alone.
        err = (r.stderr or b"").decode("utf-8", "replace")
        fatal = [l for l in err.splitlines() if "error:" in l.lower() and "does not exist" not in l]
        if fatal:
            raise SystemExit(f"[archive] pg_restore {rel} failed:\n" + "\n".join(fatal[:10]))
        say(f"  sql -> {c}/{dbname}  ({e.get('note')})")

    # app-owned restores LAST: they need their containers, which need the volumes above.
    for root, aid in enabled_apps():
        if only and aid != only:
            continue
        hook = app_hook(root, aid, "restore")
        src = d / "apps" / aid
        if not hook or not src.is_dir():
            continue
        say(f"app {aid}: {hook.relative_to(REPO).as_posix()}")
        res = _run_hook(hook, [str(src), man["mode"]])
        before = man["facts"].get(aid, {})
        for k, v in sorted(res["facts"].items()):
            was = before.get(k)
            flag = "OK " if str(was) == str(v) else "DIFF"
            print(f"    {flag} {aid}.{k}: exported={was} restored={v}")
            if flag == "DIFF":
                man.setdefault("_diffs", []).append(f"{aid}.{k}: {was} -> {v}")

    diffs = man.get("_diffs") or []
    if diffs:
        say(f"{len(diffs)} FACT MISMATCH(ES) — the restore is NOT equivalent:")
        for x in diffs:
            print(f"    {x}")
        return 1
    say("DONE — every recorded fact matches. Now: ./bbox run")
    return 0


def cmd_verify(a):
    """Re-read the LIVE estate and diff it against a manifest's recorded facts."""
    d = pathlib.Path(a.dir).resolve()
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for root, aid in enabled_apps():
        hook = app_hook(root, aid, "facts")
        if not hook:
            continue
        res = _run_hook(hook, [])
        for k, v in sorted(res["facts"].items()):
            was = (man.get("facts", {}).get(aid) or {}).get(k)
            same = str(was) == str(v)
            bad += 0 if same else 1
            print(f"  {'OK ' if same else 'DIFF'} {aid}.{k}: manifest={was} live={v}")
    return 1 if bad else 0


def main():
    p = argparse.ArgumentParser(prog="bbox export|import")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("--mode", choices=("config", "full"), default="full",
                   help="full = everything incl. execution history and OCR caches; "
                        "config = the deployment without its history")
    e.add_argument("--out")
    e.add_argument("--quiesce", action="store_true",
                   help="stop every app's declared writers (data.writers) for the duration, for a cross-store "
                        "consistent snapshot (right for a migration, wrong for a live backup)")
    e.add_argument("--force", action="store_true", help="redo artifacts already present")
    e.add_argument("--app", metavar="ID",
                   help="export ONLY this app's declared stores, as a self-contained archive that "
                        "can be imported into a different deployment on its own")
    # `bbox export --verify DIR`, the form this file's header documents: bbox hands every word after `export` to
    # this parser, so the `verify` subcommand below had no door from bbox at all (issues/a-stranger-cannot-follow-…)
    e.add_argument("--verify", metavar="DIR",
                   help="export nothing: re-read the live estate and diff it against the manifest in DIR")
    e.set_defaults(fn=cmd_export)

    i = sub.add_parser("import")
    i.add_argument("dir", nargs="?")
    i.add_argument("--app", metavar="ID",
                   help="restore ONLY this app's artifacts out of the archive")
    i.add_argument("--force", action="store_true",
                   help="allow restoring over the deployment the archive came from")
    i.add_argument("--allow-shared-network", action="store_true",
                   help="permit joining a network another compose project is on. An outright ALIAS "
                        "collision is refused regardless — see assert_network_isolation.")
    i.set_defaults(fn=cmd_import)

    v = sub.add_parser("verify")
    v.add_argument("dir")
    v.set_defaults(fn=cmd_verify)

    a = p.parse_args()
    if a.cmd == "export" and a.verify is not None:
        # an empty DIR (`--verify "$DIR"` with DIR unset) must not fall through into a full export
        if not a.verify.strip():
            p.error("export --verify needs the directory of an export's manifest")
        if a.out or a.app or a.quiesce or a.force or a.mode != "full":
            p.error("export --verify reads the live estate against DIR's manifest; it takes no export option")
        a.dir, a.fn = a.verify, cmd_verify
    try:
        return a.fn(a)
    except RuntimeError as ex:
        print(f"[archive] error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
