#!/usr/bin/env python3
"""test_port_findings — the bugs in reconcile.py that porting it to Go found (cyc-227…237, DGO-627…637).

    python3 platform/manager/test_port_findings.py      # needs PyYAML (reconcile.py imports it)

The Go twin (packaging/dgo) was written to answer exactly as reconcile.py does — the bugs included, because
Python is its oracle. Each case here is one of those bugs, on the Python side, and fails on the code before
its fix; the Go side of the same fix is held by the oracle tests in packaging/dgo/internal/compiler.

- DGO-632: a generations (or plans) folder named «²» — str.isdigit() takes it, int() refuses it, every render fell.
- DGO-631: sync_identity wrote a CRLF .env back as LF — read_text had read its endings as \\n already.
- DGO-630: a route with no `auth` got the sign-in's gate (the routers default to sso) but no provider: a 404 host.
- DGO-629: an effective CPU plan that is not UTF-8 stopped compose-files — only OSError was caught around read_text.
- DGO-628: the edge's files (zz-serve, zz-https, remote.override) were written on every render, past write().
- DGO-627: a linked office's `order: null` beside numbers — a TypeError in the sorts, mid-render.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import unittest

import yaml  # noqa: F401 — reconcile.py imports it: said here, so G72 names it NOT RUN where absent

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_port_findings", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_port_findings"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


class Patched(unittest.TestCase):
    """A temporary checkout: REPO, GEN, GENS and PLANS point into it, and are put back after each case."""

    NAMES = ("REPO", "GEN", "GENS", "PLANS")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.gen = self.root / ".generated"
        self.gen.mkdir()
        self._saved = {n: getattr(rc, n) for n in self.NAMES}
        rc.REPO, rc.GEN, rc.GENS, rc.PLANS = self.root, self.gen, self.gen / "generations", self.gen / "plans"

    def tearDown(self):
        for n, v in self._saved.items():
            setattr(rc, n, v)
        self._tmp.cleanup()


class Generations(Patched):
    """DGO-632: only ASCII digits name a generation or a plan."""

    def test_a_superscript_generation_is_skipped(self):
        (self.gen / "compose.yml").write_text("services: {}\n", encoding="utf-8")
        (rc.GENS / "0001").mkdir(parents=True)
        (rc.GENS / "²").mkdir()
        (rc.GENS / "٣").mkdir()                      # an Arabic-Indic three: isdigit() too
        self.assertEqual([d.name for d in rc._gen_dirs()], ["0001"])
        self.assertEqual(rc.archive_generation(), "0002")
        self.assertTrue((rc.GENS / "²").is_dir())     # not ours to remove: skipped, left as it is

    def test_a_superscript_plan_is_skipped(self):
        rc.PLANS.mkdir(parents=True)
        (rc.PLANS / "0003.yaml").write_text("plan: '0003'\n", encoding="utf-8")
        (rc.PLANS / "².yaml").write_text("plan: x\n", encoding="utf-8")
        pid, _digest = rc.write_plan({}, {}, [], [])
        self.assertEqual(pid, "0004")
        (rc.PLANS / "0010.yaml").write_text("plan: '0010'\n", encoding="utf-8")
        self.assertEqual(rc._plan_ids(), ["0003", "0004", "0010"])   # what apply takes the last of: 0010, never «²»


class Identity(Patched):
    """DGO-631: sync_identity writes a stale slug back in the file's own line endings."""

    def sync(self, before: bytes) -> bytes:
        env = self.root / ".env"
        self.assertEqual(rc.ENVFILE, env)              # the guard moved it with REPO: never the repo's own
        env.write_bytes(before)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rc.sync_identity(), "bina-solutions-ltd")
        return env.read_bytes()

    def test_a_crlf_env_stays_crlf(self):
        after = self.sync(b'BUSINESS_NAME="Bina Solutions Ltd."\r\n#@derived slug\r\nCOMPANY_SLUG=old\r\nX=1\r\n')
        self.assertEqual(after, b'BUSINESS_NAME="Bina Solutions Ltd."\r\n#@derived slug\r\n'
                                b'COMPANY_SLUG=bina-solutions-ltd\r\nX=1\r\n')

    def test_an_lf_env_stays_lf(self):
        after = self.sync(b'BUSINESS_NAME="Bina Solutions Ltd."\n#@derived slug\nCOMPANY_SLUG=old\n')
        self.assertEqual(after, b'BUSINESS_NAME="Bina Solutions Ltd."\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd\n')

    def test_every_line_keeps_its_own_ending(self):
        for before, after in (
                # a lone \r still ends a line (universal newlines), and stays
                (b'A=1\rBUSINESS_NAME="Bina Solutions Ltd."\r\n#@derived slug\r\nCOMPANY_SLUG=old\r\n',
                 b'A=1\rBUSINESS_NAME="Bina Solutions Ltd."\r\n#@derived slug\r\nCOMPANY_SLUG=bina-solutions-ltd\r\n'),
                # one CRLF line in an LF file: only that line keeps CRLF — the file is not made CRLF
                (b'BUSINESS_NAME="Bina Solutions Ltd."\n#@derived slug\nCOMPANY_SLUG=old\r\nX=1\n',
                 b'BUSINESS_NAME="Bina Solutions Ltd."\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd\r\nX=1\n'),
                # the slug planted under BUSINESS_NAME takes that line's ending
                (b'A=1\r\nBUSINESS_NAME="Bina Solutions Ltd."\r\nB=2\r\n',
                 b'A=1\r\nBUSINESS_NAME="Bina Solutions Ltd."\r\n#@derived slug\r\nCOMPANY_SLUG=bina-solutions-ltd\r\nB=2\r\n'),
                # …and under a last line with no ending, the file still ends without one
                (b'A=1\nBUSINESS_NAME="Bina Solutions Ltd."',
                 b'A=1\nBUSINESS_NAME="Bina Solutions Ltd."\n#@derived slug\nCOMPANY_SLUG=bina-solutions-ltd')):
            self.assertEqual(self.sync(before), after, before)


class CpuBudget(Patched):
    """DGO-629: compose-files' own overlays that are not UTF-8 (half-written, another encoding) are written again, as
    missing ones are — not a UnicodeDecodeError that stopped every dc call, nor a broken file handed to compose."""

    def test_an_effective_plan_that_is_not_utf8_is_written_again(self):
        (self.gen / "cpu-budget.yml").write_text("services:\n  traefik: {cpus: 1}\n  gone: {cpus: 1}\n", encoding="utf-8")
        out = self.gen / "cpu-budget.effective.yml"
        out.write_bytes(b"old \xff\n")
        saved, rc._compiled_services = rc._compiled_services, lambda: {"traefik"}
        try:
            got = rc._effective_cpu_budget()
        finally:
            rc._compiled_services = saved
        self.assertEqual(got, out)
        self.assertIn("Dropped — no such service in the compiled set any more: gone", out.read_text(encoding="utf-8"))

    def test_a_bootstrap_overlay_that_is_not_utf8_is_written_again(self):
        (self.gen / "compose.yml").write_text("include: []\n", encoding="utf-8")
        out = self.gen / "authentik-bootstrap.override.yml"
        out.write_bytes(b"old \xff\n")
        saved, rc._compiled_services = rc._compiled_services, lambda: {"authentik-bootstrap"}
        try:
            got = rc._bootstrap_inputs_overlay()
        finally:
            rc._compiled_services = saved
        self.assertEqual(got, out)
        self.assertIn("bbox.bootstrap-inputs: ", out.read_text(encoding="utf-8"))


class EdgeFiles(Patched):
    """DGO-628: the edge's files are left alone when a render says the same — traefik's file provider reloads on
    any write, and zz-serve.yaml, zz-https.yaml and remote.override.yml were written on every render."""

    def setUp(self):
        super().setUp()
        (self.root / "platform-base/traefik/config").mkdir(parents=True)
        self.doc = "http:\n  routers: {}\n"
        self._fns = rc.serve.render, rc.serve.render_aliases
        rc.serve.render = lambda *a, **k: self.doc
        rc.serve.render_aliases = lambda served: "services: {}\n"

    def tearDown(self):
        rc.serve.render, rc.serve.render_aliases = self._fns
        super().tearDown()

    def render(self):
        rc.render_serve({}, [])
        rc.render_https_redirect({}, [])

    def test_a_second_render_touches_none_of_them(self):
        files = [self.root / "platform-base/traefik/config/zz-serve.yaml",
                 self.root / "platform-base/traefik/config/zz-https.yaml", self.gen / "remote.override.yml"]
        self.render()
        old = 1_000_000_000_000_000_000
        for p in files:
            os.utime(p, ns=(old, old))
        self.render()
        self.assertEqual([p.stat().st_mtime_ns for p in files], [old] * 3)
        self.doc = "http:\n  routers: {a: {}}\n"                 # a real change is still written
        self.render()
        self.assertEqual(files[0].read_text(encoding="utf-8"), self.doc)
        self.assertNotEqual(files[0].stat().st_mtime_ns, old)


class LinkedOrder(unittest.TestCase):
    """DGO-627: a linked office's `order` that is not a number reads as a missing one (900) — a null beside numbers
    was a TypeError in the sorts, after half the files were written: one linked office stopped this one's render."""

    REMOTE = """remote:
- office: macbook
  address: 10.79.3.2
  apps:
  - {app: bina-ds, alias: bina, port: 3080, order: 1}
  - {app: drive, port: 8975, order: null}
  - {app: browser42, port: 80, order: soon}
  - {app: sites, port: 8979}
"""

    def test_a_null_or_a_word_reads_as_900(self):
        entries, errs = rc.serve.plan(yaml.safe_load(self.REMOTE), {})
        self.assertEqual(errs, [])
        orders = {a["app"]: a["order"] for e in entries for a in e["apps"]}
        self.assertEqual(orders, {"bina-ds": 1, "drive": 900, "browser42": 900, "sites": 900})
        rows = rc.remote_records(entries)                       # what the tiles and app rows are built from
        self.assertEqual(sorted(r["order"] for r in rows.values()), [1, 900, 900, 900])


class RemoteDoor(unittest.TestCase):
    """DGO-553 (found by the Go render oracle on e67a5ec38): a linked app's record carries its door — the base and
    the Host its office answers under — which the computers app reads to merge a linked office's machines."""

    def test_the_record_carries_the_door(self):
        state = yaml.safe_load("""remote:
- office: macbook
  address: 10.79.3.2
  link_port: 9002
  apps:
  - {app: computers, port: 9003, host: computers.localhost, identity: {to: owner}}
""")
        entries, errs = rc.serve.plan(state, {})
        self.assertEqual(errs, [])
        rec = rc.remote_records(entries)["remote.macbook.computers.json"]
        self.assertEqual(rec["door"], {"base": "http://computers.macbook:9002", "host": "computers.localhost",
                                       "user": "owner"})
        self.assertEqual(list(rec)[-2:], ["door", "remote"])           # the Go twin's key order


class SsoDefault(unittest.TestCase):
    """DGO-630: a route that writes no `auth` is behind the sign-in (the routers' default) — and gets its provider."""

    SSO = {"slug": "notes", "display_name": "Notes", "base_url_env": "NOTES_BASE_URL",
           "default_host": "notes.localhost"}

    def cat(self, route):
        return {"notes": {"layer": 3, "routing": [dict(route, host="notes", port=80, sso=self.SSO)]}}

    def test_no_auth_is_sso_for_the_provider_and_the_host(self):
        for route in ({"auth": "sso"}, {}):                  # the same app, auth written and auth left out
            cat = self.cat(route)
            self.assertEqual([(aid, s["slug"], host) for aid, s, host in rc.sso_providers(cat, ["notes"])],
                             [("notes", "notes", "notes")], route)
            self.assertEqual(rc.published_hosts(cat, ["notes"]),
                             {"NOTES_BASE_URL": "notes.${DEPLOYMENT_DOMAIN:-localhost}"}, route)

    def test_auth_none_is_still_open(self):
        cat = self.cat({"auth": "none"})
        self.assertEqual(rc.sso_providers(cat, ["notes"]), [])
        self.assertEqual(rc.published_hosts(cat, ["notes"]), {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
