#!/usr/bin/env python3
"""catalog — the signed app index, and everything that reads it.

    bbox catalog keygen | build | verify | list | show | disclose | trust | selftest
    bbox app install <ref>            (platform/manager/appinstall.py)

THE PROBLEM. Until now the "app store" was `ls apps/` with `enabled: false` in
platform.state.yaml. Every installable app had to already be a folder in this repo, so the store
could only ever show what shipped with the platform. There was no way to install an app from
anywhere else, which means it was a gallery, not a store.

THE MODEL: F-DROID index-v2. F-Droid does not run an API. It publishes a SIGNED FILE:
`entry.jar` (signed, tiny) carries the sha256 of `index-v2.json` (big, unsigned), which carries
the sha256 of every APK. One signature covers the whole chain. The consequences are the reason to
copy it rather than invent something:

  * it works offline and from any dumb file host — S3, a git raw URL, a USB stick;
  * verification needs no control plane, no online CA, no phone-home;
  * the index is a diffable artifact you can archive, mirror and reproduce;
  * a mirror can be untrusted, because the bytes are checked, not the source.

WHAT IS ADAPTED, AND WHY:

  * JAR signing -> a detached Ed25519 envelope (`index-v1.sig.json`). JAR signing means Java. See
    signing.py for the full trust model and its limits.
  * APK -> a deterministic zip of the app directory (its app.json, compose, hooks, blueprint).
  * The index carries the whole DISCLOSURE surface (credentials, capabilities, routes, volumes,
    resources) so a user can be told what an app will do BEFORE a single byte of it is fetched.
    F-Droid does the same with Anti-Features and permissions.

WHAT IS NOT COPIED: mirrors, localised repo metadata, incremental index diffs, per-entry
signing keys. Each is a real F-Droid feature and none is load-bearing for a single-deployment
store; the format leaves room (`repo.mirrors`, per-entry `key_id`) without implementing them.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import signing                                            # noqa: E402
import reconcile                                          # noqa: E402

try:
    import yaml
except ImportError:                                       # pragma: no cover
    sys.exit("PyYAML required: pip install pyyaml")

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = REPO / "apps"
# NOT under .generated/. `.generated/` is COMPILED CONFIG: reconcile.py archives all of it into a
# numbered generation on every render, and keeps twenty. The catalog is a PUBLISHED ARTIFACT — tens
# of megabytes of app zips — so putting it there multiplied it by twenty and filled the disk on the
# first try. Different lifetime, different directory.
DEFAULT_OUT = REPO / ".catalog"
INDEX_NAME = "index-v1.json"
SIG_NAME = "index-v1.sig.json"
INDEX_FORMAT = "bina.catalog/v1"
PROVIDERS = REPO / "platform-base" / "connections" / "providers"

# Never packaged into an artifact: build detritus, local secrets, and anything a fresh clone would
# not have. The default source list is `git ls-files`, which already excludes all of it — this is
# the belt for the (legitimate) case of packaging a directory that is not in a git repo.
SKIP_PARTS = {"__pycache__", ".git", "node_modules", ".venv", ".pytest_cache"}
SKIP_SUFFIX = (".pyc", ".pyo")
SKIP_NAMES = {"portainer_password.txt", ".DS_Store", "Thumbs.db"}


# ── artifact packaging ────────────────────────────────────────────────────────
def _sources(app_dir):
    """Files to package, repo-app-relative, sorted. `git ls-files` when possible: it is exactly
    'what a fresh clone would contain', which is the same question fresh-clone-lint asks."""
    app_dir = pathlib.Path(app_dir)
    try:
        out = subprocess.run(["git", "-C", str(app_dir), "ls-files"],
                             capture_output=True, text=True, timeout=30)
        rels = [l for l in out.stdout.splitlines() if l.strip()] if out.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        rels = []
    if not rels:
        rels = []
        for root, dirs, files in os.walk(app_dir):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS)
            for f in files:
                p = pathlib.Path(root) / f
                if f in SKIP_NAMES or f.endswith(SKIP_SUFFIX):
                    continue
                rels.append(p.relative_to(app_dir).as_posix())
    keep = [r for r in sorted(set(rels))
            if not (set(r.split("/")) & SKIP_PARTS)
            and r.rsplit("/", 1)[-1] not in SKIP_NAMES
            and not r.endswith(SKIP_SUFFIX)
            and (app_dir / r).is_file()]
    return keep


def pack(app_dir, dest_zip, app_id=None):
    """Deterministic zip of one app directory, entries prefixed with the app id.

    REPRODUCIBILITY IS THE POINT. The index carries the artifact's sha256, so if packing the same
    tree twice produced two hashes, "verify the hash" would only ever mean "verify it against the
    one copy I happen to have", and nobody could independently rebuild the artifact to check what
    is in it. So: sorted entries, a fixed 1980-01-01 timestamp, fixed permissions."""
    app_dir = pathlib.Path(app_dir)
    app_id = app_id or app_dir.name
    dest_zip = pathlib.Path(dest_zip)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    files = _sources(app_dir)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            info = zipfile.ZipInfo(f"{app_id}/{rel}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            src = app_dir / rel
            # Preserve only the x-bit: a hook that loses it stops being runnable, and everything
            # else about mode is machine noise that would break reproducibility.
            executable = os.access(src, os.X_OK) or rel.startswith("hooks/")
            info.external_attr = (0o755 if executable else 0o644) << 16
            z.writestr(info, src.read_bytes())
    return dest_zip, len(files)


def unpack(archive, dest_dir):
    """Extract a zip/tar artifact into dest_dir, refusing path traversal. Returns the app dir."""
    dest_dir = pathlib.Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = pathlib.Path(archive)

    def safe(name):
        # An artifact is untrusted input. `../../../etc/x` and absolute members are the classic
        # zip-slip; refuse rather than sanitise, because a member that needs sanitising is a lie
        # about what the archive contains.
        n = name.replace("\\", "/")
        if n.startswith("/") or ".." in n.split("/") or re.match(r"^[A-Za-z]:", n):
            raise ValueError(f"unsafe path in archive: {name}")
        return n

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for m in z.namelist():
                safe(m)
            z.extractall(dest_dir)
    else:
        try:
            with tarfile.open(archive) as t:
                for m in t.getmembers():
                    safe(m.name)
                    if m.issym() or m.islnk():
                        raise ValueError(f"archive contains a link member: {m.name}")
                t.extractall(dest_dir)
        except tarfile.TarError as e:
            raise ValueError(f"not a zip or tar archive: {e}")
    # the app dir is whichever extracted directory holds an app.json (top level or one below)
    if (dest_dir / "app.json").is_file():
        return dest_dir
    subs = [d for d in sorted(dest_dir.iterdir()) if d.is_dir() and (d / "app.json").is_file()]
    if len(subs) == 1:
        return subs[0]
    if not subs:
        raise ValueError("archive contains no app.json — not an app artifact")
    raise ValueError(f"archive contains {len(subs)} app.json manifests — expected exactly one")


# ── fetch ─────────────────────────────────────────────────────────────────────
def fetch(ref, timeout=120):
    """Bytes for a local path or an http(s)/file URL. Returns (bytes, source_description)."""
    if re.match(r"^https?://", ref):
        req = urllib.request.Request(ref, headers={"User-Agent": "bina-platform-catalog/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - scheme checked
            return r.read(), ref
    if ref.startswith("file://"):
        p = urllib.request.url2pathname(ref[len("file://"):].lstrip("/"))
        return pathlib.Path(p).read_bytes(), ref
    p = pathlib.Path(ref)
    if not p.is_absolute():
        p = (pathlib.Path.cwd() / p) if (pathlib.Path.cwd() / p).exists() else (REPO / ref)
    return p.read_bytes(), str(p)


def _sibling(ref, name):
    """The URL/path of a file next to `ref`."""
    if re.match(r"^[a-z]+://", ref):
        return ref.rsplit("/", 1)[0] + "/" + name
    return str(pathlib.Path(ref).parent / name)


# ── index build ───────────────────────────────────────────────────────────────
def _providers_catalog():
    """id -> {title, kind} from the connections provider catalog, for the credential disclosure.

    Read best-effort: a catalog entry the platform does not know about still discloses its id,
    which is the honest thing to show, rather than hiding a credential we cannot describe."""
    entries = []
    for f in sorted(PROVIDERS.glob("*.yaml")):
        try:
            entries += yaml.safe_load(f.read_text(encoding="utf-8")) or []
        except Exception:
            continue
    # …and the rows an app declares for ITSELF (contributes.connection_providers). They are catalog
    # entries like any other, and the app that owns one is the app being disclosed: portainer's own
    # admin password was shown to its installer as the bare id `portainer-admin`, kind "unknown".
    for m in sorted([*APPS.glob("*/app.json"), *(REPO / "platform-base").glob("*/app.json")]):
        try:
            entries += (json.loads(m.read_text(encoding="utf-8")).get("contributes") or {}) \
                .get("connection_providers") or []
        except Exception:
            continue
    return {e["id"]: {"title": e.get("title") or e["id"], "title_he": e.get("title_he") or "",
                      "kind": e.get("kind") or "secret"}
            for e in entries if isinstance(e, dict) and e.get("id")}


def _compose_facts(app_dir, manifest):
    """The parts of an app's compose a user must be told about: published host ports, host bind
    mounts, the docker socket, privileged mode, images.

    These are NOT in app.json. They are in the compose file the artifact ships, which is the file
    that actually gets executed — so a disclosure computed only from the manifest would miss the
    single scariest thing an app can ask for (`/var/run/docker.sock`, i.e. root on the host)."""
    facts = {"images": [], "ports": [], "host_paths": [], "docker_socket": False,
             "privileged": False, "services": []}
    comp = manifest.get("compose")
    if not comp:
        return facts
    p = pathlib.Path(app_dir) / comp
    if not p.is_file():
        return facts
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return facts
    for name, spec in (doc.get("services") or {}).items():
        if not isinstance(spec, dict):
            continue
        facts["services"].append(name)
        if spec.get("image"):
            facts["images"].append(str(spec["image"]))
        elif spec.get("build"):
            facts["images"].append(f"(built from source: {name})")
        if spec.get("privileged"):
            facts["privileged"] = True
        for prt in (spec.get("ports") or []):
            facts["ports"].append(str(prt))
        for v in (spec.get("volumes") or []):
            if not isinstance(v, str):
                continue
            src = v.split(":")[0]
            if "docker.sock" in v:
                facts["docker_socket"] = True
            if src.startswith(("/", ".", "~", "$")):
                facts["host_paths"].append(v)
    for k in ("images", "ports", "host_paths", "services"):
        facts[k] = sorted(set(facts[k]))
    return facts


def entry_from_manifest(manifest, app_dir, artifact=None):
    """One catalog entry. Everything a store screen and a disclosure need, WITHOUT the artifact."""
    routing = []
    for r in (manifest.get("routing") or []):
        routing.append({"host": r.get("host"), "port": r.get("port"),
                        "auth": r.get("auth", "sso"),
                        "sso": bool(r.get("sso")),
                        "tile": bool((r.get("module") or {}).get("id"))})
    bp = manifest.get("blueprints") or {}
    n8n_dir = (bp.get("n8n") or "").strip()
    workflows = 0
    if n8n_dir:
        d = pathlib.Path(app_dir) / n8n_dir
        workflows = len(list(d.glob("*.json"))) if d.is_dir() else 0
    e = {
        "id": manifest.get("id"),
        "version": manifest.get("version") or "0.0.0",
        "title": manifest.get("title") or {},
        "summary": manifest.get("summary") or {},
        "layer": manifest.get("layer"),
        "kind": manifest.get("kind"),
        "provides": [{"name": c.get("name"), "type": c.get("type"),
                      "interface": c.get("interface")}
                     for c in (manifest.get("capabilities") or [])],
        "uses": [{"capability": u.get("capability"),
                  "strength": u.get("strength", "requires"),
                  "ops": u.get("ops") or []}
                 for u in (manifest.get("use") or [])],
        "connections": [{"id": c.get("id"), "required": bool(c.get("required", True))}
                        for c in (manifest.get("connections") or [])],
        "routing": routing,
        "volumes": (manifest.get("data") or {}).get("volumes") or [],
        "on_uninstall": (manifest.get("data") or {}).get("on_uninstall", "prompt"),
        "resources": manifest.get("resources") or {},
        "automations": {"n8n": bool(n8n_dir), "workflows": workflows,
                        "requires_stdlib": bp.get("requires_stdlib")},
        "runtime": _compose_facts(app_dir, manifest),
        "manifest_sha256": signing.sha256_bytes(
            (pathlib.Path(app_dir) / "app.json").read_bytes()),
    }
    if artifact:
        e["artifact"] = artifact
    return e


def build(out_dir=None, repo_name=None, base_url=None, sign_it=True,
          secret_path=None, keyring_path=None, source_dir=None):
    """Compile apps/ into a signed catalog. THIS is what turns the existing gallery into catalog #1.

    Layer 3 only: layers 1-2 are the chassis, not installable, so publishing them in a store index
    would advertise something the control plane refuses to install."""
    out = pathlib.Path(out_dir or DEFAULT_OUT)
    art_dir = out / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(source_dir or APPS)

    entries = []
    for m in sorted(src.glob("*/app.json")):
        manifest = json.loads(m.read_text(encoding="utf-8"))
        if manifest.get("layer") != 3:
            continue
        aid = manifest.get("id") or m.parent.name
        ver = manifest.get("version") or "0.0.0"
        name = f"{aid}-{ver}.zip"
        zpath, nfiles = pack(m.parent, art_dir / name, aid)
        art = {"name": name, "format": "zip", "files": nfiles,
               "size": zpath.stat().st_size, "sha256": signing.sha256_file(zpath),
               "url": (base_url.rstrip("/") + "/artifacts/" + name) if base_url
                      else "artifacts/" + name}
        entries.append(entry_from_manifest(manifest, m.parent, art))

    entries.sort(key=lambda e: e["id"])
    index = {
        "format": INDEX_FORMAT,
        "repo": {
            "name": repo_name or os.getenv("DEPLOYMENT_NAME", "bina-platform") + " app catalog",
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artifact_base": (base_url.rstrip("/") + "/artifacts/") if base_url else "artifacts/",
            "mirrors": [],
        },
        "entries": entries,
    }
    idx_path = out / INDEX_NAME
    # The signature covers the BYTES ON DISK, so the serialisation must be the one that is written
    # — never re-serialised at verify time. (F-Droid signs the file hash for the same reason.)
    signing.write_lf(idx_path,
                     json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    sig_path = out / SIG_NAME
    if sign_it:
        env = signing.sign_envelope(idx_path, secret_path, keyring_path)
        signing.write_lf(sig_path,
                         json.dumps(env, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    elif sig_path.exists():
        sig_path.unlink()
    return out, index


# ── index load + verify ───────────────────────────────────────────────────────
class IndexError_(Exception):
    pass


def load_index(ref, keyring_path=None, require_signature=True):
    """Fetch an index (path or URL) and REFUSE it unless its signature verifies.

    Returns (index_dict, meta). `meta.signature` says exactly what was proved."""
    raw, where = fetch(ref)
    sig_ref = _sibling(ref, SIG_NAME)
    env = None
    try:
        sraw, _ = fetch(sig_ref)
        env = json.loads(sraw.decode("utf-8"))
    except Exception as e:
        if require_signature:
            raise IndexError_(f"no signature at {sig_ref} ({e.__class__.__name__}) — an unsigned "
                              f"index is refused; pass --insecure to read it anyway")
    if env is not None:
        ok, why = signing.verify_envelope(env, raw, keyring_path)
        if not ok:
            raise IndexError_(f"index REFUSED: {why}")
        sig_state = why
    else:
        sig_state = "UNSIGNED — nothing about this index is verified"
    try:
        index = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise IndexError_(f"index is not valid JSON: {e}")
    if index.get("format") != INDEX_FORMAT:
        raise IndexError_(f"unsupported index format '{index.get('format')}' "
                          f"(expected {INDEX_FORMAT})")
    return index, {"source": where, "signature": sig_state,
                   "key_id": (env or {}).get("key_id"),
                   "signed_at": (env or {}).get("signed_at"),
                   "entries": len(index.get("entries") or [])}


def find_entry(index, app_id):
    for e in (index.get("entries") or []):
        if e.get("id") == app_id:
            return e
    return None


def artifact_url(index, entry, index_ref):
    """Resolve an entry's artifact reference against the index location (relative URLs are the
    default so a catalog directory can be moved or mirrored wholesale)."""
    url = (entry.get("artifact") or {}).get("url") or ""
    if re.match(r"^[a-z]+://", url) or pathlib.Path(url).is_absolute():
        return url
    return _sibling(index_ref, url)


# ── disclosure (roadmap item 9) ───────────────────────────────────────────────
def disclose(entry, cat=None, state=None, manifest=None, app_dir=None):
    """What installing this app will actually do — computed, never hand-written.

    Order is deliberate and is the finding from Home Assistant / F-Droid Anti-Features / Flathub:
    CREDENTIALS FIRST. Everything else on the list is reversible; a secret handed to an app is not.
    Then: what runs as root-equivalent, what else gets installed, what it claims, what it costs.
    """
    if entry is None and manifest is not None:
        entry = entry_from_manifest(manifest, app_dir)
    provs = _providers_catalog()
    creds = []
    for c in (entry.get("connections") or []):
        meta = provs.get(c["id"], {})
        creds.append({"id": c["id"], "required": c.get("required", True),
                      "title": meta.get("title") or c["id"],
                      "title_he": meta.get("title_he") or "",
                      "kind": meta.get("kind") or "unknown"})

    rt = entry.get("runtime") or {}
    powers = []
    if rt.get("docker_socket"):
        powers.append({"level": "critical", "id": "docker-socket",
                       "text": "Mounts the Docker socket — this is root-equivalent control of the "
                               "whole machine, including every other app and its data."})
    if rt.get("privileged"):
        powers.append({"level": "critical", "id": "privileged",
                       "text": "Runs a privileged container — it can escape to the host."})
    for hp in (rt.get("host_paths") or []):
        if "docker.sock" in hp:
            continue
        powers.append({"level": "warn", "id": "host-path",
                       "text": f"Mounts a host path: {hp}"})
    for prt in (rt.get("ports") or []):
        powers.append({"level": "warn", "id": "host-port",
                       "text": f"Publishes a port on the host: {prt}"})
    if any(r.get("auth") == "none" for r in (entry.get("routing") or [])):
        powers.append({"level": "warn", "id": "no-auth",
                       "text": "Publishes a route with NO single-sign-on in front of it."})
    if (entry.get("automations") or {}).get("n8n"):
        n = entry["automations"].get("workflows") or 0
        powers.append({"level": "info", "id": "automations",
                       "text": f"Imports {n} workflow(s) into the shared n8n automation engine "
                               f"on install, and removes them on disable."})

    pulls, conflicts, notes = [], [], []
    if cat is not None and state is not None and entry.get("id") in cat:
        # resolve() already computes the transitive provider closure and every diagnostic — the
        # store must never grow a second, subtly different dependency solver.
        order, diags = reconcile.resolve(cat, state, roots=[entry["id"]])
        already = reconcile.enabled_ids(state, cat)
        for aid in order:
            if aid == entry["id"] or aid in already:
                continue
            t = (cat[aid].get("title") or {})
            pulls.append({"id": aid, "title": t.get("he") or t.get("en") or aid,
                          "layer": cat[aid].get("layer")})
        for lvl, msg in diags:
            if lvl == "error":
                conflicts.append(msg)
            elif "pulled in as provider" in msg or "bound to" in msg:
                notes.append(msg)

    hosts = []
    for r in (entry.get("routing") or []):
        if not r.get("host"):
            continue
        hosts.append({"host": r["host"], "url": f"http://{r['host']}.localhost",
                      "port": r.get("port"), "auth": r.get("auth", "sso"),
                      "tile": r.get("tile", False)})

    return {
        "id": entry.get("id"),
        "version": entry.get("version"),
        "title": entry.get("title") or {},
        "summary": entry.get("summary") or {},
        "layer": entry.get("layer"),
        "kind": entry.get("kind"),
        "credentials": creds,
        "powers": powers,
        "capabilities_used": entry.get("uses") or [],
        "capabilities_provided": entry.get("provides") or [],
        "pulls_in": pulls,
        "hosts": hosts,
        "volumes": entry.get("volumes") or [],
        "on_uninstall": entry.get("on_uninstall", "prompt"),
        "resources": entry.get("resources") or {},
        "images": rt.get("images") or [],
        "services": rt.get("services") or [],
        "automations": entry.get("automations") or {},
        "conflicts": conflicts,
        "notes": notes,
        "artifact": entry.get("artifact"),
    }


def format_disclosure(d, signature=None):
    """Plain-text disclosure for the CLI. Same content as the UI sheet, same order."""
    t = d.get("title") or {}
    name = t.get("en") or t.get("he") or d.get("id")
    out = [f"", f"  {name}  ({d.get('id')} v{d.get('version')})  layer {d.get('layer')} · "
                f"{d.get('kind')}"]
    s = (d.get("summary") or {}).get("en") or (d.get("summary") or {}).get("he") or ""
    if s:
        out.append(f"  {s}")
    if signature:
        out.append(f"  provenance: {signature}")
    out.append("")
    creds = d.get("credentials") or []
    out.append(f"  CREDENTIALS IT WILL HOLD ({len(creds)})")
    if creds:
        for c in creds:
            out.append(f"    ! {c['title']}  [{c['kind']}]"
                       f"{'' if c['required'] else '  (optional)'}")
    else:
        out.append("    (none — this app asks for no secrets)")
    pw = d.get("powers") or []
    if pw:
        out.append("")
        out.append("  WHAT IT CAN DO ON THIS MACHINE")
        for p in pw:
            mark = {"critical": "!!", "warn": " !", "info": "  "}.get(p["level"], "  ")
            out.append(f"   {mark} {p['text']}")
    if d.get("pulls_in"):
        out.append("")
        out.append("  ALSO INSTALLED (pulled in as providers)")
        for p in d["pulls_in"]:
            out.append(f"      {p['title']} ({p['id']}, layer {p['layer']})")
    if d.get("capabilities_used"):
        out.append("")
        out.append("  CAPABILITIES USED")
        for u in d["capabilities_used"]:
            ops = f"  ops: {', '.join(u['ops'])}" if u.get("ops") else ""
            out.append(f"      {u['capability']}  [{u.get('strength', 'requires')}]{ops}")
    if d.get("capabilities_provided"):
        out.append("")
        out.append("  CAPABILITIES PROVIDED")
        for c in d["capabilities_provided"]:
            out.append(f"      {c['name']}  [{c.get('type')}]")
    if d.get("hosts"):
        out.append("")
        out.append("  ROUTES CLAIMED")
        for h in d["hosts"]:
            out.append(f"      {h['url']} -> :{h['port']}  auth={h['auth']}"
                       f"{'  + console tile' if h.get('tile') else ''}")
    if d.get("volumes"):
        out.append("")
        out.append(f"  STORAGE  volumes: {', '.join(d['volumes'])}  "
                   f"(on uninstall: {d.get('on_uninstall')})")
    r = d.get("resources") or {}
    if r or d.get("images"):
        out.append("")
        out.append(f"  COST  cpus: {r.get('cpus', '—')}  memory: {r.get('memory', '—')}  "
                   f"images: {', '.join(d.get('images') or []) or '—'}")
    a = d.get("artifact") or {}
    if a:
        out.append("")
        out.append(f"  ARTIFACT  {a.get('name')}  {a.get('size')} bytes  "
                   f"sha256:{str(a.get('sha256'))[:16]}…")
    if d.get("conflicts"):
        out.append("")
        out.append("  REFUSALS")
        for c in d["conflicts"]:
            out.append(f"    x {c}")
    out.append("")
    return "\n".join(out)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cmd_build(a):
    out, index = build(a.out, repo_name=a.name, base_url=a.base_url,
                       sign_it=not a.unsigned, source_dir=a.source,
                       secret_path=a.key, keyring_path=a.keyring)
    print(f"catalog built: {out}")
    print(f"  {len(index['entries'])} entry(ies): "
          f"{', '.join(e['id'] for e in index['entries'])}")
    for e in index["entries"]:
        art = e["artifact"]
        print(f"    {e['id']:<24} v{e['version']:<8} {art['size']:>8} B  "
              f"sha256:{art['sha256'][:16]}…  ({art['files']} files)")
    if not a.unsigned:
        env = json.loads((out / SIG_NAME).read_text(encoding="utf-8"))
        print(f"  signed: ed25519 key {env['key_id']} at {env['signed_at']}")
    else:
        print("  UNSIGNED (--unsigned) — this index will be refused on read")
    return 0


def _cmd_verify(a):
    ref = a.ref or str(DEFAULT_OUT / INDEX_NAME)
    index, meta = load_index(ref, require_signature=not a.insecure)
    print(f"index: {meta['source']}")
    print(f"  {meta['signature']}")
    print(f"  {meta['entries']} entry(ies), generated {index['repo'].get('generated')}")
    bad = 0
    for e in index.get("entries") or []:
        art = e.get("artifact") or {}
        url = artifact_url(index, e, ref)
        try:
            blob, _ = fetch(url)
        except Exception as ex:
            print(f"  MISSING  {e['id']}: {url} ({ex.__class__.__name__})")
            bad += 1
            continue
        got = signing.sha256_bytes(blob)
        if got != art.get("sha256"):
            print(f"  TAMPERED {e['id']}: sha256 {got[:16]}… != {str(art.get('sha256'))[:16]}…")
            bad += 1
        else:
            print(f"  ok       {e['id']:<24} v{e['version']:<8} sha256:{got[:16]}…")
    if bad:
        print(f"VERIFY FAILED — {bad} entry(ies) do not match the signed index")
        return 1
    print("VERIFY OK — signature and every per-entry hash match")
    return 0


def _cmd_list(a):
    ref = a.ref or str(DEFAULT_OUT / INDEX_NAME)
    index, meta = load_index(ref, require_signature=not a.insecure)
    if a.json:
        print(json.dumps({"meta": meta, "entries": index["entries"]},
                         indent=2, ensure_ascii=False))
        return 0
    print(f"{index['repo'].get('name')}  —  {meta['signature']}")
    for e in index.get("entries") or []:
        t = e.get("title") or {}
        print(f"  {e['id']:<24} v{e.get('version'):<8} {(t.get('en') or t.get('he') or '')[:38]:<40}"
              f" {len(e.get('connections') or [])} cred(s)")
    return 0


def _cmd_show(a):
    ref = a.index or str(DEFAULT_OUT / INDEX_NAME)
    index, meta = load_index(ref, require_signature=not a.insecure)
    e = find_entry(index, a.id)
    if not e:
        print(f"no entry '{a.id}' in {ref}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(e, indent=2, ensure_ascii=False))
        return 0
    cat, state = reconcile.load_catalog(), reconcile.load_state()
    print(format_disclosure(disclose(e, cat if a.id in cat else None,
                                     state if a.id in cat else None),
                            meta["signature"]))
    return 0


def _cmd_keygen(a):
    kid, pub = signing.keygen(a.label or "")
    print(f"generated ed25519 signing key")
    print(f"  key id     : {kid}")
    print(f"  public key : {pub}")
    print(f"  secret     : {signing.SECRET_KEY.name} (gitignored — back it up, it cannot be "
          f"regenerated)")
    print(f"  trusted in : {signing.KEYRING.relative_to(REPO).as_posix()}")
    return 0


def _cmd_trust(a):
    kid = signing.trust(a.public_key, a.label or "")
    if a.key_id and a.key_id != kid:
        print(f"REFUSED: this public key hashes to '{kid}', not '{a.key_id}' — the id and the key "
              f"do not belong together", file=sys.stderr)
        return 1
    print(f"trusted key {kid}  ({a.label or 'no label'})")
    print("  this deployment will now accept any catalog index signed by that key.")
    return 0


def _cmd_keys(a):
    kr = signing.load_keyring()
    keys = kr.get("keys") or {}
    if not keys:
        print("no trusted keys — run: bbox catalog keygen")
        return 0
    for kid, k in sorted(keys.items()):
        print(f"  {kid}  {k.get('alg')}  {k.get('label') or ''}  added {k.get('added')}")
        print(f"      {k.get('public_key')}")
    return 0


def _cmd_selftest(a):
    ok, detail = signing.selftest()
    print(("OK   " if ok else "FAIL ") + detail)
    return 0 if ok else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="bbox catalog",
                                 description="signed app catalog (F-Droid index-v2 model)")
    sub = ap.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("build", help="compile apps/ into a signed catalog index + artifacts")
    p.add_argument("--out", help=f"output dir (default {DEFAULT_OUT.relative_to(REPO).as_posix()})")
    p.add_argument("--name", help="repo display name")
    p.add_argument("--base-url", help="absolute base URL the artifacts will be served from")
    p.add_argument("--unsigned", action="store_true", help="skip signing (the index is then refused on read)")
    # A publisher is not necessarily this repo. --source/--key/--keyring are what let a third-party
    # author build and sign their OWN catalog with this same tool, from a directory of app folders.
    p.add_argument("--source", help="directory of app folders to publish (default: apps/)")
    p.add_argument("--key", help="signing key file (default: .catalog-signing-key.json)")
    p.add_argument("--keyring", help="keyring the key is registered in")
    p.set_defaults(fn=_cmd_build)

    p = sub.add_parser("verify", help="verify an index signature and every artifact hash")
    p.add_argument("ref", nargs="?", help="path or URL to index-v1.json")
    p.add_argument("--insecure", action="store_true", help="allow an unsigned index")
    p.set_defaults(fn=_cmd_verify)

    p = sub.add_parser("list", help="list entries in an index")
    p.add_argument("ref", nargs="?")
    p.add_argument("--json", action="store_true")
    p.add_argument("--insecure", action="store_true")
    p.set_defaults(fn=_cmd_list)

    p = sub.add_parser("show", help="pre-install disclosure for one entry")
    p.add_argument("id")
    p.add_argument("--index")
    p.add_argument("--json", action="store_true")
    p.add_argument("--insecure", action="store_true")
    p.set_defaults(fn=_cmd_show)

    p = sub.add_parser("keygen", help="create this deployment's signing key")
    p.add_argument("--label")
    p.set_defaults(fn=_cmd_keygen)

    p = sub.add_parser("trust", help="pin a third-party public key (the ONE trust decision)")
    p.add_argument("key_id", nargs="?")
    p.add_argument("public_key")
    p.add_argument("--label")
    p.set_defaults(fn=_cmd_trust)

    p = sub.add_parser("keys", help="list trusted keys")
    p.set_defaults(fn=_cmd_keys)

    p = sub.add_parser("selftest", help="RFC 8032 test vectors for the signature implementation")
    p.set_defaults(fn=_cmd_selftest)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except IndexError_ as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
