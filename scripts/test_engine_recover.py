#!/usr/bin/env python3
"""test_engine_recover — a frozen engine is told apart from a live one, and booted again by itself (DGO-1964).

    python3 scripts/test_engine_recover.py

On 2026-11-14 the Mac engine's systemd (PID 1) went into its freeze() after an unattended re-exec: 3 open files,
blocked in waitid. Running containers ran on, none could start, and every link of the Mac was down until the owner
came to the machine, 2 days 10 hours later. What is asked:
  * engine.sh pid1_state says «frozen» (status 3) only for few open files AND do_wait. A live systemd has ~150
    files open and waits in epoll, and also blocks in waitid for a moment while it runs its generators: that one is
    alive. A guest that does not answer, or an engine that is not running, is «unknown» (status 1), never «frozen».
  * engine.sh cmd_recover leaves a live engine and an unreadable one alone (no stop of any kind) unless --force;
    boots a frozen one through the gentle path (dockerd stopped in the guest, then `limactl stop --force`) and
    stamps data/power/engine-recover.json at the stop; stops a live one under --force the ordinary way (its
    systemd would restart a SIGTERMed dockerd); refuses while another recovery runs; and frees its lock after.
  * engine.sh start_link_stack starts, after a boot, only this office's link plane and door (dgo-extend, dgo-net,
    dgo-link, dgo-carry) that compose created and nothing started: never n8n's workers the Mac keeps off, another
    project's, a one-off, or a container somebody stopped; and nothing at all without a link plane.
  * power-agent.py recovers after the SECOND frozen check in a row, in a session of its own (the recovery stops the
    engine, and the agent with it); never starts a second one while one runs; a frozen check within
    ENGINE_RECOVER_GAP_S of the stamp is said and not looped on; a live answer starts the count again; «unknown»
    never counts; the policy's engine_recover "off" only says it.
The functions are cut out of the real engine.sh and run with stubs for everything that would reach an engine, so
nothing here touches one; the agent runs a fake engine.sh (BBOX_ENGINE_SH). On a Mac the shell is /bin/bash, the
3.2 the engine's scripts run under there.
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
ENGINE_SH = REPO / "packaging" / "macos" / "engine.sh"
AGENT_PY = REPO / "packaging" / "macos" / "power-agent.py"
BASH = "/bin/bash" if sys.platform == "darwin" else (shutil.which("bash") or "bash")


def cut(name):
    """The function `name` from engine.sh, from its first line to the `}` that closes it at column 0."""
    m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(name), ENGINE_SH.read_text(encoding="utf-8"), re.S | re.M)
    assert m, "%s() not found in engine.sh" % name
    return m.group(0)


def pid1(answer, running=True):
    """pid1_state with the guest answering `answer` («<open files> <wchan>», or nothing) → (status, line)."""
    script = "\n".join([
        "set -euo pipefail",
        "INSTANCE=bbox",
        "state() { %s; }" % ("echo Running" if running else "echo Stopped"),
        "lima() { printf '%%s' %s; }" % json.dumps(answer),
        cut("pid1_state"),
        "pid1_state",
    ])
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout.strip()


class Pid1State(unittest.TestCase):
    def test_the_freeze_of_2026_11_14_is_frozen(self):
        code, line = pid1("3 do_wait")
        self.assertEqual(code, 3)
        self.assertTrue(line.startswith("frozen: "), line)

    def test_a_live_systemd_is_ok(self):
        code, line = pid1("162 ep_poll")
        self.assertEqual((code, line.split(":")[0]), (0, "ok"))

    def test_a_live_systemd_running_its_generators_is_ok(self):
        # waitid for a moment, with every file of its own still open
        self.assertEqual(pid1("150 do_wait")[0], 0)

    def test_few_files_but_not_in_waitid_is_ok(self):
        self.assertEqual(pid1("5 ep_poll")[0], 0)

    def test_a_guest_that_does_not_answer_is_unknown_never_frozen(self):
        for answer in ("", "ssh: connect to host 127.0.0.1 port 64698: Connection refused"):
            code, line = pid1(answer)
            self.assertEqual(code, 1, answer)
            self.assertTrue(line.startswith("unknown: "), line)

    def test_an_engine_that_is_not_running_is_unknown(self):
        code, line = pid1("3 do_wait", running=False)
        self.assertEqual(code, 1)
        self.assertIn("not running", line)

    def test_the_guest_is_asked_from_slash_under_a_limit(self):
        # `limactl shell` cd's to the caller's folder (the home mount, whose stall began the freeze) unless told
        body = cut("pid1_state")
        self.assertIn("lima shell --workdir / ", body)
        self.assertIn("sudo timeout ", body)


class CmdRecover(unittest.TestCase):
    """engine.sh cmd_recover with every engine-facing call a stub that only writes down that it was called."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="cmd-recover-"))
        (self.tmp / "repo").mkdir()
        (self.tmp / "home").mkdir()
        self.other = None

    def tearDown(self):
        if self.other is not None:
            self.other.kill()
            self.other.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def another_recovery(self):
        """A live process whose command line is an engine.sh, as a running recovery's is."""
        (self.tmp / "engine.sh").write_text("sleep 30\n", encoding="utf-8")
        self.other = subprocess.Popen([BASH, str(self.tmp / "engine.sh")])
        return self.other.pid

    def run_recover(self, answers, *args, running_pid=None):
        """answers: pid1_state's (status, line) in the order it is asked → (exit, stdout, calls)."""
        (self.tmp / "answers").write_text("".join("%d|%s\n" % a for a in answers), encoding="utf-8")
        if running_pid is not None:
            (self.tmp / "home" / "engine-recover.pid").write_text("%d\n" % running_pid, encoding="utf-8")
        t = str(self.tmp)
        script = "\n".join([
            "set -euo pipefail",
            "T=%s; INSTANCE=bbox; LIMACTL=limactl; REPO_ROOT=$T/repo; BBOX_MACOS_HOME=$T/home; c0=; cy=" % json.dumps(t),
            'RECOVER_PID="${BBOX_MACOS_HOME}/engine-recover.pid"',
            'say() { echo "say: $*"; }',
            'ok() { echo "ok: $*"; }',
            'die() { echo "die: $*"; exit 1; }',
            'ensure_runtime() { :; }',
            'pid1_state() { local k; k=$(cat "$T/n" 2>/dev/null || echo 0); echo $((k + 1)) > "$T/n"; '
            'local a; a="$(sed -n "$((k + 1))p" "$T/answers")"; echo "${a#*|}"; return "${a%%|*}"; }',
            'lima() { echo "lima $*" >> "$T/calls"; cat > /dev/null; }',
            'power_agent_stop() { echo power_agent_stop >> "$T/calls"; }',
            'lan_door_stop() { echo lan_door_stop >> "$T/calls"; }',
            'cmd_start() { echo cmd_start >> "$T/calls"; }',
            'power_agent_start() { echo power_agent_start >> "$T/calls"; }',
            'lan_door_start() { :; }',
            'console_door_start() { :; }',
            cut("recover_stamp"),
            cut("recover_lock"),
            cut("cmd_recover"),
            "cmd_recover %s < /dev/null" % " ".join(args),
        ])
        p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60)
        calls = (self.tmp / "calls").read_text().splitlines() if (self.tmp / "calls").exists() else []
        return p.returncode, p.stdout, calls

    def stamp(self):
        f = self.tmp / "repo" / "data" / "power" / "engine-recover.json"
        return json.loads(f.read_text()) if f.exists() else None

    def test_a_live_engine_is_left_alone(self):
        code, out, calls = self.run_recover([(0, "ok: 162 open files")])
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to recover", out)
        self.assertFalse([c for c in calls if c.startswith("lima")], calls)
        self.assertIsNone(self.stamp())

    def test_an_unreadable_engine_is_left_alone(self):
        code, out, calls = self.run_recover([(1, "unknown: the guest did not answer")])
        self.assertEqual(code, 1, out)
        self.assertIn("nothing done", out)
        self.assertFalse([c for c in calls if c.startswith("lima")], calls)
        self.assertIsNone(self.stamp())

    def test_a_frozen_engine_is_booted_gently(self):
        code, out, calls = self.run_recover([(3, "frozen: 3 open files, do_wait"), (0, "ok: 160 open files")])
        self.assertEqual(code, 0, out)
        shell = [c for c in calls if c.startswith("lima shell")]
        self.assertTrue(shell and "--workdir /" in shell[0], calls)
        self.assertLess(calls.index(shell[0]), calls.index("lima stop --force bbox"))
        self.assertLess(calls.index("power_agent_stop"), calls.index("lima stop --force bbox"))
        self.assertLess(calls.index("lima stop --force bbox"), calls.index("cmd_start"))
        self.assertEqual(self.stamp()["why"], "frozen: 3 open files, do_wait")
        self.assertFalse((self.tmp / "home" / "engine-recover.pid").exists(), "the lock is freed")
        self.assertIn("power_agent_start", calls, "the host helpers are brought back whatever happened")

    def test_force_stops_a_live_engine_the_ordinary_way(self):
        code, out, calls = self.run_recover([(0, "ok: 162"), (0, "ok: 160")], "--force")
        self.assertEqual(code, 0, out)
        self.assertIn("lima stop bbox", calls)
        self.assertFalse([c for c in calls if c.startswith("lima shell")], "no SIGTERM to a dockerd systemd restarts")
        self.assertTrue(self.stamp()["why"].startswith("forced: "))

    def test_force_on_an_unreadable_engine_is_the_ordinary_stop_too(self):
        # alive but slow is possible, and a live systemd would restart a SIGTERMed dockerd under the cut
        code, out, calls = self.run_recover([(1, "unknown: the guest did not answer"), (0, "ok: 160")], "--force")
        self.assertEqual(code, 0, out)
        self.assertIn("lima stop bbox", calls)
        self.assertFalse([c for c in calls if c.startswith("lima shell")], calls)

    def test_no_stop_without_the_stamp(self):
        (self.tmp / "repo" / "data").write_text("a file where the folder should be", encoding="utf-8")
        code, out, calls = self.run_recover([(3, "frozen: x"), (0, "ok: 160")])
        self.assertEqual(code, 1, out)
        self.assertIn("not stopping the engine", out)
        self.assertFalse([c for c in calls if c.startswith("lima stop")], calls)
        self.assertNotIn("cmd_start", calls)

    def test_one_recovery_at_a_time(self):
        code, out, calls = self.run_recover([(3, "frozen: x"), (0, "ok: 160")], running_pid=self.another_recovery())
        self.assertEqual(code, 1, out)
        self.assertIn("already running", out)
        self.assertEqual(calls, [])
        self.assertEqual((self.tmp / "home" / "engine-recover.pid").read_text().strip(), str(self.other.pid),
                         "the other recovery's lock is left as it is")

    def test_a_lock_left_by_a_killed_recovery_is_taken_over(self):
        # a live pid that is not an engine.sh: the system reused it after the lock's owner was killed
        code, out, calls = self.run_recover([(3, "frozen: x"), (0, "ok: 160")], running_pid=os.getpid())
        self.assertEqual(code, 0, out)
        self.assertIn("lima stop --force bbox", calls)
        self.assertFalse((self.tmp / "home" / "engine-recover.pid").exists())


class StartLinkStack(unittest.TestCase):
    """The guest-side script of engine.sh start_link_stack, run against a docker stub that answers from a table."""

    DOCKER = r'''
docker() {
  local cmd="$1"; shift
  case "${cmd}" in
    ps)
      local all=0 ids=0 status="" svc="" proj="" oneoff=""
      while [ $# -gt 0 ]; do
        case "$1" in
          -a) all=1 ;; -q) ids=1 ;; -aq) all=1; ids=1 ;;
          --filter) shift; case "$1" in
              status=*) status="${1#status=}" ;;
              label=com.docker.compose.service=*) svc="${1#label=com.docker.compose.service=}" ;;
              label=com.docker.compose.project=*) proj="${1#label=com.docker.compose.project=}" ;;
              label=com.docker.compose.oneoff=*) oneoff="${1#label=com.docker.compose.oneoff=}" ;;
            esac ;;
          --format) shift ;;
        esac
        shift
      done
      while read -r id st pr sv oo; do
        [ "${all}" = 1 ] || [ "${st}" = running ] || continue
        [ -z "${status}" ] || [ "${st}" = "${status}" ] || continue
        [ -z "${svc}" ] || [ "${sv}" = "${svc}" ] || continue
        [ -z "${proj}" ] || [ "${pr}" = "${proj}" ] || continue
        [ -z "${oneoff}" ] || [ "${oo}" = "${oneoff}" ] || continue
        if [ "${ids}" = 1 ]; then echo "${id}"; else echo "${pr}"; fi
      done < "$T/containers" ;;
    inspect) echo "/${3}" ;;
    start) echo "$1" >> "$T/started" ;;
  esac
}
'''

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="link-stack-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def started(self, table):
        """table: «id state project service oneoff» lines → the ids the script started, in order."""
        (self.tmp / "containers").write_text("\n".join(table) + "\n", encoding="utf-8")
        body = re.search(r"<<'SH' \|\| true\n(.*?)\nSH\n", cut("start_link_stack"), re.S).group(1)
        script = "T=%s\n%s\n%s\n" % (json.dumps(str(self.tmp)), self.DOCKER, body)
        p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        f = self.tmp / "started"
        return f.read_text().split() if f.exists() else []

    def test_the_door_of_this_office_only(self):
        self.assertEqual(self.started([
            "ext running office dgo-extend False",
            "carry created office dgo-carry False",
            "net created office dgo-net False",
            "link created office dgo-link False",
            "n8nw created office n8n-worker-1 False",          # created and kept off on purpose
            "othernet created other dgo-net False",            # another project's door
            "oneoff created office dgo-net True",              # a `compose run`
            "stopped exited office dgo-link False",            # stopped is somebody's decision
        ]), ["net", "link", "carry"])

    def test_a_link_plane_recreated_with_the_door_comes_up_first(self):
        # a `bbox run` during the freeze recreated dgo-extend too: it is «created» like the door
        self.assertEqual(self.started([
            "net created office dgo-net False",
            "ext created office dgo-extend False",
            "link created office dgo-link False",
        ]), ["ext", "net", "link"])

    def test_no_link_plane_no_start(self):
        self.assertEqual(self.started(["net created office dgo-net False"]), [])


class AgentRecovers(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="engine-recover-"))
        self.fake = self.tmp / "engine.sh"
        # the fake recover does what the real one does with the stamp, then stays a moment
        self.fake.write_text("\n".join([
            "#!/bin/bash",
            'case "$1" in',
            '  health) cat "${FAKE_DIR}/answer"; exit "$(cat "${FAKE_DIR}/code")" ;;',
            '  recover)',
            '    mkdir -p "${FAKE_DIR}/data/power"',
            '    printf \'{"started_at": %s, "pid": %s}\\n\' "$(date +%s)" "$$" > "${FAKE_DIR}/data/power/engine-recover.json"',
            '    echo "recover $$" >> "${FAKE_DIR}/recovered"',
            '    sleep "${FAKE_RECOVER_S:-0}" ;;',
            "esac",
        ]) + "\n", encoding="utf-8")
        os.environ["FAKE_DIR"] = str(self.tmp)
        os.environ["BBOX_ENGINE_SH"] = str(self.fake)
        spec = importlib.util.spec_from_file_location("power_agent_under_test", AGENT_PY)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod.ENGINE_CHECK_S = 0
        self.agent = self.mod.Agent(self.tmp, 0, 15)
        self.policy = self.mod.load_policy(self.tmp / "no-policy.json")

    def tearDown(self):
        for k in ("BBOX_ENGINE_SH", "FAKE_DIR", "FAKE_RECOVER_S"):
            os.environ.pop(k, None)
        if self.agent.recovering is not None:
            self.agent.recovering.wait(timeout=10)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def answer(self, line, code):
        (self.tmp / "answer").write_text(line + "\n", encoding="utf-8")
        (self.tmp / "code").write_text(str(code), encoding="utf-8")

    def check(self, line, code, policy=None):
        self.answer(line, code)
        self.agent.notes = []
        return self.agent.check_engine(policy or self.policy, time.time())

    def recoveries(self, wait=3.0):
        f = self.tmp / "recovered"
        end = time.time() + wait
        while time.time() < end and not f.exists():
            time.sleep(0.05)
        time.sleep(0.2)
        return f.read_text().count("recover") if f.exists() else 0

    def test_the_fake_engine_is_the_one_asked(self):
        self.assertEqual(self.mod.ENGINE_SH, str(self.fake))

    def test_default_policy_recovers(self):
        self.assertEqual(self.policy["engine_recover"], "auto")

    def test_one_frozen_check_waits_two_recover_once(self):
        frozen = "frozen: the guest's systemd (PID 1) holds 3 open files and waits in do_wait"
        self.assertEqual(self.check(frozen, 3)["frozen_checks"], 1)
        self.assertEqual(self.recoveries(wait=0.5), 0)
        self.check(frozen, 3)
        self.assertEqual(self.recoveries(), 1)
        self.assertTrue(any("recovering" in n for n in self.agent.notes), self.agent.notes)
        self.agent.recovering.wait(timeout=10)
        # frozen again within the gap of the stamp the recovery wrote: said, not looped on
        status = self.check(frozen, 3)
        self.assertEqual(self.recoveries(wait=0.5), 1)
        self.assertTrue(any("not recovering in a loop" in n for n in self.agent.notes), self.agent.notes)
        self.assertEqual(status["last_recover"]["pid"], self.agent.recovering.pid)

    def test_the_recovery_runs_in_a_session_of_its_own(self):
        os.environ["FAKE_RECOVER_S"] = "2"
        self.check("frozen: x", 3)
        self.check("frozen: x", 3)
        child = self.agent.recovering
        self.assertIsNotNone(child)
        self.assertEqual(os.getsid(child.pid), child.pid)
        self.assertNotEqual(os.getsid(child.pid), os.getsid(0))

    def test_no_second_recovery_while_one_runs(self):
        os.environ["FAKE_RECOVER_S"] = "2"
        self.check("frozen: x", 3)
        self.check("frozen: x", 3)
        self.assertEqual(self.recoveries(), 1)
        self.check("frozen: x", 3)
        self.assertTrue(any("under way" in n for n in self.agent.notes), self.agent.notes)
        self.agent.recovering.wait(timeout=10)
        self.assertEqual(self.recoveries(wait=0.3), 1)

    def test_a_live_answer_starts_the_count_again(self):
        self.check("frozen: x", 3)
        self.assertEqual(self.check("ok: the guest's systemd holds 162 open files and waits in ep_poll", 0)["frozen_checks"], 0)
        self.check("frozen: x", 3)
        self.assertEqual(self.recoveries(wait=0.5), 0)

    def test_unknown_never_counts_as_frozen(self):
        for _ in range(3):
            self.assertEqual(self.check("unknown: the guest did not answer", 1)["frozen_checks"], 0)
        self.assertEqual(self.recoveries(wait=0.5), 0)

    def test_policy_off_only_says_it(self):
        off = dict(self.policy, engine_recover="off")
        self.check("frozen: x", 3, off)
        self.check("frozen: x", 3, off)
        self.assertEqual(self.recoveries(wait=0.5), 0)
        self.assertTrue(any("engine_recover is off" in n for n in self.agent.notes), self.agent.notes)

    def test_a_stored_policy_turns_it_off(self):
        (self.tmp / "policy.json").write_text(json.dumps({"engine_recover": "off"}), encoding="utf-8")
        self.assertEqual(self.mod.load_policy(self.tmp / "policy.json")["engine_recover"], "off")
        (self.tmp / "policy.json").write_text(json.dumps({"engine_recover": "maybe"}), encoding="utf-8")
        self.assertEqual(self.mod.load_policy(self.tmp / "policy.json")["engine_recover"], "auto")

    def test_a_check_that_hangs_leaves_nothing_behind(self):
        # the whole process group goes at the limit, not only bash (limactl and ssh held guest sessions: DGO-1783)
        hang = self.tmp / "hang.sh"
        hang.write_text('#!/bin/bash\nsleep 30 &\necho "$!" > "%s/child"\nwait\n' % self.tmp, encoding="utf-8")
        t0 = time.time()
        code, out = self.mod.run_group(["/bin/bash", str(hang)], timeout=1)
        self.assertEqual(code, 1)
        self.assertLess(time.time() - t0, 10)
        child = int((self.tmp / "child").read_text())
        time.sleep(0.2)
        self.assertFalse(self.mod.pid_alive(child), "the grandchild was killed with its group")


if __name__ == "__main__":
    unittest.main(verbosity=2)
