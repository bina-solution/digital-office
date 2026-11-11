#!/usr/bin/env python3
"""test_deployment_archive_writers — a quiesced export stops what the apps DECLARE as their writers (DGO-1510).

    python3 scripts/test_deployment_archive_writers.py
    ARCHIVER_PATH=<an older deployment-archive.py> python3 …   # the same cases against another archiver

`--quiesce` used to stop containers picked by name (n8n-*, incoming-documents, mailboxd, mailapi). Now each app says
which of its compose services write to its stores (`data.writers`), and G26 holds each to a service of the app's
compose whose container is `<service>-${DEPLOYMENT_NAME}`, never a database. Held here, with docker answered by fakes:
  - the REAL `cmd_export --app <x> --quiesce`, its first hook made to fail: it stops exactly the running declared
    writers of every INSTALLED app (a disabled app's included: its volumes are exported too), in declaration order,
    once each — never a postgres, never another deployment's container (`n8n-x-<name>`, which the old suffix match
    hit) — a new app joins by its declaration alone, and exactly what was stopped is started again;
  - the real manifests (this checkout's) declare the ten writers the name list stopped;
  - G26 refuses a writer that is not a service, whose container the archiver would not find, or that is a database.
"""
import argparse
import importlib.util
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("ARCHIVER_PATH") or HERE / "deployment-archive.py")
spec = importlib.util.spec_from_file_location("archiver", SRC)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
FAIL: list[str] = []
DN = "acme"
RUNNING = [f"n8n-{DN}", f"n8n-postgres-{DN}", f"n8n-worker-1-{DN}", f"incoming-documents-{DN}", f"mailboxd-{DN}",
           f"mailserver-{DN}", f"drive-{DN}", f"brand-new-{DN}", "n8n-other-office", f"n8n-x-{DN}",
           "incoming-documents-other"]
# a small office: n8n enabled; indox and mail installed but DISABLED (their containers still running); a new app
MANIFESTS = {
    "n8n": {"id": "n8n", "data": {"writers": ["n8n", "n8n-webhook", "n8n-worker-1"]}},
    "indox": {"id": "indox", "data": {"writers": ["incoming-documents"]}},
    "mail": {"id": "mail", "data": {"writers": ["mailboxd", "mailapi"]}},
    "newapp": {"id": "newapp", "data": {"writers": ["brand-new", "n8n"]}},       # n8n named twice: stopped once
    "drive": {"id": "drive", "data": {}},
}
INSTALLED = [("apps", a) for a in MANIFESTS]
ENABLED = [("apps", "n8n"), ("apps", "drive")]


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(f"{name}: {detail}")


class HookFailed(Exception):
    pass


def quiesced_export(scope):
    """cmd_export --app <scope> --quiesce, its first hook failing: (stopped, started)."""
    calls = []

    def sh(argv, env=None):
        calls.append(list(argv))
        if argv[:2] == ["docker", "ps"]:
            return "\n".join(RUNNING) + "\n"
        return ""

    def run(argv, env=None, **kw):
        calls.append(list(argv))
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def hook_fails(*a, **kw):
        raise HookFailed("the first hook fails")

    A.read_env = lambda key: DN if key == "DEPLOYMENT_NAME" else ""
    A.sh, A.run = sh, run
    A.installed_apps = lambda: list(INSTALLED)
    A.enabled_apps = lambda: list(ENABLED)
    A.app_manifest = lambda root, aid: MANIFESTS.get(aid, {})
    A.app_hook = lambda root, aid, name: A.REPO / root / aid / "hooks" / name     # never run: _run_hook fails
    A._run_hook = hook_fails
    A._assert_gitignored = lambda p: None
    for fn in ("project_name", "engine_id"):
        setattr(A, fn, lambda: "acme-project")
    out = pathlib.Path(tempfile.mkdtemp(prefix="quiesce-"))
    args = argparse.Namespace(out=str(out), mode="full", force=False, quiesce=True, app=scope)
    try:
        A.cmd_export(args)
        check(f"--app {scope}: the failing hook stops the export", False, "it ran to its end")
    except HookFailed:
        pass
    stops = [c[2:] for c in calls if c[:2] == ["docker", "stop"]]
    starts = [c[2:] for c in calls if c[:2] == ["docker", "start"]]
    return (stops[0] if stops else []), (starts[0] if starts else [])


def main() -> int:
    want = [f"n8n-{DN}", f"n8n-worker-1-{DN}", f"incoming-documents-{DN}", f"mailboxd-{DN}", f"brand-new-{DN}"]
    for scope in ("indox", "drive"):
        stopped, started = quiesced_export(scope)
        check(f"--app {scope}: every installed app's running declared writers, in declaration order, once each",
              stopped == want, f"{stopped}")
        check(f"--app {scope}: a disabled app's running writers are stopped (its volumes are exported too)",
              {f"incoming-documents-{DN}", f"mailboxd-{DN}"} <= set(stopped), f"{stopped}")
        check(f"--app {scope}: a new app joins by its declaration alone", f"brand-new-{DN}" in stopped, f"{stopped}")
        check(f"--app {scope}: never a postgres, another app's or another deployment's container",
              not {f"n8n-postgres-{DN}", f"mailserver-{DN}", f"drive-{DN}", "n8n-other-office",
                   f"n8n-x-{DN}", "incoming-documents-other"} & set(stopped), f"{stopped}")
        check(f"--app {scope}: exactly what was stopped is started again, after the failure",
              started == stopped, f"stopped {stopped}, started {started}")

    # the name list's set, from THIS checkout's manifests (not the archiver's REPO): nothing it quiesced is missed
    import json
    repo = HERE.parent
    declared = set()
    for aid in ("n8n", "indox", "mail"):
        data = json.loads((repo / "apps" / aid / "app.json").read_text(encoding="utf-8")).get("data") or {}
        declared |= set(data.get("writers") or [])
    old_set = {"n8n", "n8n-webhook", "n8n-task-runners", "n8n-worker-1", "n8n-worker-1-runners", "n8n-worker-2",
               "n8n-worker-2-runners", "incoming-documents", "mailboxd", "mailapi"}
    check("the manifests declare every writer the name list stopped (a new one may join)", old_set <= declared,
          f"missing {sorted(old_set - declared)}")

    # G26 holds a declaration to the compose
    gspec = importlib.util.spec_from_file_location("g26", HERE / "refactor" / "data-volumes-lint.py")
    G = importlib.util.module_from_spec(gspec)
    gspec.loader.exec_module(G)
    if hasattr(G, "bad_writers"):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "docker-compose.yml").write_text(
            "services:\n  web:\n    container_name: web-${DEPLOYMENT_NAME:-bina-deployment}\n"
            "  api:\n    container_name: api-${DEPLOYMENT_NAME}\n"
            "  job:\n    container_name: the-job\n"
            "  old:\n    container_name: old-${DEPLOYMENT_NAME}-legacy\n"      # starts right, is another name
            "  bare:\n    image: x\n"                                          # compose names it <project>-bare-1
            "  odd:\n    container_name: odd-${DEPLOYMENT_NAME:-other}\n"      # the archiver looks for odd-bina-…
            "  nocolon:\n    container_name: nocolon-${DEPLOYMENT_NAME-bina-deployment}\n"   # set but empty: `nocolon-`
            "  db:\n    image: postgres:16\n    container_name: db-${DEPLOYMENT_NAME:-bina-deployment}\n")
        found = G.bad_writers("demo", {"data": {"writers": ["web", "api", "job", "old", "bare", "odd", "nocolon", "db",
                                                            "ghost"]}}, d)
        check("G26: not a service, a container the archiver would not find, or a database, is refused",
              [w.split()[0] for _, w in found] == ["job", "old", "bare", "odd", "nocolon", "db", "ghost"], f"{found}")
        check("G26: a good writer passes", G.bad_writers("demo", {"data": {"writers": ["web", "api"]}}, d) == [], "")
    else:
        check("G26 checks data.writers", False, "no bad_writers in data-volumes-lint.py")

    for f in FAIL:
        print("FAIL:", f)
    print("test_deployment_archive_writers:", "all passed" if not FAIL else f"{len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
