#!/usr/bin/env python3
"""datahome — every app's state in the DGO folder's `data/<app>/`, and the move that puts it there (DGO-2019).

    python3 platform/manager/datahome.py plan [--json]       what each store of each enabled app is, and will be
    python3 platform/manager/datahome.py ensure [--dry-run]  before `up` (bbox run): move, seed, or keep waiting
    python3 platform/manager/datahome.py verify              after `up`: what moved this run is healthy and the same
    python3 platform/manager/datahome.py check [--json]      a running office: state in volumes or container layers

The owner, 2026-11-18: «All importent data of any dgo app should alwase be saved to local mapped drive drirectly into
dgo main folder/data/app-name … I want backup to simply need to copy that data folder and have all!! statfull data dgo
has created … move manually all the data to there so nothing lost and everything keeps working with the exact state».

A STORE is a host folder `data/<app>/<store>` an app's compose binds (`../../data/<app>/<store>:<target>`; a copy of
an app, `instances/<app>-<key>/`, binds `data/<app>-<key>/<store>`). Its app.json says, in `data.moved_from`, which
docker volume held those bytes before the standard: a compose volume by its key (the project's `<project>_<key>`), or
one compose never made — a hand-made container's — by its whole name, `external:<name>`. `ensure` decides each store,
in this order:

  READY  the folder holds data — it is the truth, nothing to do.
  MOVE   the folder is empty and the old volume holds data: stop the containers that use the volume, copy it into the
         folder (tar inside a helper container, as root: owners, modes, times and links kept), compare the two trees
         file by file (type, mode, owner, size, time, sha256), and write the ledger data/.moves/<app>/<store>.json.
         THE OLD VOLUME IS NEVER CHANGED OR REMOVED HERE: an update that is rolled back (follow) brings the office up
         on the old compose, on exactly the bytes it left. Removing a moved volume is a separate, later decision.
  SEED   the folder is new and no volume held it: it is filled with what the image ships at the mount's target, with
         the image's owners (what docker does for an empty named volume, and does not do for a bind). The image not
         here yet (built at the run's `up`): a store that was a volume waits on it — docker fills it from the image,
         owner included — and the next run moves it; one that was always a host folder is made empty, as before.
         Nothing at the target in the image: a store that was a volume is root:root 755, as docker's empty volume.
  WAIT   the store cannot move on this office yet — its DGO folder is on a filesystem that does not hold databases
         (WSL's drvfs on /mnt/c, 9p, a network or FUSE mount: the HP until DGO-1999 moves its folder), there is no
         room for a second copy, or a move failed. The store keeps running from its volume: `data/.moves/wait/<app>.yml`
         puts the volume back at the mount's target (compose merges a service's mounts by target), and every `dc`
         reads it while the app is compiled (scripts/lib.sh compose_args). Nothing on the office changes; the next
         run tries again.
  CONFLICT both the folder and the volume hold data and no ledger says which is newer, or the ledger says the store
         moved and its folder is empty now — never guessed: the store keeps running from its volume (what it ran on
         until now, as WAIT), and the run says so and fails.
A move that failed (its copy, its compare, or the check after `up`) is never tried again by itself: the store waits
on its volume until `./bbox data retry <app>` (each try stops the app and copies, and a volume the app writes on
would look new every run). Every decision is recorded in data/.moves/<app>/<store>.json (platform/manager/datamoves.py
reads it without the engine, for `waits` and for the backup, which carries a store's old volume until its move is
proven).

`verify` runs after `up` for what moved in this run: every container of the app that was healthy before the move is
healthy again (or running, where it has no healthcheck) and, where the app has `hooks/state` (lines `<name> <value>`),
it still holds what it held — a value that is not a number the same, a count above zero still above zero (same_state).
A store that fails goes back to its volume (WAIT, the volume untouched since the stop) and its services are printed
for the caller to bring up again.
"""
from __future__ import annotations

import argparse, datetime, hashlib, json, os, pathlib, re, subprocess, sys, time

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datamoves                                                        # noqa: E402 — the ledger, read by the backup too

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data"
LEDGER = DATA / ".moves"
#: One compose file per app whose stores wait on their volumes. Not in .generated/, which is the compiler's; and one
#: per app, so that compose_args reads it only while the app is compiled: a file naming a service that compose no
#: longer has would fail every command of the office.
WAIT = LEDGER / "wait"
ROOTS = ("platform-base", "apps", "instances")
HELPER = os.environ.get("DATAHOME_HELPER_IMAGE") or "alpine:3"
#: Filesystems a database's files must not live on: WSL's drvfs (/mnt/c, 9p underneath), a FUSE or a network mount,
#: a hypervisor's shared folder. `DGO_DATA_FS_OK=<type>[,<type>]` in .env admits one after it was proven on that office.
BAD_FS = {"9p", "v9fs", "drvfs", "fuse", "fuseblk", "fuse.sshfs", "fuse.osxfs", "fuse.grpcfuse", "cifs", "smb3", "smbfs",
          "nfs", "nfs4", "virtiofs", "vboxsf", "prl_fs", "vmhgfs", "fuse.vmhgfs-fuse"}
#: Room kept free beyond the copy itself.
SPARE = 1 << 30
#: …and on C: under WSL, the office's own disk floor there (scripts/lib.sh disk_floor_gb).
WSL_C_FLOOR = 20 << 30
#: `data.moved_from` names a volume compose never made by this prefix and its whole name (`external:tg_group_relay_state`)
EXTERNAL = datamoves.EXTERNAL
#: …and a host folder it was in before by this prefix, relative to the checkout (`path:apps/apitools/storage`)
PATH = datamoves.PATH


# ── docker ──────────────────────────────────────────────────────────────────────────────────────
def sh(args, *, input=None, timeout=3600, check=True):
    r = subprocess.run(args, input=input, capture_output=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args[:6]))}… exit {r.returncode}: "
                           f"{r.stderr.decode(errors='replace').strip()[-400:]}")
    return r


def helper(mounts, script, *args, input=None, timeout=3600):
    """Run `script` (with `args` as $1…) in a throwaway helper container — root, no network — with `mounts`
    [(source, target, ro)]: a volume and a host folder are read and written the same way, by the engine itself."""
    a = ["docker", "run", "--rm", "-i" if input is not None else "--init", "--network", "none", "--entrypoint", "sh"]
    for s, t, ro in mounts:
        a += ["-v", f"{s}:{t}{':ro' if ro else ''}"]
    return sh(a + [HELPER, "-c", script, "sh", *args], input=input, timeout=timeout)


#: Extended attributes ride no busybox tar (the helper's), and the manifest's `stat` sees none: storage-api keeps each
#: Drive object's content-type and cache-control as `user.supabase.*` attributes, and a copy without them serves every
#: file as an untyped download, while every count and every hash still agrees (the reader of Drive's bytes). So a
#: move also copies each entry's attributes and compares them, both trees, in a helper that can read them.
XATTR_HELPER = os.environ.get("DATAHOME_XATTR_IMAGE") or "python:3.12-alpine"
#: `list <root>`: one `path|name|sha256 of the value` per attribute, sorted; `copy <src> <dst>`: each entry's onto its
#: copy. Never past a link (its own attributes, if any, are the link's). A filesystem that has none lists none.
XATTRS = r"""
import hashlib, os, sys
sys.stdout.reconfigure(errors="surrogateescape")   # a name that is not UTF-8 is listed as it is, never a crash
def walk(root):
    yield "."
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            yield os.path.relpath(os.path.join(d, n), root)
def attrs(p):
    try:
        return {n: os.getxattr(p, n, follow_symlinks=False) for n in os.listxattr(p, follow_symlinks=False)}
    except OSError as e:
        if e.errno in (95, 61):                    # EOPNOTSUPP, ENODATA: none here
            return {}
        raise
if sys.argv[1] == "copy":
    for r in walk(sys.argv[2]):
        for n, v in attrs(os.path.join(sys.argv[2], r)).items():
            os.setxattr(os.path.join(sys.argv[3], r), n, v, follow_symlinks=False)
else:
    for r in sorted(walk(sys.argv[2])):
        for n, v in sorted(attrs(os.path.join(sys.argv[2], r)).items()):
            print(f"{r}|{n}|{hashlib.sha256(v).hexdigest()}")
"""


def pyhelper(mounts, code, *args, timeout=3600):
    """`code` with `args` in a throwaway python helper — root, no network — with `mounts` [(source, target, ro)]."""
    a = ["docker", "run", "--rm", "--init", "--network", "none", "--entrypoint", "python3"]
    for s, t, ro in mounts:
        a += ["-v", f"{s}:{t}{':ro' if ro else ''}"]
    return sh(a + [XATTR_HELPER, "-c", code, *args], timeout=timeout)


def xattrs_of(source) -> str:
    """The extended attributes of a volume or a folder: `path|name|sha256` per attribute (XATTRS)."""
    return pyhelper([(source, "/m", True)], XATTRS, "list", "/m", timeout=7200).stdout.decode(errors="surrogateescape")


def volume_exists(name) -> bool:
    return sh(["docker", "volume", "inspect", name], check=False).returncode == 0


def source_exists(st) -> bool:
    """Whether a store's old source is there: its volume, or — `path:` — its old host folder (never asked of docker,
    whose `-v` of a missing path would make it, root's)."""
    return os.path.isdir(st["volume"]) if st.get("_from_path") else volume_exists(st["volume"])


#: One line per entry, sorted: path|kind|mode|uid|gid[|size|mtime[|sha256]]. Directories and links carry no size or
#: time (a copy re-packs a directory and may not keep a link's own time), sockets and pipes are runtime, not data.
MANIFEST = r"""
set -e
cd "$1"
# every listing must succeed: a find or a stat that fails would give two EMPTY manifests that compare equal
find . -mindepth 1 \( -type s -o -type p \) -prune -o -exec stat -c '%n|%F|%a|%u|%g|%s|%Y' {} + > /tmp/s
awk -F'|' '{ if ($2 ~ /directory/) print $1"|d|"$3"|"$4"|"$5; else if ($2 ~ /symbolic/) print $1"|l|"$4"|"$5;
             else print $1"|f|"$3"|"$4"|"$5"|"$6"|"$7 }' /tmp/s > /tmp/m
if [ "$2" = hash ]; then
  # sha256sum prints the hash, two spaces, the name: the name is everything from the 67th character, spaces kept
  find . -mindepth 1 -type f -exec sha256sum {} + > /tmp/h0
  while IFS= read -r l; do printf '%s|%s\n' "$(printf '%s' "$l" | cut -c67-)" "$(printf '%s' "$l" | cut -c1-64)"; done \
    < /tmp/h0 > /tmp/h
  awk -F'|' 'NR==FNR { n=split($0,a,"|"); h[substr($0,1,length($0)-length(a[n])-1)]=a[n]; next }
             { if ($2=="f") print $0"|"h[$1]; else print }' /tmp/h /tmp/m > /tmp/mh
  mv /tmp/mh /tmp/m
fi
find . -mindepth 1 -type l -exec sh -c 'for l; do echo "$l|->|$(readlink "$l")"; done' _ {} + >> /tmp/m
LC_ALL=C sort /tmp/m
"""


def manifest(source, hashed: bool) -> str:
    """The manifest of a volume or a host folder (see MANIFEST)."""
    return helper([(source, "/m", True)], MANIFEST, "/m", "hash" if hashed else "nohash",
                  timeout=7200).stdout.decode(errors="surrogateescape")


def fingerprint(source) -> str:
    """sha256 of the manifest without contents: changes when anything in the store is written."""
    return hashlib.sha256(manifest(source, False).encode(errors="surrogateescape")).hexdigest()


def is_empty(source) -> bool:
    r = helper([(source, "/m", True)], "[ -z \"$(ls -A /m 2>/dev/null)\" ] && echo EMPTY || echo FULL")
    return r.stdout.strip() == b"EMPTY"


def size_of(source) -> int:
    r = helper([(source, "/m", True)], "du -sk /m | cut -f1")
    return int(r.stdout.strip() or 0) * 1024


# ── the office ──────────────────────────────────────────────────────────────────────────────────
def project() -> str:
    """The compose project the office runs under, as scripts/lib.sh office_project names it: COMPOSE_PROJECT_NAME
    when set or pinned in .env, else the folder's own name as compose normalises it. The variable is EMPTY on most
    offices (the HP's `mydgo`, vps1's `digital-office` are their folders' names) — reading only it stopped every
    move there (the second reader of DGO-2019)."""
    p = os.environ.get("COMPOSE_PROJECT_NAME") or env_value("COMPOSE_PROJECT_NAME")
    if not p:
        p = re.sub(r"^[^a-z0-9]*", "", re.sub(r"[^a-z0-9_-]", "", pathlib.Path(os.path.realpath(REPO)).name.lower()))
    return p or "digital-office"


def fs_type(path: pathlib.Path) -> str:
    """The filesystem `path` is on, from this process's mount table (inside a container: the bind's own fs)."""
    real = os.path.realpath(path if path.exists() else path.parent)
    best, kind = "", "?"
    try:
        lines = pathlib.Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return "?"
    for line in lines:
        left, _, right = line.partition(" - ")
        mp = left.split()[4].replace("\\040", " ")
        if (real == mp or real.startswith(mp.rstrip("/") + "/")) and len(mp) >= len(best):
            best, kind = mp, right.split()[0]
    return kind


def fs_refusal() -> str:
    """'' when data/ may hold databases on this office, else why not."""
    if os.environ.get("DGO_DATA_HOLD"):
        # the run `bbox home move` makes from the new folder (DGO-2019): every store stays on its volume, so a move
        # that goes back loses nothing, and the stores' copy into data/ is the next run's, with its own room check
        return "this run holds every store on its volume (the office is moving its folder: `bbox home move`)"
    kind = fs_type(DATA)
    ok = {k.strip() for k in (os.environ.get("DGO_DATA_FS_OK") or env_value("DGO_DATA_FS_OK")).split(",") if k.strip()}
    if kind in BAD_FS and kind not in ok:
        return (f"the DGO folder is on {kind} ({REPO}), which does not hold databases — its state stays in its volumes "
                f"until the folder is on the machine's own disk (DGO-1999)")
    return ""


def windows_drive_free() -> int | None:
    """Under WSL, the bytes free on C: — the distro's own disk is a file there (ext4.vhdx), whose own free space is its
    virtual size's: a copy that fits it can still fill C:, and a full C: gives that disk I/O errors (DGO-625). None
    elsewhere. A C: that cannot be read counts as full: a move then waits rather than guess."""
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as f:
            if "microsoft" not in f.read().lower():
                return None
    except OSError:
        return None
    if not os.path.isdir("/mnt/c"):
        return None
    try:
        s = os.statvfs("/mnt/c")
        return s.f_bavail * s.f_frsize
    except OSError:
        return 0


def office_floor() -> int:
    """The bytes this office keeps free on its disk whatever else happens — the floor its builds already keep
    (scripts/lib.sh disk_floor_gb): BBOX_DISK_MIN_GB from the environment or .env, else 5 GiB. A move never takes the
    disk under it. Until DGO-2188 a move asked for 1 GiB to spare, and its old volume is never removed: on vps1, 7.9 GB
    free of 99 (2026-11-24), the stores of one take would have left about 1 GB for the mail, the recordings and the
    databases of a public office to share."""
    raw = (os.environ.get("BBOX_DISK_MIN_GB") or env_value("BBOX_DISK_MIN_GB")).strip()
    return (int(raw) if raw.isdigit() else 5) << 30


def folder_free() -> int:
    """The bytes free where data/ is (or will be)."""
    fs = os.statvfs(DATA if DATA.exists() else REPO)
    return fs.f_bavail * fs.f_frsize


def env_value(key: str) -> str:
    p = REPO / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(rf"\s*{re.escape(key)}\s*=\s*['\"]?([^'\"#]*)", line)
            if m:
                return m.group(1).strip()
    return ""


def enabled_apps() -> dict:
    """{app id: manifest (with _dir)} of the apps this office runs."""
    sys.path.insert(0, str(REPO / "platform" / "manager"))
    import reconcile                                                    # noqa: E402 — the compiler's own reading
    cat, state = reconcile.load_catalog(), reconcile.load_state()
    return {a: cat[a] for a in sorted(reconcile.enabled_ids(state, cat))}


def binds_of(m: dict) -> tuple[dict, list, dict]:
    """(compose document, every bind into data/ as [(repo-relative folder, service, target, read-only)], {service: its
    mount targets}) of one app's compose."""
    d = pathlib.Path(m["_dir"])
    comp = m.get("compose") if isinstance(m.get("compose"), str) else "docker-compose.yml"
    if not (d / comp).is_file():
        return {}, [], {}
    doc = yaml.safe_load((d / comp).read_text(encoding="utf-8")) or {}
    binds, targets = [], {}                             # targets: every service's mounts, what a wait file may name
    for svc, spec in (doc.get("services") or {}).items():
        for v in (spec or {}).get("volumes") or []:
            # `${VAR:-../../data/<app>/x}` is what a clone with no .env override mounts (G118 reads it the same way) —
            # resolved BEFORE the short syntax is split on its colons, whose default has one of its own
            if isinstance(v, dict):
                src = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v.get("source") or ""))
                tgt, ro = str(v.get("target") or ""), bool(v.get("read_only"))
            else:
                p = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v)).split(":")
                if len(p) < 2:
                    continue
                src, tgt, ro = p[0], p[1], len(p) > 2 and "ro" in p[2].split(",")
            targets.setdefault(svc, set()).add(tgt)
            if not src.startswith("."):
                continue
            try:
                rel = (d / src).resolve().relative_to(REPO.resolve()).as_posix()
            except ValueError:
                continue
            if rel.startswith("data/") and rel.count("/") >= 1:
                binds.append((rel, svc, tgt, ro))
    return doc, binds, targets


def host_binds_of(m: dict) -> list[tuple[str, str]]:
    """[(service, absolute folder)] of every bind of one app's compose inside the checkout, data/ or not — what a store
    that was a folder (`path:`) is still read or written through."""
    doc = binds_of(m)[0]
    d, out = pathlib.Path(m["_dir"]), []
    for svc, spec in (doc.get("services") or {}).items():
        for v in (spec or {}).get("volumes") or []:
            if isinstance(v, dict):
                if v.get("type") not in (None, "bind"):
                    continue
                src = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v.get("source") or ""))
            else:
                src = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v)).split(":")[0]
            if not src.startswith((".", "/")):
                continue
            try:
                rel = (d / src).resolve().relative_to(REPO.resolve()).as_posix()
            except ValueError:
                continue
            out.append((svc, os.path.normpath(str(REPO / rel))))
    return out


def stores_of(aid: str, m: dict) -> list[dict]:
    """The stores an app's compose binds under data/<aid>/: [{app, rel, abs, mounts: [(service, target, ro, subpath)],
    image, build, volume, readers}] — `volume` is the old volume's full name (data.moved_from); `readers` the binds of
    OTHER apps into the store, which plan() attaches."""
    doc, binds, targets = binds_of(m)
    if not doc:
        return []
    vols = doc.get("volumes") or {}
    moved = ((m.get("data") or {}).get("moved_from") or {})
    services = {s: (spec or {}) for s, spec in (doc.get("services") or {}).items()}
    out = {}
    for rel, svc, tgt, ro in binds:
        if rel == f"data/{aid}" or rel.startswith(f"data/{aid}/"):
            out.setdefault(rel, {"app": aid, "rel": rel, "abs": str(REPO / rel), "mounts": [], "readers": []})[
                "mounts"].append((svc, tgt, ro))
    # A bind INSIDE another store's folder is that store's (Claude Desktop's /config is home/desktop, the subpath it
    # had in the volume): moved, seeded and waiting with it, its mount carrying the subpath.
    for rel in sorted(out, key=len, reverse=True):
        outer = next((o for o in out if o != rel and rel.startswith(o + "/")), None)
        if outer:
            sub = rel[len(outer) + 1:]
            out[outer]["mounts"] += [(s, t, ro, sub) for s, t, ro, *_ in out.pop(rel)["mounts"]]
    for rel, st in out.items():
        st["mounts"] = [m if len(m) == 4 else (*m, "") for m in st["mounts"]]
        # the service a new store is seeded from: the first that writes it at its root (a reader's view of it, or a
        # subfolder's, is not the image's view of the store)
        svc = next((s for s, _, ro, sub in st["mounts"] if not ro and not sub), st["mounts"][0][0])
        # the image as compose names it: `ghcr.io/…/forward-auth:${IMAGE_TAG:-latest}` with this office's value or the
        # default — the raw string is no image, and a new store was then never seeded from it (the second reader)
        # `${VAR:?message}` (n8n's `binaos/n8n:${N8N_VERSION:?set …}`) is the value alone, as compose reads it: once
        # left raw, n8n's image was never one, and its home never seeded nor moved
        image = re.sub(r"\$\{(\w+)(?::?-([^}]*)|:?\?[^}]*)?\}",
                       lambda g: os.environ.get(g[1]) or env_value(g[1]) or (g[2] or ""),
                       str(services[svc].get("image") or "")) or None
        if not image and services[svc].get("build"):
            image = f"{project()}-{svc}"     # a `build:` with no `image:`: compose's own name for what it builds
        st.update({"service": svc, "image": image, "build": bool(services[svc].get("build")),
                   "_manifest": m, "_targets": targets, "_was_volume": rel in moved})
        old = moved.get(rel) or auto_key(rel)
        if old.startswith(PATH):
            # a host folder of the checkout the store was in before (a source-tree `./storage`, apitools'):
            # moved the same way — copied, compared, left as it was — its users found by their bind's source, and a
            # wait file binding it back. Its absolute path stands where a volume's name does. It was never a VOLUME:
            # docker fills no bind from the image, so a new office's store never waits for one (it would make the old
            # folder, root's, in the source tree), and a new folder keeps the owner a host folder always had
            st["volume"] = os.path.normpath(str(REPO / old[len(PATH):]))
            st["volume_key"] = None
            st["_from_path"] = True
            st["_was_volume"] = False
        elif old.startswith(EXTERNAL):
            # a volume compose never made (a hand-made container's, the Telegram group relay's): its own name, with
            # no project's prefix — and a wait file names it by that name
            st["volume"] = old[len(EXTERNAL):]
            st["volume_key"] = re.sub(r"[^a-z0-9_]", "_", st["volume"].lower())
        else:
            st["volume_key"] = old
            spec = vols.get(old) if isinstance(vols.get(old), dict) else {}
            st["volume"] = spec.get("name") or f"{project()}_{old}"
    return list(out.values())


def attach_readers(stores: list[dict], apps: dict) -> None:
    """Give each store the binds other apps make into it (`readers`: [{app, mount: (service, target, ro, subpath),
    _targets}]): lan-console's read of forward-auth's users, any-concurrency's of n8n's home. A reader waits with the
    store it reads — on an office that waits, its bind would show it an empty folder — so its mount goes back on the
    owner's volume in the READER's own wait file, read only while the reader is compiled."""
    by_rel = {st["rel"]: st for st in stores}
    for aid, m in apps.items():
        _, binds, targets = binds_of(m)
        for rel, svc, tgt, ro in binds:
            if rel == f"data/{aid}" or rel.startswith(f"data/{aid}/"):
                continue
            owner = next((r for r in sorted(by_rel, key=len, reverse=True) if rel == r or rel.startswith(r + "/")),
                         None)
            if owner:
                by_rel[owner]["readers"].append({"app": aid, "mount": (svc, tgt, ro, rel[len(owner) + 1:]),
                                                 "_targets": targets})


def named_of(m: dict) -> list[tuple[str, str]]:
    """[(service, the volume's full name)] of every NAMED volume one app's compose mounts. An app that still mounts a
    store's old volume by name (any-concurrency's n8n_storage, the agents' obsidian_vault) keeps that store from moving:
    a move would stop it with nothing to start it again, or leave it writing a copy nobody reads."""
    doc = binds_of(m)[0]
    if not doc:
        return []
    vols = doc.get("volumes") or {}
    out = []
    for svc, spec in (doc.get("services") or {}).items():
        for v in (spec or {}).get("volumes") or []:
            if isinstance(v, dict):
                src = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v.get("source") or ""))
            else:
                src = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(v)).split(":")[0]
            if src not in vols:
                continue
            spec_v = vols[src] if isinstance(vols[src], dict) else {}
            name = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", str(spec_v.get("name") or "")) or f"{project()}_{src}"
            out.append((svc, name))
    return out


def auto_key(rel: str) -> str:
    """The volume a store with no old volume waits in, on an office that cannot hold it in data/ yet (WAIT): moved
    like any old volume once the office can."""
    return re.sub(r"[^a-z0-9_]", "_", "dh_" + rel[len("data/"):].lower())


def ledger_path(st) -> pathlib.Path:
    """data/.moves/<app>/<store>.json — `_.json` for an app whose one store is data/<app> itself (datamoves)."""
    return LEDGER / st["app"] / datamoves.ledger_name(st["rel"])


def read_ledger(st) -> dict:
    return datamoves.read(REPO, st["app"], st["rel"])


def write_ledger(st, rec: dict) -> None:
    p = ledger_path(st)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ── deciding ────────────────────────────────────────────────────────────────────────────────────
def decide(st, refusal: str) -> tuple[str, str]:
    """(action, why) for one store — READY, MOVE, SEED, WAIT or CONFLICT (module docstring)."""
    vol = st["volume"]
    if st.get("_from_path"):
        a, b = os.path.normpath(st["abs"]), vol
        root = os.path.normpath(str(REPO))
        if not b.startswith(root + os.sep):
            # `path:../x`, which G118 refuses: never a folder outside the DGO folder bound read-write by a wait file
            return "CONFLICT", f"{b} is outside the DGO folder: a `path:` names a folder inside it"
        if a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep):
            # copied into itself (browser42's data/browser42 → data/browser42/state): never by itself
            return "CONFLICT", f"the old folder {b} and the store {st['rel']} hold one another: it cannot be copied"
        if os.path.lexists(b) and not os.path.isdir(b):
            # a FILE (portainer's password file): read as missing it would be seeded empty, and the file dropped
            return "CONFLICT", f"{b} is a file, not a folder: a store is a folder — name the folder that holds it"
    exists = pathlib.Path(st["abs"]).exists()
    empty = (not exists) or is_empty(st["abs"])
    has_vol = source_exists(st)
    vol_empty = (not has_vol) or is_empty(vol)
    led = read_ledger(st)
    if led.get("failed"):
        # never again by itself: a move that failed its copy or its check is looked at first (each retry stops the
        # app and copies again, and a volume the app keeps writing would look "changed" every run)
        return "WAIT", f"the last move failed ({led['failed'][:120]}) — `./bbox data retry {st['app']}` after a look"
    if empty and led.get("moved_at"):
        return "CONFLICT", (f"{st['rel']} is empty, and the ledger says it moved there at {led['moved_at']}: the folder "
                            f"was emptied or this is another checkout — never filled again from the old volume by itself")
    # (a record written before `image_absent` says it in its words)
    absent = led.get("image_absent") or str(led.get("seeded") or "").startswith("created empty (the image")
    if empty and led.get("seeded_at") and not absent and exists and not (has_vol and not vol_empty):
        # seeded from what the image has, and still empty with nothing behind it — a store its app never writes
        # (MinIO's /data): ready, never seeded again at every run (Plane's reader). One made empty because the image
        # was not here yet is seeded again once it is: its owner may be the image's, which a non-root app needs
        return "READY", ""
    if not empty:
        if has_vol and not vol_empty and not led.get("moved_at"):
            return "CONFLICT", f"{st['rel']} and the volume {vol} both hold data, and no move is recorded"
        if has_vol and led.get("source_fp") and fingerprint(vol) != led["source_fp"]:
            # the volume was written AFTER the move: an update rolled back and ran on it. The folder is stale, unless
            # it was written too — then both moved on, and that is not ours to choose.
            if fingerprint(st["abs"]) == led.get("dest_fp"):
                return ("WAIT", refusal) if refusal else ("MOVE", f"{vol} was written after the move of "
                                                                   f"{led['moved_at']} (a rollback ran on it): again")
            return "CONFLICT", f"{vol} and {st['rel']} were both written after the move of {led['moved_at']}"
        return "READY", ""
    if has_vol and not vol_empty:
        if refusal:
            return "WAIT", refusal
        return "MOVE", f"{vol} → {st['rel']}"
    if refusal:
        return "WAIT", refusal
    return "SEED", "a new store"


def plan(apps: dict | None = None, services: set | None = None) -> list[dict]:
    """Every store of the enabled apps (or of `apps`), decided; with `services`, only the stores those mount (a
    targeted `bbox run <svc>…` moves only what it brings up again)."""
    refusal = fs_refusal()
    apps = apps if apps is not None else enabled_apps()
    every = [st for aid, m in apps.items() for st in stores_of(aid, m)]
    # the stores of an app that is OFF but read by one that runs (n8n off, any-concurrency on): never moved or seeded
    # here — only read where they are, which is their volume until a run of their own app moved them
    off = owners_off(apps)
    for st in off:
        st["off"] = True
    attach_readers(every + off, apps)
    named, bound = {}, {}
    for aid, m in apps.items():
        for svc, name in named_of(m):
            named.setdefault(name, []).append(f"{aid}/{svc}")
        for svc, src in host_binds_of(m):
            bound.setdefault(src, []).append(f"{aid}/{svc}")
    out = []
    for st in every + off:
        # a targeted run decides only the stores of what it brings up — never a store its services merely read: that
        # would stop the owner (the office's sign-in, for forward-auth) and `up` of the reader alone never starts it
        if services and not any(x[0] in services for x in st["mounts"]):
            if not any(r["mount"][0] in services for r in st["readers"]):
                continue
        st["action"], st["why"] = decide(st, refusal)
        if st.get("off") and st["action"] in ("MOVE", "SEED"):
            st["action"], st["why"] = "WAIT", f"{st['app']} is off: its readers read its volume until it runs"
        if st["action"] in ("MOVE", "SEED") and named.get(st["volume"]):
            st["action"], st["why"] = "WAIT", (f"{', '.join(sorted(named[st['volume']]))} still mount {st['volume']} "
                                               f"by name: it moves once they bind {st['rel']}")
        if st["action"] in ("MOVE", "SEED") and st.get("_from_path"):
            # a store that was a FOLDER, which another compose still binds (dashboard's read of data/power): moved, it
            # would leave them a copy nobody writes, or writing the old one nobody reads (the folder reader)
            old = st["volume"]
            users = sorted({u for src, us in bound.items() if src == old or src.startswith(old + os.sep) for u in us})
            if users:
                st["action"], st["why"] = "WAIT", (f"{', '.join(users)} still bind {old}: it moves once they bind "
                                                   f"{st['rel']}")
        if services and st["action"] in ("MOVE", "SEED"):
            outside = sorted(({m[0] for m in st["mounts"]} | {r["mount"][0] for r in st["readers"]}) - set(services))
            if outside:
                st["action"], st["why"] = "WAIT", (f"a targeted run does not bring up {', '.join(outside)}, which use "
                                                   f"it too: it moves at the next whole `bbox run`")
        out.append(st)
    return out


def owners_off(apps: dict) -> list[dict]:
    """The stores of apps NOT in `apps` (off, or not compiled) that an app in `apps` binds read-only, read from those
    apps' own manifests and compose on disk."""
    want = set()
    for aid, m in apps.items():
        for rel, *_ in binds_of(m)[1]:
            other = rel.split("/")[1]
            if other != aid and other not in apps:
                want.add(other)
    out = []
    for other in sorted(want):
        for root in ROOTS:
            mf = REPO / root / other / "app.json"
            if mf.is_file():
                m = json.loads(mf.read_text(encoding="utf-8"))
                m["_dir"] = mf.parent
                out += stores_of(other, m)
                break
    return out


# ── doing ───────────────────────────────────────────────────────────────────────────────────────
def say(msg):
    print(f"[data-home] {msg}", flush=True)


def users_of(vol, every: bool = False) -> list[str]:
    """The running containers that mount `vol` — every one, stopped too, with `every`."""
    r = sh(["docker", "ps", "-q"] + (["-a"] if every else []) + ["--filter", f"volume={vol}"], check=False)
    ids = r.stdout.decode().split()
    if not ids:
        return []
    r = sh(["docker", "inspect", "--format", "{{.Name}}"] + ids, check=False)
    return [n.strip().lstrip("/") for n in r.stdout.decode().splitlines() if n.strip()]


def state_hook(st) -> pathlib.Path | None:
    """The app's hooks/state (a copy measures itself with its template's)."""
    tpl = (st.get("_manifest") or {}).get("instance_of") or st["app"]
    return next((REPO / r / tpl / "hooks" / "state" for r in ROOTS if (REPO / r / tpl / "hooks" / "state").is_file()),
                None)


def state_probe(st) -> dict:
    """{name: value} from the app's hooks/state, or {} — read while the app runs. The hook is told the container it
    measures (DGO_STATE_CONTAINER: the store's first running container); by hand it finds the office's own."""
    h = state_hook(st)
    if not h:
        return {}
    running = [n for n in containers_of([st["service"]]) if container_running(n)]
    if not running:
        # never the hook's by-hand path: it measures the app's MAIN service, which may not be this store's (the relay's
        # cursor read as telegram's chats, then «gone» after the move — the second reader). Nothing said: the move waits.
        return {}
    env = {**os.environ, "DGO_STATE_CONTAINER": running[0], "COMPOSE_PROJECT_NAME": project()}
    r = subprocess.run(["bash", str(h)], capture_output=True, timeout=300, cwd=str(REPO), env=env)
    out = {}
    for line in r.stdout.decode(errors="replace").splitlines():
        k, _, v = line.strip().partition(" ")
        if k:
            out[k] = v.strip()
    return out


def healthy(names: list[str]) -> dict:
    """{container: its health now} — `healthy`, `none` (no healthcheck, running) or what else docker says."""
    out = {}
    for n in names:
        r = sh(["docker", "inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}"
                "{{else}}none{{end}}", n], check=False)
        status, _, hs = r.stdout.decode().strip().partition(" ")
        out[n] = hs if status == "running" else status or "gone"
    return out


#: Run in the source tree, after a move's copy into /dst: each symbolic link gets the owner it has in the source.
#: busybox's tar makes a link as the user who extracts it — root — never its owner in the source, so a link a non-root
#: app owns (n8n's npm tree: nodes/node_modules/.bin/*, uid 1000) differed in the copy and the move refused (the n8n
#: proof). The comparison after it checks every link's owner.
LINK_OWNERS = ("find . -type l -exec sh -c "
               "'for p; do chown -h \"$(stat -c %u:%g \"$p\")\" \"/dst/$p\" || exit 1; done' sh {} +")


def move(st) -> dict:
    """Copy the old volume into the folder and prove the two trees equal. Raises on any difference."""
    vol, dst = st["volume"], st["abs"]
    need = size_of(vol)
    free = folder_free()
    # the old volume stays, so every move costs its store's size for good: what is left after the copy is never
    # under the office's own disk floor (office_floor)
    spare = max(SPARE, office_floor())
    c = windows_drive_free()
    if c is not None and c < free:
        # the copy grows the .vhdx, and the .vhdx is a file on C: — which keeps the office's own floor after it
        # (lib.sh disk_floor_gb: 20 GiB under WSL; DGO-625 had the VM stopped from outside at 2.3 GB free)
        free, spare = c, max(SPARE, WSL_C_FLOOR)
    if free < need * 1.1 + spare:
        raise Waiting(f"{vol} is {need >> 20} MB and {free >> 20} MB are free: no room for a second copy that leaves "
                      f"the office its {spare >> 30} GiB floor")
    # the attributes' helper is first needed after the stop: here, or pulled now, or the store waits — never an app
    # stopped for a move that then cannot finish (the reader of the attributes' fix)
    if sh(["docker", "image", "inspect", XATTR_HELPER], check=False).returncode != 0:
        sh(["docker", "pull", XATTR_HELPER], check=False, timeout=900)
        if sh(["docker", "image", "inspect", XATTR_HELPER], check=False).returncode != 0:
            raise Waiting(f"the helper image {XATTR_HELPER} is not here and could not be pulled: nothing was stopped")
    # fresh, as close to the stop as can be; ensure's early read only when no container of the service it is read in
    # runs — an earlier move of this run stopped it (security's second store). An early read of a store late in a long
    # run is minutes old, and a row its app removed meanwhile would send a good move back; a running service whose
    # hook says nothing now waits, as before (the engine's reader)
    before = state_probe(st)
    if not before and not any(container_running(n) for n in containers_of([st["service"]])):
        before = st.get("_before") or {}
    if state_hook(st) and not before:
        # an app that says what it holds and says nothing now: what would the check after the move compare to?
        raise Waiting(f"its hooks/state said nothing before the move (is {st['service']} up?)")
    users = users_of(vol)
    if st.get("_from_path"):
        # …and the store's own services, whatever docker says a bind's source is (a checkout reached through a link,
        # Docker Desktop's own spelling of a host path): a folder its app still writes is never copied
        own = [m[0] for m in st["mounts"]] + [r["mount"][0] for r in st.get("readers") or []]
        users = sorted(set(users) | {n for n in containers_of(own) if container_running(n)})
    was = healthy(users)                       # the check after the move asks only these to be healthy again
    run = st.get("_run")
    if run:
        # …and a container an earlier move of this run already stopped that uses this volume too (security, for its
        # second store): its health from just before that stop (the engine's reader)
        was.update({n: run[n] for n in users_of(vol, every=True) if n in run and n not in was})
    if users:
        say(f"stopping {', '.join(users)} (they use {vol})")
        st["_stopped"] = users                 # whatever happens next, ensure has them brought back at once (REUP)
        if run is not None:
            run.update({n: was[n] for n in users})
        sh(["docker", "stop", "-t", "60"] + users, timeout=600)
    if pathlib.Path(dst).exists() and not is_empty(dst):
        put_aside(st)                       # a stale copy (the volume ran on after a rollback): never merged into
    pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    helper([(vol, "/src", True), (dst, "/dst", False)],
           "cd /src && tar -cf - . | tar -C /dst -xpf - && " + LINK_OWNERS +
           " && chown \"$(stat -c %u:%g /src)\" /dst && chmod \"$(stat -c %a /src)\" /dst", timeout=7200)
    # …and its extended attributes, which the tar above drops: set on the copy where the source has any, and the two
    # trees' compared always (a copy that gained some, from a default ACL above it, is as different as one that lost)
    xa = xattrs_of(vol)
    if xa.strip():
        pyhelper([(vol, "/src", True), (dst, "/dst", False)], XATTRS, "copy", "/src", "/dst", timeout=7200)
    xb = xattrs_of(dst)
    if xa != xb:
        diff = [x for x in set(xa.splitlines()) ^ set(xb.splitlines())][:5]
        raise RuntimeError(f"the extended attributes of the copy of {vol} differ from it: {diff}")
    a, b = manifest(vol, True), manifest(dst, True)
    if a != b:
        diff = [x for x in set(a.splitlines()) ^ set(b.splitlines())][:5]
        raise RuntimeError(f"the copy of {vol} differs from it: {diff}")
    files = sum(1 for x in a.splitlines() if "|f|" in x)
    if not a.strip():
        # MOVE is only decided for a volume that holds something: a manifest of nothing means the listing failed. A
        # store of folders alone (made before its first file) lists them, owners and modes: a real comparison
        raise RuntimeError(f"the manifest of {vol} lists nothing, and the volume is not empty: nothing was compared")
    rec = {"app": st["app"], "store": st["rel"], "volume": vol, "moved_at": now(), "seconds": round(time.time() - t0),
           "bytes": need, "files": files, "xattrs": len(xa.splitlines()),
           "manifest_sha256": hashlib.sha256(a.encode(errors="surrogateescape")).hexdigest(),
           "source_fp": fingerprint(vol), "dest_fp": fingerprint(dst), "stopped": users, "before": before,
           "healthy_before": sorted(n for n, h in was.items() if h in ("healthy", "none")), "verified": False}
    write_ledger(st, rec)
    say(f"moved {vol} → {st['rel']}: {files} files, {need >> 20} MB, identical")
    return rec


def seed(st) -> str:
    """Fill a new folder with what the image ships at the mount's target, owners kept. Returns what was done."""
    dst = st["abs"]
    if st.get("_from_path"):
        # it was a host folder, which docker never fills from the image: what the app saw there was the folder alone
        # (chat's image COPYs its whole source tree) — so the new one is made empty, its owner a host folder's
        pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
        return "created empty (it was a host folder, which docker never fills from the image)"
    tgt = next((m[1] for m in st["mounts"] if m[0] == st["service"] and not m[3]), st["mounts"][0][1])
    img = st.get("image")
    if not img or sh(["docker", "image", "inspect", img], check=False).returncode != 0:
        if img and not st.get("build"):
            sh(["docker", "pull", img], check=False, timeout=900)
        if not img or sh(["docker", "image", "inspect", img], check=False).returncode != 0:
            subpath = any(m[3] for m in st["mounts"] + [r["mount"] for r in st.get("readers") or []])
            if st.get("_was_volume") and not subpath:
                # a store that was a volume, on a new office whose image is built at this run's `up` (or cannot be
                # pulled now): it starts on its volume, which docker fills from the image at its first mount —
                # files, owner and mode, a non-root app's (n8n's `node`) included — and the next run moves it, owners
                # kept. An empty folder now would be root's or the bbox user's, and the app could not write it
                raise Waiting(f"its image {img or '(built)'} is not here yet: it starts on its volume, which docker "
                              f"fills from the image, and the next run moves it")
            # a host folder, as it always was (owner untouched); a store a mount reads by a subpath needs its folder now
            # — docker neither makes a volume's subpath nor fills one from the image: root:root 755, as an empty volume.
            # Recorded as made without the image (`image_absent`), so a later run seeds it from the image once it is
            # here rather than take the empty folder as ready
            pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
            st["_image_absent"] = True
            return as_empty_volume(st, f"created empty (the image {img or '(built)'} is not here yet)")
    pathlib.Path(dst).mkdir(parents=True, exist_ok=True)
    cid = sh(["docker", "create", img]).stdout.decode().strip()
    try:
        tar = sh(["docker", "cp", f"{cid}:{tgt}", "-"], check=False)
        if tar.returncode != 0:
            return as_empty_volume(st, f"created empty ({img} has nothing at {tgt})")
        # the stream's one top entry is the target directory itself: its contents go in, its owner and mode onto
        # the folder — what docker gives an empty named volume
        # (no LINK_OWNERS here: busybox's tar -x into /x already made every link root's, so there is no owner left to
        # copy — and a link's own owner decides nothing about who may follow it; the move, which compares, keeps them)
        helper([(dst, "/dst", False)], "mkdir /x && tar -C /x -xpf - && set -- /x/* && cp -a \"$1\"/. /dst/ "
                                       "&& chown \"$(stat -c %u:%g \"$1\")\" /dst && chmod \"$(stat -c %a \"$1\")\" /dst",
               input=tar.stdout)
        return f"seeded from {img}:{tgt}"
    finally:
        # -v: an image that declares a VOLUME at the target (forgejo's /data) made an anonymous one at `create`; left,
        # it is a stray volume G118 and `bbox data check` name (batch E's second reader)
        sh(["docker", "rm", "-f", "-v", cid], check=False)


def as_empty_volume(st, said: str) -> str:
    """A new folder with nothing from the image, for a store that was a volume (data.moved_from), gets what docker gave
    that empty volume, root:root 755 — not the owner and the umask of the process that made it: under an unprivileged
    `bbox` that is uid 1000, and a root container with every capability dropped (security) cannot write into a folder
    it does not own (batch D's second reader). A store that was always a host folder keeps what it had: browser42's
    data/browser42 is written from the host by its hooks, as the bbox user."""
    if st.get("_was_volume"):
        helper([(st["abs"], "/dst", False)], "chown 0:0 /dst && chmod 755 /dst")
    return said


class Waiting(Exception):
    """A store that cannot move on this run: it keeps its volume (WAIT)."""


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_override(waiting: list[dict], engine: bool = True) -> None:
    """`data/.moves/wait/<app>.yml`: each waiting store's mounts back on its volume; no file for an app none waits.
    Without the engine (`waits`) a volume is named by its compose key alone, which compose knows as its own."""
    per_app, targets_of = {}, {}

    def put(app, targets, key, vol, mount):
        services, volumes = per_app.setdefault(app, ({}, {}))
        targets_of[app] = targets
        svc, tgt, ro, sub = mount
        if key is None:
            # a store that was a host FOLDER (`path:`): bound back to it, at its subpath, by its absolute path
            services.setdefault(svc, {"volumes": []})["volumes"].append(
                {"type": "bind", "source": os.path.join(vol, sub) if sub else vol, "target": tgt,
                 **({"read_only": True} if ro else {})})
            return
        volumes[key] = vol
        services.setdefault(svc, {"volumes": []})["volumes"].append(
            {"type": "volume", "source": key, "target": tgt, **({"read_only": True} if ro else {}),
             **({"volume": {"subpath": sub}} if sub else {})})

    for st in waiting:
        key, name = st["volume_key"], st["volume"]
        if st.get("_from_path"):
            if not os.path.isdir(name):
                # no old folder: nothing to hold there, and a bind of a missing path fails `up` or makes it, root's,
                # in the source tree — it runs from its own folder (the folder reader)
                continue
            vol = name                                   # put() binds the old folder itself
        else:
            vol = {"name": name, "external": True} if engine and volume_exists(name) else {"name": name}
        for mnt in st["mounts"]:
            put(st["app"], st["_targets"], key, vol, mnt)
        # a reader of the store reads it where it is: on its volume, in the reader's own file (read while compiled)
        for r in st.get("readers") or []:
            put(r["app"], r["_targets"], key, vol, r["mount"])
    head = ("# Written by platform/manager/datahome.py (DGO-2019) at every bbox run — never by hand. These stores\n"
            "# cannot move to data/<app>/ on this office yet, so each keeps running from its volume (compose merges a\n"
            "# service's mounts by target). `./bbox data plan` says why, store by store.\n")
    WAIT.mkdir(parents=True, exist_ok=True)
    if engine:                              # only the run that looked at the engine says a store no longer waits
        for old in WAIT.glob("*.yml"):
            if old.stem not in per_app:
                old.unlink()
    for app, (services, volumes) in per_app.items():
        p = WAIT / f"{app}.yml"
        if not engine and p.is_file():
            # what a run wrote stays, but only for a service and a mount target the app's compose still has: one it
            # no longer has would be a service with no image, and every compose command of the office would fail
            have = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            now_targets = targets_of[app]
            for svc, spec in (have.get("services") or {}).items():
                if svc not in now_targets:
                    continue
                mine = services.setdefault(svc, {"volumes": []})["volumes"]
                mine += [v for v in spec.get("volumes") or [] if v.get("target") in now_targets[svc]
                         and v.get("target") not in {x["target"] for x in mine}]
            used = {v["source"] for spec in services.values() for v in spec["volumes"]}
            for k, v in (have.get("volumes") or {}).items():
                # the run's entry stands for the same volume: it asked docker, and says `external` of one compose
                # never made (a hand-made volume) — without it compose warns at every command, and `down -v` takes it
                if k in used and (k not in volumes or (volumes[k] or {}).get("name") == (v or {}).get("name")):
                    volumes[k] = v
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(head + yaml.safe_dump({"services": services, "volumes": volumes}, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, p)


def compiled_apps() -> dict:
    """{app id: manifest (with _dir)} of the apps the compiled compose includes — read from .generated/compose.yml,
    the files compose itself reads, with no engine and no compiler."""
    out = {}
    try:
        incs = (yaml.safe_load((REPO / ".generated" / "compose.yml").read_text(encoding="utf-8")) or {}).get("include")
    except (OSError, yaml.YAMLError):
        return out
    for inc in incs or []:
        p = inc.get("path") if isinstance(inc, dict) else inc
        p = p[0] if isinstance(p, list) and p else p
        mf = (REPO / p).parent / "app.json" if isinstance(p, str) else None
        if mf and mf.is_file():
            m = json.loads(mf.read_text(encoding="utf-8"))
            m["_dir"] = mf.parent
            out[m.get("id") or mf.parent.name] = m
    return out


def folder_holds_data(path: str) -> bool:
    """Files only, no engine: does the folder hold anything? An unreadable one (a database's, owned by its user) does."""
    try:
        return bool(os.listdir(path))
    except FileNotFoundError:
        return False
    except OSError:
        return True


def waits() -> int:
    """No engine, files only — every compose command runs it (scripts/lib.sh compose_args). So a change that lands
    between two runs (a pull, a commit in the checkout) never starts an app on an empty folder before `bbox run` has
    looked at it. A store with no record (no run decided it) waits on its old volume when it has one; on a filesystem
    that does not hold databases, a store with no record waits when its folder is still empty — never a folder that
    already holds its data (browser42's data/browser42 stays bound); a store whose move failed keeps waiting.
    Exit 1 when an app's stores could not be read: compose_args then refuses to run compose for it."""
    bad_fs = bool(fs_refusal())
    waiting, broken, binding = [], 0, {}
    compiled = compiled_apps()
    for aid, m in compiled.items():
        moved = (m.get("data") or {}).get("moved_from") or {}
        comp = pathlib.Path(m["_dir"]) / (m.get("compose") or "docker-compose.yml")
        try:
            text = comp.read_text(encoding="utf-8")
        except OSError as e:
            if moved or bad_fs:                                   # a store of it may be undecided: never passed over
                print(f"[data-home] {aid}: its compose could not be read ({e})", file=sys.stderr)
                broken += 1
            continue
        if "data/" in text:
            binding[aid] = m                                      # it may read another app's store
        if not moved and not bad_fs:
            continue
        try:
            if f"data/{aid}" not in text:
                continue                                          # binds no folder of its own: nothing to decide
            for st in stores_of(aid, m):
                led = read_ledger(st)
                if led.get("failed") or led.get("conflict_at"):
                    waiting.append(st)
                elif not led and (st["rel"] in moved or (bad_fs and not folder_holds_data(st["abs"]))):
                    waiting.append(st)
        except Exception as e:                                    # noqa: BLE001 — said, and the caller refuses
            print(f"[data-home] {aid}: its stores could not be read ({e})", file=sys.stderr)
            broken += 1
    try:
        # an app that is OFF and read by one that runs: its store is read where it is — on its volume, until a run
        # of its own app moved it into its folder
        waiting += [st for st in owners_off(binding) if not folder_holds_data(st["abs"])]
        attach_readers(waiting, binding)                          # a reader waits with the store it reads
    except Exception as e:                                        # noqa: BLE001 — said, and the caller refuses
        print(f"[data-home] the readers of the waiting stores could not be read ({e})", file=sys.stderr)
        broken += 1
    if waiting:
        write_override(waiting, engine=False)
    prune_wait_files(compiled)
    return 1 if broken else 0


def prune_wait_files(compiled: dict) -> None:
    """Every wait file of a compiled app keeps only the services and mount targets its compose still has: a pull that
    renamed a service would otherwise leave one with no image, and every compose command of the office would fail."""
    for p in sorted(WAIT.glob("*.yml")) if WAIT.is_dir() else []:
        m = compiled.get(p.stem)
        if not m:
            continue                                              # not compiled: compose_args does not read it
        try:
            targets = binds_of(m)[2]
            have = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:                                         # noqa: BLE001 — left as it is, said by waits
            continue
        services = {s: {"volumes": [v for v in (spec or {}).get("volumes") or [] if v.get("target") in targets[s]]}
                    for s, spec in (have.get("services") or {}).items() if s in targets}
        services = {s: spec for s, spec in services.items() if spec["volumes"]}
        if services == (have.get("services") or {}):
            continue
        used = {v["source"] for spec in services.values() for v in spec["volumes"]}
        if not services:
            p.unlink()
            continue
        volumes = {k: v for k, v in (have.get("volumes") or {}).items() if k in used}
        head = "".join(ln + "\n" for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("#"))
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(head + yaml.safe_dump({"services": services, "volumes": volumes}, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, p)


def ensure(dry: bool = False, apps: dict | None = None, services: set | None = None) -> int:
    """Before `up`: 0, or 1 when a store is in CONFLICT or a move failed — said, and that store keeps its volume."""
    stores = plan(apps, services)
    # a targeted run keeps every OTHER waiting store waiting: the override is the whole office's — each store once
    mine = {s["rel"] for s in stores}
    others = [s for s in plan(apps) if s["action"] in ("WAIT", "CONFLICT")] if services else []
    waiting, bad = [s for s in others if s["rel"] not in mine], 0
    if not dry:
        # one record for the run: each container a move stopped, with its health just before (move() asks a later
        # store's check to include it)
        run = {}
        for st in stores:
            st["_run"] = run
        # what every moving store holds, read before ANY move stops anything — kept only for a store whose own read
        # at its move says nothing: two stores read in one service (security's data and sensor, both in `security`),
        # the first move stops it, and the second read nothing and waited a whole run (batch D's second reader)
        moving = [st for st in stores if st["action"] == "MOVE" and state_hook(st)]
        if len(moving) > 1:
            say(f"reading what {len(moving)} moving stores hold, before any is stopped")
            for st in moving:
                try:
                    st["_before"] = state_probe(st)
                except Exception as e:                                    # noqa: BLE001 — move() reads it again
                    say(f"  {st['rel']}: not read now ({e}); it is read at its move")
    try:
        for st in stores:
            act = st["action"]
            if act == "READY":
                if not dry and not read_ledger(st):
                    # a folder that already held its data: recorded, so the no-engine `waits` knows it is decided
                    write_ledger(st, {"app": st["app"], "store": st["rel"], "ready_at": now()})
                continue
            say(f"{st['app']}: {st['rel']} — {act}{': ' + st['why'] if st['why'] else ''}")
            if dry:
                continue
            try:
                if act == "WAIT" and st.get("_from_path") and not os.path.isdir(st["volume"]) \
                        and not os.path.lexists(st["volume"]):
                    # a store that was a folder, gone here: nothing to hold, and no wait to bind it to — made now as
                    # a seed makes it (the process user's), and recorded, so an old folder appearing later (an old
                    # commit checked out) never takes the app away from the folder it writes (the folder reader)
                    pathlib.Path(st["abs"]).mkdir(parents=True, exist_ok=True)
                    how = seed(st)
                    write_ledger(st, {"app": st["app"], "store": st["rel"], "seeded_at": now(), "seeded": how})
                    say(f"  {how}: its old folder is not here, so it has nothing to wait with")
                elif act == "WAIT":
                    waiting.append(st)
                elif act == "CONFLICT":
                    led = read_ledger(st)
                    led.update({"app": st["app"], "store": st["rel"], "conflict_at": now(), "conflict": st["why"]})
                    write_ledger(st, led)
                    waiting.append(st)
                    bad += 1
                elif act == "SEED":
                    try:
                        how = seed(st)
                    except Waiting as e:
                        st["action"], st["why"] = "WAIT", str(e)
                        say(f"  waits: {e}")
                        waiting.append(st)
                    else:
                        write_ledger(st, {"app": st["app"], "store": st["rel"], "seeded_at": now(), "seeded": how,
                                          **({"image_absent": True} if st.get("_image_absent") else {})})
                        say(f"  {how}")
                elif act == "MOVE":
                    try:
                        move(st)
                    except Waiting as e:
                        st["action"], st["why"] = "WAIT", str(e)
                        say(f"  waits: {e}")
                        waiting.append(st)
            except Exception as e:                                       # noqa: BLE001 — said, and it waits
                # FAIL CLOSED: whatever went wrong, the store runs from its volume (the volume is never touched here)
                say(f"  FAILED, it stays on its volume: {e}")
                waiting.append(st)
                bad += 1
                if act == "MOVE":
                    try:
                        put_aside(st)
                    except Exception as e2:                              # noqa: BLE001 — a full disk fails this too
                        say(f"  and its partial copy could not be set aside ({e2}): it stays in {st['rel']}")
                try:
                    led = read_ledger(st)
                    led.update({"app": st["app"], "store": st["rel"], "volume": st["volume"], "failed_at": now(),
                                "failed": f"{act}: {e}"[:300], "verified": False})
                    led.pop("moved_at", None)
                    write_ledger(st, led)
                except Exception as e3:                                  # noqa: BLE001 — the same full disk
                    say(f"  and its ledger could not be written ({e3}): `./bbox data plan` decides it again")
        if not dry:
            write_override(waiting)
        n = {a: sum(1 for s in stores if s["action"] == a) for a in ("READY", "MOVE", "SEED", "WAIT", "CONFLICT")}
        say(f"{len(stores)} store(s): " + ", ".join(f"{v} {k.lower()}" for k, v in n.items() if v))
    finally:
        # What a move stopped comes back NOW, not at the run's `up` after every hook and build: the office's sign-in
        # (forward-auth) was down for the whole run, and a run cut short left it stopped (`docker stop` is not
        # restarted by `restart: unless-stopped`). On its folder when the move held, on its volume (the wait file)
        # when it did not — and said whatever broke after the stop. Only what was STOPPED, by its compose service: a
        # container no compose of this office makes (a hand-made one) still mounts the OLD volume, and restarted as
        # it is it would write a copy the office no longer reads — said, never brought up.
        stopped = [n for st in stores for n in st.get("_stopped") or []]
        reup, alone = services_of(stopped) if stopped else ([], [])
        if alone:
            say(f"stopped by the move, made by no compose of this office, and still mounting the old volume: "
                f"{' '.join(alone)} — point it at the store's folder or retire it; restarted as it is, it writes a "
                f"copy nobody reads")
        if reup:
            print("REUP " + " ".join(reup), flush=True)
    return 1 if bad else 0


def services_of(names: list[str]) -> tuple[list[str], list[str]]:
    """(the compose services of these containers in this office's project, the containers that are none of them)."""
    svcs, alone = set(), []
    for n in names:
        r = sh(["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}|'
                '{{index .Config.Labels "com.docker.compose.service"}}', n], check=False)
        proj, _, svc = r.stdout.decode().strip().partition("|")
        if proj == project() and svc:
            svcs.add(svc)
        else:
            alone.append(n)
    return sorted(svcs), alone


def health(names: list[str], deadline: float) -> list[str]:
    """The containers among `names` not healthy (or not running, without a healthcheck) by `deadline`."""
    left = list(names)
    while left and time.time() < deadline:
        nxt = []
        for n in left:
            r = sh(["docker", "inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}"
                    "{{else}}none{{end}}", n], check=False)
            status, _, hs = r.stdout.decode().strip().partition(" ")
            if not (status == "running" and hs in ("healthy", "none")):
                nxt.append(n)
        left = nxt
        if left:
            time.sleep(5)
    return left


def same_state(before: dict, after: dict) -> list[str]:
    """What of `before` the app no longer holds after the move. The bytes were already proven identical (the
    manifest); this asks whether the app READS them: a value that is not a number (a key's fingerprint, an account,
    signed-in) must be the same, and a count that was above zero must still be above zero — an app that came up on an
    empty store says 0. A count may change otherwise: the app ran on between the two reads (it deletes rows too)."""
    out = []
    for k, v in before.items():
        w = after.get(k)
        if w is None:
            out.append(f"{k} gone (was {v})")
        elif re.fullmatch(r"-?\d+", v or "") and re.fullmatch(r"-?\d+", w or ""):
            if int(v) > 0 and int(w) <= 0:
                out.append(f"{k} {v} → {w}")
        elif w != v:
            out.append(f"{k} {v!r} → {w!r}")
    return out


def put_aside(st) -> None:
    """Move a store's folder out of the way (data/.moves/aside/<app>/<store>-<time>): a copy that failed, or one a
    rollback left behind. The store then reads as empty and its volume is what runs or moves; nothing is deleted."""
    aside = f"/d/.moves/aside/{st['app']}/{pathlib.Path(st['rel']).name}-{now()}"
    helper([(str(DATA), "/d", False)], 'mkdir -p "$(dirname "$2")" && { [ ! -e "$1" ] || mv "$1" "$2"; }',
           "/d/" + st["rel"][len("data/"):], aside)


def containers_of(services) -> list[str]:
    """The containers of these compose services, in this office's project."""
    out = []
    for s in sorted(set(services)):
        r = sh(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project()}", "--filter",
                f"label=com.docker.compose.service={s}", "--format", "{{.Names}}"], check=False)
        out += r.stdout.decode().split()
    return out


def container_running(name) -> bool:
    r = sh(["docker", "inspect", "--format", "{{.State.Running}}", name], check=False)
    return r.stdout.strip() == b"true"


def verify(timeout: int = 600, apps: dict | None = None) -> int:
    """After `up`: each store moved and not yet verified. Prints `REUP <service>…` for a store sent back to its
    volume, for the caller to bring up again (the override already says where it runs)."""
    bad, reup, back = 0, [], []
    deadlines, stopped_here = {}, set()
    for st in plan(apps):
        led = read_ledger(st)
        if not led.get("moved_at") or led.get("verified"):
            continue
        services_here = [m[0] for m in st["mounts"]] + [r["mount"][0] for r in st.get("readers") or []]
        users = containers_of(services_here)
        # only what was healthy before the move must be healthy after it: a container that was red for its own
        # reasons (notifications without GlitchTip's token) says nothing about its data
        was = led.get("healthy_before")
        must = [n for n in users if was is None or n in was]
        if stopped_here & set(must):
            # another store of the same app failed this check and its containers were stopped for it: this one is
            # not judged now — still moved and unverified, the next run's check judges it
            say(f"{st['app']}: {st['rel']} — not judged now: {', '.join(sorted(stopped_here & set(must)))} were "
                f"stopped for another store's failed check; the next run checks it")
            continue
        # an app that boots slowly says how slowly (`progress_deadline_seconds`: Plane's 1800, its boot measured at
        # 21 minutes): that long, from this check's start, once per app — never a store sent back to its volume over
        # a boot still running, and never the wait counted again for each of its stores (Plane's and the folder reader)
        if st["app"] not in deadlines:
            try:
                slow = int((st.get("_manifest") or {}).get("progress_deadline_seconds") or 0)
            except (TypeError, ValueError):
                slow = 0
            deadlines[st["app"]] = time.time() + max(timeout, slow)
        left = (health(must, deadlines[st["app"]]) if users
                else ["(no container of " + st["service"] + " is up)"])
        diff = same_state(led.get("before") or {}, state_probe(st)) if not left else []
        if left or diff:
            why = f"not healthy: {', '.join(left)}" if left else "its state is not the same: " + "; ".join(diff)
            say(f"{st['app']}: {st['rel']} — {why}; back on {st['volume']} (untouched since the move)")
            if users:
                sh(["docker", "stop", "-t", "60"] + users, check=False, timeout=600)
                stopped_here.update(users)
            put_aside(st)
            led.update({"verified": False, "failed_at": now(), "failed": why})
            led.pop("moved_at", None)
            write_ledger(st, led)
            back.append(st)
            reup += services_here
            bad += 1
            continue
        led.update({"verified": True, "verified_at": now(), "after": state_probe(st)})
        write_ledger(st, led)
        say(f"{st['app']}: {st['rel']} — verified ({len(must)} container(s) healthy"
            f"{', the same state' if led.get('before') else ''})")
    if back:
        write_override([s for s in plan(apps) if s["action"] in ("WAIT", "CONFLICT")])
        print("REUP " + " ".join(sorted(set(reup))))
    return 1 if bad else 0


def retry(apps: list[str]) -> int:
    """`bbox data retry <app>…`: a store whose move failed waits until someone looked (decide); this lets the next
    `bbox run` try it again. The failure stays in the record (`failed_before`), and nothing else changes."""
    if not apps:
        raise SystemExit("bbox data retry <app>… — the app whose failed move may be tried again")
    n = 0
    for app in apps:
        for p in sorted((LEDGER / app).glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("failed") or rec.get("conflict_at"):
                rec["failed_before"] = rec.pop("failed", None) or rec.pop("conflict", None)
                rec.pop("conflict_at", None)
                p.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
                say(f"{app}: {p.stem} will be tried again at the next bbox run")
                n += 1
    if not n:
        say("no failed move to try again")
    return 0


# ── the live check ──────────────────────────────────────────────────────────────────────────────
#: Places in a container's own layer that are not state: scratch, runtime, caches, logs, bytecode.
DISPOSABLE = re.compile(r"^/(tmp|run|var/run|var/tmp|var/cache|var/log|proc|dev|sys)(/|$)|/\.cache(/|$)|"
                        r"/__pycache__(/|$)|\.pyc$|^/root/\.npm(/|$)|^/etc/(hostname|hosts|resolv\.conf|mtab)$")


def check(as_json: bool = False) -> int:
    """A running office: named and anonymous volumes holding state, and writes into container layers."""
    apps = enabled_apps()
    cache = {f"{project()}_{v}" for m in apps.values() for v in ((m.get("data") or {}).get("cache") or [])}
    names = sh(["docker", "ps", "--filter", f"label=com.docker.compose.project={project()}", "--format",
                "{{.Names}}"]).stdout.decode().split()
    found = []
    for n in sorted(names):
        ins = json.loads(sh(["docker", "inspect", n]).stdout)[0]
        for mt in ins.get("Mounts") or []:
            if mt["Type"] != "volume" or mt.get("Name") in cache:
                continue
            anon = bool(re.fullmatch(r"[0-9a-f]{64}", mt.get("Name") or ""))
            found.append({"container": n, "kind": "anonymous volume" if anon else "volume",
                          "what": f"{mt.get('Name')} → {mt['Destination']}"})
        layer = [ln[2:] for ln in sh(["docker", "diff", n], check=False).stdout.decode().splitlines() if ln[:1] in "AC"]
        mounted = [mt["Destination"] for mt in ins.get("Mounts") or []]
        keep = [p for p in layer if not DISPOSABLE.search(p)
                and not any(p == d or p.startswith(d + "/") or d.startswith(p + "/") for d in mounted)
                and not re.match(r"^/(usr|etc|opt|app|srv|bin|lib|sbin)(/|$)", p)]
        if keep:
            found.append({"container": n, "kind": "container layer", "what": f"{len(keep)} path(s): " +
                          ", ".join(sorted(keep)[:6])})
    if as_json:
        print(json.dumps(found, indent=1, ensure_ascii=False))
    else:
        for f in found:
            print(f"  {f['container']:32} {f['kind']:16} {f['what']}")
        print(f"[data-home] {len(names)} container(s) of {project()}: {len(found)} place(s) hold state outside data/")
    return 1 if found else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="datahome")
    ap.add_argument("verb", choices=["plan", "ensure", "verify", "check", "waits", "retry"])
    ap.add_argument("services", nargs="*", help="ensure: only the stores these services mount (a targeted run)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.verb == "plan":
        rows = plan()
        if a.json:
            print(json.dumps([{**{k: v for k, v in r.items() if not k.startswith("_") and k != "readers"},
                               "readers": [{"app": x["app"], "mount": x["mount"]} for x in r.get("readers") or []]}
                              for r in rows], indent=1, ensure_ascii=False))
        else:
            for st in rows:
                print(f"  {st['app']:22} {st['rel']:44} {st['action']:8} {st['why']}")
            if fs_refusal():
                print(f"[data-home] {fs_refusal()}")
        return 0
    if a.verb == "ensure":
        return ensure(dry=a.dry_run, services=set(a.services) or None)
    if a.verb == "verify":
        return verify()
    if a.verb == "waits":
        return waits()
    if a.verb == "retry":
        return retry(a.services)
    return check(as_json=a.json)


if __name__ == "__main__":
    sys.exit(main())
