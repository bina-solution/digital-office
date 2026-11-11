#!/usr/bin/env python3
"""test_over_computer — `bbox agent --office <office>` reaches an office that is NOT linked through this office's
Computers app (DGO-1684): the right computer, the command as typed minus the local flags, and nothing of ours
crossing to the other office.

    python3 scripts/bbox_agent/test_over_computer.py

Python 3.9, standard library only; no engine, no network: `bbox computers ssh` is played by a fake runner, and
the remote script is checked by running it in a local `sh` against a fake `docker` and a fake checkout.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()          # never the operator's cached tokens
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _stream in (sys.stdout, sys.stderr):                     # a failure prints Hebrew: UTF-8 on every host (G10)
    _stream.reconfigure(encoding="utf-8")

from bbox_agent import over_computer as oc  # noqa: E402
from bbox_agent.client import AgentError  # noqa: E402

LIST = (
    f"{'computer_local-local':28} {'המחשב הזה':24} root@172.18.0.1\n"
    f"{'computer_ssh-b154fa0c':28} {'שרת פיתוח בינה סלושנס':24} root@93.184.216.5\n"
    f"{'computer_ssh-0259c905':28} {'שרת דוגמה':24} root@93.184.216.11\n"
)


class FakeBbox:
    """`bbox computers ssh list` and the office probe, per computer; records every call."""

    def __init__(self, offices: dict):
        self.offices = offices            # computer id → the console container's name there ("" = no office)
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(args)
        if args[:3] == ["computers", "ssh", "list"]:
            return subprocess.CompletedProcess(args, 0, LIST, "")
        name = self.offices.get(args[2], "")
        return subprocess.CompletedProcess(args, 0, f"{name}\t/root/digital-office\n" if name else "", "")


class Flags(unittest.TestCase):
    def test_local_flags_never_cross(self):
        typed = ["--office", "exampleu", "--app", "bina-claude", "--token", "SECRET", "--url=http://x", "send", "abc", "שלום עולם"]
        self.assertEqual(oc.strip_local_flags(typed), ["--app", "bina-claude", "send", "abc", "שלום עולם"])
        self.assertEqual(oc.strip_local_flags(["--office=exampleu", "list", "--json"]), ["list", "--json"])

    def test_an_abbreviated_token_or_office_is_refused_not_forwarded(self):
        for typed in (["--tok", "SECRET", "list"], ["--off", "exampleu", "list"], ["--ur=http://x", "list"]):
            with self.assertRaises(AgentError):
                oc.strip_local_flags(typed)

    def test_a_local_file_is_refused(self):
        for typed in (["new", "-f", "brief.md", "go"], ["send", "x", "--file=a.txt", "go"], ["new", "--fi", "a", "go"]):
            with self.assertRaises(AgentError):
                oc.strip_local_flags(typed)

    def test_a_long_label_does_not_shift_the_host(self):
        line = f"{'computer_ssh-0259c905':28} {'שרת דוגמה, הראשי של הלקוח הגדול':24} root@93.184.216.11  (shared)"
        self.assertEqual(oc.parse_list(line), [{"id": "computer_ssh-0259c905", "label": "שרת דוגמה, הראשי של הלקוח הגדול",
                                                "host": "93.184.216.11"}])


class FindTheComputer(unittest.TestCase):
    def setUp(self):
        oc.save_config({})

    def test_by_the_name_the_office_calls_itself_then_remembered(self):
        fake = FakeBbox({"computer_ssh-b154fa0c": "console-staging", "computer_ssh-0259c905": "console-exampleu"})
        f = oc.Finder(run=fake)
        self.assertEqual(f.find("exampleu"), "computer_ssh-0259c905")
        self.assertNotIn("computer_local-local", [c[2] for c in fake.calls if len(c) > 2])
        fake.calls.clear()
        self.assertEqual(oc.Finder(run=fake).find("Exampleu"), "computer_ssh-0259c905")
        self.assertEqual(fake.calls, [], "the second time asks nobody")
        self.assertEqual(oc.Finder(run=fake).find("staging"), "computer_ssh-b154fa0c", "learnt on the way")

    def test_by_id_label_or_host_without_asking_any_computer(self):
        fake = FakeBbox({})
        for name in ("computer_ssh-0259c905", "שרת דוגמה", "93.184.216.11"):
            self.assertEqual(oc.Finder(run=fake).find(name), "computer_ssh-0259c905")
        self.assertTrue(all(c[:3] == ["computers", "ssh", "list"] for c in fake.calls))

    def test_an_office_nobody_runs_is_an_error_that_says_how_offices_are_found(self):
        f = oc.Finder(run=FakeBbox({"computer_ssh-0259c905": "console-exampleu"}))
        with self.assertRaises(AgentError) as e:
            oc.run_there("nowhere", ["list"], finder=f)
        self.assertIn("DEPLOYMENT_NAME", e.exception.message)

    def test_every_office_on_a_computer_is_learnt(self):
        def run(args, timeout):
            if args[:3] == ["computers", "ssh", "list"]:
                return subprocess.CompletedProcess(args, 0, LIST, "")
            out = "console-exampleu-ci\t/root/ci\nconsole-exampleu\t/root/digital-office\n" if args[2] == "computer_ssh-0259c905" else ""
            return subprocess.CompletedProcess(args, 0, out, "")
        f = oc.Finder(run=run)
        self.assertEqual(f.find("exampleu"), "computer_ssh-0259c905")
        self.assertEqual(oc.Finder(run=FakeBbox({})).find("exampleu-ci"), "computer_ssh-0259c905", "remembered")

    def test_a_computer_that_times_out_costs_only_itself(self):
        def run(args, timeout):
            if args[2] == "computer_ssh-b154fa0c":
                raise subprocess.TimeoutExpired(args, timeout)
            return FakeBbox({"computer_ssh-0259c905": "console-exampleu"})(args, timeout)
        self.assertEqual(oc.Finder(run=run).find("exampleu"), "computer_ssh-0259c905")


class TheRemoteScript(unittest.TestCase):
    """What arrives on the far side, run by a real `sh` against a fake docker and checkout."""

    def run_far(self, script, console_dir, also=""):
        d = Path(tempfile.mkdtemp())
        (d / "bin").mkdir()
        (d / "bin" / "docker").write_text(f"#!/bin/sh\nprintf '{also}console-exampleu\\t{console_dir}\\n'\n")
        (d / "bin" / "docker").chmod(0o755)
        line = oc.wrapped(script)
        env = {**os.environ, "PATH": f"{d / 'bin'}:{os.environ['PATH']}"}
        return subprocess.run(["sh", "-c", line], capture_output=True, text=True, env=env)

    def test_runs_bbox_agent_in_the_offices_checkout_with_the_words_intact(self):
        co = Path(tempfile.mkdtemp())
        (co / "bbox").write_text("#!/bin/sh\nprintf '%s|' \"$PWD\" \"$@\"\n")
        (co / "bbox").chmod(0o755)
        args = ["--app", "bina-claude", "new", "-F", "תבדוק את הדיסק, ואת ה-$HOME שלך \"עכשיו\"; rm -rf /"]
        p = self.run_far(oc.agent_script(args, "exampleu"), co)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "|".join([str(co), "agent", *args]) + "|")

    def test_the_office_by_its_name_when_the_computer_runs_two(self):
        co = Path(tempfile.mkdtemp())
        (co / "bbox").write_text("#!/bin/sh\nprintf '%s' \"$PWD\"\n")
        (co / "bbox").chmod(0o755)
        p = self.run_far(oc.agent_script(["list"], "exampleu"), co, also="console-exampleu-ci\\t/root/ci\\n")
        self.assertEqual((p.returncode, p.stdout), (0, str(co)), p.stderr)
        p = self.run_far(oc.agent_script(["list"], "elsewhere"), co, also="console-exampleu-ci\\t/root/ci\\n")
        self.assertEqual(p.returncode, oc.NO_CHECKOUT, "two offices and neither by that name: none")

    def test_a_computer_without_an_office_answers_97(self):
        p = self.run_far(oc.agent_script(["list"], "exampleu"), "/nonexistent")
        self.assertEqual(p.returncode, oc.NO_CHECKOUT)
        self.assertIn("no office checkout", p.stderr)

    def test_the_wrapped_line_has_nothing_a_hop_could_requote(self):
        line = oc.wrapped("echo 'שלום' \"$x\" `y`")
        self.assertRegex(line, r'^sh -c "\$\(echo [A-Za-z0-9+/=]+ \| base64 -d\)"$')


if __name__ == "__main__":
    unittest.main(verbosity=2)
