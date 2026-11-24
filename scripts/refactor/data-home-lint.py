#!/usr/bin/env python3
"""data-home-lint — gate G118: every app keeps its state in the DGO folder's `data/<app>/`, and nowhere else.

    python3 scripts/refactor/data-home-lint.py [--self-test]

The owner, 2026-11-18 (DGO-2019), after an update re-created Claude Desktop and its sign-in was gone (DGO-2016): «All importent
data of any dgo app should alwase be saved to local mapped drive drirectly into dgo main folder/data/app-name … I want
backup to simply need to copy that data folder and have all!! statfull data dgo has created. Nothing should be saved
into the continers or drive that are not mapped to the apps data folder and no other hidden place!!!!»

So the standard (ai/context/build-your-first-app.md, «Where an app keeps its state»): an app's state is host folders
`data/<app>/<store>` of the DGO folder, bound from its compose as `../../data/<app>/<store>`; a docker named volume
holds only what `data.cache` says can be fetched again; no image VOLUME is left to an anonymous volume. This gate reads
that from the tree alone (no docker, no .env), per app of apps/ and platform-base/:

  H1 VOLUME   — a named volume the app's compose mounts is state, unless it is in the app's `data.cache`.
  H2 BIND     — a writable bind that holds state (G26's rule: not tracked by git, not the checkout itself, not a
                device or a socket) is under `data/<app>/`, the app's own home.
  H3 ANOTHER  — a bind into another app's home `data/<other>/` is read-only: that home is the other app's to write.
  H4 DECLARED — `data.paths` names every `data/<app>/…` the compose binds; every key of `data.moved_from` is one of
                them, and its value (the volume the bytes came from, or `path:<folder>`, a folder of the DGO folder
                named relative to it) is no longer a volume, or a bind, of the compose.
  H5 IMAGE    — every VOLUME of a Dockerfile a service builds is covered by a mount of that service (an uncovered
                one is an anonymous volume: state no folder holds).
  H6 IGNORED  — every `data/<app>/` the compose binds is ignored by git, so state never rides the tree.

A RATCHET, not a retrofit (AGENTS.md rule 8: warn first, then refuse): platform/data-home-pending.yaml lists the
findings the tree had when the standard was written, each to be moved by DGO-2019. Anything not on it fails; an entry
that matches nothing fails too (stale), so the list only shrinks. `waived:` in the same file holds the decisions that
are not state (the backup's own destination, a job's scratch), each with its reason.

What a running office does that the tree cannot show — a write into the container layer, an anonymous volume of an
image built elsewhere — is `bbox data check` (platform/manager/datahome.py check).

Exit 0 = no finding outside the list; 1 = a finding, or a stale entry.
"""
import json, pathlib, posixpath, re, subprocess, sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = ("platform-base", "apps")
LIST = "platform/data-home-pending.yaml"

# Not state, whatever their mode: the engine's socket and the kernel's pseudo-filesystems.
DEVICE_PREFIX = ("/var/run", "/run", "/proc", "/sys", "/dev", "/etc/localtime", "/etc/timezone")
# The office's own directories under data/ that belong to no one app: the heavy-job slot (scripts/lib.sh heavy_admit).
PLATFORM_HOMES = ("data/.locks",)

_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}")


def compose_default(spec):
    """`${VAR:-default}` read as its default — what a clone with no .env mounts (G26's reading)."""
    return _DEFAULT.sub(lambda m: m.group(2), spec)


def tracked_files(repo):
    """Every FILE git tracks; None when this is not a git checkout.

    Files, not the directories holding them: a tracked file bound into a container is configuration (G26's rule),
    but a writable bind of a tracked DIRECTORY is a place the app can write state into — traefik's ./config is
    tracked and holds acme.json, every TLS key the office was issued."""
    try:
        raw = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return {r for r in raw.decode("utf-8", errors="surrogateescape").split("\0") if r}


def ignored(repo, rels):
    """The subset of repo-relative paths git ignores; None when git cannot say."""
    if not rels:
        return set()
    try:
        r = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"], cwd=repo,
                           input="\0".join(rels).encode(), capture_output=True)
    except FileNotFoundError:
        return None
    if r.returncode not in (0, 1):
        return None
    return {x for x in r.stdout.decode("utf-8", errors="surrogateescape").split("\0") if x}


def load_yaml(p):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:                                        # a broken compose is G12's
        print(f"  ! could not parse {p}: {e}")
        return {}


def mounts(svc):
    """[(kind, source, target, read_only)] of one compose service: kind is volume | bind | anonymous."""
    out = []
    for m in (svc or {}).get("volumes") or []:
        if isinstance(m, dict):
            src = compose_default(str(m.get("source") or ""))
            kind = m.get("type") or ("bind" if src.startswith((".", "/")) else "volume")
            out.append((kind if src else "anonymous", src, str(m.get("target") or ""), bool(m.get("read_only"))))
            continue
        s = compose_default(str(m))
        parts = s.split(":")
        if len(parts) == 1:
            out.append(("anonymous", "", parts[0], False))
            continue
        src, tgt = parts[0], parts[1]
        ro = len(parts) > 2 and "ro" in parts[2].split(",")
        out.append(("bind" if src.startswith((".", "/", "~")) else "volume", src, tgt, ro))
    return out


def repo_rel(repo, app_dir, src):
    """A bind source resolved as compose resolves it, repo-relative; None outside the repo; "" for the repo itself."""
    s = src.replace("\\", "/")
    try:
        p = pathlib.Path(s) if s.startswith("/") else app_dir / s
        rel = p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    return "" if rel == "." else rel


def home_of(rel):
    """`data/<app>/…` → <app>; None for a path outside data/ or a platform directory."""
    parts = rel.split("/")
    if len(parts) >= 2 and parts[0] == "data" and not any(rel == h or rel.startswith(h + "/") for h in PLATFORM_HOMES):
        return parts[1]
    return None


def dockerfile_volumes(app_dir, svc):
    """VOLUME paths of the Dockerfile a service builds (first-party images only)."""
    b = (svc or {}).get("build")
    if not b:
        return []
    ctx, df = (b, "Dockerfile") if isinstance(b, str) else (b.get("context") or ".", b.get("dockerfile") or "Dockerfile")
    p = (app_dir / ctx / df)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*VOLUME\s+(.*)$", line, re.I)
        if not m:
            continue
        v = m.group(1).strip()
        try:
            vals = json.loads(v) if v.startswith("[") else v.split()
        except json.JSONDecodeError:
            vals = v.strip("[]").replace('"', "").split(",")
        out.extend(x.strip() for x in vals if x.strip())
    return out


def manifests(repo):
    """[(app id, app dir, app.json)] of apps/ and platform-base/."""
    out = []
    for root in ROOTS:
        base = repo / root
        for app_dir in sorted(base.iterdir()) if base.is_dir() else []:
            mf = app_dir / "app.json"
            if mf.is_file():
                app = json.loads(mf.read_text(encoding="utf-8"))
                out.append((app.get("id") or app_dir.name, app_dir, app))
    return out


def findings(repo, tracked):
    """[(app, rule, subject, sentence)] over the tree, and the denominators scanned. `tracked` is the set of files
    git tracks; None (no git) reads a bound regular file of the tree as tracked config."""
    out, seen = [], {"apps": 0, "compose": 0, "services": 0, "mounts": 0}
    homes_bound = {}                                    # app → {repo-relative data path} its compose binds
    every_bind, folders = {}, []                        # app → every repo-relative bind source; the `path:` stores
    apps = manifests(repo)
    ids = {a for a, _, _ in apps}

    def add(aid, rule, subject, sentence):
        if not any(f[0] == aid and f[1] == rule and f[2] == subject for f in out):    # once per app and subject
            out.append((aid, rule, subject, sentence))

    for aid, app_dir, app in apps:
        data = app.get("data") or {}
        cache = set(data.get("cache") or [])
        shares = set(data.get("shares") or [])
        seen["apps"] += 1
        cf = app_dir / (app.get("compose") if isinstance(app.get("compose"), str) else "docker-compose.yml")
        if not cf.is_file():
            continue
        seen["compose"] += 1
        cfg = load_yaml(cf)
        declared_vols = set((cfg.get("volumes") or {}).keys())
        # …and the whole names they are given (`name:`), which an `external:<name>` of data.moved_from goes by
        declared_vols |= {str(s.get("name")) for s in (cfg.get("volumes") or {}).values() if isinstance(s, dict)
                          and s.get("name")}
        bound = homes_bound.setdefault(aid, set())
        binds = set()                                     # every repo-relative bind source, for `path:` of moved_from
        for sname, svc in (cfg.get("services") or {}).items():
            if not isinstance(svc, dict):
                continue
            seen["services"] += 1
            targets = set()
            for kind, src, tgt, ro in mounts(svc):
                seen["mounts"] += 1
                targets.add(tgt.rstrip("/"))
                if kind == "anonymous":
                    add(aid, "H5", f"{sname}:{tgt}", f"{sname} mounts an anonymous volume at {tgt}: state no folder "
                        f"holds — bind ../../data/{aid}/<store> there")
                    continue
                if kind == "volume":
                    if src in cache:
                        continue
                    if src in shares:
                        add(aid, "H1", src, f"{sname} mounts {src}, another app's named volume — bind that app's "
                            f"../../data/<app>/<store> read-only once it has moved")
                    else:
                        add(aid, "H1", src, f"named volume {src} ({sname}:{tgt}) holds state outside data/{aid}/ — "
                            f"bind ../../data/{aid}/<store> instead, or say in data.cache why it is fetched again")
                    continue
                if src.startswith(DEVICE_PREFIX) or src in ("/", ""):
                    continue
                rel = repo_rel(repo, app_dir, src)
                if rel == "":                             # the checkout itself: the office's hands, not its state
                    continue
                if rel is not None:
                    binds.add(rel)
                if rel is None:                           # an absolute host path outside the DGO folder
                    if not ro:
                        add(aid, "H2", src, f"{sname} writes {src} on the host, outside the DGO folder — its state "
                            f"belongs in data/{aid}/")
                    continue
                owner = home_of(rel)
                if owner is not None:
                    if owner == aid:
                        bound.add(rel)
                    elif ro:
                        pass
                    elif owner not in ids:
                        add(aid, "H2", src, f"{sname} writes {rel}/, which is no app's home — keep it in "
                            f"data/{aid}/<store>")
                    else:
                        add(aid, "H3", src, f"{sname} writes data/{owner}/, {owner}'s home — mount it read-only, "
                            f"or keep this state in data/{aid}/")
                    continue
                if ro or any(rel == h or rel.startswith(h + "/") for h in PLATFORM_HOMES):
                    continue
                if (rel in tracked) if tracked is not None else (repo / rel).is_file():
                    continue                              # a tracked file: config injected into the container (G26)
                add(aid, "H2", src, f"{sname} writes {rel}/, outside data/{aid}/ — move it to data/{aid}/<store>")
            for v in dockerfile_volumes(app_dir, svc):
                if v.rstrip("/") not in targets:
                    add(aid, "H5", f"{sname}:{v}", f"the image {sname} builds declares VOLUME {v} and nothing is "
                        f"mounted there: an anonymous volume — bind ../../data/{aid}/<store>")
        paths = set(data.get("paths") or [])
        # a bind inside a declared store is that store's (Claude Desktop's /config is home/desktop)
        for rel in sorted(r for r in bound if not any(r == p or r.startswith(p + "/") for p in paths)):
            add(aid, "H4", rel, f"binds {rel} and data.paths does not name it")
        for rel, vol in sorted((data.get("moved_from") or {}).items()):
            if rel not in bound:
                add(aid, "H4", rel, f"data.moved_from names {rel}, which the compose does not bind")
            if str(vol).startswith("path:"):
                folders.append((aid, rel, str(vol)))       # judged below, against every app's binds
            elif str(vol).removeprefix("external:") in declared_vols:
                add(aid, "H4", vol, f"data.moved_from moves {vol} into {rel}, and the compose still declares it")
        every_bind[aid] = binds
    # a store that was a FOLDER of the DGO folder (`path:<folder>`, a source-tree `./storage`): named relative to it,
    # inside it, no other app's or the data move's; bound by NO compose any more (another app's read of it would be left
    # a copy nobody writes); and holding no tracked file — a tracked file keeps the old folder from ever being empty or
    # the same, so a restore onto a fresh clone or a pull after the move would be a CONFLICT for good (the folder reader)
    for aid, rel, vol in folders:
        raw = vol[len("path:"):]
        old = posixpath.normpath(raw)
        if raw.startswith("/") or any(p in ("", ".", "..") for p in raw.split("/")):
            add(aid, "H4", vol, f"data.moved_from moves {vol} into {rel}: name a folder inside the DGO folder, "
                f"relative to it, with no empty, `.` or `..` part")
            continue
        owner = home_of(old)
        if old == rel or old.startswith(rel + "/") or rel.startswith(old + "/"):
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}: the two hold one another")
        elif old == "data/.moves" or old.startswith("data/.moves/") or (owner in ids and owner != aid):
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}: it is {owner or 'the data move'}'s")
        users = sorted({a for a, bs in every_bind.items() for b in bs if b == old or b.startswith(old + "/")})
        if users:
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}, and {', '.join(users)} still bind it")
        if old == ".git" or old.startswith(".git/"):
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}: it is git's own")
        held = sorted(f for f in tracked or () if f == old or f.startswith(old + "/"))
        if held:
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}, which holds {len(held)} tracked file(s) "
                f"({held[0]}…): untrack them in the same change, and ignore the folder from a file outside it")
        # …and ignored by git, from outside it: the move leaves the old folder full (as it was), and a folder ignored
        # only by its own tracked .gitignore (chat's) would put the state it holds in `git status` once untracked
        ign = ignored(repo, [old + "/"]) if tracked is not None else None
        if ign is not None and old + "/" not in ign and old not in ign:
            add(aid, "H4", vol, f"data.moved_from moves {old}/ into {rel}, which git does not ignore: what the move "
                f"leaves there would ride the tree — ignore it from a file outside it")
        if (repo / old).is_file():
            add(aid, "H4", vol, f"data.moved_from moves {old} into {rel}: a file, not a folder")
    allb = sorted({r for s in homes_bound.values() for r in s})
    ign = ignored(repo, [r + "/" for r in allb]) if tracked is not None else None
    if ign is not None:
        for aid, rels in sorted(homes_bound.items()):
            for rel in sorted(rels):
                if rel + "/" not in ign and rel not in ign:
                    out.append((aid, "H6", rel, f"{rel}/ is not ignored by git: state would ride the tree"))
    seen["git"] = ign is not None
    return out, seen


def key(f):
    return f"{f[1]} {f[2]}"


def judge(found, listed):
    """(new findings, stale entries) against the list {app: {"pending": [...], "waived": [...]}} of 'H<n> subject'."""
    allowed = {(a, e) for a, v in listed.items() for k in ("pending", "waived") for e in (v or {}).get(k) or []}
    hit = {(f[0], key(f)) for f in found}
    new = [f for f in found if (f[0], key(f)) not in allowed]
    stale = sorted(allowed - hit)
    return new, stale


def read_list(repo):
    p = repo / LIST
    raw = load_yaml(p) if p.is_file() else {}
    return {a: {"pending": [str(x) for x in (v or {}).get("pending") or []],
                "waived": [str(x) for x in (v or {}).get("waived") or []]} for a, v in (raw or {}).items()}


def run(repo):
    tracked = tracked_files(repo)
    found, seen = findings(repo, tracked)
    listed = read_list(repo)
    new, stale = judge(found, listed)
    n_pending = sum(len(v["pending"]) for v in listed.values())
    n_waived = sum(len(v["waived"]) for v in listed.values())
    print(f"G118 scanned {seen['apps']} apps, {seen['compose']} compose files, {seen['services']} services, "
          f"{seen['mounts']} mounts; git {'read' if seen['git'] else 'NOT read (H6 not judged)'}")
    for f in new:
        print(f"  {f[0]:22} {f[1]}  {f[3]}")
    for a, e in stale:
        print(f"  {a:22} STALE  «{e}» is listed in {LIST} and matches nothing: take it off")
    if new or stale:
        print(f"G118 FAIL — {len(new)} finding(s) outside {LIST}, {len(stale)} stale entr(ies). The standard: "
              f"ai/context/build-your-first-app.md «Where an app keeps its state»")
        return 1
    print(f"G118 PASS — every finding is listed: {n_pending} still to move (DGO-2019), {n_waived} waived with a "
          f"reason")
    return 0


def self_test():
    """Each rule on a synthetic tree: the shapes that are findings, and the ones that must not be."""
    import tempfile
    t = pathlib.Path(tempfile.mkdtemp())
    (t / "platform").mkdir()

    def app(aid, compose, data=None, dockerfile=None):
        d = t / "apps" / aid
        d.mkdir(parents=True)
        (d / "app.json").write_text(json.dumps({"id": aid, "data": data or {}}))
        (d / "docker-compose.yml").write_text(yaml.safe_dump(compose))
        if dockerfile:
            (d / "Dockerfile").write_text(dockerfile)

    app("vol", {"services": {"s": {"image": "x", "volumes": ["vol_data:/data", "vol_cache:/c"]}},
                "volumes": {"vol_data": {}, "vol_cache": {}}}, {"cache": ["vol_cache"]})
    app("good", {"services": {"s": {"image": "x", "volumes": ["../../data/good/db:/var/lib/db",
                                                              "../../data/good/db/sub:/sub",
                                                              "../../data/vol/x:/peek:ro", "./conf:/conf:ro",
                                                              "/var/run/docker.sock:/var/run/docker.sock",
                                                              "../../:/repo"]}}},
        {"paths": ["data/good/db"], "moved_from": {"data/good/db": "good_db"}})
    app("srcbind", {"services": {"s": {"image": "x", "volumes": ["./storage:/app/storage", "/srv/x:/x"]}}})
    app("other", {"services": {"s": {"image": "x", "volumes": ["../../data/good/db:/db"]}}})
    app("undeclared", {"services": {"s": {"image": "x", "volumes": ["../../data/undeclared/a:/a"]}},
                       "volumes": {"old": {}}},
        {"moved_from": {"data/undeclared/b": "old"}})
    app("anon", {"services": {"s": {"build": ".", "volumes": ["/scratch"]}}}, None, 'FROM x\nVOLUME ["/data"]\n')
    # a volume compose never made, moved by its whole name: a compose that still declares it (here by `name:`) fails;
    # one that no longer does passes
    app("byhand", {"services": {"s": {"image": "x", "volumes": ["../../data/byhand/state:/s"]}},
                   "volumes": {"kept": {"name": "made_by_hand"}}},
        {"paths": ["data/byhand/state"], "moved_from": {"data/byhand/state": "external:made_by_hand"}})
    app("byhandok", {"services": {"s": {"image": "x", "volumes": ["../../data/byhandok/state:/s"]}}},
        {"paths": ["data/byhandok/state"], "moved_from": {"data/byhandok/state": "external:other_by_hand"}})
    # a store that was a folder of the source tree (`path:`): one no service binds any more passes; one still bound
    # (here read-only, inside it) fails, and so does one named outside the DGO folder
    app("folder", {"services": {"s": {"image": "x", "volumes": ["../../data/folder/store:/app/storage"]}}},
        {"paths": ["data/folder/store"], "moved_from": {"data/folder/store": "path:apps/folder/storage"}})
    app("folderkept", {"services": {"s": {"image": "x", "volumes": ["../../data/folderkept/store:/app/storage",
                                                                    "./storage/sub:/peek:ro"]}}},
        {"paths": ["data/folderkept/store"], "moved_from": {"data/folderkept/store": "path:apps/folderkept/storage"}})
    app("folderout", {"services": {"s": {"image": "x", "volumes": ["../../data/folderout/store:/s"]}}},
        {"paths": ["data/folderout/store"], "moved_from": {"data/folderout/store": "path:../elsewhere"}})
    # …one that holds a tracked file (never empty, never the same); one ANOTHER app still binds; a `.` part; the data
    # move's own folder; and one inside the store it moves into
    def folder(aid, old):
        app(aid, {"services": {"s": {"image": "x", "volumes": [f"../../data/{aid}/store:/s"]}}},
            {"paths": [f"data/{aid}/store"], "moved_from": {f"data/{aid}/store": f"path:{old}"}})
    folder("foldertracked", "apps/foldertracked/storage")
    folder("folderread", "apps/folderread/storage")
    app("reader", {"services": {"s": {"image": "x", "volumes": ["../folderread/storage/sub:/peek:ro"]}}})
    folder("folderdot", "apps/./x")
    folder("foldermoves", "data/.moves/x")
    folder("folderinside", "data/folderinside/store/old")
    folder("foldergit", ".git/x")
    found, seen = findings(t, {"apps/foldertracked/storage/.gitignore"})
    got = {(f[0], f[1], f[2]) for f in found}
    want = {("vol", "H1", "vol_data"), ("srcbind", "H2", "./storage"), ("srcbind", "H2", "/srv/x"),
            ("other", "H3", "../../data/good/db"), ("undeclared", "H4", "data/undeclared/a"),
            ("undeclared", "H4", "data/undeclared/b"), ("undeclared", "H4", "old"),
            ("anon", "H5", "s:/scratch"), ("anon", "H5", "s:/data"), ("byhand", "H4", "external:made_by_hand"),
            ("folderkept", "H4", "path:apps/folderkept/storage"), ("folderout", "H4", "path:../elsewhere"),
            ("foldertracked", "H4", "path:apps/foldertracked/storage"), ("folderread", "H4", "path:apps/folderread/storage"),
            ("folderdot", "H4", "path:apps/./x"), ("foldermoves", "H4", "path:data/.moves/x"),
            ("folderinside", "H4", "path:data/folderinside/store/old"), ("foldergit", "H4", "path:.git/x")}
    ok = True
    for w in sorted(want - got):
        print(f"  MISSED  {w}"); ok = False
    for g in sorted(got - want):
        print(f"  EXTRA   {g}"); ok = False
    # the ratchet: a listed finding passes, an unlisted one fails, an entry matching nothing is stale
    listed = {"vol": {"pending": ["H1 vol_data"], "waived": []}, "good": {"pending": ["H1 gone"], "waived": []}}
    new, stale = judge(found, listed)
    if any(f[0] == "vol" for f in new) or ("good", "H1 gone") not in stale or not any(f[0] == "srcbind" for f in new):
        print("  RATCHET wrong:", new, stale); ok = False
    print(f"data-home self-test {'PASS' if ok else 'FAIL'} — {len(want)} findings expected, {len(got)} found, "
          f"{seen['mounts']} mounts read")
    return 0 if ok else 1


def print_findings(repo):
    """Every finding of the tree in the list's own shape, one `- "H<n> subject"  # sentence` per line — what an
    entry of the list is copied from."""
    found, _ = findings(repo, tracked_files(repo))
    for aid in sorted({f[0] for f in found}):
        print(f"{aid}:\n  pending:")
        for f in (f for f in found if f[0] == aid):
            print(f"    - \"{key(f)}\"  # {f[3]}")


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    root = pathlib.Path(sys.argv[sys.argv.index("--repo") + 1]) if "--repo" in sys.argv else REPO
    if "--findings" in sys.argv[1:]:
        sys.exit(print_findings(root))
    sys.exit(run(root))
