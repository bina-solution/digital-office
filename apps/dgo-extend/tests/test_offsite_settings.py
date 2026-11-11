"""Every off-site setting converge.py reads reaches the dgo-extend container (DGO-1799).

    python3 apps/dgo-extend/tests/test_offsite_settings.py

converge.py read DGO_OFFSITE_KEEP (how many verified copies a store keeps) and DGO_OFFSITE_HELPER, but the
compose passed only DGO_OFFSITE_TO and DGO_OFFSITE_DIR — so the MacBook's engine, whose disk the clients' copies
were filling, could not be told to keep fewer: the setting was inert. What holds:
  1. every `os.environ.get("DGO_OFFSITE_…")` in converge.py has its line in the dgo-extend service's environment;
  2. each line's compose default is the code's own default, so passing it changes nothing until an office sets it;
  3. the template names DGO_OFFSITE_KEEP, so an office can see it exists;
  4. a value that is not a count of 1 or more is refused by name before any copy is touched — never a crash at
     import (a non-number) and never a wipe (`head -n -0` deletes every verified copy).
"""
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
CONVERGE = (HERE / "converge.py").read_text(encoding="utf-8")
COMPOSE = (HERE / "docker-compose.yml").read_text(encoding="utf-8")


def service_env(name):
    """The `- KEY=VALUE` lines of one service's environment, as text (no YAML parser needed)."""
    block = re.search(r"(?ms)^  %s:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)" % re.escape(name), COMPOSE).group(1)
    return dict(re.findall(r"^\s+- (DGO_[A-Z_]+)=(.*)$", block, re.M))


class OffsiteSettings(unittest.TestCase):
    def test_every_setting_read_is_passed(self):
        read = dict(re.findall(r'os\.environ\.get\("(DGO_OFFSITE_[A-Z_]+)",?\s*"?([^")]*)"?\)', CONVERGE))
        self.assertGreaterEqual(len(read), 4, "scan found %d settings" % len(read))
        env = service_env("dgo-extend")
        missing = sorted(k for k in read if k not in env)
        self.assertEqual(missing, [], "read by converge.py, not passed by the compose")

    def test_defaults_agree(self):
        read = dict(re.findall(r'os\.environ\.get\("(DGO_OFFSITE_[A-Z_]+)",\s*"([^"]*)"\)', CONVERGE))
        env = service_env("dgo-extend")
        for key, default in read.items():
            m = re.fullmatch(r"\$\{%s:-(.*)\}" % key, env.get(key, ""))
            self.assertIsNotNone(m, key)
            self.assertEqual(m.group(1), default, key)

    def test_the_template_names_the_retention(self):
        self.assertRegex((REPO / ".env.ex").read_text(encoding="utf-8"), r"(?m)^DGO_OFFSITE_KEEP=")

    def test_a_bad_retention_is_refused_by_name_never_a_crash_or_a_wipe(self):
        # the parser, lifted out of converge.py and run alone (the module needs the app's environment)
        import ast
        tree = ast.parse(CONVERGE)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "offsite_keep")
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "converge.py", "exec"), ns)
        keep = ns["offsite_keep"]
        self.assertEqual([keep(x) for x in (None, "", " ", "7", "3", " 3 ")], [7, 7, 7, 7, 3, 3])
        self.assertEqual([keep(x) for x in ("0", "-1", "three", "3.5")], [0, -1, 0, 0])
        # and the step refuses anything below 1 before it snapshots: `head -n -0` would delete every copy
        step = CONVERGE[CONVERGE.index("def step_offsite("):]
        first = step[:step.index("p, oid = q(office")]
        self.assertIn("if OFFSITE_KEEP < 1:", first)
        self.assertIn("raise StepFailed(", first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
