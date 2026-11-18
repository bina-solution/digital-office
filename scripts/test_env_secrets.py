"""test_env_secrets.py — scripts/env-secrets.py mints an office's own secrets, and never over its data (DGO-1220).

    python3 scripts/test_env_secrets.py

Run against a copy of the real template, with `docker` answered by a stub on PATH (a data volume, none, or
no answer). What it holds: a fresh office gets every TABLE key, the Supabase keys signed by its own JWT
secret; a value that is already real is kept; a placeholder counts as missing; an office with data, or one
docker cannot be asked about, is not written; the file keeps its link, gets mode 0600 and a backup; and no
value ever reaches the output.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "env-secrets.py")
sys.path.insert(0, os.path.join(REPO, "scripts"))
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("env_secrets", SCRIPT)
ES = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ES)


def values(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for k, v in re.findall(r"^([A-Z0-9_]+)=(.*)$", fh.read(), re.M):
            out[k] = v
    return out


class EnvSecrets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = os.path.join(self.dir, ".env")
        shutil.copy(os.path.join(REPO, ".env.ex"), self.env)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def docker(self, script):
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\n" + script + "\n")
        os.chmod(p, 0o755)

    def run_it(self, *args):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run([sys.executable, SCRIPT, "--env", self.env, *args], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr

    def assert_no_value_printed(self, out):
        for k, v in values(self.env).items():
            if k in ES.TABLE and len(v) >= 12:
                self.assertNotIn(v, out, f"{k}'s value reached the output")

    def test_a_fresh_office_gets_every_secret_its_own(self):
        self.docker("exit 0")                      # docker answers: no volume at all
        code, out = self.run_it("--if-fresh")
        self.assertEqual(code, 0, out)
        v = values(self.env)
        self.assertEqual([k for k in ES.TABLE if not v.get(k)], [])
        secret = v["SUPABASE_JWT_SECRET"]
        for key, role in (("SUPABASE_ANON_KEY", "anon"), ("SUPABASE_SERVICE_KEY", "service_role")):
            head, body, sig = v[key].split(".")
            want = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{head}.{body}".encode(),
                                                     hashlib.sha256).digest()).decode().rstrip("=")
            self.assertEqual(sig, want)
            self.assertEqual(json.loads(base64.urlsafe_b64decode(body + "=="))["role"], role)
        self.assertEqual(stat.S_IMODE(os.stat(self.env).st_mode), 0o600)
        self.assertTrue(any(f.startswith(".env.bak-") for f in os.listdir(self.dir)))
        self.assert_no_value_printed(out)
        before = values(self.env)
        self.run_it("--if-fresh")
        self.assertEqual(values(self.env), before, "a second run changed a value")

    @unittest.skipUnless(getattr(os, "geteuid", lambda: 1)() == 0, "only root writes a file another user owns")
    def test_a_rewrite_by_root_never_takes_the_file_from_the_office_user(self):
        # The HP, 2026-11-12 18:36Z (DGO-1863): the follow cycle (root) left .env root:root 0600, and the office's
        # own user — who owns the checkout and runs bbox as itself — could read no .env from then on.
        user, other = (4321, 4322), (1234, 1235)
        for checkout, old, want in ((user, (4321, 4325), (4321, 4325)),  # the user's file: stays exactly as it was
                                    (user, (0, 0), user),                # root's file in the user's checkout: the user's
                                    (user, None, user),                  # no file yet, in the user's checkout: the user's
                                    ((0, 0), other, other),              # someone's file in root's checkout: stays theirs
                                    ((0, 0), (0, 0), (0, 0))):           # an office run as root: root's, as before
            os.chown(self.dir, *checkout)
            if old is None:
                os.remove(self.env)
            else:
                os.chown(self.env, *old)
            ES.write(self.env, "DEPLOYMENT_NAME=hp\n")
            st = os.stat(self.env)
            self.assertEqual((st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)), (*want, 0o600),
                             f"checkout {checkout}, old file {old}")

    def test_two_offices_share_nothing(self):
        self.docker("exit 0")
        self.run_it("--fill")
        first = values(self.env)
        shutil.copy(os.path.join(REPO, ".env.ex"), self.env)
        self.run_it("--fill")
        second = values(self.env)
        self.assertEqual([k for k in ES.TABLE if first[k] == second[k]], [])

    def test_a_real_value_is_kept_and_a_placeholder_is_not(self):
        with open(self.env, "a") as fh:
            fh.write("\nPOSTGRES_PASSWORD=kept-by-the-owner-123456\nREDIS_PASSWORD=CHANGE_ME\n")
        self.run_it("--fill")
        v = values(self.env)
        self.assertEqual(v["POSTGRES_PASSWORD"], "kept-by-the-owner-123456")
        self.assertNotIn(v["REDIS_PASSWORD"], ("", "CHANGE_ME"))
        self.assertEqual(len(re.findall(r"^REDIS_PASSWORD=", open(self.env).read(), re.M)), 2)
        self.assertEqual(len(set(re.findall(r"^REDIS_PASSWORD=(.*)$", open(self.env).read(), re.M))), 1)

    def test_an_office_with_data_keeps_every_key_its_data_locks(self):
        every = " ".join(f"digital-office_{v}" for v in ES.DATA_VOLUMES)
        self.docker(f"for v in {every}; do echo $v; done")
        with open(self.env, "a") as fh:
            fh.write("\nCHAT_AUTH_PASS=CHANGE_ME\n")           # a placeholder in use: named, never replaced
        code, out = self.run_it("--if-fresh")
        v = values(self.env)
        for key in ES.LOCKED_BY:                                  # every volume is there: none of these made
            self.assertEqual(v.get(key, ""), "", key)
        self.assertEqual(v["CHAT_AUTH_PASS"], "CHANGE_ME")
        self.assertTrue(v["MCP_AUTH_TOKEN"])                      # locks no data: an empty one is made
        self.assertIn("this office has data", out)
        self.assertIn("POSTGRES_PASSWORD", out)                   # empty, so named for the rotation
        self.assert_no_value_printed(out)

    def test_an_app_switched_on_later_gets_its_keys(self):
        self.docker("echo digital-office_connections_vault; echo digital-office_supabase_db_data")
        self.run_it("--if-fresh")
        v = values(self.env)
        self.assertTrue(v["GLITCHTIP_DB_PASSWORD"] and v["PLANE_DB_PASSWORD"])   # their data is not there yet
        self.assertEqual(v["SUPABASE_DB_PASSWORD"], "")                          # its data is
        self.assertEqual(v["CONNECTIONS_ROOT_KEY"], "")

    def test_docker_without_an_answer_is_never_fresh(self):
        self.docker("exit 1")
        with open(self.env, "rb") as fh:
            before = fh.read()
        _, out = self.run_it("--if-fresh")
        with open(self.env, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertIn("could not be asked", out)

    def test_the_link_is_kept(self):
        self.docker("exit 0")
        target = os.path.join(self.dir, "binaos.env")
        os.rename(self.env, target)
        os.symlink(target, self.env)
        self.run_it("--if-fresh")
        self.assertTrue(os.path.islink(self.env))
        self.assertTrue(values(target)["POSTGRES_PASSWORD"])

    def test_a_published_value_is_named(self):
        known = ES.public_hashes()
        self.assertGreater(len(known), 0)
        with open(self.env, "a") as fh:
            fh.write("\nCONNECTIONS_ROOT_KEY=dev-root-key-not-for-production\n")
        _, out = self.run_it("--check")
        self.assertIn("CONNECTIONS_ROOT_KEY", out)

    def test_a_short_value_the_template_once_held_is_named_from_history(self):
        # DGO-1015: the hash file leaves out low-entropy values (their hash could be reversed); the checkout's own
        # history names them, in memory. A git checkout whose .env.ex once held a short POSTGRES_PASSWORD:
        git = ["git", "-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        short = "pg" + "4u2Xq9"                                  # 8 characters, made up here
        theirs = "jvb" + "Zq81mR0pLx"                            # an app's own secret, made up here
        with open(os.path.join(self.dir, ".env.ex"), "w") as fh:
            fh.write(f"POSTGRES_PASSWORD={short}\nMEET_JVB_PASSWORD={theirs}\n")
        subprocess.run(git + ["add", ".env.ex"], check=True)
        subprocess.run(git + ["commit", "-qm", "the old template"], check=True)
        with open(os.path.join(self.dir, ".env.ex"), "w") as fh:
            fh.write("POSTGRES_PASSWORD=\nMEET_JVB_PASSWORD=\n")
        subprocess.run(git + ["commit", "-qam", "the template carries none"], check=True)
        ES.fill(self.env)
        lines = [ln for ln in open(self.env, encoding="utf-8").read().splitlines()
                 if not ln.startswith(("POSTGRES_PASSWORD=", "MEET_JVB_PASSWORD="))]
        with open(self.env, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines + [f"POSTGRES_PASSWORD={short}", f"MEET_JVB_PASSWORD={theirs}"]) + "\n")
        self.assertNotIn(hashlib.sha256(short.encode()).hexdigest(), ES.public_hashes())
        self.assertIn("POSTGRES_PASSWORD", ES.still_public(self.env, history=True))
        self.assertNotIn("POSTGRES_PASSWORD", ES.still_public(self.env))
        self.assertEqual(ES.public_outside_table(self.env), ["MEET_JVB_PASSWORD"])
        # a value that only a merged-away side branch published is in the history too (--full-history -m)
        side = "sd" + "Q7w1Zk"
        subprocess.run(git + ["checkout", "-qb", "side"], check=True)
        with open(os.path.join(self.dir, ".env.ex"), "w") as fh:
            fh.write(f"POSTGRES_PASSWORD=\nMEET_JVB_PASSWORD=\nCHAT_AUTH_PASS={side}\n")
        subprocess.run(git + ["commit", "-qam", "a side branch"], check=True)
        subprocess.run(git + ["checkout", "-q", "-"], check=True)
        subprocess.run(git + ["merge", "-q", "-s", "ours", "side", "-m", "keep ours"], check=True)
        subprocess.run(git + ["branch", "-qD", "side"], check=True)
        self.assertIn(hashlib.sha256(side.encode()).hexdigest(), ES.history_hashes(self.dir))
        # a DSN's embedded password counts
        dsn_pw = "dsn" + "Pw55xq"
        self.assertTrue(ES.DSN_PW.findall(f"postgres://u:{dsn_pw}@h:5432/db") == [dsn_pw])
        rc, out = self.run_it("--check")
        self.assertEqual(rc, 1)
        self.assertIn("POSTGRES_PASSWORD", out)
        self.assertIn("MEET_JVB_PASSWORD", out)
        self.assertNotIn(short, out)
        self.assertNotIn(theirs, out)


class RotationPlan(unittest.TestCase):
    """DGO-1015: `--rotate … --plan` says how each key is rotated and who reads it, and writes nothing."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "apps", "demo", "blueprint"))
        with open(os.path.join(self.dir, "apps", "demo", "docker-compose.yml"), "w") as fh:
            fh.write("services:\n  demo:\n    environment:\n      - TOKEN=${DEMO_TOKEN:?set}\n"
                     "  demo-worker:\n    env_file: ../../.env\n  demo-own:\n    env_file:\n    - path: .env\n"
                     "      required: false\n  other:\n    image: x\n"
                     "      # ${DEMO_TOKEN} in a comment reads nothing\n")
        with open(os.path.join(self.dir, "apps", "demo", "blueprint", "flow.json"), "w") as fh:
            fh.write('{"auth": "$env.DEMO_TOKEN"}\n')
        with open(os.path.join(self.dir, "apps", "demo", "hook.sh"), "w") as fh:
            fh.write("curl -H \"X: $DEMO_TOKEN\"\nDEMO_TOKENS=1\n")
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        ES._TREES.clear()
        ES._INDEX.clear()

    def test_every_kind_of_consumer_is_named(self):
        c = ES.consumers("DEMO_TOKEN", self.dir)
        self.assertEqual(c["services"], ["apps/demo/docker-compose.yml: demo"])
        # ../../.env is the office's; `path: .env` beside the compose is the app's own file, not the office's
        self.assertEqual(c["whole_env"], ["apps/demo/docker-compose.yml: demo-worker"])
        self.assertEqual(c["blueprints"], ["apps/demo/blueprint/flow.json"])
        self.assertEqual(c["code"], ["apps/demo/hook.sh"])

    def test_a_key_is_named_whole_never_by_its_prefix(self):
        self.assertEqual(ES.consumers("DEMO_TOK", self.dir)["services"], [])

    def test_each_key_has_its_class(self):
        # on the real tree: n8n's credentials copy the webhook pass; n8n issues its API key; authentik's key locks
        # data; chat's relay key is an identity others verify
        self.assertEqual(ES.rotation_class("EXAMPLEM_API_TOKEN"), "token")
        self.assertEqual(ES.rotation_class("CHAT_RELAY_KEY"), "locked")
        self.assertEqual(ES.rotation_class("N8N_WEBHOOK_PASS"), "n8n-copy")
        self.assertEqual(ES.rotation_class("N8N_API_KEY"), "app-made")
        self.assertEqual(ES.rotation_class("AUTHENTIK_SECRET_KEY"), "locked")
        self.assertEqual(ES.rotation_class("BROWSER42_STATE_PASSPHRASE"), "encryption")
        self.assertEqual(ES.rotation_class("POSTGRES_PASSWORD"), "db-role")
        self.assertEqual(ES.rotation_class("SUPABASE_JWT_SECRET"), "signing")
        self.assertEqual(ES.rotation_class("N8N_ENCRYPTION_KEY"), "encryption")
        self.assertEqual(ES.rotation_class("OPENAI_API_KEY"), "external")
        for name in ("DEPLOYMENT_NAME", "DGO_SERVE_SECRETS", "GLITCHTIP_SENTRY_DSN"):
            self.assertIsNone(ES.rotation_class(name), name)

    def test_n8n_reads_its_own_env_file_not_the_offices(self):
        whole = ES.consumers("EXAMPLEM_API_TOKEN")["whole_env"]
        self.assertIn("platform-base/connections/docker-compose.yml: connections", whole)
        self.assertFalse([w for w in whole if w.startswith("apps/n8n/")], whole)

    def test_nothing_is_written_and_no_value_is_printed(self):
        env = os.path.join(self.dir, ".env")
        secret = "tok" + "9Qz7Lm2Xr8Vb"
        with open(env, "w") as fh:
            fh.write(f"EXAMPLEM_API_TOKEN={secret}\nPOSTGRES_PASSWORD=CHANGE_ME\n")
        before = open(env).read()
        for args in (["--rotate"], ["--rotate", "EXAMPLEM_API_TOKEN"],          # the rotation itself: not built yet
                     ["--rotate", f"EXAMPLEM_API_TOKEN={secret}", "--plan"],     # a value where a name goes
                     ["--rotate", "--fill", "--plan"]):                        # two modes: never the fill
            r = subprocess.run([sys.executable, SCRIPT, "--env", env, *args], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, args[:3])
            self.assertNotIn(secret, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, SCRIPT, "--rotate", "EXAMPLEM_API_TOKEN", "--plan", "--env", env],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("EXAMPLEM_API_TOKEN — token", r.stdout)
        self.assertNotIn("not a secret", r.stdout)                  # the --env operand is not taken for a key
        self.assertNotIn(secret, r.stdout + r.stderr)
        self.assertEqual(open(env).read(), before)


class RotateToken(unittest.TestCase):
    """DGO-1015: a TOKEN rotates whole — new value, its running readers recreated and healthy — or not at all.
    Compose is a stateful fake: what runs, what its dry run would recreate, and an up that deploys or fails; the
    up's process and its group's signals are fakes too, so no test touches a real process."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "apps", "chat", "blueprint"))
        with open(os.path.join(self.dir, "apps", "chat", "docker-compose.yml"), "w") as fh:
            fh.write("services:\n  chat:\n    environment:\n      - AUTH=${EXAMPLEM_API_TOKEN:?x}\n"
                     "  chat-off:\n    environment:\n      - AUTH=${EXAMPLEM_API_TOKEN:?x}\n")
        with open(os.path.join(self.dir, "apps", "chat", "blueprint", "w.json"), "w") as fh:
            fh.write('{"h": "$env.ASSETS_API_TOKEN"}\n')
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        self.env = os.path.join(self.dir, ".env")
        self.old = "old" + "Tok3n9xQ"
        with open(self.env, "w") as fh:
            fh.write(f"DEPLOYMENT_NAME=local\nEXAMPLEM_API_TOKEN={self.old}\nASSETS_API_TOKEN=as{'Z' * 9}\n")
        self.calls, self.ups, self.kills = [], [], []
        self.state = {"chat": "running"}
        self.deployed = self.hash_now()
        self.pending = False          # the container is not what the compose says already
        self.ignores_env = False      # compose never sees the change
        self.on_dry = None            # something another writer does while compose is asked
        self.names = {}               # container names compose reports, by service (default <svc>-local)
        self.foreign = []             # names the ENGINE holds in another compose project
        self.compiled_name = "chat-local"   # the container_name the compiled compose gives chat
        self.extra_rows = []          # more `ps -a` rows (a one-off, a row compose cannot place)
        self.events = []              # popen / wait / kill, in order
        self.second_signal = False
        self.dry_name = "chat-local"  # the container the dry run names for chat
        self.dry_prefix = ""          # compose 2.40 starts every dry-run line with «DRY-RUN MODE -»

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        ES._TREES.clear()
        ES._INDEX.clear()

    def hash_now(self):
        return values(self.env).get("EXAMPLEM_API_TOKEN", "")

    def compose(self, cmd, **_):
        self.calls.append(cmd[1:])
        args, out, err = cmd[1:], "", ""
        if cmd[0] == "docker":                           # the engine itself: names in ANY project
            out = "\n".join(self.foreign + ["unrelated-thing"])
        elif args[:3] == ["config", "--format", "json"]:
            out = json.dumps({"name": "proj", "services": {"chat": {"container_name": self.compiled_name},
                                                           "other": {}}})
        elif args[:2] == ["config", "--services"]:
            out = "chat\nother\n"
        elif args[:1] == ["ps"]:
            out = "\n".join([json.dumps({"Service": s, "Name": self.names.get(s, f"{s}-local"), "State": st,
                                         "Labels": "com.docker.compose.oneoff=False"})
                             for s, st in self.state.items()] + [json.dumps(r) for r in self.extra_rows])
        elif args[:2] == ["--dry-run", "up"]:
            if self.on_dry:
                self.on_dry()
            changed = self.hash_now() != self.deployed and not self.ignores_env
            if (changed or self.pending) and self.state.get("chat") == "running":
                # as compose prints it: progress on STDERR, with colour; and a neighbour's line is not ours
                p = self.dry_prefix
                err = (f"\x1b[1m{p} Container {self.dry_name}  Recreate\x1b[0m\n{p} Container {self.dry_name}  "
                       f"Recreated\n{p} Container chat-off-local  Running\n")
        return subprocess.CompletedProcess(cmd, 0, out, err)

    def popen(self, up_rc=0, raise_first=None):
        test = self

        class Proc:
            pid = 424242

            def __init__(self, cmd, **kw):
                test.ups.append((cmd[1:], kw.get("start_new_session")))
                self.n = len(test.ups)
                test.events.append(("popen", self.n))

            def wait(self, timeout=None):
                test.events.append(("wait", self.n))
                if raise_first is not None and self.n == 1 and not test.kills:
                    raise raise_first
                rc = up_rc if (test.hash_now() != test.deployed and self.n == 1) else 0
                if rc == 0:
                    test.deployed = test.hash_now()
                return rc
        return Proc

    def killpg(self, pid, sig):
        self.kills.append((pid, sig))
        self.events.append(("kill", sig))
        if self.second_signal and len(self.kills) == 1:  # a second, REAL SIGTERM lands while the first up stops
            import signal as sg
            os.kill(os.getpid(), sg.SIGTERM)

    def rotate(self, key="EXAMPLEM_API_TOKEN", path=None, **kw):
        return ES.rotate(path or self.env, key, self.dir, self.compose, self.popen(**kw), self.killpg)

    def value(self):
        return values(self.env)["EXAMPLEM_API_TOKEN"]

    def test_a_token_gets_a_new_value_and_its_running_reader_is_recreated_in_its_own_group(self):
        code, said = self.rotate()
        self.assertEqual(code, 0, said)
        self.assertNotEqual(self.value(), self.old)
        self.assertEqual(self.ups, [(["up", "-d", "--no-build", "--no-deps", "--wait", "--wait-timeout", "180",
                                      "chat"], True)])
        self.assertNotIn(self.value(), said)
        self.assertTrue([f for f in os.listdir(self.dir) if f.startswith(".env.bak-")], "a backup first")

    def test_readers_that_do_not_come_back_get_the_old_value_back(self):
        code, said = self.rotate(up_rc=1)
        self.assertEqual(code, 1, said)
        self.assertEqual(self.value(), self.old)
        self.assertEqual(len(self.ups), 2)                      # the rotation's up, then the old value's

    def test_an_interruption_stops_the_whole_group_then_puts_the_old_value_back(self):
        import signal as sig
        with self.assertRaises(KeyboardInterrupt):
            self.rotate(raise_first=KeyboardInterrupt())
        self.assertEqual(self.kills[0], (424242, sig.SIGTERM))
        self.assertEqual(self.value(), self.old)
        self.assertEqual(len(self.ups), 2)

    def test_a_change_compose_never_sees_is_not_called_done(self):
        self.ignores_env = True
        code, said = self.rotate()
        self.assertEqual((code, self.value(), self.ups), (1, self.old, []), said)

    def test_a_reader_with_something_else_pending_is_refused_untouched(self):
        self.pending = True
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.ups), (2, before, []), said)

    def test_compose_2_40s_prefixed_dry_run_is_read(self):
        # compose v2.40.3's own lines (measured on the MacBook, 2026-11-11): « DRY-RUN MODE -  Container x  Recreate»
        self.dry_prefix = " DRY-RUN MODE - "
        code, said = self.rotate()
        self.assertEqual(code, 0, said)                         # it used to read «nothing recreated» and restore
        self.assertNotEqual(self.value(), self.old)
        self.pending, self.deployed, self.ups = True, self.hash_now(), []
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.ups), (2, before, []), said)   # pending work refuses, untouched

    def test_a_stopped_reader_is_refused_it_would_come_back_on_the_old_value(self):
        for st in ("exited", "created"):
            self.state = {"chat": st}
            before = open(self.env).read()
            code, said = self.rotate()
            self.assertEqual((code, open(self.env).read(), self.ups), (2, before, []), f"{st}: {said}")

    def test_a_reader_with_no_container_yet_is_made_with_the_new_value(self):
        self.state = {}
        code, said = self.rotate()
        self.assertEqual((code, self.ups), (0, []), said)
        self.assertNotEqual(self.value(), self.old)

    def test_a_reader_running_under_another_project_is_refused(self):
        self.state, self.foreign = {}, ["chat-local"]
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.ups), (2, before, []), said)

    def test_the_compiled_container_name_is_what_is_looked_for(self):
        # supabase's studio is `supabase-studio-<dep>`, not `<svc>-<dep>`: the compose's own name is the one asked
        self.state, self.compiled_name, self.foreign = {}, "supabase-chat-odd", ["supabase-chat-odd"]
        before = open(self.env).read()
        self.assertEqual((self.rotate()[0], open(self.env).read()), (2, before))

    def test_a_row_compose_cannot_place_is_refused_and_a_one_off_is_not_the_service(self):
        self.extra_rows = [{"Name": "x", "State": "running", "Labels": ""}]          # no Service
        before = open(self.env).read()
        self.assertEqual((self.rotate()[0], open(self.env).read()), (1, before))
        self.extra_rows = [{"Service": "chat", "Name": "p-chat-run-1", "State": "exited",
                            "Labels": "com.docker.compose.oneoff=True"}]
        code, said = self.rotate()
        self.assertEqual(code, 0, said)

    def test_a_second_signal_while_the_first_up_stops_waits_for_it_before_the_restore(self):
        self.second_signal = True
        with self.assertRaises(KeyboardInterrupt):
            self.rotate(raise_first=KeyboardInterrupt())
        self.assertEqual(self.value(), self.old)
        import signal as sg
        killed = self.events.index(("kill", sg.SIGTERM))
        second_up = self.events.index(("popen", 2))
        self.assertIn(("wait", 1), self.events[killed + 1:second_up],
                      f"the first up's group is waited on AFTER it is stopped and BEFORE the restore: {self.events}")

    def test_a_service_runs_only_if_all_its_containers_do(self):
        # the stopped one listed FIRST and a running one after it: last-row-wins would call the service running
        self.state = {"chat": "exited"}
        self.extra_rows = [{"Service": "chat", "Name": "chat-local-2", "State": "running", "Labels": ""}]
        before = open(self.env).read()
        self.assertEqual((self.rotate()[0], open(self.env).read()), (2, before))

    def test_a_container_named_its_own_way_is_read_by_what_compose_says_it_is(self):
        self.names = {"chat": "rest-of-a-supabase-thing"}       # supabase's rest, kong… are not <svc>-<deployment>
        self.dry_name = "rest-of-a-supabase-thing"
        code, said = self.rotate()
        self.assertEqual(code, 0, said)

    def test_a_restarting_reader_is_refused(self):
        self.state = {"chat": "restarting"}
        before = open(self.env).read()
        self.assertEqual((self.rotate()[0], open(self.env).read()), (2, before))

    def test_another_writers_line_survives_the_rotation(self):
        def other():
            if "OTHER_WRITER_KEY" not in open(self.env).read():
                with open(self.env, "a") as fh:
                    fh.write("OTHER_WRITER_KEY=added\n")
        self.on_dry = other
        code, said = self.rotate()
        self.assertEqual(code, 0, said)
        self.assertEqual(values(self.env).get("OTHER_WRITER_KEY"), "added")

    def test_only_the_offices_own_env_and_only_its_plain_form(self):
        other = os.path.join(self.dir, "other.env")
        shutil.copy(self.env, other)
        self.assertEqual(self.rotate(path=other)[0], 2)
        with open(self.env, "a") as fh:
            fh.write(f"export EXAMPLEM_API_TOKEN={self.old}\n")
        before = open(self.env).read()
        self.assertEqual(self.rotate()[0], 2)
        self.assertEqual((open(self.env).read(), self.ups), (before, []))

    def test_a_copy_elsewhere_or_another_class_is_refused_untouched(self):
        before = open(self.env).read()
        for key in ("ASSETS_API_TOKEN", "POSTGRES_PASSWORD", "N8N_ENCRYPTION_KEY", "OPENAI_API_KEY",
                    "AUTHENTIK_SECRET_KEY", "N8N_API_KEY", "CHAT_RELAY_KEY"):
            code, said = self.rotate(key)
            self.assertEqual(code, 2, f"{key}: {said}")
        self.assertEqual((open(self.env).read(), self.ups, self.calls), (before, [], []))


class RotateN8nCopy(RotateToken):
    """DGO-1015: an N8N-COPY key — a token n8n also keeps in an env-managed credential — rotates as a token does (every
    RotateToken case runs again here, with n8n's copy in the tree; n8n runs unless a case sets its own state, and the
    cases that do run the no-n8n path), and n8n's copy follows:
    `apps/n8n/hooks/push --reseed-only` after the readers, on the NEW .env; when it does not take, everything is undone
    and it runs again on the OLD .env. The re-seed is a fake process like the up: it notes the value .env holds when
    it runs, and says what the hook says."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.dir, "apps", "n8n"))
        with open(os.path.join(self.dir, "apps", "n8n", "blueprint.yml"), "w") as fh:
            fh.write("workflows: []\n"
                     '  notAnOverride01: {"name":"x","type":"t","data":{"k":"${NOT_READ_BEFORE_THE_BLOCK}"}}\n'
                     "credential_overrides:\n"
                     '  chatAuth0000001: {"name":"Chat","type":"httpBasicAuth","data":{"user":"${CHAT_USER_X}",'
                     '"password":"${EXAMPLEM_API_TOKEN}"}}\n')
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        with open(self.env, "a") as fh:
            fh.write("CHAT_USER_X=chat\n")
        self.state["n8n"] = "running"
        self.reseeds, self.reseed_rcs = [], []    # the .env value each re-seed ran on; the exit codes they give
        self.cut_at, self.cut_with = None, None   # the re-seed (1 = the proof) whose first wait raises, and what
        self.settles, self.settle_rc = 0, 0       # the waits for a cut-off re-seed inside n8n; what they answer
        self.restore_fails, self.reseed_said = False, {}   # the old value's up fails; re-seed n's own output

    def compose(self, cmd, **kw):
        if cmd[1:3] == ["exec", "-T"]:                   # `dc exec -T n8n sh -c RESEED_SETTLE`
            self.assertEqual(cmd[3:6], ["n8n", "sh", "-c"])
            self.settles += 1
            self.events.append(("settle", self.settles))
            return subprocess.CompletedProcess(cmd, self.settle_rc, "", "")
        return super().compose(cmd, **kw)

    def popen(self, up_rc=0, raise_first=None):
        test, up = self, RotateToken.popen(self, up_rc, raise_first)

        def proc(cmd, **kw):
            if cmd[0] != "bash":
                p = up(cmd, **kw)
                if test.restore_fails and p.n == 2:            # the old value's up does not come back healthy
                    first = p.wait
                    p.wait = lambda timeout=None: (first(timeout), 1)[1]
                return p
            test.assertEqual(cmd[1:], [os.path.join(test.dir, "apps", "n8n", "hooks", "push"), "--reseed-only"])
            test.reseeds.append(test.hash_now())
            n = len(test.reseeds)
            test.events.append(("reseed", n))
            rc = test.reseed_rcs.pop(0) if test.reseed_rcs else 0
            if n in test.reseed_said:                           # the hook's own words, as given
                kw["stdout"].write(test.reseed_said[n])
            else:
                kw["stdout"].write(f"[n8n-push] owner exists\n[n8n-push]   reseed chatAuth0000001 HTTP 400 "
                                   f"{test.hash_now()}\n" if rc else "")      # n8n's answer body: never repeated
                kw["stdout"].write(f"[n8n-push]   reseeded {0 if rc else 1}/1 env-driven credential(s) from .env\n")

            class Reseed:
                pid = 434343
                waited = False

                def wait(self, timeout=None):
                    first, self.waited = not self.waited, True
                    if first and test.cut_at == n:             # cut off from outside: a signal, or the limit
                        raise test.cut_with
                    return rc
            return Reseed()
        return proc

    def test_n8n_s_copy_follows_the_new_value_after_the_readers(self):
        code, said = self.rotate()
        self.assertEqual(code, 0, said)
        self.assertEqual(self.reseeds, [self.old, self.value()])      # the proof on today's .env, then the NEW one
        self.assertLess(self.events.index(("reseed", 1)), self.events.index(("popen", 1)))
        self.assertLess(self.events.index(("wait", 1)), self.events.index(("reseed", 2)))
        self.assertIn("n8n's credentials re-seeded (reseeded 1/1", said)
        self.assertNotIn(self.value(), said)
        self.assertEqual(self.settles, 0)                              # nothing was cut off: nothing to wait out

    def test_a_reseed_that_does_not_run_on_today_s_env_refuses_before_anything_moves(self):
        self.reseed_rcs = [3]
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.ups, self.reseeds), (1, before, [], [self.old]), said)
        self.assertIn("does not run on this office as it is (reseed chatAuth0000001 HTTP 400", said)
        self.assertNotIn(self.old, said)

    def test_a_reseed_that_does_not_take_undoes_all_of_it_n8n_s_copy_included(self):
        self.reseed_rcs = [0, 3, 0]
        code, said = self.rotate()
        self.assertEqual(code, 1, said)
        self.assertEqual(self.value(), self.old)
        new = self.reseeds[1]
        self.assertEqual(self.reseeds, [self.old, new, self.old])     # proof, the new value, the old one again
        self.assertNotEqual(new, self.old)
        self.assertEqual(len(self.ups), 2)                             # the rotation's up, then the old value's
        self.assertIn("reseed chatAuth0000001 HTTP 400", said)
        self.assertIn("recreated with the old one (healthy), n8n re-seeded with the old one", said)
        self.assertNotIn(new, said)                                    # not even through n8n's answer body
        self.assertEqual(self.settles, 0)                              # it ended by itself: nothing to wait out

    def test_an_undo_that_cannot_reseed_says_what_to_run(self):
        self.reseed_rcs = [0, 3, 3]
        code, said = self.rotate()
        self.assertEqual((code, self.value()), (1, self.old), said)
        self.assertIn("could NOT be re-seeded with the old one: run `bbox n8n push all --reseed-only` now", said)

    def test_with_no_reader_container_the_copy_still_follows_and_is_still_undone(self):
        self.state = {"n8n": "running"}                                # chat has no container: no up at all
        code, said = self.rotate()
        self.assertEqual((code, self.ups, self.reseeds), (0, [], [self.old, self.value()]), said)
        self.reseed_rcs, self.reseeds = [0, 3, 0], []
        before = self.value()
        code, said = self.rotate()
        self.assertEqual((code, self.value(), self.ups), (1, before, []), said)
        self.assertEqual(self.reseeds[2], before)
        self.assertNotIn("recreated with the old one", said)
        self.assertIn(".env restored, n8n re-seeded with the old one", said)

    def test_an_interruption_during_the_reseed_waits_it_out_in_n8n_then_undoes_it_and_says_so(self):
        import contextlib
        import io
        self.cut_at, self.cut_with = 2, KeyboardInterrupt("signal")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            self.rotate()
        self.assertEqual(self.value(), self.old)
        self.assertEqual(self.reseeds[2:], [self.old])
        self.assertIn(434343, [pid for pid, _ in self.kills])         # the re-seed's own group was stopped
        self.assertEqual(self.settles, 1)                              # and what it left inside n8n waited out
        self.assertLess(self.events.index(("settle", 1)), self.events.index(("reseed", 3)))   # BEFORE the undo
        self.assertIn("EXAMPLEM_API_TOKEN: stopped — .env restored, chat recreated with the old one (healthy), n8n "
                      "re-seeded with the old one", err.getvalue())

    def test_an_interruption_whose_readers_do_not_come_back_says_so(self):
        import contextlib
        import io
        self.cut_at, self.cut_with, self.restore_fails = 2, KeyboardInterrupt("signal"), True
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            self.rotate()
        self.assertIn("chat recreated with the old one (NOT healthy: look at them now)", err.getvalue())

    def test_a_re_seed_its_guard_refused_left_n8n_untouched_and_says_so(self):
        # the push guard refuses before any PATCH (origin moved during the up): n8n still holds the old copy, and the
        # same command would be refused again — so no undo re-seed and no instruction to run one
        self.reseed_rcs = [0, 1]
        self.reseed_said = {2: "this checkout (HEAD 1a2b3c4) is BEHIND its office's branch:\n"
                               "Error: n8n push refused (above). Nothing was changed.\n"}
        code, said = self.rotate()
        self.assertEqual((code, self.value(), len(self.reseeds)), (1, self.old, 2), said)
        self.assertIn("n8n push refused (above). Nothing was changed", said)
        self.assertIn("n8n untouched (its re-seed was refused before any PATCH)", said)
        self.assertNotIn("--reseed-only` now", said)

    def test_a_proof_stopped_at_its_limit_gives_the_signals_back(self):
        import signal as sg
        before = {s: sg.getsignal(s) for s in (sg.SIGINT, sg.SIGTERM, sg.SIGHUP)}
        self.cut_at, self.cut_with = 1, subprocess.TimeoutExpired("bash", 1200)
        code, said = self.rotate()
        self.assertEqual((code, self.value()), (1, self.old), said)
        self.assertIn("no answer in 1200 s — stopped", said)
        self.assertEqual({s: sg.getsignal(s) for s in before}, before)   # not left ignored: the next one can be stopped

    def test_the_wait_finds_the_re_seed_where_busybox_pgrep_can_see_it(self):
        # busybox's pgrep -f reads 1023 bytes of a command line: the marker the wait looks for must be there, at the
        # head of the hook's own re-seed script — a phrase deeper in it was never matched (the second reader)
        hook = open(os.path.join(REPO, "apps", "n8n", "hooks", "push"), encoding="utf-8").read()
        start = hook.index("node -e '/*dgo-reseed*/")
        self.assertIn("RESEED_STRICT", hook[hook.rindex("RESEED_ENV", 0, start) - 400:start])   # the re-seed's own
        script = hook[start + len("node -e '"):]
        self.assertTrue(script.startswith("/*dgo-reseed*/"), script[:40])     # the script's very first bytes
        self.assertIn('pgrep -f "[d]go-reseed"', ES.RESEED_SETTLE)

    def test_what_the_hook_says_when_it_cannot_run_is_repeated_in_its_words(self):
        hook = open(os.path.join(REPO, "apps", "n8n", "hooks", "push"), encoding="utf-8").read()
        for line, said in (("[n8n-push] LOCKED — another push is already running: pid=1 host=h started=t scope=all",
                            "LOCKED — another push is already running"),
                           ("[n8n-push] ERROR: still locked after 15m — refusing to wait longer.",
                            "still locked after 15m"),
                           ("[n8n-push] FATAL: N8N_ENCRYPTION_KEY in .env does not match the running instance, and",
                            "N8N_ENCRYPTION_KEY in .env does not match the running instance"),
                           ("Error: 'n8n-local' not running.", "'n8n-local' not running")):
            self.assertEqual(ES.RESEED_SAID.search(line).group(0), said)
            self.assertIn(said.replace("n8n-local", "${N8N_CONTAINER}"), hook)    # still the hook's own words

    def test_an_interruption_whose_undo_fails_says_so(self):
        import contextlib
        import io
        self.cut_at, self.cut_with, self.reseed_rcs = 2, KeyboardInterrupt("signal"), [0, 0, 3]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            self.rotate()
        self.assertEqual(self.value(), self.old)
        self.assertIn("could NOT be re-seeded with the old one: run `bbox n8n push all --reseed-only` now",
                      err.getvalue())
        self.assertNotIn(self.reseeds[1], err.getvalue())

    def test_a_reseed_past_its_limit_is_stopped_waited_out_and_said(self):
        self.cut_at, self.cut_with = 2, subprocess.TimeoutExpired("bash", 1200)
        self.settle_rc = 1                                             # still running inside n8n after two minutes
        code, said = self.rotate()
        self.assertEqual((code, self.value(), self.settles), (1, self.old, 1), said)
        self.assertIn("no answer in 1200 s — stopped", said)
        self.assertIn("could not be seen to end inside n8n: run `bbox n8n push all --reseed-only` again", said)

    def test_a_key_n8n_itself_reads_goes_with_the_full_push(self):
        with open(os.path.join(self.dir, "apps", "n8n", "docker-compose.yml"), "w") as fh:
            fh.write("services:\n  n8n:\n    environment:\n      - P=${EXAMPLEM_API_TOKEN:?x}\n")
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.reseeds), (2, before, []), said)
        self.assertIn("that is `bbox n8n push all`'s", said)

    def test_an_n8n_service_that_loads_the_whole_env_goes_with_the_full_push_too(self):
        with open(os.path.join(self.dir, "apps", "n8n", "docker-compose.yml"), "w") as fh:
            fh.write("services:\n  n8n:\n    env_file: ../../.env\n")
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        self.assertIn("apps/n8n/docker-compose.yml: n8n", ES.consumers("EXAMPLEM_API_TOKEN", self.dir)["whole_env"])
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.reseeds), (2, before, []), said)
        self.assertIn("that is `bbox n8n push all`'s", said)

    def test_n8n_under_another_project_is_refused(self):
        del self.state["n8n"]
        self.foreign = ["proj-n8n-1"]
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.reseeds), (2, before, []), said)
        self.assertIn("n8n runs under another compose project (proj-n8n-1)", said)

    def test_set_means_what_read_env_says_it_means(self):
        shapes = {"PLAIN": "chat", "EMPTY": "", "REF": "${PLAIN}", "MISSING": "${NOPE}", "DFLT": "${NOPE:-d}",
                  "MID": "x${PLAIN}y", "OPEN": "${", "OPEN2": "${PLAIN", "TWO": "${PLAIN}${EMPTY}", "DUP": "",
                  "QUOTED": '"q"', "CRLF": "v\r"}
        lines = [f"{k}={v}" for k, v in shapes.items()] + ["DUP=second"]
        with open(os.path.join(self.dir, ".env"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        lib = os.path.join(REPO, "scripts", "lib.sh")
        for k in [*shapes, "ABSENT"]:
            r = subprocess.run(["bash", "-c", f'REPO_ROOT="$1"; . "$2" >/dev/null 2>&1; read_env {k}', "_", self.dir,
                                lib], capture_output=True, text=True)
            self.assertEqual(ES._env_resolved(lines, k), r.stdout, k)

    def test_a_credential_the_reseed_would_skip_is_refused_untouched(self):
        for line in ("", "CHAT_USER_X=\n", "CHAT_USER_X=${NOT_SET_ANYWHERE}\n"):
            with open(self.env, "w") as fh:
                fh.write(f"DEPLOYMENT_NAME=local\nEXAMPLEM_API_TOKEN={self.old}\n{line}")
            before = open(self.env).read()
            code, said = self.rotate()
            self.assertEqual((code, open(self.env).read(), self.ups, self.reseeds), (2, before, [], []), said)
            self.assertIn("SKIP n8n's credential chatAuth0000001", said)
            self.assertIn("CHAT_USER_X empty", said)
        with open(self.env, "a") as fh:                                # read_env takes the FIRST line: still empty
            fh.write("CHAT_USER_X=chat\n")
        self.assertEqual(self.rotate()[0], 2)
        with open(self.env, "w") as fh:                                # a default makes it set, as read_env does
            fh.write(f"DEPLOYMENT_NAME=local\nEXAMPLEM_API_TOKEN={self.old}\nCHAT_USER_X=${{NOT_SET_ANYWHERE:-chat}}\n")
        code, said = self.rotate()
        self.assertEqual((code, self.reseeds), (0, [self.old, self.value()]), said)

    def test_a_copy_the_reseed_never_reaches_is_refused_untouched(self):
        os.makedirs(os.path.join(self.dir, "apps", "n8n", "credentials"))
        with open(os.path.join(self.dir, "apps", "n8n", "credentials", "c.json"), "w") as fh:
            fh.write('{"data": "${EXAMPLEM_API_TOKEN}"}\n')
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.reseeds), (2, before, []), said)
        self.assertIn("apps/n8n/credentials/c.json", said)

    def test_n8n_stopped_is_refused_and_n8n_absent_is_told_how_to_seed(self):
        self.state["n8n"] = "exited"
        before = open(self.env).read()
        self.assertEqual((self.rotate()[0], open(self.env).read(), self.reseeds), (2, before, []))
        del self.state["n8n"]
        code, said = self.rotate()
        self.assertEqual((code, self.reseeds), (0, []), said)
        self.assertNotEqual(self.value(), self.old)
        self.assertIn("`bbox n8n push all --reseed-only` gives its credentials the new value", said)

    def test_only_the_overrides_block_is_read_as_the_hook_reads_it(self):
        self.assertEqual(ES.n8n_overrides(self.dir), {"chatAuth0000001": {"CHAT_USER_X", "EXAMPLEM_API_TOKEN"}})

    def test_every_n8n_copy_key_on_the_real_tree_is_one_the_reseed_reaches(self):
        keys = [k for k in sorted(ES.TABLE) if ES.rotation_class(k) == "n8n-copy"]
        self.assertTrue(keys)
        reached = {k for names in ES.n8n_overrides(ES.ROOT).values() for k in names}
        self.assertEqual([k for k in keys if k not in reached], [])


def _claims(token, secret):
    """A Supabase key's claims when `secret` signed it, else None."""
    head, body, sig = token.split(".")
    good = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    if good.decode().rstrip("=") != sig:
        return None
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


class RotateSigning(unittest.TestCase):
    """DGO-1015: the SIGNING class rotates WHOLE — a key re-signed with the same secret leaves the old one valid — so
    naming any of the three mints the secret and both keys signed with the NEW one, recreates every reader of the
    three together and re-seeds n8n's copy of the service key; any failure or signal puts all three back, n8n's copy
    included. Compose and the hook are fakes that note the value each step ran on."""
    READS = {"connections": list(ES.SIGNING), "db": ["SUPABASE_JWT_SECRET"], "rest": ["SUPABASE_JWT_SECRET"],
             "kong": ["SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"]}
    LEASED = "drive-local"                     # leases the service key from connections: compose blanks it there

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        files = {"platform-base/postgres/docker-compose.yml":
                 "services:\n  db:\n    environment:\n      JWT_SECRET: ${SUPABASE_JWT_SECRET}\n",
                 "apps/supabase/docker-compose.yml":
                 "services:\n  rest:\n    environment:\n      PGRST_JWT_SECRET: ${SUPABASE_JWT_SECRET}\n"
                 "  kong:\n    environment:\n      A: ${SUPABASE_ANON_KEY}\n      S: ${SUPABASE_SERVICE_KEY}\n",
                 "apps/n8n/blueprint.yml":
                 'credential_overrides:\n  supabaseStorage001: {"name":"Supabase Storage","type":"httpHeaderAuth",'
                 '"data":{"name":"Authorization","value":"Bearer ${SUPABASE_SERVICE_KEY}"}}\n',
                 "platform-base/connections/docker-compose.yml":
                 "services:\n  connections:\n    env_file: ../../.env\n",
                 "apps/drive-local/docker-compose.yml":
                 "services:\n  drive-local:\n    environment:\n      K: ${SUPABASE_SERVICE_KEY}\n",
                 "apps/drive-local/app.json":
                 '{"id": "drive-local", "broker": {"service": "drive-local", "blank_env": ["SUPABASE_SERVICE_KEY"]}}\n'}
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.dir, rel)), exist_ok=True)
            with open(os.path.join(self.dir, rel), "w") as fh:
                fh.write(text)
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        self.env = os.path.join(self.dir, ".env")
        self.secret = "old" + "S3cret" * 6
        old = {"SUPABASE_JWT_SECRET": self.secret}
        for k in ES.SIGNING[1:]:
            old[k] = ES.make(k, old)
        self.old = old
        with open(self.env, "w") as fh:
            fh.write("DEPLOYMENT_NAME=local\n" + "".join(f"{k}={v}\n" for k, v in old.items()))
        self.state = {"connections": "running", "db": "running", "rest": "running", "kong": "running",
                      "n8n": "running", self.LEASED: "running"}
        self.deployed = {s: self.reads(s) for s in self.READS}
        self.events, self.ups, self.reseeds, self.leases = [], [], [], []
        self.reseed_rcs, self.up_rcs, self.cut_reseed_at, self.lease_rcs = [], [], None, []
        self.foreign, self.lease_pending = [], False

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        ES._TREES.clear()
        ES._INDEX.clear()

    def now(self):
        return values(self.env)

    def reads(self, svc):
        return [self.now().get(k) for k in self.READS[svc]]

    def compose(self, cmd, **_):
        args, out, err, rc = cmd[1:], "", "", 0
        if cmd[0] == "docker":
            out = "\n".join(["unrelated-thing", *self.foreign])
        elif args[:3] == ["config", "--format", "json"]:
            out = json.dumps({"name": "proj", "services": {s: {} for s in [*self.READS, self.LEASED]}})
        elif args[:2] == ["config", "--services"]:
            out = "\n".join([*self.READS, self.LEASED]) + "\n"
        elif args[:1] == ["ps"]:
            out = "\n".join(json.dumps({"Service": s, "Name": f"{s}-local", "State": st, "Labels": ""})
                            for s, st in self.state.items())
        elif args[:2] == ["--dry-run", "up"]:
            err = "".join(f"Container {s}-local  Recreate\n" for s in args if s in self.READS
                          and self.reads(s) != self.deployed[s])
            if self.lease_pending and self.LEASED in args:          # undeployed work of its own, not the key
                err += f"Container {self.LEASED}-local  Recreate\n"
        return subprocess.CompletedProcess(cmd, rc, out, err)

    def popen(self):
        test = self

        class Proc:
            pid = 515151

            def __init__(self, cmd, **kw):
                self.rc, self.cut = 0, False
                if cmd[0] == "bash":                           # the hook's --reseed-only: what n8n's copy becomes
                    test.reseeds.append(test.now()["SUPABASE_SERVICE_KEY"])
                    test.events.append(("reseed", len(test.reseeds)))
                    self.rc = test.reseed_rcs.pop(0) if test.reseed_rcs else 0
                    self.cut = test.cut_reseed_at == len(test.reseeds)
                    kw["stdout"].write(f"[n8n-push]   reseeded {0 if self.rc else 1}/1 env-driven credential(s)\n")
                elif "--force-recreate" in cmd:                # a lease reader asks connections again at start
                    test.assertEqual([a for a in cmd if a in (test.LEASED, *test.READS)], [test.LEASED])
                    test.leases.append(test.deployed["connections"][2])   # what connections serves: ITS env
                    test.events.append(("lease", len(test.leases)))
                    self.rc = test.lease_rcs.pop(0) if test.lease_rcs else 0
                else:
                    targets = [a for a in cmd if a in test.READS]
                    test.assertNotIn(test.LEASED, cmd)          # never in compose's own proof
                    test.ups.append(targets)
                    test.events.append(("up", len(test.ups)))
                    self.rc = test.up_rcs.pop(0) if test.up_rcs else 0
                    if self.rc == 0:
                        for s in targets:
                            test.deployed[s] = test.reads(s)

            def wait(self, timeout=None):
                if self.cut:                                   # a signal mid-re-seed, its first wait only
                    self.cut = False
                    raise KeyboardInterrupt("signal")
                return self.rc
        return Proc

    def rotate(self, key="SUPABASE_SERVICE_KEY"):
        return ES.rotate(self.env, key, self.dir, self.compose, self.popen(), lambda *_: None)

    def test_naming_any_of_the_three_rotates_the_secret_and_both_keys_signed_with_it(self):
        code, said = self.rotate("SUPABASE_SERVICE_KEY")
        self.assertEqual(code, 0, said)
        new = self.now()
        self.assertNotEqual(new["SUPABASE_JWT_SECRET"], self.secret)
        for k, role in (("SUPABASE_ANON_KEY", "anon"), ("SUPABASE_SERVICE_KEY", "service_role")):
            self.assertEqual((_claims(new[k], new["SUPABASE_JWT_SECRET"]) or {}).get("role"), role, k)
            self.assertIsNone(_claims(new[k], self.secret), f"{k} must not verify under the old secret")
        self.assertEqual(self.ups, [["connections", "db", "kong", "rest"]])   # every reader of the three, together
        self.assertEqual(self.leases, [new["SUPABASE_SERVICE_KEY"]])  # the lease reader took the NEW key, after
        self.assertEqual(self.reseeds, [self.old["SUPABASE_SERVICE_KEY"], new["SUPABASE_SERVICE_KEY"]])
        self.assertEqual([e[0] for e in self.events], ["reseed", "up", "lease", "reseed"])   # proof, readers,
        self.assertIn("rotated with the two keys it signs (SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY)", said)   # lease,
        self.assertIn("drive-local leased it again from connections", said)                                  # n8n
        for v in [new[k] for k in ES.SIGNING] + list(self.old.values()):
            self.assertNotIn(v, said)

    def test_readers_that_do_not_come_back_put_all_three_back(self):
        self.up_rcs = [1, 0]
        code, said = self.rotate("SUPABASE_JWT_SECRET")
        self.assertEqual(code, 1, said)
        self.assertEqual({k: self.now()[k] for k in ES.SIGNING}, self.old)
        self.assertEqual(len(self.ups), 2)                              # the rotation's, then the old values'
        self.assertEqual(len(self.reseeds), 1)                          # n8n never touched past the proof

    def test_n8n_s_copy_that_does_not_take_puts_all_three_back(self):
        self.reseed_rcs = [0, 3, 0]
        code, said = self.rotate()
        self.assertEqual(code, 1, said)
        self.assertEqual({k: self.now()[k] for k in ES.SIGNING}, self.old)
        self.assertEqual(self.reseeds[-1], self.old["SUPABASE_SERVICE_KEY"])
        self.assertEqual(self.ups[-1], ["connections", "db", "kong", "rest"])
        self.assertEqual(len(self.leases), 2)                           # the new lease, then the old one again
        self.assertEqual(self.leases[0], self.reseeds[1])               # the new one: what n8n was given too
        self.assertNotEqual(self.leases[0], self.old["SUPABASE_SERVICE_KEY"])
        self.assertEqual(self.leases[1], self.old["SUPABASE_SERVICE_KEY"])
        self.assertIn("connections, db, kong, rest, drive-local recreated with the old one (healthy), n8n re-seeded with "
                      "the old one",
                      said)

    def test_a_signal_in_the_re_seed_puts_all_three_back_and_says_so(self):
        import contextlib
        import io
        self.cut_reseed_at = 2
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(KeyboardInterrupt):
            self.rotate()
        self.assertEqual({k: self.now()[k] for k in ES.SIGNING}, self.old)
        self.assertEqual(self.reseeds[-1], self.old["SUPABASE_SERVICE_KEY"])
        self.assertIn("SUPABASE_JWT_SECRET: stopped — .env restored, connections, db, kong, rest, drive-local recreated "
                      "with the old one (healthy), n8n re-seeded with the old one", err.getvalue())
        self.assertEqual(self.leases[-1], self.old["SUPABASE_SERVICE_KEY"])   # the lease reader back on the old one

    def test_a_lease_reader_that_does_not_come_back_puts_all_three_back(self):
        self.lease_rcs = [1, 0]
        code, said = self.rotate()
        self.assertEqual((code, {k: self.now()[k] for k in ES.SIGNING}), (1, self.old), said)
        self.assertEqual(self.leases[-1], self.old["SUPABASE_SERVICE_KEY"])
        self.assertEqual(len(self.reseeds), 1)                          # n8n never touched past the proof
        self.assertIn("drive-local did not come back healthy on the new lease", said)

    def test_a_lease_reader_without_connections_or_not_running_is_refused_untouched(self):
        before = open(self.env).read()
        for state in ({"connections": "exited"}, {"connections": None}, {self.LEASED: "exited"}):
            self.tearDown()                                             # the last case's directory, not leaked
            self.setUp()
            before = open(self.env).read()
            for s, st in state.items():
                if st is None:
                    del self.state[s]
                else:
                    self.state[s] = st
            code, said = self.rotate()
            self.assertEqual((code, open(self.env).read(), self.ups, self.leases), (2, before, [], []),
                             f"{state}: {said}")

    def test_a_lease_reader_under_another_project_or_with_work_pending_is_refused_untouched(self):
        for case in ("foreign", "pending"):
            self.tearDown()                                             # the last case's directory, not leaked
            self.setUp()
            if case == "foreign":
                del self.state[self.LEASED]
                self.foreign = ["proj-drive-local-1"]
            else:
                self.lease_pending = True
            before = open(self.env).read()
            code, said = self.rotate()
            self.assertEqual((code, open(self.env).read(), self.ups, self.leases), (2, before, [], []),
                             f"{case}: {said}")
            self.assertIn("drive-local", said)

    def test_lease_readers_whose_connections_would_not_be_recreated_are_refused(self):
        # connections runs, but this rotation would not recreate it (it no longer reads the keys): it would keep
        # serving the old value to the lease readers
        with open(os.path.join(self.dir, "platform-base", "connections", "docker-compose.yml"), "w") as fh:
            fh.write("services:\n  connections:\n    image: x\n")
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        ES._TREES.clear()
        ES._INDEX.clear()
        before = open(self.env).read()
        code, said = self.rotate()
        self.assertEqual((code, open(self.env).read(), self.ups, self.leases), (2, before, [], []), said)
        self.assertIn("which this rotation would not recreate", said)

    def test_readers_that_do_not_come_back_never_re_lease(self):
        self.up_rcs = [1, 0]
        code, said = self.rotate()
        self.assertEqual((code, self.leases), (1, []), said)           # the lease readers never moved

    def test_the_second_and_third_key_are_checked_as_the_first(self):
        for broken in ("", "export SUPABASE_ANON_KEY=x\n"):
            self.tearDown()                                             # the last case's directory, not leaked
            self.setUp()
            text = "".join(ln for ln in open(self.env).read().splitlines(True)
                           if not ln.startswith("SUPABASE_ANON_KEY="))
            with open(self.env, "w") as fh:
                fh.write(text + broken)
            before = open(self.env).read()
            code, said = self.rotate("SUPABASE_JWT_SECRET")
            self.assertEqual((code, open(self.env).read(), self.ups), (2, before, []), said)
            self.assertIn("SUPABASE_ANON_KEY", said)

    def test_two_keys_of_the_class_named_rotate_it_once(self):
        calls, real = [], ES.rotate
        ES.rotate = lambda path, key, *a, **k: (calls.append(key), (0, "ok"))[1]
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ES.main(["--env", self.env, "--rotate", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET",
                              "EXAMPLEM_API_TOKEN"])
        finally:
            ES.rotate = real
        self.assertEqual((rc, calls), (0, ["SUPABASE_ANON_KEY", "EXAMPLEM_API_TOKEN"]))

    def test_the_plan_names_the_readers_of_all_three(self):
        plan = "\n".join(ES.rotation_plan("SUPABASE_ANON_KEY", self.dir))
        self.assertIn("rotates with: SUPABASE_JWT_SECRET, SUPABASE_SERVICE_KEY", plan)
        for reader in ("platform-base/postgres/docker-compose.yml: db", "apps/supabase/docker-compose.yml: rest",
                       "apps/supabase/docker-compose.yml: kong"):
            self.assertIn(reader, plan)
        for k in ES.SIGNING:
            self.assertEqual(ES.rotation_class(k), "signing", k)


class RecreatesReadsComposesLines(unittest.TestCase):
    """_recreates on compose's own shapes — v2.40.3's prefixed lines (the Recreate, Running and error lines as captured
    on the MacBook 2026-11-11, the herd lane's ci-artifacts/king-2026-11-10/lanes/herd-agents/dryrun-2-40-3.txt; the
    Recreated, Network, colour and warning lines in the shapes compose prints, the set scripts/test_stale_containers.py
    feeds lib.sh) — and the old unprefixed one."""
    V2_40 = (" DRY-RUN MODE -  Container lan-signin-local  Recreate\n"
             " DRY-RUN MODE -  Container dgo-net-local  Running\n"
             " DRY-RUN MODE -  Container \x1b[32mapp-management-local\x1b[0m  Recreate\n"
             " DRY-RUN MODE -  Container forge-local  Recreated\n"
             " DRY-RUN MODE -  Network traefik-network  Created\n"
             " DRY-RUN MODE -  Container browser42-mcp-local  Error response from daemon: No such image\n"
             'time="2026-11-11T07:25:00+03:00" level=warning msg="The \\"POSTGRES_PASSWORD\\" variable is not set."\n')
    OLD = "Container lan-signin-local  Recreate\nContainer dgo-net-local  Running\n Container redis-local  Recreate\n"

    @staticmethod
    def answer(err, rc=0):
        return lambda cmd, **_: subprocess.CompletedProcess(cmd, rc, "", err)

    def test_the_prefixed_lines_name_what_compose_would_recreate(self):
        self.assertEqual(ES._recreates(self.answer(self.V2_40), "dc", ["x"]),
                         {"lan-signin-local", "app-management-local"})

    def test_the_old_unprefixed_lines_still_read(self):
        self.assertEqual(ES._recreates(self.answer(self.OLD), "dc", ["x"]), {"lan-signin-local", "redis-local"})

    def test_a_dry_run_that_failed_is_could_not_tell_never_nothing(self):
        self.assertIsNone(ES._recreates(self.answer(self.V2_40, rc=1), "dc", ["x"]))


if __name__ == "__main__":
    unittest.main()
