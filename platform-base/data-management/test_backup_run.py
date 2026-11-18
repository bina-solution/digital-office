"""test_backup_run.py — one backup of an office into restic through the store (backup_run.py, DGO-1523).

The real app under uvicorn, the fake generic drive of test_restic_store.py, a fake vault, a fake export
(the archiver itself is the program /api/export has always run), and — when docker is reachable — the
REAL helper container (restic/restic:0.18.0 by digest) on a docker network it shares with this process:

  - the first run makes the key in the vault once, creates the repository, backs up and checks;
  - a second run reuses the key and adds only what changed;
  - a key the repository does not open is never answered with a new repository;
  - a missing key in front of an existing repository, a silent vault, no room, a failed export, a
    second run at once, an undeclared target: each stops before anything is sent, and says so;
  - the key and the run's token are never on the helper's argv, in the log or in the result.

    # inside the data-management image, with the docker socket, on a network the helper joins, and
    # with the shared directory at the same path inside and outside (the helper mounts staging by it):
    docker network create probe-net
    docker run --rm --network probe-net --name probe -e TEST_SELF_HOST=probe -e TEST_NETWORK=probe-net \\
        -e TEST_SHARED_DIR=/tmp/shared -v /tmp/shared:/tmp/shared -v /var/run/docker.sock:/var/run/docker.sock \\
        -v "$PWD":/t -w /t -v <restic binary>:/usr/local/bin/restic:ro <data-management image> \\
        python3 test_backup_run.py
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("DEPLOYMENT_NAME", "exampleu")     # the office a run through the API backs up

import test_restic_store as T  # noqa: E402  (its fake drive, its WORK dir and the env it sets)
import uvicorn  # noqa: E402

import backup_run as BR  # noqa: E402
import restic_store as RS  # noqa: E402

SHARED = pathlib.Path(os.environ.get("TEST_SHARED_DIR") or tempfile.mkdtemp(prefix="backup-run-"))
SELF_HOST = os.environ.get("TEST_SELF_HOST") or ""
NETWORK = os.environ.get("TEST_NETWORK") or ""
RESTIC = os.environ.get("RESTIC_BIN") or shutil.which("restic")


def _docker_ok() -> bool:
    if not (SELF_HOST and NETWORK and shutil.which("docker")):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


DOCKER = _docker_ok()


class FakeVault(http.server.ThreadingHTTPServer):
    """connections' instance API: GET /api/instances/<id>/secret (200/404), POST /api/instances (200/409)."""
    daemon_threads = True

    def __init__(self):
        self.instances: dict[str, dict] = {}
        self.posts = 0
        self.fail = 0
        self.gets: dict[str, int] = {}
        self.swap: tuple[str, int, str] | None = None   # (id, on the n-th read, the key it holds from then)
        super().__init__(("127.0.0.1", T._port()), _VaultHandler)


class _VaultHandler(http.server.BaseHTTPRequestHandler):
    server: FakeVault

    def log_message(self, *a):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.server.fail:
            return self._send(self.server.fail, {"error": "vault down"})
        parts = self.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "instances"] and parts[3] == "secret":
            n = self.server.gets[parts[2]] = self.server.gets.get(parts[2], 0) + 1
            sw = self.server.swap
            if sw and sw[0] == parts[2] and n >= sw[1] and parts[2] in self.server.instances:
                self.server.instances[parts[2]]["secret"] = {"key": sw[2]}
            rec = self.server.instances.get(parts[2])
            return self._send(200, {"secret": rec["secret"]}) if rec else self._send(404, {"error": "unknown"})
        return self._send(404, {})

    def do_POST(self):
        self.server.posts += 1                          # every attempt to make a key, answered or not
        if self.server.fail:
            return self._send(self.server.fail, {"error": "vault down"})
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if b["id"] in self.server.instances:
            return self._send(409, {"error": "exists"})
        self.server.instances[b["id"]] = {"protocol": b["protocol"], "secret": b["secret"]}
        return self._send(200, {"id": b["id"]})


VAULT: FakeVault
SERVER: uvicorn.Server
OFFICE = "exampleu"


def setUpModule():
    global VAULT, SERVER
    T.setUpModule()                                   # the fake drive and the targets file
    BR.MIN_INTERVAL = 0                               # runs back to back here; the interval has its own test
    VAULT = FakeVault()
    threading.Thread(target=VAULT.serve_forever, daemon=True).start()
    BR.VAULT = f"http://127.0.0.1:{VAULT.server_address[1]}"
    if DOCKER:
        # a second listener of the same app, on every interface, for the helper container to reach
        port = T._port()
        SERVER = uvicorn.Server(uvicorn.Config(T.APP.app, host="0.0.0.0", port=port, log_level="warning",
                                               lifespan="off"))
        threading.Thread(target=SERVER.run, daemon=True).start()
        for _ in range(100):
            if SERVER.started:
                break
            time.sleep(0.05)
        BR.SELF = f"{SELF_HOST}:{port}"
        BR.NETWORK = NETWORK
    tgt = json.loads((T.WORK / "targets.json").read_text())
    tgt["targets"]["herd-run"] = dict(tgt["targets"]["herd-exampleu"], folder="/גיבויים/run")
    tgt["targets"]["herd-wrongkey"] = dict(tgt["targets"]["herd-exampleu"], folder="/גיבויים/wrongkey")
    tgt["targets"]["herd-swapped"] = dict(tgt["targets"]["herd-exampleu"], folder="/גיבויים/swapped")
    tgt["targets"]["herd-unlock"] = dict(tgt["targets"]["herd-exampleu"], folder="/גיבויים/unlock")
    (T.WORK / "targets.json").write_text(json.dumps(tgt, ensure_ascii=False))


def tearDownModule():
    if DOCKER:
        SERVER.should_exit = True
    VAULT.shutdown()
    T.tearDownModule()


def fake_export(files: dict[str, bytes], calls: list | None = None):
    def export(staging: pathlib.Path, log):
        if calls is not None:
            calls.append(staging)
        for rel, data in files.items():
            p = staging / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (staging / "manifest.json").write_text(json.dumps({"artifacts": sorted(files)}))
        log(f"exported {len(files)} file(s)")
    return export


class Recorder:
    """subprocess.run as backup_run calls it, with every argv and stdin kept for the assertions."""

    def __init__(self):
        self.calls: list[tuple[list, str]] = []
        self._real = subprocess.run

    def __call__(self, argv, *a, **kw):
        self.calls.append((list(argv), kw.get("input") or ""))
        return self._real(argv, *a, **kw)


def _local_snapshots(folder: str, key: str) -> list[dict]:
    """The drive's folder opened as a plain local repository, with nothing of DGO."""
    pw = SHARED / "pw-check"
    pw.write_text(key)
    try:
        p = subprocess.run([RESTIC, "-r", str(T.DRIVE.root / folder.strip("/")), "--no-cache", "snapshots", "--json"],
                           env={"PATH": os.environ.get("PATH", ""), "RESTIC_PASSWORD_FILE": str(pw)},
                           capture_output=True, text=True, timeout=120)
    finally:
        pw.unlink()
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


# ── without docker: the parts that decide ───────────────────────────────────────────────────────
class Decisions(unittest.TestCase):
    def setUp(self):
        VAULT.instances.clear()
        VAULT.posts = 0
        VAULT.fail = 0

    def test_the_key_is_made_once_and_only_for_a_new_repository(self):
        k1, fp1 = BR.office_key(OFFICE, repo_exists=False)
        k2, fp2 = BR.office_key(OFFICE, repo_exists=True)
        self.assertEqual((k1, fp1), (k2, fp2))
        self.assertEqual(VAULT.posts, 1)
        self.assertEqual(VAULT.instances[f"backup_key-{OFFICE}"]["protocol"], "backup_key")

    def test_a_missing_key_in_front_of_an_existing_repository_is_never_replaced(self):
        with self.assertRaises(BR.Failed) as c:
            BR.office_key(OFFICE, repo_exists=True)
        self.assertIn("No new key", str(c.exception))
        self.assertEqual(VAULT.posts, 0)

    def test_a_vault_that_does_not_answer_makes_nothing(self):
        for st in (500, 503):
            VAULT.fail = st
            with self.assertRaises(BR.Failed):
                BR.office_key(OFFICE, repo_exists=False)
        VAULT.fail = 0
        self.assertEqual((VAULT.posts, VAULT.instances), (0, {}))
        BR.VAULT, saved = "http://127.0.0.1:9", BR.VAULT        # nothing listens there
        try:
            with self.assertRaises(BR.Failed):
                BR.office_key(OFFICE, repo_exists=False)
        finally:
            BR.VAULT = saved

    def test_the_helper_argv_carries_no_secret_and_a_pinned_image(self):
        argv = BR.helper_argv("n", pathlib.Path("/s"), OFFICE, "r1", "3/7")
        self.assertIn("@sha256:", BR.RESTIC_IMAGE)
        self.assertEqual(argv[argv.index("--log-driver") + 1], "none")
        self.assertIn("/s:/backup/office:ro", argv)
        self.assertFalse(any("RESTIC_PASSWORD=" in a or a.startswith("-e") for a in argv))

    def test_restic_lines_become_a_result(self):
        out = "\n".join([json.dumps({"step": "init", "ok": True}),
                         json.dumps({"message_type": "summary", "snapshot_id": "ab" * 32,
                                     "total_files_processed": 3, "total_bytes_processed": 99, "data_added": 7}),
                         "not json", json.dumps({"step": "check", "ok": True, "subset": "1/7"})])
        r = BR._parse(out)
        self.assertEqual((r["snapshot"], r["files"], r["added"]), ("ab" * 32, 3, 7))
        self.assertEqual([s["step"] for s in r["steps"]], ["init", "check"])

    def test_refusals_happen_before_anything_is_sent(self):
        calls = []
        for target, why in (("nobody", "no backup target"),):
            with self.assertRaises(BR.Refused) as c:
                BR.run(target, OFFICE, SHARED, SHARED / "state", fake_export({"a": b"x"}, calls), lambda s: None)
            self.assertIn(why, str(c.exception))
        with self.assertRaises(BR.Refused):
            BR.run("herd-run", "Not An Office", SHARED, SHARED / "state", fake_export({}, calls), lambda s: None)
        saved = BR.MIN_FREE
        BR.MIN_FREE = 1 << 62
        try:
            with self.assertRaises(BR.Refused) as c:
                BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export({}, calls), lambda s: None)
            self.assertIn("GB free", str(c.exception))
        finally:
            BR.MIN_FREE = saved
        self.assertTrue(BR._ONE.acquire(blocking=False))
        try:
            with self.assertRaises(BR.Refused) as c:
                BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export({}, calls), lambda s: None)
            self.assertIn("already going", str(c.exception))
        finally:
            BR._ONE.release()
        self.assertEqual(calls, [], "an export ran for a refused run")
        self.assertEqual(VAULT.posts, 0, "a key was made for a refused run")

    def test_a_failed_export_sends_nothing_and_leaves_nothing(self):
        def broken(staging, log):
            (staging / "half").write_bytes(b"half an archive")
            raise BR.Failed("the export stopped (exit 1)")
        opened = []
        real_open = RS.RUNS.open
        RS.RUNS.open = lambda *a, **k: opened.append(a) or real_open(*a, **k)
        try:
            with self.assertRaises(BR.Failed):
                BR.run("herd-run", OFFICE, SHARED, SHARED / "state", broken, lambda s: None)
        finally:
            RS.RUNS.open = real_open
        self.assertEqual(opened, [], "a token was opened for an export that failed")
        self.assertEqual(list((SHARED / ".restic-staging").iterdir()), [], "staging left behind")

    def test_the_runs_result_names_what_the_export_left_out(self):
        # DGO-1510: «every run's report and manifest name the unclaimed volumes with their size». The archiver's
        # manifest names them; the run's result (what is kept and shown) carries the same list, or says the
        # listing failed. The helper is faked here: what is tested is what the run makes of the export.
        def export_naming(man_extra):
            def export(staging, log):
                (staging / "a").write_bytes(b"x")
                (staging / "manifest.json").write_text(json.dumps({"artifacts": ["a"], **man_extra}))
            return export

        summary = json.dumps({"message_type": "summary", "snapshot_id": "cd" * 32, "total_files_processed": 1,
                              "total_bytes_processed": 1, "data_added": 1})
        real_run = BR.subprocess.run

        def helper(argv, *a, **kw):
            if argv[:2] == ["docker", "run"]:
                return subprocess.CompletedProcess(argv, 0, stdout=summary + "\n", stderr="")
            return real_run(argv, *a, **kw)

        named = {"undeclared_volumes": [{"name": "exf-release", "project": None, "ours": False, "size": "33MB"},
                                        {"name": "exampleu_old", "project": "exampleu", "ours": True, "size": None}],
                 "anonymous_volumes": 2}
        failed = {"undeclared_volumes_error": "TimeoutExpired: docker volume ls"}
        BR.subprocess.run = helper
        try:
            lines: list[str] = []
            r = BR.run("herd-run", OFFICE, SHARED, SHARED / "state-left-out", export_naming(named), lines.append)
            self.assertEqual(r["not_carried"], {"volumes": [{"name": "exf-release", "project": None, "size": "33MB"},
                                                            {"name": "exampleu_old", "project": "exampleu", "size": None}],
                                                "anonymous": 2})
            self.assertEqual(BR.last(SHARED / "state-left-out", "herd-run")["not_carried"], r["not_carried"])
            self.assertTrue(any("exf-release (33MB)" in s and "exampleu_old (size unknown)" in s and "2 anonymous" in s
                                for s in lines), lines)
            BR.MIN_INTERVAL, saved = 0, BR.MIN_INTERVAL
            try:
                r = BR.run("herd-run", OFFICE, SHARED, SHARED / "state-left-out", export_naming(failed), lines.append)
            finally:
                BR.MIN_INTERVAL = saved
            self.assertEqual(r["not_carried"], {"volumes": None, "anonymous": None,
                                                "error": "TimeoutExpired: docker volume ls"})
            self.assertTrue(any("UNKNOWN" in s for s in lines), lines)
        finally:
            BR.subprocess.run = real_run

    def test_a_manifest_that_says_nothing_of_the_listing_is_unknown_never_nothing_left_out(self):
        # an older archiver, an app-scoped export, a manifest that is not what it should be: UNKNOWN, and never the
        # run's end — the list is a report (the second reader)
        d = pathlib.Path(tempfile.mkdtemp(prefix="left-out-"))
        for body in (json.dumps({"artifacts": []}), json.dumps(["not", "a", "dict"]),
                     json.dumps({"undeclared_volumes": [1, 2]}), json.dumps({"undeclared_volumes": None}), "{torn"):
            (d / "manifest.json").write_text(body)
            out = BR.left_out(d)
            self.assertEqual((out["volumes"], out["anonymous"]), (None, None), body)
            self.assertTrue(out["error"], body)
        (d / "manifest.json").unlink()
        self.assertIsNone(BR.left_out(d)["volumes"])
        (d / "manifest.json").write_text(json.dumps({"undeclared_volumes": [], "anonymous_volumes": 0}))
        self.assertEqual(BR.left_out(d), {"volumes": [], "anonymous": 0})

    def test_runs_keep_their_interval_across_a_restart(self):
        state = SHARED / "state-interval"
        BR._mark_started(state, "herd-run")               # kept in the volume: a restarted service reads it
        saved, BR.MIN_INTERVAL = BR.MIN_INTERVAL, 3600
        calls = []
        try:
            with self.assertRaises(BR.Refused) as c:
                BR.run("herd-run", OFFICE, SHARED, state, fake_export({}, calls), lambda s: None)
            self.assertIn("min ago", str(c.exception))
        finally:
            BR.MIN_INTERVAL = saved
        self.assertEqual((calls, VAULT.posts), ([], 0))

    def test_what_a_run_cut_short_left_in_staging_goes_at_the_next_start(self):
        left = SHARED / ".restic-staging" / "20261109T000000Z-dead"
        (left / "volumes").mkdir(parents=True)
        (left / "volumes" / "n8n.tar.gz").write_bytes(b"x" * 1000)
        saved, BR.MIN_FREE = BR.MIN_FREE, 1 << 62       # refused at the room check, after the sweep
        try:
            with self.assertRaises(BR.Refused):
                BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export({}), lambda s: None)
        finally:
            BR.MIN_FREE = saved
        self.assertFalse(left.exists())

    def test_the_room_asked_for_is_the_last_export_and_a_fifth(self):
        state = SHARED / "state-room"
        BR._keep(state, "herd-run", {"snapshot": "x", "bytes": shutil.disk_usage(SHARED).free})
        with self.assertRaises(BR.Refused) as c:
            BR.run("herd-run", OFFICE, SHARED, state, fake_export({}), lambda s: None)
        self.assertIn("the last export", str(c.exception))

    def test_an_export_that_hangs_is_stopped_at_its_deadline(self):
        probe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            probe.kill()
        except PermissionError:
            probe.wait()
            # Ubuntu 26.04's stacked AppArmor label denies signals inside a container (DGO-1604): the
            # watchdog cannot work here, so this host proves nothing about it either way
            self.skipTest("this host denies signals inside a container (DGO-1604)")
        probe.wait()
        repo = SHARED / "fake-repo"
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        (repo / "scripts" / "deployment-archive.py").write_text(
            "import sys, time\nprint('exporting', flush=True)\ntime.sleep(60)\n")
        saved, BR.EXPORT_TIMEOUT = BR.EXPORT_TIMEOUT, 1.0
        t0 = time.monotonic()
        try:
            with self.assertRaises(BR.Failed) as c:
                BR.archiver_export(repo)(SHARED / "fake-out", lambda s: None)
        finally:
            BR.EXPORT_TIMEOUT = saved
        self.assertIn("ran past", str(c.exception))
        self.assertLess(time.monotonic() - t0, 20)

    def test_the_default_address_is_this_offices_own_container(self):
        # compose's container_name: two offices on one engine both answer to the bare service name
        env = dict(os.environ, DEPLOYMENT_NAME="exampleu")
        env.pop("DATA_REPO_SELF", None)
        p = subprocess.run([sys.executable, "-c", "import backup_run as b; print(b.SELF)"], cwd=str(HERE), env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.stdout.strip(), "data-management-exampleu:8080", p.stderr)


# ── with docker: the real helper ────────────────────────────────────────────────────────────────
@unittest.skipUnless(DOCKER and RESTIC, "needs docker on a shared network (TEST_SELF_HOST, TEST_NETWORK) and restic")
class RealHelper(unittest.TestCase):
    def setUp(self):
        VAULT.fail = 0

    def test_runs_keys_restic_and_secrets(self):
        VAULT.instances.clear()
        VAULT.posts = 0
        rec = Recorder()
        BR.subprocess.run, real = rec, BR.subprocess.run
        logs: list[str] = []
        files = {"apps/plane/plane.dump": os.urandom(2 * 1024 * 1024), "volumes/notes.txt": "פגישה\n".encode() * 999}
        try:
            r1 = BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export(files), logs.append, weekday=2)
            files["volumes/notes.txt"] = b"changed\n"
            r2 = BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export(files), logs.append, weekday=3)
        finally:
            BR.subprocess.run = real

        key = VAULT.instances[f"backup_key-{OFFICE}"]["secret"]["key"]
        self.assertEqual(VAULT.posts, 1, "the key is made once")
        self.assertEqual(r1["key_fingerprint"], r2["key_fingerprint"])
        self.assertNotEqual(r1["snapshot"], r2["snapshot"])
        self.assertLess(r2["added"], 1024 * 1024, "the second run sent the unchanged dump again")
        self.assertEqual((r1["check"], r2["check"]), ("2/7 ok", "3/7 ok"))
        self.assertEqual(BR.last(SHARED / "state", "herd-run")["snapshot"], r2["snapshot"])

        snaps = _local_snapshots("/גיבויים/run", key)
        self.assertEqual(len(snaps), 2)
        self.assertEqual({s["hostname"] for s in snaps}, {OFFICE})
        self.assertTrue(all(f"office={OFFICE}" in s["tags"] for s in snaps))
        self.assertEqual({s["paths"][0] for s in snaps}, {"/backup/office"})

        # the secrets: on stdin only — never on an argv, in the log, or in what is kept
        helpers = [(a, i) for a, i in rec.calls if a[:2] == ["docker", "run"]]
        self.assertEqual(len(helpers), 2)
        for argv, stdin in helpers:
            self.assertNotIn(key, " ".join(argv))
            self.assertIn(key, stdin)
            address = urllib.parse.urlsplit(stdin.splitlines()[0][len("rest:"):])
            token = address.password
            self.assertTrue(token and len(token) >= 40 and address.username.startswith("run-"), address.username)
            self.assertNotIn(token, " ".join(argv))
            for text in logs + [json.dumps(r1), json.dumps(r2)]:
                self.assertNotIn(token, text)
                self.assertNotIn(key, text)
        self.assertEqual(RS.RUNS._runs, {}, "a run's token outlived the run")
        self.assertEqual(list((SHARED / ".restic-staging").iterdir()), [])

        # the key is gone from the vault, the repository is there: the next run stops, sends nothing
        del VAULT.instances[f"backup_key-{OFFICE}"]
        with self.assertRaises(BR.Failed) as c:
            BR.run("herd-run", OFFICE, SHARED, SHARED / "state", fake_export(files), logs.append)
        self.assertIn("No new key", str(c.exception))
        self.assertEqual(VAULT.posts, 1)
        self.assertEqual(len(_local_snapshots("/גיבויים/run", key)), 2)

    def test_a_key_the_repository_does_not_open_is_never_answered_with_a_new_repository(self):
        VAULT.instances.clear()
        office = "wrongkey"
        BR.run("herd-wrongkey", office, SHARED, SHARED / "state", fake_export({"a": b"first"}), lambda s: None)
        first = VAULT.instances[f"backup_key-{office}"]["secret"]["key"]
        VAULT.instances[f"backup_key-{office}"]["secret"]["key"] = "not the key that made it"
        logs: list[str] = []
        with self.assertRaises(BR.Failed):
            BR.run("herd-wrongkey", office, SHARED, SHARED / "state", fake_export({"a": b"second"}), logs.append)
        self.assertEqual(len(_local_snapshots("/גיבויים/wrongkey", first)), 1, "the repository was touched")
        self.assertIn("  open: FAILED", logs, "stopped by the helper's own gate (restic exit 12), not later")
        self.assertNotIn("  init: ok", logs)
        self.assertEqual(RS.RUNS._runs, {})

    def test_a_new_repositorys_key_must_still_be_the_vaults_when_the_run_ends(self):
        VAULT.instances.clear()
        VAULT.gets.clear()
        office = "swapped"
        # read 1: none (404) · make it · read 2: the key that makes the repository · read 3, at the end: another
        VAULT.swap = (f"backup_key-{office}", 3, "a key the vault was rewritten with")
        try:
            with self.assertRaises(BR.Failed) as c:
                BR.run("herd-swapped", office, SHARED, SHARED / "state", fake_export({"a": b"x"}), lambda s: None)
        finally:
            VAULT.swap = None
        self.assertIn("no longer the key", str(c.exception))
        self.assertIsNone(BR.last(SHARED / "state", "herd-swapped"), "a run that cannot be opened was kept as good")

    def test_the_helper_clears_stale_locks_before_it_backs_up(self):
        VAULT.instances.clear()
        logs: list[str] = []
        BR.run("herd-unlock", "unlocks", SHARED, SHARED / "state-unlock", fake_export({"a": b"y"}), logs.append)
        self.assertIn("  unlock: ok", logs)


class TheApi(unittest.TestCase):
    """POST /api/backup runs a job; a refused run is `skipped`, never `done`."""

    def _job(self, target):
        req = urllib.request.Request(T.BASE + f"/api/backup?target={target}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            job = json.loads(r.read())["job"]
        for _ in range(600):
            with urllib.request.urlopen(T.BASE + f"/api/jobs/{job}", timeout=30) as r:
                js = json.loads(r.read())
            if js.get("state") not in ("starting", "running"):
                return js
            time.sleep(0.2)
        self.fail("the job never finished")

    def test_an_undeclared_target_is_skipped_with_its_reason(self):
        js = self._job("nobody")
        self.assertEqual(js["state"], "skipped")
        self.assertTrue(any("no backup target" in line for line in js["log"]))

    def test_no_backup_starts_while_a_restore_or_an_export_runs(self):
        for kind in ("import", "export"):
            T.APP.JOBS["busy-" + kind] = {"id": "busy-" + kind, "kind": kind, "state": "running", "log": []}
            try:
                req = urllib.request.Request(T.BASE + "/api/backup?target=herd-run", data=b"", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as c:
                    urllib.request.urlopen(req, timeout=30)
                self.assertEqual(c.exception.code, 409)
            finally:
                del T.APP.JOBS["busy-" + kind]

    def test_no_recorded_backup_is_a_404(self):
        try:
            urllib.request.urlopen(T.BASE + "/api/backup/last?target=nobody", timeout=30)
            self.fail("answered")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
