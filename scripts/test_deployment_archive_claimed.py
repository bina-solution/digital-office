#!/usr/bin/env python3
"""test_deployment_archive_claimed — a store an app's own backup claims is never tarred live from its folder (DGO-2019).

    python3 scripts/test_deployment_archive_claimed.py
    ARCHIVER_PATH=<dir>/scripts/deployment-archive.py python3 …   # against another archiver: <dir>/platform/manager
                                                                  # beside it (it imports datamoves from there)

An app's hooks/backup claims a volume it carries itself — `SKIPVOL <volume>`: a database it dumps (glitchtip, n8n,
postgres, authentik, Plane), a queue it leaves out on purpose (redis). Once that store moves to the DGO folder's
data/<app>/<store>, the folder is a bind, and the binds step tarred it: a live copy of a database's files beside the
dump, which a restore would lay over the dump's (the secret guards' second reader). Held here, with the REAL
cmd_export --app on a temp checkout (no docker): the claimed store's folder is not tarred and is said, an unclaimed
store of the same app is.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("ARCHIVER_PATH") or HERE / "deployment-archive.py")
FAIL: list[str] = []


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(f"{name}: {detail}")


def checkout(paths, moved):
    """A temp checkout with one app, its stores' folders each holding a file."""
    repo = pathlib.Path(tempfile.mkdtemp(prefix="claimed-"))
    app = repo / "apps" / "app"
    (app / "hooks").mkdir(parents=True)
    (app / "app.json").write_text(json.dumps({"id": "app", "compose": "docker-compose.yml",
                                              "data": {"volumes": [], "paths": paths, "moved_from": moved}}),
                                  encoding="utf-8")
    (app / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (app / "hooks" / "backup").write_text("#!/bin/sh\n", encoding="utf-8")
    for rel in paths:
        (repo / rel).mkdir(parents=True, exist_ok=True)
        (repo / rel / "a-file").write_text("x", encoding="utf-8")
    return repo


def export(repo, claims, out=None):
    """The REAL cmd_export --app app, to its end (no docker in --app scope): (exit, {folder: what it excluded}, what it
    said, the manifest's artifacts, the archiver, the archive directory). `claims`: the hook's SKIPVOL lines."""
    spec = importlib.util.spec_from_file_location("archiver", SRC)
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    A.REPO = repo
    A.read_env = lambda key: "acme" if key == "DEPLOYMENT_NAME" else ""
    A.project_name = lambda: "acme"
    A.engine_id = lambda: "engine"
    A._assert_gitignored = lambda p: None
    A.sh = lambda argv, env=None: ""
    A.installed_apps = lambda: [("apps", "app")]
    A.enabled_apps = lambda: [("apps", "app")]
    A._volume_exists = lambda v: False
    A._run_hook = lambda hook, args: {"artifacts": [], "facts": {}, "skipvols": list(claims)}
    A.app_sql_decls = lambda apps: []
    tarred, said = {}, []

    def tar(src, part, exclude=()):
        tarred[pathlib.Path(src).relative_to(repo).as_posix()] = list(exclude)
        pathlib.Path(part).write_bytes(b"x")
    A._tar_dir_as_root = tar
    A.say = lambda s: said.append(s)
    out = out or pathlib.Path(tempfile.mkdtemp(prefix="claimed-out-"))
    try:
        rc = A.cmd_export(argparse.Namespace(out=str(out), mode="full", force=False, quiesce=False, app="app"))
    except SystemExit as e:
        rc = f"SystemExit: {e}"
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8")).get("artifacts") or {}
    return rc, tarred, said, man, A, out


def main() -> int:
    # a database it dumps (its hook claims app_pg), files it does not
    repo = checkout(["data/app/db", "data/app/files"], {"data/app/db": "app_pg", "data/app/files": "app_files"})
    rc, tarred, said, man, A, out = export(repo, ["app_pg"])
    check("the export runs to its end", rc == 0, f"{rc} — {said[-3:]}")
    check("the claimed store's folder is never tarred", "data/app/db" not in tarred, f"{tarred}")
    check("…and is said, as its volume was", any("data/app/db" in s and "claimed by app" in s for s in said),
          f"{said[-6:]}")
    check("an unclaimed store of the same app is tarred", "data/app/files" in tarred, f"{tarred}")
    check("the manifest names the claimed folder as skipped, the app's",
          (man.get("binds/data__app__db.HANDLED") or {}).get("kind") == "skipped"
          and man["binds/data__app__db.HANDLED"].get("app") == "app", f"{sorted(man)}")
    check("…which an import's checks take as it is", "binds/data__app__db.HANDLED" not in A.restore_skips(
        man, {"services": {}}), "restore_skips names it")
    try:
        A._assert_app_owns("app", man)
    except SystemExit as e:
        check("…and an import --app app accepts", False, str(e))

    # an earlier run, before the claim, tarred the folder into this same directory: resumed, that tarball goes
    repo = checkout(["data/app/db"], {"data/app/db": "app_pg"})
    _, tarred, _, man, _, out = export(repo, [])
    check("unclaimed, the folder is tarred (the run before the claim)", "data/app/db" in tarred, f"{tarred}")
    rc, _, _, man, _, _ = export(repo, ["app_pg"], out)
    check("resumed with the claim: the earlier tarball is out of the manifest and off the disk",
          rc == 0 and "binds/data__app__db.tar.gz" not in man and not (out / "binds" / "data__app__db.tar.gz").exists(),
          f"{rc} {sorted(man)}")

    # a bind ABOVE the claimed store (the app's whole home beside its database): tarred, without the database
    repo = checkout(["data/app", "data/app/db"], {"data/app/db": "app_pg"})
    rc, tarred, _, man, _, _ = export(repo, ["app_pg"])
    check("the bind above is tarred, the claimed store left out of it",
          rc == 0 and tarred.get("data/app") == ["db"] and "data/app/db" not in tarred, f"{rc} {tarred}")
    for f in FAIL:
        print("FAIL", f)
    print("PASS test_deployment_archive_claimed" if not FAIL else f"{len(FAIL)} failure(s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
