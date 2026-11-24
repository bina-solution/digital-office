#!/usr/bin/env python3
"""test_deployment_archive_folders — a store that was a FOLDER (`moved_from: path:`) is carried from where it lives (DGO-2019).

    python3 scripts/test_deployment_archive_folders.py
    ARCHIVER_PATH=<dir>/scripts/deployment-archive.py python3 …   # against another archiver: <dir>/platform/manager
                                                                  # beside it (it imports datamoves from there)

apitools' OCR store was its source tree's ./storage; since DGO-2019 it is data/apitools/storage, moved once by the
engine. An app-scoped export takes the app's DECLARED paths — the new folder — so on an office whose move waits (the
HP's C:) the store, still in its old folder, was left out of the archive without a word: its document signer with it
(the reader of apitools' move). Held here, with the REAL cmd_export --app on a temp checkout (no docker): the old
folder is carried while the move is not proven, and not once it is; and an import accepts a bind for the old folder,
which the next `bbox run` moves, as it accepts a store's old volume.
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


def checkout():
    """A temp checkout with one app whose store came from its source tree's ./storage, the old folder holding a file."""
    repo = pathlib.Path(tempfile.mkdtemp(prefix="folders-"))
    app = repo / "apps" / "app"
    (app / "storage").mkdir(parents=True)
    (app / "storage" / "dev_signer.p12").write_text("x", encoding="utf-8")
    (app / "app.json").write_text(json.dumps({"id": "app", "compose": "docker-compose.yml", "data": {
        "volumes": [], "paths": ["data/app/storage"], "moved_from": {"data/app/storage": "path:apps/app/storage"}}}),
        encoding="utf-8")
    (app / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return repo


def archiver(repo):
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
    A.app_sql_decls = lambda apps: []
    A.say = lambda s: None
    return A


def export(repo):
    """The REAL cmd_export --app app: (exit, the folders it tarred)."""
    A = archiver(repo)
    tarred = []

    def tar(src, part, exclude=()):
        tarred.append(pathlib.Path(src).relative_to(repo).as_posix())
        pathlib.Path(part).write_bytes(b"x")
    A._tar_dir_as_root = tar
    out = pathlib.Path(tempfile.mkdtemp(prefix="folders-out-"))
    try:
        rc = A.cmd_export(argparse.Namespace(out=str(out), mode="full", force=False, quiesce=False, app="app"))
    except SystemExit as e:
        rc = f"SystemExit: {e}"
    return rc, tarred


def main():
    # an office that waits: the store is still in its old folder, the new one not made — carried from the old one
    repo = checkout()
    rc, tarred = export(repo)
    check("waiting: the export ends well", rc in (0, None), rc)
    check("waiting: the old folder is carried (its signer with it)", "apps/app/storage" in tarred, tarred)
    # its move proven (moved, compared, verified): the store is the new folder — the old one is a copy, never carried
    (repo / "data" / "app" / "storage").mkdir(parents=True)
    (repo / "data" / "app" / "storage" / "dev_signer.p12").write_text("x", encoding="utf-8")
    (repo / "data" / ".moves" / "app").mkdir(parents=True)
    (repo / "data" / ".moves" / "app" / "storage.json").write_text(
        json.dumps({"moved_at": "t", "verified": True}), encoding="utf-8")
    rc, tarred = export(repo)
    check("moved: the new folder is carried", "data/app/storage" in tarred, tarred)
    check("moved: the old folder is not", "apps/app/storage" not in tarred, tarred)
    # an import onto an office that moved: a bind for the old folder (an archive of an office that waited) is accepted —
    # the next `bbox run` moves it — as a store's old volume is
    A = archiver(repo)
    A.writable_binds = lambda cfg: {"data/app/storage"}
    A.path_owner_map = lambda: ({"data/app/storage": "app"}, {})
    art = {"binds/apps__app__storage.tar.gz": {"kind": "bind", "note": "apps/app/storage"}}
    skips = A.restore_skips(art, {})
    check("import: the old folder's bind is accepted", "binds/apps__app__storage.tar.gz" not in skips, skips)
    for f in FAIL:
        print(f"FAIL {f}")
    print("test_deployment_archive_folders: " + ("all passed" if not FAIL else f"{len(FAIL)} failed"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
