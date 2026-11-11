#!/usr/bin/env python3
"""test_deployment_archive_shares — a volume has ONE owner; an app that mounts another's SHARES it (DGO-1510).

    python3 scripts/test_deployment_archive_shares.py
    ARCHIVER_PATH=<an older deployment-archive.py> python3 …   # the archiver cases against another archiver

`n8n_storage` was in the data.volumes of n8n AND any-concurrency, `cad_projects` of cad AND cad-api. So
`uninstall --purge` of any-concurrency (app-management removes data.volumes) deleted n8n's data, an export scoped to
any-concurrency carried n8n's volume, and importing that archive wrote n8n's data back to its day. Held here:
  - this checkout's manifests: one owner per volume; any-concurrency and cad-api name theirs in data.shares, so
    neither's purge list (data.volumes) holds the other's volume;
  - G26 refuses two owners, a share nobody owns, a share of its own volume, a share its compose does not mount;
  - the REAL cmd_export --app any-concurrency carries no n8n_storage and says where it is;
  - the REAL cmd_import of an archive made BEFORE (any-concurrency's scope, n8n_storage inside), with --app and
    without, never reaches the restore with n8n_storage in it.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SRC = pathlib.Path(os.environ.get("ARCHIVER_PATH") or HERE / "deployment-archive.py")
FAIL: list[str] = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(f"{name}: {detail}")


class Reached(Exception):
    pass


def archiver():
    A = load(SRC, "archiver")
    A.REPO = REPO                                     # this checkout's manifests, wherever the archiver file is
    A.read_env = lambda key: "acme" if key == "DEPLOYMENT_NAME" else ""
    A.project_name = lambda: "acme-here"
    A.engine_id = lambda: "engine-here"
    A._assert_gitignored = lambda p: None
    A.sh = lambda argv, env=None: ""
    return A


def exported(scope, out=None):
    """The REAL cmd_export --app <scope> into `out` (a new directory by default): (volumes it tarred, what it said),
    stopped at step 2c — or at the SystemExit it refuses with, as said[-1]."""
    A = archiver()
    tarred, said = [], []
    A.say = lambda s: said.append(s)
    A.app_hook = lambda root, aid, name: None
    A._volume_exists = lambda v: True

    def tar(vol, part):
        tarred.append(vol)
        pathlib.Path(part).write_bytes(b"x")
    A._tar_volume = tar

    def stop(apps):
        raise Reached()
    A.app_sql_decls = stop                            # step 2c: the volumes are done by then
    out = out or pathlib.Path(tempfile.mkdtemp(prefix="shares-export-"))
    try:
        A.cmd_export(argparse.Namespace(out=str(out), mode="full", force=False, quiesce=False, app=scope))
    except Reached:
        pass
    except SystemExit as e:
        said.append(f"SystemExit: {e}")
    exported.dir = out
    return tarred, said


def import_dir(d, only):
    """The REAL cmd_import of the archive in `d`, into another deployment: the artifacts it reaches its restore
    with (or the SystemExit it stops with), and what it said."""
    A = archiver()
    A.project_name = lambda: "another-deployment"
    said, reached = [], {}
    A.say = lambda s: said.append(s)

    def carried(artifacts):
        reached.update(artifacts)
        raise Reached()
    A.carried_skips = carried
    try:
        A.cmd_import(argparse.Namespace(dir=str(d), app=only, force=False, allow_shared_network=False))
        return {"ran to its end": True}, said
    except Reached:
        return reached, said
    except SystemExit as e:
        return {"SystemExit": str(e)}, said
    except FileNotFoundError as e:                   # an export that never saved its manifest
        return {"SystemExit": f"no archive: {e}"}, said


def old_archive(scope_in_archive, artifacts):
    """An archive made before data.shares: its manifest, with these artifacts, in a new directory."""
    A = archiver()
    d = pathlib.Path(tempfile.mkdtemp(prefix="shares-import-"))
    man = {"format_version": A.FORMAT_VERSION, "deployment_name": "old", "compose_project": "old-project",
           "engine": "engine-there", "mode": "full", "quiesced": False, "scope": {"app": scope_in_archive},
           "artifacts": {rel: {"kind": "volume", "sha256": "x", "bytes": 1, "note": "", "app": app}
                         for rel, app in artifacts.items()}}
    (d / "manifest.json").write_text(json.dumps(man))
    return d


def imported(scope_in_archive, only):
    """The REAL cmd_import of an old archive whose manifest carries n8n_storage under `scope_in_archive`."""
    return import_dir(old_archive(scope_in_archive, {"volumes/n8n_storage.tar.gz": "any-concurrency"}), only)


def main() -> int:
    # this checkout's manifests: one owner per volume
    def data(aid):
        return json.loads((REPO / "apps" / aid / "app.json").read_text(encoding="utf-8")).get("data") or {}
    for sharer, owner, vol in (("any-concurrency", "n8n", "n8n_storage"), ("cad-api", "cad", "cad_projects")):
        check(f"{sharer} shares {vol}", vol in (data(sharer).get("shares") or []), f"{data(sharer)}")
        check(f"{sharer}'s purge list (data.volumes) does not hold {owner}'s {vol}",
              vol not in (data(sharer).get("volumes") or []), f"{data(sharer).get('volumes')}")
        check(f"{owner} owns {vol}", vol in (data(owner).get("volumes") or []), f"{data(owner).get('volumes')}")

    # G26
    G = load(HERE / "refactor" / "data-volumes-lint.py", "g26")
    if hasattr(G, "bad_shares"):
        m = {"own": {"data": {"volumes": ["v", "w"]}}, "other": {"data": {"volumes": ["w"]}},
             "good": {"data": {"shares": ["v"]}}, "orphan": {"data": {"shares": ["nobody"]}},
             "self": {"data": {"volumes": ["s"], "shares": ["s"]}}, "unmounted": {"data": {"shares": ["v"]}}}
        mounted = {"own": {"v", "w"}, "other": {"w"}, "good": {"v"}, "orphan": {"nobody"}, "self": {"s"},
                   "unmounted": set()}
        found = sorted((a, s.split("  ")[0], s.split("(")[1][:20]) for a, s in G.bad_shares(m, mounted))
        check("G26: two owners, a share nobody owns, a share of its own volume, an unmounted share",
              [(a, v) for a, v, _ in found] == [("orphan", "nobody"), ("own", "w"), ("self", "s"), ("unmounted", "v")],
              f"{found}")
        check("G26: this checkout passes", G.main() == 0, "data-volumes-lint main() != 0")
    else:
        check("G26 checks data.shares", False, "no bad_shares in data-volumes-lint.py")

    # the export scoped to the sharer
    tarred, said = exported("any-concurrency")
    check("export --app any-concurrency carries no n8n_storage", "n8n_storage" not in tarred, f"{tarred}")
    check("…and says where it is", any("n8n_storage" in s and "export --app n8n" in s for s in said),
          f"{[s for s in said if 'n8n_storage' in s]}")
    # …and that archive, as the export saved it, imports back with the sharer's own --app (an app move: export
    # here, `import --app` there) — the marker is filed under the app, and nothing of n8n's is restored
    for sharer, vol in (("any-concurrency", "n8n_storage"), ("cad-api", "cad_projects")):
        exported(sharer)
        reached, said = import_dir(exported.dir, sharer)
        check(f"export --app {sharer} then import --app {sharer} reaches the restore",
              "SystemExit" not in reached and "ran to its end" not in reached, f"{reached} {said[-2:]}")
        check(f"…with {vol} only as its marker", f"volumes/{vol}.tar.gz" not in reached
              and (reached.get(f"volumes/{vol}.SHARED") or {}).get("app") == sharer, f"{reached}")
    tarred, _ = exported("n8n")
    check("export --app n8n carries n8n_storage (its owner)", "n8n_storage" in tarred, f"{tarred}")
    # a sharer's run into the owner's directory resumes nothing of it and removes nothing from it
    owners_dir = exported.dir
    _, said = exported("any-concurrency", owners_dir)
    check("export --app any-concurrency into n8n's archive directory refuses",
          said and said[-1].startswith("SystemExit") and "holds an archive of n8n" in said[-1], f"{said[-2:]}")
    check("…and n8n's tarball is still there", (owners_dir / "volumes" / "n8n_storage.tar.gz").exists(),
          f"{sorted(p.name for p in (owners_dir / 'volumes').iterdir())}")

    # an old WHOLE-office archive filed cad_projects under whichever of its two apps came last (cad-api): the
    # owner's --app restore still finds it, and the sharer's does not
    d = old_archive(None, {"volumes/cad_projects.tar.gz": "cad-api", "volumes/cad_config.tar.gz": "cad"})
    reached, _ = import_dir(d, "cad")
    check("import --app cad of an old whole-office archive restores cad_projects filed under cad-api",
          "volumes/cad_projects.tar.gz" in reached and "volumes/cad_config.tar.gz" in reached, f"{reached}")
    reached, said = import_dir(d, "cad-api")
    check("…and import --app cad-api of it restores nothing of cad's", reached == {}
          and any("cad_projects" in s and "cad owns it" in s for s in said), f"{reached} {said[-2:]}")

    # the restore plan names the volume of the marker
    P = load(REPO / "platform-base" / "data-management" / "plan.py", "plan")
    check("the plan reads volumes/<v>.SHARED as the volume <v>", P._vol_short("volumes/n8n_storage.SHARED") ==
          "n8n_storage", P._vol_short("volumes/n8n_storage.SHARED"))

    # an archive made before: any-concurrency's scope, n8n_storage inside
    for only in ("any-concurrency", None):
        reached, said = imported("any-concurrency", only)
        check(f"import ({'--app ' + only if only else 'no --app'}) of an old any-concurrency archive never "
              f"restores n8n_storage", "volumes/n8n_storage.tar.gz" not in reached, f"{reached}")
        check(f"…and says so ({only})", any("n8n_storage" in s and "n8n owns it" in s for s in said),
              f"{said[-3:]}")
        # the old archive filed nothing else under any-concurrency: it restores nothing, as the new export of an app
        # that only shares does (an app move from an office on the older code must not stop on the owner's volume)
        check(f"…and, with nothing of its own left, reaches its restore with nothing ({only})",
              reached == {}, f"{reached}")
    # an archive of ANOTHER app never restores the owner's volume alone, even with the owner's --app (it came
    # without the owner's database)
    reached, _ = imported("any-concurrency", "n8n")
    check("import --app n8n of an old any-concurrency archive restores nothing of n8n's from it",
          "volumes/n8n_storage.tar.gz" not in reached and "holds nothing for 'n8n'" in reached.get("SystemExit", ""),
          f"{reached}")

    for f in FAIL:
        print("FAIL:", f)
    print("test_deployment_archive_shares:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
