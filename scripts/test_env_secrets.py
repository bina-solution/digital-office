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
