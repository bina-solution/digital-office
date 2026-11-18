#!/usr/bin/env python3
"""test_governor — the emulator's heat rule, its core and its command line (DGO-1797, package 11).

    python3 apps/android-emulator/test_governor.py      (G72 runs it; standard library only)

The rule is the one android-install-check.yml measured on the Dell: start under 80°C, pause at 85, resume under
80, stop at 90 — on one physical core.
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("emu_governor", os.path.join(HERE, "server", "governor.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def zone(root, n, kind, millideg):
    d = os.path.join(root, f"thermal_zone{n}")
    os.makedirs(d)
    with open(os.path.join(d, "type"), "w") as f:
        f.write(kind + "\n")
    with open(os.path.join(d, "temp"), "w") as f:
        f.write(f"{millideg}\n")


class Heat(unittest.TestCase):
    def test_the_package_zone_is_read_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as root:
            zone(root, 0, "acpitz", 99000)
            zone(root, 1, "x86_pkg_temp", 83500)
            self.assertEqual(g.package_temp(root), 83)
        with tempfile.TemporaryDirectory() as root:
            zone(root, 0, "acpitz", 40000)
            self.assertIsNone(g.package_temp(root))            # no package zone: not taken as cool

    def test_the_rule(self):
        cases = [
            (79, g.WAITING, "start"), (80, g.WAITING, "wait"), (None, g.WAITING, "wait"),
            (84, g.RUNNING, None), (85, g.RUNNING, "pause"), (85, g.BOOTING, "pause"),
            (84, g.PAUSED, None), (80, g.PAUSED, None), (79, g.PAUSED, "resume"),
            (90, g.RUNNING, "stop"), (95, g.PAUSED, "stop"), (None, g.RUNNING, None), (99, g.OFF, None),
        ]
        for temp, state, want in cases:
            self.assertEqual(g.decide(temp, state), want, (temp, state))


class CoreAndCommand(unittest.TestCase):
    def test_cpu0_and_its_sibling(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "cpu0", "topology"))
            with open(os.path.join(root, "cpu0", "topology", "thread_siblings_list"), "w") as f:
                f.write("0,4\n")
            self.assertEqual(g.pinned_cpus(root), "0,4")
            with open(os.path.join(root, "cpu0", "topology", "thread_siblings_list"), "w") as f:
                f.write("0;rm -rf /\n")
            self.assertEqual(g.pinned_cpus(root), "0")           # never a word taskset would run
        self.assertEqual(g.pinned_cpus("/nonexistent"), "0")

    def test_the_command_line_has_a_window_and_two_vcpus(self):
        argv = g.emulator_argv("dgo", 3072, 4096)
        self.assertNotIn("-no-window", argv)
        self.assertEqual(argv[argv.index("-cores") + 1], "2")   # the pin holds the heat; one vCPU starves Android
        self.assertEqual(argv[argv.index("-gpu") + 1], "swiftshader_indirect")
        self.assertEqual((argv[argv.index("-memory") + 1], argv[argv.index("-partition-size") + 1]), ("3072", "4096"))


if __name__ == "__main__":
    unittest.main()
