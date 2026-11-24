"""test_deployment_archive_carry — what the archive carries that a clone does not bring, and what it
says it left.

    python3 scripts/test_deployment_archive_carry.py
    ARCHIVER_PATH=<an older deployment-archive.py> python3 …   # the same cases against another archiver

Beside the archiver it tests (scripts/deployment-archive.py), which names the files it carries.

DGO-1510 (ob-3 of ai/context/office-backup.md), measured 2026-11-09:
  - platform.state.yaml (the apps the owner chose) is gitignored on the public copy, so a client's
    office's archive did not hold it; .state/outbox (Plane writes not yet sent) was in no archive;
  - on a packaged office .env is a link to /etc/binaos/binaos.env; inside data-management that target
    is not mounted, `exists()` follows the link, and the export stepped over .env without a word;
  - portainer's password lives in apps/portainer/, the archiver looked at the repo root;
  - 26 volumes on the MacBook were in no app's declaration and in no list.
And `.dgo/` must NOT be carried: .gitignore says it is this machine's rendering of the link.

A temp directory stands in for the checkout. No docker, no network, nothing of the office is read.
"""
import importlib.util
import os
import pathlib
import stat
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve()
SRC = pathlib.Path(os.environ.get("ARCHIVER_PATH") or HERE.parent / "deployment-archive.py")
spec = importlib.util.spec_from_file_location("archiver", SRC)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

RESULTS = []


def case(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except Exception as e:                            # noqa: BLE001 — the reason IS the report
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def checkout():
    """A fresh stand-in checkout, made the archiver's REPO."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="archive-carry-")).resolve()
    A.REPO = tmp
    return tmp


@case("portainer's password is looked for where portainer keeps it")
def _():
    assert "apps/portainer/portainer_password.txt" in A.SECRET_PATHS, A.SECRET_PATHS


@case("the state file and the outbox are carried as the office's declarations")
def _():
    assert list(A.DECLARATION_PATHS) == ["platform.state.yaml", ".state/outbox"], A.DECLARATION_PATHS


@case(".dgo/ is carried neither as a secret nor as a declaration")
def _():
    paths = list(A.SECRET_PATHS) + list(getattr(A, "DECLARATION_PATHS", []))
    assert not [p for p in paths if p.strip("/").split("/")[0] == ".dgo"], paths


@case("a plain file is read where it is; a missing one is nothing to carry")
def _():
    repo = checkout()
    (repo / "platform.state.yaml").write_text("apps: {}\n")
    assert A.carried_source("platform.state.yaml") == repo / "platform.state.yaml"
    assert A.carried_source(".env") is None


@case("a link is read at its target (a packaged office's .env)")
def _():
    repo = checkout()
    etc = repo.parent / (repo.name + "-etc")
    etc.mkdir()
    (etc / "binaos.env").write_text("N8N_ENCRYPTION_KEY=x\n")
    os.symlink(etc / "binaos.env", repo / ".env")
    got = A.carried_source(".env")
    assert got == (etc / "binaos.env").resolve(), got


@case("a link whose target is not visible FAILS the run, it is never stepped over")
def _():
    repo = checkout()
    os.symlink("/nonexistent-binaos-dgo1510/binaos.env", repo / ".env")
    try:
        A.carried_source(".env")
    except RuntimeError as e:
        assert "/nonexistent-binaos-dgo1510/binaos.env" in str(e), str(e)
        return
    raise AssertionError("a dangling .env link was not refused")


@case("undeclared volumes: this project's and the others' are named, declared ones are not")
def _():
    listing = [("p_kept", "p", "1kB"), ("p_project_pln_mq", "p", "4.687MB"),
               ("exampleu-meets-import", "", "448MB"), ("office_git_state", "office", "0B"),
               ("dgo-offsite-examplef-20261026-075600", "", "383.3MB"), ("a" * 64, "", "0B")]
    rows, anon = A.undeclared_volumes(listing, {"kept"}, "p")
    by = {r["name"]: r for r in rows}
    assert "p_kept" not in by, rows
    assert by["p_project_pln_mq"]["ours"] is True and by["p_project_pln_mq"]["size"] == "4.687MB", rows
    assert by["exampleu-meets-import"]["ours"] is False and by["exampleu-meets-import"]["project"] is None, rows
    assert by["office_git_state"]["project"] == "office", rows
    assert "dgo-offsite-examplef-20261026-075600" in by, rows
    assert anon["count"] == 1 and ("a" * 64) not in by, (rows, anon)


@case("the label decides whose a volume is; docker's N/A is no size")
def _():
    listing = [("p_x_data", "p_x", "1MB"), ("p_old", "p", "N/A"), ("p_unlabelled", "", "2kB")]
    rows, _anon = A.undeclared_volumes(listing, set(), "p")
    by = {r["name"]: r for r in rows}
    assert by["p_x_data"]["ours"] is False and by["p_x_data"]["project"] == "p_x", rows
    assert by["p_old"]["ours"] is True and by["p_old"]["size"] is None, rows
    assert by["p_unlabelled"]["ours"] is True, rows


@case("a declared volume is carried by its name, whatever its label: never named as left out")
def _():
    # _tar_volume carries `<project>_<short>`; a label of another project does not stop that (DGO-1510)
    listing = [("p_data", "other", "1MB"), ("p_data2", "p", "1MB"), ("data", "", "1MB")]
    rows, _anon = A.undeclared_volumes(listing, {"data", "data2"}, "p")
    assert sorted(r["name"] for r in rows) == ["data"], rows


@case("into an empty slot: a secret lands 0600, a declaration keeps its own mode (0640)")
def _():
    repo = checkout()
    arch = repo.parent / (repo.name + "-archive")
    arch.mkdir()
    (arch / ".env").write_text("K=v\n")
    (arch / "platform.state.yaml").write_text("apps: {}\n")
    os.chmod(arch / "platform.state.yaml", 0o640)
    assert A.install_carried(arch / ".env", ".env", secret=True) is None
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600
    assert A.install_carried(arch / "platform.state.yaml", "platform.state.yaml", secret=False) is None
    assert stat.S_IMODE((repo / "platform.state.yaml").stat().st_mode) == 0o640
    assert (repo / "platform.state.yaml").read_text() == "apps: {}\n"


@case("a carried file goes only to a path the archiver carries, under the name the export gives it")
def _():
    arts = {
        "secrets/.env": {"kind": "secret", "note": ".env"},
        "secrets/secrets.tar.gz": {"kind": "secret", "note": "secrets"},
        "declarations/platform.state.yaml": {"kind": "declaration", "note": "platform.state.yaml"},
        "declarations/.state__outbox.tar.gz": {"kind": "declaration", "note": ".state/outbox"},
        "secrets/platform-base__n8n__.credentials-state.tar.gz":       # an archive from before n8n moved
            {"kind": "secret", "note": "platform-base/n8n/.credentials-state"},
        "secrets/x": {"kind": "secret", "note": "scripts/dc"},
        "declarations/..__x": {"kind": "declaration", "note": "../x"},
        "secrets/elsewhere": {"kind": "secret", "note": ".env"},       # an allowed path, another name
        "volumes/v.tar.gz": {"kind": "volume", "note": "anything"},     # not a carried kind: not asked
    }
    skips = A.carried_skips(arts)
    assert set(skips) == {"secrets/platform-base__n8n__.credentials-state.tar.gz", "secrets/x",
                          "declarations/..__x", "secrets/elsewhere"}, skips


@case("a declaration tree is unpacked through a container, a secret tree by the operator's tar")
def _():
    repo = checkout()
    arch = repo.parent / (repo.name + "-archive")
    arch.mkdir()
    (arch / ".state__outbox.tar.gz").write_bytes(b"x")
    (arch / "secrets.tar.gz").write_bytes(b"x")
    calls, real_sh = [], A.sh
    A.sh = lambda cmd, **kw: calls.append(list(cmd)) or ""
    try:
        assert A.install_carried(arch / ".state__outbox.tar.gz", ".state/outbox", secret=False) is None
        assert A.install_carried(arch / "secrets.tar.gz", "secrets", secret=True) is None
    finally:
        A.sh = real_sh
    assert calls[0][:3] == ["docker", "run", "--rm"], calls
    assert f"{repo / '.state'}:/p" in calls[0] and "/p/outbox" in calls[0][-1], calls   # .state only, not the checkout
    assert calls[1][0] == "tar" and calls[1][-1] == str(repo / "secrets"), calls


@case("an occupied slot is kept, and the archive's copy lands beside it")
def _():
    repo = checkout()
    arch = repo.parent / (repo.name + "-archive")
    arch.mkdir()
    (arch / "platform.state.yaml").write_text("apps: {meet: {enabled: true}}\n")
    (repo / "platform.state.yaml").write_text("apps: {}\n")
    side = A.install_carried(arch / "platform.state.yaml", "platform.state.yaml", secret=False)
    assert side == "platform.state.yaml.from-archive", side
    assert (repo / "platform.state.yaml").read_text() == "apps: {}\n"
    assert (repo / side).read_text() == "apps: {meet: {enabled: true}}\n"


@case("a dangling link in the slot is occupied: nothing is written through it")
def _():
    repo = checkout()
    arch = repo.parent / (repo.name + "-archive")
    arch.mkdir()
    (arch / ".env").write_text("K=v\n")
    far = repo.parent / (repo.name + "-far")
    os.symlink(far / "binaos.env", repo / ".env")
    side = A.install_carried(arch / ".env", ".env", secret=True)
    assert side == ".env.from-archive", side
    assert not (far / "binaos.env").exists()


def _office(repo):
    """Two installed apps, one disabled, and the compose config this office would render (DGO-1510)."""
    manifests = {"x": {"data": {"volumes": ["n8n_storage"], "sql": [{"database": "x_db"}]}},
                 "z": {"data": {"paths": ["apps/z/store"], "volumes": [{"name": "z_cache"}]}}}
    A.installed_apps = lambda: [("apps", "x"), ("apps", "z")]
    A.app_manifest = lambda root, aid: manifests[aid]
    (repo / "platform-base/postgres").mkdir(parents=True, exist_ok=True)
    (repo / "platform-base/postgres/roles.sql").write_text("-- a single-file mount\n")
    return {"services": {
        "x": {"volumes": [{"type": "bind", "source": str(repo / "apps/x/data")},
                          {"type": "bind", "source": str(repo / "apps/x/data/inner")},
                          {"type": "bind", "source": str(repo / "apps/x/conf"), "read_only": True},
                          {"type": "bind", "source": "/var/run/docker.sock"},
                          {"type": "bind", "source": str(repo / "platform-base/postgres/roles.sql")},
                          {"type": "bind", "source": str(repo / "secrets")},
                          {"type": "volume", "source": "n8n_storage"}]}}}


def _bind(note):
    return {"binds/" + note.split("  ")[0].replace("/", "__") + ".tar.gz": {"kind": "bind", "note": note}}


@case("a bind is restored only to a directory this office mounts read-write or an app declares")
def _():
    repo = checkout()
    saved = (A.installed_apps, A.app_manifest)
    try:
        cfg = _office(repo)
        arts = {**_bind("apps/x/data"), **_bind("apps/z/store"), **_bind("apps/x/conf"), **_bind("scripts"),
                **_bind("../../etc"), **_bind("apps/x/../../etc"), **_bind("/etc"),
                **_bind("platform-base/postgres/roles.sql"), **_bind("secrets"),
                "binds/elsewhere.tar.gz": {"kind": "bind", "note": "apps/x/data"}}
        skips = A.restore_skips(arts, cfg)
        assert "binds/apps__x__data.tar.gz" not in skips and "binds/apps__z__store.tar.gz" not in skips, skips
        for rel in ("binds/apps__x__conf.tar.gz", "binds/scripts.tar.gz", "binds/..__..__etc.tar.gz",
                    "binds/apps__x__..__..__etc.tar.gz", "binds/__etc.tar.gz", "binds/elsewhere.tar.gz",
                    "binds/platform-base__postgres__roles.sql.tar.gz", "binds/secrets.tar.gz"):
            assert rel in skips, (rel, skips)
        assert "inside the checkout" in skips["binds/apps__x__..__..__etc.tar.gz"], skips
        assert "a file here" in skips["binds/platform-base__postgres__roles.sql.tar.gz"], skips
        assert "carried secret" in skips["binds/secrets.tar.gz"], skips
        # a config-mode note (its excluded subpaths after two spaces) is the same directory
        excl = A.restore_skips(_bind("apps/x/data  (excluded: apps/x/data/tmp)"), cfg)
        assert not excl, excl
    finally:
        A.installed_apps, A.app_manifest = saved


@case("a volume is restored only if an app installed here declares it, by a plain name")
def _():
    repo = checkout()
    saved = (A.installed_apps, A.app_manifest)
    try:
        cfg = _office(repo)
        arts = {"volumes/n8n_storage.tar.gz": {"kind": "volume"},
                "volumes/z_cache.tar.gz": {"kind": "volume-dormant"},
                "volumes/vault_data.tar.gz": {"kind": "volume"},
                "volumes/x;rm -rf .tar.gz": {"kind": "volume"},
                "volumes/a:b.tar.gz": {"kind": "volume"},
                "elsewhere/n8n_storage.tar.gz": {"kind": "volume"},
                "secrets/.env": {"kind": "secret", "note": ".env"}}
        skips = A.restore_skips(arts, cfg)
        assert set(skips) == {"volumes/vault_data.tar.gz", "volumes/x;rm -rf .tar.gz", "volumes/a:b.tar.gz",
                              "elsewhere/n8n_storage.tar.gz"}, skips
        assert "vault_data" in skips["volumes/vault_data.tar.gz"], skips
    finally:
        A.installed_apps, A.app_manifest = saved


@case("an old volume of a store now in data/<app>/ is restored too, whole or for the app alone (DGO-2019)")
def _():
    # a backup of an office that still ran a store from its volume (the HP's drvfs: every store waits) carries that
    # volume; a restore that refused it brought forward-auth up with no account — the next `bbox run` moves it instead
    checkout()
    saved = (A.installed_apps, A.app_manifest)
    try:
        manifests = {"fa": {"data": {"volumes": [], "paths": ["data/fa/state", "data/fa/relay"],
                                     "moved_from": {"data/fa/state": "fa_data", "data/fa/relay": "external:by_hand"}}}}
        A.installed_apps = lambda: [("platform-base", "fa")]
        A.app_manifest = lambda root, aid: manifests[aid]
        arts = {"volumes/fa_data.tar.gz": {"kind": "volume", "app": "fa"},
                "volumes/by_hand.tar.gz": {"kind": "volume", "app": "fa"}}
        skips = A.restore_skips(arts, {"services": {}})
        assert set(skips) == {"volumes/by_hand.tar.gz"}, skips          # never a volume compose did not make
        A._assert_app_owns("fa", {"volumes/fa_data.tar.gz": arts["volumes/fa_data.tar.gz"]})   # its own: no refusal
        try:
            A._assert_app_owns("fa", {"volumes/vault_data.tar.gz": {"kind": "volume", "app": "fa"}})
        except SystemExit as e:
            assert "vault_data" in str(e), e
        else:
            raise AssertionError("another app's volume was taken as fa's")
    finally:
        A.installed_apps, A.app_manifest = saved


@case("SQL is restored only into a database the app it is filed under declares here")
def _():
    repo = checkout()
    saved = (A.installed_apps, A.app_manifest)
    try:
        cfg = _office(repo)
        arts = {"apps/x/db.dump": {"kind": "sql", "app": "x", "database": "x_db"},
                "apps/x/fn.sql": {"kind": "sql-functions", "app": "x", "database": "x_db"},
                "apps/x/auth.dump": {"kind": "sql", "app": "x", "database": "authentik"},
                "apps/z/db.dump": {"kind": "sql", "app": "z", "database": "x_db"},
                "apps/q/fn.sql": {"kind": "sql-functions", "database": "x_db"}}
        assert set(A.restore_skips(arts, cfg)) == {"apps/x/auth.dump", "apps/z/db.dump", "apps/q/fn.sql"}, \
            A.restore_skips(arts, cfg)
    finally:
        A.installed_apps, A.app_manifest = saved


@case("import writes nothing a skip names, and a link planted by one bind does not aim the next")
def _():
    import argparse
    import hashlib
    import json
    repo = checkout()
    arch = repo.parent / (repo.name + "-archive")
    names = {"binds/apps__x__data.tar.gz": {"kind": "bind", "note": "apps/x/data"},
             "binds/apps__x__data__inner.tar.gz": {"kind": "bind", "note": "apps/x/data/inner"},
             "binds/..__..__etc.tar.gz": {"kind": "bind", "note": "../../etc"},
             "volumes/n8n_storage.tar.gz": {"kind": "volume"},
             "volumes/vault_data.tar.gz": {"kind": "volume"},
             "apps/x/auth.dump": {"kind": "sql", "app": "x", "database": "authentik", "instance": "supabase-db-a"}}
    for rel, e in names.items():
        (arch / rel).parent.mkdir(parents=True, exist_ok=True)
        (arch / rel).write_bytes(rel.encode())
        e["sha256"] = hashlib.sha256(rel.encode()).hexdigest()
    (arch / "manifest.json").write_text(json.dumps({
        "format_version": A.FORMAT_VERSION, "deployment_name": "far", "compose_project": "far-project",
        "engine": "other-engine", "mode": "full", "quiesced": False, "facts": {}, "artifacts": names}))
    evil = repo.parent / (repo.name + "-evil")
    evil.mkdir()
    ran = []

    def sh(cmd, **kw):
        ran.append(" ".join(map(str, cmd)))
        if f"{repo / 'apps/x/data'}:/dst" in ran[-1]:          # the outer tree plants a link where the inner goes
            (repo / "apps/x/data").mkdir(parents=True, exist_ok=True)
            os.symlink(evil, repo / "apps/x/data/inner")
        return ""
    saved = {n: getattr(A, n) for n in ("installed_apps", "app_manifest", "sh", "compose_config",
                                        "assert_network_isolation", "engine_id", "project_name", "read_env",
                                        "enabled_apps", "pg_instances")}
    real_run = A.subprocess.run
    try:
        cfg = _office(repo)
        A.sh, A.compose_config = sh, lambda: cfg
        A.assert_network_isolation = lambda *a, **k: None
        A.engine_id, A.project_name, A.read_env = (lambda: "this-engine"), (lambda: "here"), (lambda k: "")
        A.enabled_apps, A.pg_instances = (lambda: []), (lambda: [("supabase-db-b", "postgres", None)])
        A.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"SQL ran: {a}"))
        A.cmd_import(argparse.Namespace(dir=str(arch), app=None, force=False, allow_shared_network=False))
    finally:
        for n, f in saved.items():
            setattr(A, n, f)
        A.subprocess.run = real_run
    joined = "\n".join(ran)
    assert f"{repo / 'apps/x/data'}:/dst" in joined and "here_n8n_storage" in joined, joined
    assert "vault_data" not in joined and "etc:/dst" not in joined and str(evil) not in joined, joined
    assert "apps__x__data__inner" not in joined, f"the inner bind followed the planted link: {joined}"


def main():
    print(f"archiver: {SRC}")
    bad = 0
    for name, ok, why in RESULTS:
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — {why}"))
    print(f"\narchive-carry: {len(RESULTS) - bad}/{len(RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
