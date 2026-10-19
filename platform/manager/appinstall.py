#!/usr/bin/env python3
"""appinstall — `bbox app install <ref>`: install an app that is not a folder in this repo.

A ref is one of three things, and the difference that matters is WHAT PROVES THE BYTES:

  <app-id>            an entry in a signed catalog index. The index signature covers the entry's
                      sha256, so the artifact is verified against a signature. This is the good path.
  <url> | <path>      a zip/tarball. Nothing proves it, so `--sha256 <hex>` is REQUIRED and is
                      checked, or `--allow-unverified` must be passed explicitly and is reported
                      loudly in the result. There is no silent unverified install.
  <dir>               a local directory containing app.json — for an app author iterating. Same
                      validation and disclosure, no hash (there is no artifact to hash).

ORDER OF OPERATIONS, and why each step is before the next:

  1. fetch                  — cheap, and nothing is trusted yet
  2. verify hash            — before ANY of the archive is read as structure
  3. unpack (traversal-safe)— into a temp dir, never into apps/
  4. validate the manifest  — reconcile.validate() over the REAL catalog with the candidate spliced
                              in. Structural + type validation and the id/route-host/console-tile
                              conflict detection all already live there; reimplementing any of it
                              would create a second definition of "valid app".
  5. resolve                — reconcile.resolve(roots=[id]) for the provider closure and conflicts
  6. disclose               — the user sees credentials/powers/routes/cost BEFORE step 7
  7. place + enable         — move into apps/<id>, write platform.state.yaml, `reconcile render`,
                              then the EXISTING lifecycle brings the containers up.

Steps 1-6 mutate nothing. If step 7 fails part-way it is rolled back (the directory is removed and
the state entry withdrawn), because a half-installed app is worse than a failed install.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import catalog                                             # noqa: E402
import reconcile                                           # noqa: E402
import signing                                             # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = REPO / "apps"
STATE = REPO / "platform.state.yaml"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class InstallError(Exception):
    pass


# ── platform.state.yaml (the one file the platform writes) ────────────────────
def _write_lf(path, text):
    """Always LF. Python's text mode translates '\\n' to '\\r\\n' on Windows, so a state file
    edited on a laptop came back with every one of its 76 lines rewritten — an unreviewable diff
    for a one-line change, and, for the index, an OS-dependent sha256. The platform's files have
    one line ending."""
    pathlib.Path(path).write_text(text, encoding="utf-8", newline="\n")


def state_has(aid):
    return re.search(rf"^\s+{re.escape(aid)}:\s*[\{{]", STATE.read_text(encoding="utf-8"), re.M)


def state_upsert(aid, enabled, by="install"):
    """Add or update apps.<id> — delegated to reconcile.set_disposition(), the one writer.

    This carried its own regex + append logic, making it one of four independent writers of
    platform.state.yaml. reconcile owns that format: it holds the only reader (`disposition()`), so
    it holds the writer too. `create=True` is the install path — an app being installed by reference
    has no entry yet.
    """
    try:
        return reconcile.set_disposition(aid, "enabled" if enabled else "disabled",
                                         by=by, create=True)
    except ValueError as e:
        raise InstallError(str(e))


def state_remove(aid):
    txt = STATE.read_text(encoding="utf-8")
    new = re.sub(rf"^\s+{re.escape(aid)}:\s*\{{[^}}]*\}}.*\n", "", txt, count=1, flags=re.M)
    _write_lf(STATE, new)


# ── resolve a ref to a candidate app directory ────────────────────────────────
def _looks_like_id(ref):
    return bool(ID_RE.match(ref)) and not pathlib.Path(ref).exists()


def match_known_hash(sha, index_ref=None):
    """Is this blob already named by a signed index we trust?

    An uploaded file or a bare URL carries no signature of its own — but if its sha256 is one the
    signed catalog already vouches for, it IS verified, by exactly the chain that verifies an
    install-by-id. This is what makes 'download the artifact, hand it to a colleague on a stick,
    upload it' a verified path rather than a leap of faith."""
    iref = index_ref or str(catalog.DEFAULT_OUT / catalog.INDEX_NAME)
    try:
        index, meta = catalog.load_index(iref, require_signature=True)
    except Exception:
        return None, None
    for e in index.get("entries") or []:
        if (e.get("artifact") or {}).get("sha256") == sha:
            return e, meta
    return None, None


def stage(ref, index_ref=None, expect_sha=None, allow_unverified=False, workdir=None,
          insecure_index=False):
    """Fetch + verify + unpack. Returns (app_dir, provenance dict). Mutates nothing outside tmp."""
    work = pathlib.Path(workdir or tempfile.mkdtemp(prefix="bbox-install-"))
    prov = {"ref": ref, "verified": False, "how": None, "index": None, "entry": None}

    # (a) a local directory an author is iterating on
    p = pathlib.Path(ref)
    if p.is_dir() and (p / "app.json").is_file():
        dest = work / p.name
        shutil.copytree(p, dest, ignore=shutil.ignore_patterns(*catalog.SKIP_PARTS, "*.pyc"))
        prov.update(how="local directory (no artifact, nothing to hash)", verified=False,
                    unverified_ok=True)
        return dest, prov

    # (b) an id in a signed index
    if _looks_like_id(ref):
        iref = index_ref or str(catalog.DEFAULT_OUT / catalog.INDEX_NAME)
        try:
            index, meta = catalog.load_index(iref, require_signature=not insecure_index)
        except catalog.IndexError_ as e:
            # A refused index is an ordinary, expected outcome (untrusted key, bad signature,
            # tampered bytes) and must read as one — not as a stack trace.
            raise InstallError(str(e))
        entry = catalog.find_entry(index, ref)
        if not entry:
            raise InstallError(f"no app '{ref}' in {iref} "
                               f"(have: {', '.join(e['id'] for e in index.get('entries') or [])})")
        url = catalog.artifact_url(index, entry, iref)
        expect_sha = (entry.get("artifact") or {}).get("sha256")
        prov.update(index=meta, entry=entry, artifact_url=url)
        blob, where = catalog.fetch(url)
        got = signing.sha256_bytes(blob)
        if got != expect_sha:
            raise InstallError(f"artifact hash mismatch for '{ref}': got {got}, the signed index "
                               f"says {expect_sha} — REFUSED")
        prov.update(verified=True,
                    how=f"signed index ({meta['signature']}) + artifact sha256 match")
    else:
        # (c) a raw URL or file. Nothing signs it, so an explicit hash or an explicit override.
        blob, where = catalog.fetch(ref)
        got = signing.sha256_bytes(blob)
        known, kmeta = match_known_hash(got, index_ref)
        if expect_sha:
            if got != expect_sha:
                raise InstallError(f"artifact hash mismatch: got {got}, expected {expect_sha} "
                                   f"— REFUSED")
            prov.update(verified=True, how="operator-supplied --sha256 match")
        elif known:
            prov.update(verified=True, entry=known, index=kmeta,
                        how=f"sha256 matches entry '{known['id']}' v{known.get('version')} in the "
                            f"signed catalog ({kmeta['signature']})")
        elif allow_unverified:
            prov.update(verified=False, unverified_ok=True,
                        how=f"UNVERIFIED (--allow-unverified). sha256 of what was fetched: {got}")
        else:
            raise InstallError(
                f"'{ref}' is not in a signed index and no --sha256 was given, so nothing proves "
                f"these bytes. Either install it by id from a signed catalog, pass "
                f"--sha256 {got} after checking it against the publisher, or pass "
                f"--allow-unverified and accept that.")
        prov["artifact_url"] = where
    prov["artifact_sha256"] = got
    prov["artifact_size"] = len(blob)

    arc = work / "artifact.bin"
    work.mkdir(parents=True, exist_ok=True)
    arc.write_bytes(blob)
    app_dir = catalog.unpack(arc, work / "x")
    arc.unlink(missing_ok=True)
    return app_dir, prov


# ── validate the candidate against the LIVE catalog ───────────────────────────
def inspect(app_dir, prov=None):
    """Everything that must be true before anything is written. Returns (manifest, cat, state,
    disclosure, refusals)."""
    app_dir = pathlib.Path(app_dir)
    mf = app_dir / "app.json"
    if not mf.is_file():
        raise InstallError("no app.json in the artifact — not an app")
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InstallError(f"app.json is not valid JSON: {e}")

    aid = manifest.get("id")
    refusals = []
    if not aid or not ID_RE.match(str(aid)):
        raise InstallError(f"app id '{aid}' is not a valid id (^[a-z][a-z0-9-]{{1,30}}$)")
    if manifest.get("layer") != 3:
        refusals.append(f"layer {manifest.get('layer')} — only layer-3 apps are installable; "
                        f"layers 1-2 are the platform chassis and ship with it")

    cat = reconcile.load_catalog()
    state = reconcile.load_state()
    if aid in cat:
        refusals.append(f"id conflict: '{aid}' is already in the catalog at "
                        f"{cat[aid]['_dir'].relative_to(REPO).as_posix()} — uninstall it first")
    if (APPS / aid).exists():
        refusals.append(f"apps/{aid} already exists on disk")

    # Splice the candidate into the REAL catalog and run the compiler's own validator: structural
    # + type checks, and the route-host / console-module claim arbitration that only makes sense
    # against every other installed app.
    cand = dict(manifest)
    cand["_dir"] = app_dir
    trial = dict(cat)
    trial[aid] = cand
    errs, _ = reconcile.validate(trial)
    mine = [e for e in errs if e.startswith(f"{aid}:") or aid in e]
    others = [e for e in errs if e not in mine]
    refusals.extend(mine)
    if others:
        refusals.append(f"the existing catalog does not validate ({len(others)} error(s)) — "
                        f"fix that before installing anything")

    entry = catalog.entry_from_manifest(manifest, app_dir,
                                        artifact=(prov or {}).get("entry", {}).get("artifact")
                                        if isinstance((prov or {}).get("entry"), dict) else None)
    dis = catalog.disclose(entry, trial if not refusals else None,
                           state if not refusals else None)
    refusals.extend(dis.get("conflicts") or [])
    return manifest, cat, state, dis, refusals


# ── place + enable through the existing lifecycle ─────────────────────────────
def _render():
    r = subprocess.run([sys.executable, str(REPO / "platform" / "manager" / "reconcile.py"),
                        "render"], cwd=str(REPO), capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise InstallError("reconcile render failed: "
                           + (r.stderr or r.stdout or "").strip()[-500:])
    return (r.stdout or "").strip().splitlines()


def place(app_dir, aid, enable=True):
    """Move into apps/<id>, register in platform.state.yaml, recompile. Rolls back on failure."""
    dest = APPS / aid
    if dest.exists():
        raise InstallError(f"apps/{aid} already exists")
    shutil.copytree(app_dir, dest)
    added = False
    try:
        state_upsert(aid, enable)
        added = True
        out = _render()
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        if added:
            state_remove(aid)
            try:
                _render()
            except Exception:
                pass
        raise
    return dest, out


def start_services(services):
    """Bring the app up with the canonical compose invocation (scripts/dc) — the same one `bbox
    run` uses, so an installed app is started exactly like every other app."""
    if not services:
        return {"started": [], "note": "app owns no containers (kind: blueprint/library)"}
    r = subprocess.run(["bash", "scripts/dc", "up", "-d", *services],
                       cwd=str(REPO), capture_output=True, text=True, timeout=1800)
    return {"started": services, "rc": r.returncode,
            "out": (r.stdout or "")[-2000:], "err": (r.stderr or "")[-2000:]}


def install_ref(ref, index_ref=None, expect_sha=None, allow_unverified=False, enable=True,
                start=False, dry_run=False, insecure_index=False, workdir=None):
    """The whole flow. Returns a result dict; raises InstallError on refusal."""
    app_dir, prov = stage(ref, index_ref, expect_sha, allow_unverified, workdir, insecure_index)
    manifest, cat, state, dis, refusals = inspect(app_dir, prov)
    aid = manifest["id"]
    result = {"id": aid, "version": manifest.get("version"), "provenance": prov,
              "disclosure": dis, "refusals": refusals, "installed": False}
    if refusals:
        raise InstallError("REFUSED — " + "; ".join(refusals))
    if dry_run:
        return result
    dest, out = place(app_dir, aid, enable)
    result.update(installed=True, path=dest.relative_to(REPO).as_posix(), render=out,
                  enabled=enable, services=dis.get("services") or [])
    if start and enable:
        result["start"] = start_services(dis.get("services") or [])
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="bbox app install",
                                 description="install an app from a catalog id, a URL or a file")
    ap.add_argument("ref", help="catalog entry id | http(s) URL to a zip/tarball | local path")
    ap.add_argument("--index", help="catalog index (path or URL). Default: the local built catalog")
    ap.add_argument("--sha256", help="expected artifact hash when installing a raw URL/file")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="install bytes nothing vouches for (says so, loudly, in the result)")
    ap.add_argument("--insecure-index", action="store_true", help="accept an unsigned index")
    ap.add_argument("--dry-run", action="store_true", help="disclose and stop — writes nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="skip the interactive confirmation")
    ap.add_argument("--no-start", action="store_true", help="install and enable, but do not `up`")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        pre = install_ref(a.ref, a.index, a.sha256, a.allow_unverified,
                          enable=True, start=False, dry_run=True,
                          insecure_index=a.insecure_index)
    except InstallError as e:
        print(f"install refused: {e}", file=sys.stderr)
        return 1

    prov = pre["provenance"]
    if not a.json:
        print(catalog.format_disclosure(pre["disclosure"], prov.get("how")))
        if not prov.get("verified"):
            print("  ** these bytes are NOT verified. Nothing proves who produced them. **\n")
    if a.dry_run:
        if a.json:
            print(json.dumps(pre, indent=2, ensure_ascii=False, default=str))
        return 0
    if not a.yes:
        try:
            ans = input(f"  install {pre['id']} v{pre['version']}? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("aborted — nothing was written.")
            return 1

    try:
        res = install_ref(a.ref, a.index, a.sha256, a.allow_unverified, enable=True,
                          start=not a.no_start, insecure_index=a.insecure_index)
    except InstallError as e:
        print(f"install failed: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"installed {res['id']} v{res['version']} -> {res['path']}")
        print(f"  provenance: {res['provenance'].get('how')}")
        for ln in res.get("render") or []:
            print("  " + ln)
        st = res.get("start") or {}
        if st.get("started"):
            print(f"  started: {', '.join(st['started'])} (rc={st.get('rc')})")
        elif st.get("note"):
            print(f"  {st['note']}")
        print(f"  it now appears in the app store (apps.localhost) as installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
