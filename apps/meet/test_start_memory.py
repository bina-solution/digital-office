"""test_start_memory.py — meet-start fits what it runs (EXU-20).

    python3 apps/meet/test_start_memory.py

Exampleu's meet-start ran at 41 of its 48 MiB, was killed by its own cgroup five times on 2026-11-09 and had restarted
six times. The kernel's tables at each kill held two Pythons: the server, and the healthcheck — `python -c "import
urllib.request…"`, 24.7 MB, started every 30 s inside the cap — and the kernel killed the bigger one, the server.
What is held here, each against the file that would break it:
  1. the healthcheck starts no interpreter (busybox wget, 4 kB), and names 127.0.0.1 (the server is IPv4 only);
  2. `hooks/verify` asks the same way, never with a second Python;
  3. the cap holds what runs in here by design, by the measured numbers below — the server at its peak, ONE helper
     that imports server (cli.py from the hooks, link_tasks.py / close_items.py from «קדימה»), and the cgroup's
     page cache and kernel memory;
  4. past that, the kernel takes the helper, never the server: each helper sets its own oom_score_adj to 1000 BEFORE
     it imports server.py (whose compile is most of its cost), and server.py does it for any other importer (the
     runtime half on Linux only; skipped where no process may raise its score);
  5. app.json's `resources` are still the sums of the compose limits (what the catalog shows before install).
Stdlib only: the compose file is read as text (comment lines dropped), so the gates need no PyYAML for it.
"""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def read(*p: str) -> str:
    with open(os.path.join(HERE, *p), encoding="utf-8") as f:
        return f.read()


# the compose file without its comment lines: a limit written in a comment is no limit
COMPOSE = "\n".join(l for l in read("docker-compose.yml").splitlines() if not l.lstrip().startswith("#"))
VERIFY = read("hooks", "verify")
APP = json.loads(read("app.json"))

# Measured 2026-11-09 (EXU-20), VmHWM / memory.stat, in MB:
SERVER_PEAK = 43.1   # meet-start-staging on vps1 (Exampleu's: 38.7)
HELPER = 28.8        # `import server` in python:3.12-alpine — what cli.py, link_tasks.py and close_items.py cost
CGROUP = 10.5        # page cache 7.5 + kernel 3.0 in Exampleu's meet-start cgroup
NEED = SERVER_PEAK + HELPER + CGROUP


def service(name: str) -> str:
    """The block of one service in the compose file, as text."""
    m = re.search(rf"\n  {re.escape(name)}:\n(.*?)(?=\n  [a-z0-9_-]+:\n|\nvolumes:|\nnetworks:|\Z)", COMPOSE, re.S)
    assert m, f"no service {name} in docker-compose.yml"
    return m.group(1)


def mb(value: str) -> float:
    n, unit = float(value[:-1]), value[-1].upper()
    return n * 1024 if unit == "G" else n


LIMIT_MEM = r"limits:\s*\{[^}]*memory:\s*\"?([0-9.]+[MmGg])"
LIMIT_CPU = r"limits:\s*\{[^}]*cpus:\s*\"?([0-9.]+)"


class StartMemory(unittest.TestCase):
    def test_the_healthcheck_starts_no_interpreter(self):
        test = re.search(r"healthcheck:\s*\n\s*test:\s*(\[[^\]]*\])", service("meet-start"))
        self.assertIsNotNone(test, "meet-start has no healthcheck test")
        argv = json.loads(test.group(1))
        self.assertNotIn("python", " ".join(argv), "a healthcheck in Python is a second 25 MB process in the cap")
        self.assertEqual(argv[:2], ["CMD", "wget"])
        self.assertIn("http://127.0.0.1:8080/healthz", argv)

    def test_verify_asks_the_same_way(self):
        line = next((l for l in VERIFY.splitlines()
                     if "meet-start-" in l and "healthz" in l and not l.lstrip().startswith(("#", "echo"))), "")
        self.assertTrue(line, "hooks/verify no longer checks meet-start's /healthz")
        self.assertNotIn("python", line)
        self.assertIn("wget", line)

    def test_the_cap_holds_the_server_one_helper_and_the_cgroup(self):
        cap = re.search(LIMIT_MEM, service("meet-start"))
        self.assertIsNotNone(cap, "meet-start has no memory limit")
        self.assertGreaterEqual(mb(cap.group(1)), NEED,
                                f"{cap.group(1)} < {NEED:.0f} MB: server {SERVER_PEAK} + helper {HELPER} + cgroup {CGROUP}")

    def test_each_helper_marks_itself_before_it_imports_server(self):
        # compiling server.py is most of a helper's 28.8 MB: a mark made after it comes too late
        for rel in ("start/cli.py", "tools/flow/link_tasks.py", "tools/flow/close_items.py"):
            src = read(*rel.split("/"))
            mark, imp = src.find("/proc/self/oom_score_adj"), src.find("\nimport server")
            self.assertGreater(mark, -1, f"{rel} does not mark itself for the kernel")
            self.assertGreater(imp, -1, f"{rel} no longer imports server")
            self.assertLess(mark, imp, f"{rel} marks itself only after server.py is compiled")

    # the probe closes the file (the write happens there) and reads the value back: a refusal is seen, not swallowed
    @unittest.skipUnless(subprocess.run([sys.executable, "-c",
                                         "import sys; p = '/proc/self/oom_score_adj'; f = open(p, 'w'); f.write('1000'); "
                                         "f.close(); sys.exit(open(p).read().strip() != '1000')"],
                                        capture_output=True).returncode == 0,
                         "this host lets no process raise its oom_score_adj (no /proc: a Mac, Windows; or refused)")
    def test_a_helper_is_the_one_the_kernel_takes(self):
        # what cli.py, link_tasks.py and close_items.py do first: import server — in a child, so this test's own
        # process keeps its score
        out = subprocess.run([sys.executable, "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import server; "
                              "print(open('/proc/self/oom_score_adj').read().strip())", os.path.join(HERE, "start")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-600:])
        self.assertEqual(out.stdout.strip().splitlines()[-1], "1000")

    def test_app_json_is_the_sum_of_the_limits(self):
        mem = sum(mb(v) for v in re.findall(LIMIT_MEM, COMPOSE))
        cpu = round(sum(float(v) for v in re.findall(LIMIT_CPU, COMPOSE)), 2)
        self.assertEqual(mb(APP["resources"]["memory"]), mem,
                         f"app.json says {APP['resources']['memory']}, the compose limits sum to {mem:.0f}M")
        self.assertEqual(float(APP["resources"]["cpus"]), cpu,
                         f"app.json says {APP['resources']['cpus']} CPUs, the compose limits sum to {cpu}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
