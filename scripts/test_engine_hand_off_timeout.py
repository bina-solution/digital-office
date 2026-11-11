#!/usr/bin/env python3
"""test_engine_hand_off_timeout — a call into the Mac's engine is held to its time limit INSIDE the guest (DGO-1783).

    python3 scripts/test_engine_hand_off_timeout.py

On a Mac every call into the engine is `engine.sh exec` → `limactl shell`, and sshd keeps that session's slot while
the GUEST command runs; a timeout on the Mac's side only abandoned it. Measured 2026-11-10 at load 20–30: abandoned
calls held the guest's sessions until it refused every new one («Session open refused by peer»), for every lane.
What is asked: bbox_agent._engine_cmd puts `timeout -k 5 T` in front of the guest command when given a limit (and
nothing elsewhere: on Linux, WSL, or already inside the guest the command is unchanged); _engine_run waits T plus a
grace, and a guest that ended the command (124, 137) is one sentence — not a traceback, not a TimeoutExpired;
remote.py's _docker hands its limit to the guest the same way. Nothing is killed as a process group: engine.sh exec
starts the office's host daemons in its own group. (No `timeout` binary is run here — macOS has none.)
"""
import os
import pathlib
import subprocess
import sys
import unittest
import importlib.util

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bbox_agent import client  # noqa: E402

_spec = importlib.util.spec_from_file_location("remote_under_test", HERE / "remote.py")
remote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote)


class Platform:
    def __init__(self, name, in_guest=False):
        self.name, self.in_guest = name, in_guest

    def __enter__(self):
        self.old = (sys.platform, os.environ.get("BBOX_IN_GUEST"))
        sys.platform = self.name
        if self.in_guest:
            os.environ["BBOX_IN_GUEST"] = "1"
        else:
            os.environ.pop("BBOX_IN_GUEST", None)

    def __exit__(self, *exc):
        sys.platform = self.old[0]
        if self.old[1] is None:
            os.environ.pop("BBOX_IN_GUEST", None)
        else:
            os.environ["BBOX_IN_GUEST"] = self.old[1]


class EngineCmd(unittest.TestCase):
    def test_a_mac_host_holds_the_limit_in_the_guest(self):
        with Platform("darwin"):
            cmd = client._engine_cmd(["docker", "ps"], guest_timeout=60)
        self.assertEqual(cmd[1:4], [str(client.REPO / "packaging/macos/engine.sh"), "exec", "--"])
        self.assertEqual(cmd[4:], ["timeout", "-k", "5", "60", "docker", "ps"])

    def test_no_limit_no_wrapper(self):
        with Platform("darwin"):
            self.assertEqual(client._engine_cmd(["docker", "ps"])[4:], ["docker", "ps"])

    def test_elsewhere_the_command_is_unchanged(self):
        args = ["docker", "ps"]
        for name, guest in (("linux", False), ("darwin", True), ("win32", False)):
            with Platform(name, guest):
                self.assertIs(client._engine_cmd(args, guest_timeout=60), args, name)


class EngineRun(unittest.TestCase):
    def run_with(self, script, timeout=5):
        real = client._engine_cmd
        client._engine_cmd = lambda args, guest_timeout=None: ["sh", "-c", script]
        try:
            return client._engine_run(["docker", "ps"], timeout=timeout)
        finally:
            client._engine_cmd = real

    def test_a_guest_that_ended_the_command_is_one_sentence(self):
        for code in (124, 137):
            with self.assertRaises(client.AgentError) as e:
                self.run_with(f"sleep 1; exit {code}", timeout=1)
            self.assertIn("did not answer in 1 s", e.exception.message)

    def test_a_quick_137_is_the_command_killed_and_says_so(self):
        with self.assertRaises(client.AgentError) as e:
            self.run_with("echo 'OOMKilled' >&2; exit 137", timeout=30)
        self.assertNotIn("did not answer", e.exception.message)
        self.assertIn("OOMKilled", e.exception.message)

    def test_a_timeout_on_this_side_is_the_same_sentence(self):
        real = client.subprocess.run

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        client.subprocess.run = slow
        try:
            with self.assertRaises(client.AgentError) as e:
                client._engine_run(["docker", "ps"], timeout=4)
        finally:
            client.subprocess.run = real
        self.assertIn("did not answer in 4 s", e.exception.message)

    def test_an_answer_and_an_error(self):
        self.assertEqual(self.run_with("echo ok"), "ok")
        with self.assertRaises(client.AgentError) as e:
            self.run_with("echo broken >&2; exit 3")
        self.assertIn("broken", e.exception.message)

    def test_this_side_waits_beyond_the_guest(self):
        seen = {}
        real = client.subprocess.run
        client.subprocess.run = lambda cmd, **kw: seen.update(kw) or subprocess.CompletedProcess(cmd, 0, "x", "")
        try:
            with Platform("darwin"):
                client._engine_run(["docker", "ps"], timeout=30)
        finally:
            client.subprocess.run = real
        self.assertEqual(seen["timeout"], 30 + client.GUEST_GRACE)


class Remote(unittest.TestCase):
    def test_docker_hands_its_limit_to_the_guest(self):
        seen = []
        real = remote.subprocess.run
        remote.subprocess.run = lambda cmd, **kw: seen.append((cmd, kw)) or subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            with Platform("darwin"):
                remote._docker(["ps"], timeout=7, input_text="x")
        finally:
            remote.subprocess.run = real
        cmd, kw = seen[0]
        self.assertEqual(cmd[4:], ["timeout", "-k", "5", "7", "docker", "ps"])
        self.assertEqual((kw["timeout"], kw["input"]), (7 + client.GUEST_GRACE, "x"))


class BboxCallers(unittest.TestCase):
    """The callers on a Mac's host that run `./bbox …` with a limit of their own hand the limit to the guest in
    BBOX_GUEST_TIMEOUT (engine.sh guest_shell), a little under theirs; with no limit they set nothing."""

    def capture(self, module, call):
        seen = []
        real = module.subprocess.run
        module.subprocess.run = lambda cmd, **kw: seen.append(kw.get("env")) or \
            subprocess.CompletedProcess(cmd, 0, '{"tasks": []}', "")
        try:
            call()
        finally:
            module.subprocess.run = real
        return seen

    def test_over_computer_probe(self):
        from bbox_agent import over_computer
        env = self.capture(over_computer, lambda: over_computer._bbox(["computers", "list"], timeout=60))
        self.assertEqual(env[0]["BBOX_GUEST_TIMEOUT"], "55")
        os.environ["BBOX_GUEST_TIMEOUT"] = "7"                          # inherited: a long session must not carry it
        try:
            env = self.capture(over_computer, lambda: over_computer._bbox(["x"], capture=False))
        finally:
            del os.environ["BBOX_GUEST_TIMEOUT"]
        self.assertNotIn("BBOX_GUEST_TIMEOUT", env[0])

    def test_the_stop_hooks_plane_read(self):
        spec = importlib.util.spec_from_file_location("work_left_under_test", HERE.parent / ".claude/hooks/work-left.py")
        wl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wl)
        env = self.capture(wl, lambda: wl.tasks(str(HERE.parent), 24, "list"))
        self.assertEqual(env[0]["BBOX_GUEST_TIMEOUT"], "19")
        self.assertEqual(env[0].get("PATH"), os.environ.get("PATH"))          # the rest of the environment kept


if __name__ == "__main__":
    unittest.main(verbosity=1)
