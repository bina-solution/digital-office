"""The two restart tools name the INDOX tenant on every PATCH, and refuse an office they cannot serve (DGO-1815).

    python3 scripts/test_restart_scripts_name_instance.py

scripts/ops/restart_all_not_completed.sh and restart_blocked_merge_mains.sh read public.* (the views onto one tenant)
and PATCH documents through INDOX's BFF with no instance — the BFF's default. Once INDOX refuses an instance-less call
(stage three) they would stop working, and on an office with two production tenants a read and a write could name
different books. What holds, with a stub psql and no office: `tenant()` answers the sole enabled production tenant,
refuses two, refuses an INDOX_INSTANCE that names another one; each PATCH carries `?instance=`.

RESTART_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import os
import pathlib
import re
import shlex
import subprocess
import unittest

ROOT = pathlib.Path(os.environ.get("RESTART_ROOT") or pathlib.Path(__file__).resolve().parents[1])
SCRIPTS = [ROOT / "scripts/ops/restart_all_not_completed.sh", ROOT / "scripts/ops/restart_blocked_merge_mains.sh"]


def tenant(script, rows, declared=None, view="indox_example", psql_fails=False):
    """Run the script's own tenant() with a stub psql: the registry query answers `rows` ("id|schema", one per line,
    as psql -tA does), the view query answers `view`; returns (exit code, stdout)."""
    src = script.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^tenant \(\) \{\n.*?^\}\n", src)
    if not m:
        return None
    reg = ("printf '%s\\n' " + " ".join(shlex.quote(r) for r in rows)) if rows else ":"
    vw = ("printf '%s\\n' " + shlex.quote(view)) if view else ":"
    stub = ("PSQL() { return 1; }\n" if psql_fails else
            "PSQL() { case \"$1\" in *indox_instances*) " + reg + ";; *pg_rewrite*) " + vw + ";; esac; }\n")
    env = dict(os.environ)
    env.pop("INDOX_INSTANCE", None)
    if declared:
        env["INDOX_INSTANCE"] = declared
    body = stub + m.group(0).replace("$PSQL ", "PSQL ") + "tenant\n"
    r = subprocess.run(["bash", "-c", body], capture_output=True, text=True, env=env, timeout=20)
    return r.returncode, r.stdout.strip()


class RestartScriptsNameInstance(unittest.TestCase):
    def test_tenant_is_the_sole_production_one_and_refuses_otherwise(self):
        H = "example|indox_example"
        for s in SCRIPTS:
            self.assertEqual(tenant(s, [H]), (0, "example"), s.name)
            self.assertEqual(tenant(s, [H, "exampleu|indox_exampleu"])[0], 1, s.name)
            self.assertEqual(tenant(s, [])[0], 1, s.name)
            self.assertEqual(tenant(s, [H], declared="example"), (0, "example"), s.name)
            self.assertEqual(tenant(s, [H], declared="exampleu")[0], 1, s.name)

    def test_the_view_it_reads_must_be_that_tenants_table(self):
        for s in SCRIPTS:
            # the public views were made over example; a sole tenant that is someone else would write other books
            self.assertEqual(tenant(s, ["exampleu|indox_exampleu"], view="indox_example")[0], 1, s.name)
            # no view, or public.incoming_documents is a TABLE (measured on vps1): the query answers nothing
            self.assertEqual(tenant(s, ["example|indox_example"], view="")[0], 1, "no such view: " + s.name)
            self.assertEqual(tenant(s, ["example|indox_example"], psql_fails=True)[0], 1, "registry unread: " + s.name)

    def test_a_refusal_stops_the_run_before_any_drain(self):
        for s in SCRIPTS:
            calls = re.findall(r"^\s+patch_ids \"\$\w+\"(.*)$", s.read_text(encoding="utf-8"), re.M)
            self.assertTrue(calls, s.name)
            for rest in calls:
                self.assertTrue(rest.strip().startswith("|| exit 1"), "%s: patch_ids\"…\"%s" % (s.name, rest))

    def test_a_run_where_the_patches_did_not_take_fails_the_step(self):
        # the node scripts exited 0 whatever happened, so `|| exit 1` caught only a refusal
        a, b = (s.read_text(encoding="utf-8") for s in SCRIPTS)
        self.assertIn("process.exitCode = ok ? 0 : 1;", a)
        self.assertIn("process.exitCode = fail ? 1 : 0;", b)

    def test_every_patch_names_the_tenant(self):
        for s in SCRIPTS:
            src = s.read_text(encoding="utf-8")
            self.assertIn('inst=$(tenant) || return 1', src, s.name)
            self.assertIn('-e N="$inst"', src, s.name)
            fetches = re.findall(r'fetch\(process\.env\.B[^,]*', src)
            self.assertTrue(fetches, s.name)
            for f in fetches:
                self.assertIn('"?instance=" + encodeURIComponent(process.env.N)', f, s.name)

    def test_the_scripts_still_parse(self):
        for s in SCRIPTS:
            self.assertEqual(subprocess.run(["bash", "-n", str(s)]).returncode, 0, s.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
