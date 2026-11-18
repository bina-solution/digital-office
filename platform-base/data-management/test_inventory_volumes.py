"""test_inventory_volumes.py — the inventory names every volume on the engine, in three docker calls (DGO-1510).

    python3 test_inventory_volumes.py          # no docker, no service: docker is faked at inventory._docker

What it holds:
  - a volume of another project, or of none, is listed and UNCLAIMED with its project, even when its name is a
    short name some app declares (the inventory saw only this project's prefix: 26 volumes on the MacBook and
    `exampleu-meets-import` on Exampleu were in no list);
  - anonymous volumes are counted with their bytes, not listed;
  - who uses a volume is read from ONE `docker ps -a`, whatever the count (one per volume never finished on the
    HP: 134 volumes, past the sweep's 600 s stall guard, 2026-11-13);
  - a `system df` that times out leaves the sizes unknown and keeps every name;
  - the screen's UNCLAIMED list is the archiver's (`undeclared_volumes`): the same names its manifest gives.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
os.environ["DEPLOYMENT_PATH"] = str(HERE.parent.parent)        # the checkout: inventory loads the archiver from it
sys.path.insert(0, str(HERE))

import inventory as INV  # noqa: E402

ANON = "a" * 64
# acme_data: declared (`data`) but labelled by another project — carried by its name all the same;
# acme-import: this project's by its label (a compose `name:`), not prefixed, declared by nobody.
VOLUMES = [("acme_n8n_storage", "acme"), ("acme_forgotten", "acme"), ("exf-release", ""),
           ("other_n8n_storage", "other"), ("n8n_storage", ""), ("acme_data", "other"), ("acme-import", "acme"),
           ("acme_x_cache", "acme_x"), (ANON, "")]
SIZES = {"acme_n8n_storage": "135MB", "acme_forgotten": "1.5kB", "exf-release": "33MB",
         "other_n8n_storage": "2GB", "n8n_storage": "10B", "acme_data": "5MB", "acme-import": "N/A",
         "acme_x_cache": "1MB", ANON: "4MB"}
DECLARED = {"n8n_storage", "data"}
PS = [("n8n-acme", "acme_n8n_storage,/repo/apps/n8n/data"), ("any-acme", "acme_n8n_storage"),
      ("old-thing", "other_n8n_storage"), ("sidecar", f"{ANON},/tmp")]


class FakeDocker:
    def __init__(self, df_timeout=False):
        self.calls: list[list] = []
        self.df_timeout = df_timeout

    def __call__(self, args, timeout=90):
        self.calls.append(list(args))
        fmt = args[args.index("--format") + 1] if "--format" in args else ""
        if args[:2] == ["volume", "ls"]:
            if "Label" in fmt:
                return "\n".join(f"{n}\t{label}" for n, label in VOLUMES), 0
            return "\n".join(n for n, _ in VOLUMES), 0
        if args[:2] == ["system", "df"]:
            if self.df_timeout:
                raise subprocess.TimeoutExpired(["docker"] + args, timeout)
            if fmt:
                return "\n".join(f"{n}\t{s}" for n, s in SIZES.items()), 0
            # docker's own table: VOLUME NAME  LINKS  SIZE
            return "Local Volumes space usage:\n\nVOLUME NAME   LINKS   SIZE\n" + "\n".join(
                f"{n}   1   {s}" for n, s in SIZES.items()), 0
        if args[:1] == ["ps"]:
            if "--filter" in args:                              # the old way: one call per volume
                v = args[args.index("--filter") + 1].split("=", 1)[1]
                return "\n".join(c for c, m in PS if v in m.split(",")), 0
            return "\n".join(f"{c}\t{m}" for c, m in PS), 0
        return "", 0


class LiveVolumes(unittest.TestCase):
    def setUp(self):
        self.saved = INV._docker
        INV._docker = self.docker = FakeDocker()

    def tearDown(self):
        INV._docker = self.saved

    def rows(self):
        out = INV.live_volumes("acme", DECLARED)
        self.assertIsInstance(out, tuple, "live_volumes returns (rows, anonymous)")
        rows, anon = out
        return {r["name"]: r for r in rows}, anon

    def test_every_volume_on_the_engine_is_listed_not_only_this_projects(self):
        rows, _ = self.rows()
        self.assertEqual(sorted(rows), ["acme-import", "acme_data", "acme_forgotten", "acme_n8n_storage",
                                        "acme_x_cache", "exf-release", "n8n_storage", "other_n8n_storage"])
        r = rows["acme_n8n_storage"]
        self.assertEqual((r["short"], r["ours"], r["carried"], r["project"]), ("n8n_storage", True, True, "acme"))
        r = rows["exf-release"]
        self.assertEqual((r["short"], r["ours"], r["carried"], r["project"]), ("exf-release", False, False, None))
        self.assertEqual((rows["other_n8n_storage"]["ours"], rows["other_n8n_storage"]["project"]), (False, "other"))
        # a bare volume named exactly as a declared short name is still not this office's
        self.assertEqual((rows["n8n_storage"]["ours"], rows["n8n_storage"]["carried"]), (False, False))

    def test_ours_and_carried_are_the_archivers_in_the_edge_cases(self):
        rows, _ = self.rows()
        # declared, carried by its name `acme_data` whatever its label (_tar_volume)
        r = rows["acme_data"]
        self.assertEqual((r["short"], r["ours"], r["carried"]), ("data", True, True))
        # this project's by its label, not prefixed: ours, left out, its short is its full name, N/A is no size
        r = rows["acme-import"]
        self.assertEqual((r["short"], r["ours"], r["carried"], r["project"], r["size"]),
                         ("acme-import", True, False, "acme", None))
        # a prefixed name labelled by another project (`acme_x`) and declared by nobody is that project's
        r = rows["acme_x_cache"]
        self.assertEqual((r["short"], r["ours"], r["carried"], r["project"]), ("acme_x_cache", False, False, "acme_x"))

    def test_the_copy_of_the_rule_without_the_archiver_is_the_same(self):
        listing = [(n, label, SIZES.get(n)) for n, label in VOLUMES]
        want = INV.ARCHIVER.undeclared_volumes(listing, DECLARED, "acme")
        saved = INV.ARCHIVER
        INV.ARCHIVER = None
        try:
            got = INV._undeclared(listing, DECLARED, "acme")
        finally:
            INV.ARCHIVER = saved
        self.assertEqual(got, want)

    def test_anonymous_volumes_are_counted_not_named(self):
        rows, anon = self.rows()
        self.assertNotIn(ANON, rows)
        self.assertEqual(anon, {"count": 1, "bytes": 4_000_000, "bytes_unknown": 0})

    def test_who_uses_a_volume_is_one_docker_ps_whatever_the_count(self):
        rows, _ = self.rows()
        self.assertEqual(rows["acme_n8n_storage"]["used_by"], ["any-acme", "n8n-acme"])
        self.assertEqual(rows["other_n8n_storage"]["used_by"], ["old-thing"])
        self.assertEqual(rows["exf-release"]["used_by"], [])
        self.assertEqual(len([c for c in self.docker.calls if c[:1] == ["ps"]]), 1, self.docker.calls)
        self.assertEqual(len(self.docker.calls), 3, self.docker.calls)

    def test_sizes_that_time_out_leave_every_name(self):
        INV._docker = FakeDocker(df_timeout=True)
        rows, anon = self.rows()
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["size"] is None and r["bytes"] is None for r in rows.values()))
        self.assertEqual(anon["bytes_unknown"], 1)

    def test_the_unclaimed_rule_is_the_archivers(self):
        self.assertIsNotNone(INV.ARCHIVER, "the archiver did not load from the checkout")
        listing = [(n, label, SIZES.get(n)) for n, label in VOLUMES]
        want, _ = INV.ARCHIVER.undeclared_volumes(listing, DECLARED, "acme")
        rows, _ = self.rows()
        self.assertEqual(sorted(r["name"] for r in want), sorted(n for n, r in rows.items() if not r["carried"]))
        self.assertEqual({r["name"]: r["ours"] for r in want}, {n: r["ours"] for n, r in rows.items() if not r["carried"]})


class TheSweep(unittest.TestCase):
    """inventory_steps: the verdicts and the UNCLAIMED list the screen and `bbox data view --gaps-only` show."""

    def setUp(self):
        self.saved = (INV._docker, INV.all_apps, INV.project_name, INV.live_databases, INV.live_redis,
                      INV.secret_paths, INV.stateful_binds)
        INV._docker = FakeDocker()
        INV.project_name = lambda: "acme"
        INV.all_apps = lambda: [{"id": a, "title": a, "layer": 3, "kind": "app", "enabled": True,
                                 "volumes": [v], "paths": [], "sql": [], "kv": [],
                                 "on_uninstall": "keep", "backup_hook": a == "n8n", "restore_hook": a == "n8n"}
                                for a, v in (("n8n", "n8n_storage"), ("files", "data"))]
        INV.live_databases = lambda project, table_limit=40: []
        INV.live_redis = lambda project: []
        INV.secret_paths = lambda: []
        INV.stateful_binds = lambda: ([], None)

    def tearDown(self):
        (INV._docker, INV.all_apps, INV.project_name, INV.live_databases, INV.live_redis,
         INV.secret_paths, INV.stateful_binds) = self.saved

    def test_the_volumes_section_asks_docker_ps_once(self):
        INV.inventory()
        self.assertEqual(len([c for c in INV._docker.calls if c[:1] == ["ps"]]), 1, INV._docker.calls)

    def test_a_foreign_volume_is_unclaimed_with_its_project(self):
        o = INV.inventory()
        cov = {v["name"]: v["coverage"] for v in o["volumes"]}
        self.assertEqual(cov["acme_n8n_storage"], "covered (hook)")
        self.assertEqual(cov["acme_data"], "covered (generic tar)")      # carried by its name, label or not
        for n in ("acme_forgotten", "acme-import", "acme_x_cache", "exf-release", "other_n8n_storage", "n8n_storage"):
            self.assertEqual(cov[n], "UNCLAIMED", n)
        unc = {u["name"]: u for u in o["unclaimed"] if u["kind"] == "volume"}
        self.assertEqual(sorted(unc), ["acme-import", "acme_x_cache", "forgotten", "exf-release", "n8n_storage",
                                       "other_n8n_storage"])
        self.assertIn("project 'other'", unc["other_n8n_storage"]["why"])
        self.assertIn("no compose project", unc["exf-release"]["why"])
        self.assertNotIn("not this office's", unc["acme-import"]["why"])   # this project's by its label
        self.assertEqual(unc["exf-release"]["bytes"], 33_000_000)
        self.assertEqual(o["anonymous_volumes"]["count"], 1)
        self.assertEqual(o["summary"]["unclaimed"], 6)
        # a declared volume of THIS project that exists is not «declared but absent»
        self.assertEqual(o["declared_absent"], [])

    def test_the_footprint_and_at_risk_are_this_offices_volumes_only(self):
        # another project's gigabytes are no part of what this office's archive holds (the second reader)
        s = INV.inventory()["summary"]
        self.assertEqual(s["volumes"], 4)                                  # acme_n8n_storage, _data, _forgotten, -import
        self.assertEqual(s["volume_bytes"], 135_000_000 + 5_000_000 + 1_500)
        self.assertEqual(s["volume_bytes_unknown"], 1)                    # acme-import's N/A
        self.assertEqual((s["foreign_volumes"], s["foreign_volume_bytes"]), (4, 33_000_000 + 2_000_000_000 + 10 + 1_000_000))
        self.assertEqual(sorted(r["volume"] for r in s["at_risk"]), ["acme-import", "forgotten"])
        self.assertEqual(s["anonymous_volumes"], 1)

    def test_the_import_plan_never_counts_another_projects_volume(self):
        import plan as PLAN
        o = INV.inventory()
        man = {"artifacts": {"volumes/n8n_storage.tar.gz": {"kind": "volume", "bytes": 1}}}
        p = PLAN.build_plan(man, o)
        over = {r["volume"]: r for r in p["volumes"]["overwrite"]}
        self.assertEqual(over["n8n_storage"]["live_size"], "135MB")       # acme's, never the bare n8n_storage
        self.assertEqual(sorted(r["volume"] for r in p["volumes"]["target_only"]), ["acme-import", "data", "forgotten"])

    def test_the_plan_overwrites_only_the_volume_a_restore_writes(self):
        # a bare `n8n_storage` labelled by this project (a compose `name:`) is not what the restore writes,
        # `acme_n8n_storage` is (the second reader, v2)
        import plan as PLAN
        man = {"artifacts": {"volumes/n8n_storage.tar.gz": {"kind": "volume", "bytes": 1}}}
        bare = {"name": "n8n_storage", "short": "n8n_storage", "ours": True, "size": "10B", "bytes": 10}
        mine = {"name": "acme_n8n_storage", "short": "n8n_storage", "ours": True, "size": "135MB", "bytes": 135}
        for vols in ([mine, bare], [bare, mine]):
            p = PLAN.build_plan(man, {"project": "acme", "volumes": vols})
            self.assertEqual([r["live_size"] for r in p["volumes"]["overwrite"]], ["135MB"])
            self.assertEqual([r["volume"] for r in p["volumes"]["target_only"]], ["n8n_storage"])
        p = PLAN.build_plan(man, {"project": "acme", "volumes": [bare]})
        self.assertEqual([r["volume"] for r in p["volumes"]["create"]], ["n8n_storage"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
