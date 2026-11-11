"""test_tasks_module.py — `tasks show` and `tasks list` name the module an item is in (DGO-962), against a FAKE Plane.

    python3 apps/project-pln/test_tasks_module.py

Plane's item answers carry no module: neither the list endpoint nor the item's own read has `module_ids`, so
`tasks show DGO-1713` said `module: —` for an item in «דיווח». The module is read off each module's own list
(`modules/<id>/module-issues/`, the endpoint plan.py fills and reads). On the code before DGO-962 the first two fail.

And what the second reader asked of it, since a project has ~100 modules:
- a module Plane does not answer costs that module, never the verb;
- `show` stops at the module that holds its item, and a partial map is not cached;
- the text `list` (which prints no module) reads no module list at all;
- the map is cached under the module SET, and plan.py drops it after it places items.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(TASKS_CACHE=os.path.join(TMP, "cache.json"), PLANE_API_URL="http://127.0.0.1",
                  PLANE_LOCAL_API_TOKEN="fake", PLANE_WORKSPACE="bina")
SPEC = importlib.util.spec_from_file_location("tasks_module_mod", os.path.join(HERE, "tasks.py"))
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)

ITEM = {"id": "i12", "sequence_id": 12, "name": "the report", "state": "s_back", "label_ids": [], "assignees": [],
        "priority": "none"}
OTHER = {"id": "i13", "sequence_id": 13, "name": "loose", "state": "s_back", "label_ids": [], "assignees": [],
         "priority": "none"}
MODULES = [{"id": "m1", "name": "אחר"}, {"id": "m2", "name": "דיווח"}, {"id": "m3", "name": "שלישי"}]
MEMBERS = {"m1": ["i99"], "m2": ["i12"], "m3": ["i50"]}
STATE = {"calls": [], "refuse": set()}


def fake_page(self, path):
    STATE["calls"].append(path)
    if path == "/projects/":
        return [{"id": "p1", "identifier": "DGO", "name": "DGO"}]
    if path.endswith("/states/"):
        return [{"id": "s_back", "group": "backlog", "name": "מלאי"}]
    if path.endswith("/modules/"):
        return list(MODULES)
    if "/module-issues/" in path:
        raise AssertionError("a module's list is read through http(), not p.page (which exits on a refusal)")
    if "/issues/" in path:                                   # the list endpoint: no module_ids, as Plane answers
        return [dict(ITEM), dict(OTHER)]
    return []


def fake_http(method, url, body=None, headers=None, tries=6):
    STATE["calls"].append(url)
    if "/module-issues/" in url:
        mid = url.split("/modules/")[1].split("/")[0]
        if mid in STATE["refuse"]:
            return {"error": "x"}, 502
        return {"results": [{"id": "mi-" + i, "issue": i} for i in MEMBERS[mid]], "next_page_results": False}, 200
    if "/work-items/DGO-12/" in url or "/issues/i12/" in url:
        return dict(ITEM), 200                                # the item's own read: no module either
    return {"error": "n/a"}, 404


t.Plane.page = fake_page
t.Plane.call = lambda self, method, path, body=None: {}
t.http = fake_http


def run(*argv, keep_cache=False):
    if not keep_cache:
        try:
            os.remove(os.environ["TASKS_CACHE"])
        except OSError:
            pass
    t._ISSUES.clear()
    STATE["calls"].clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = t.main(list(argv)) or 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue()


def module_reads():
    return [c for c in STATE["calls"] if "/module-issues/" in c]


class Module(unittest.TestCase):
    def setUp(self):
        STATE["refuse"] = set()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_show_names_the_module_the_item_is_in(self):
        code, out = run("show", "DGO-12")
        self.assertEqual(code, 0, out)
        self.assertIn("module: דיווח", out)

    def test_list_json_names_each_items_module(self):
        code, out = run("list", "--project", "DGO", "--json")
        self.assertEqual(code, 0, out)
        rows = {r["ref"]: r["module"] for r in json.loads(out)["tasks"]}
        self.assertEqual(rows, {"DGO-12": "דיווח", "DGO-13": ""})

    def test_the_text_list_reads_no_module_list(self):
        for argv in (("list",), ("list", "--project", "DGO")):        # all projects (collect()) and one project
            code, out = run(*argv)
            self.assertEqual(code, 0, out)
            self.assertEqual(module_reads(), [], argv)

    def test_show_stops_at_the_module_that_holds_the_item_and_the_next_show_reads_nothing(self):
        run("show", "DGO-12")
        self.assertEqual(len(module_reads()), 2, module_reads())          # m1, then m2 holds it; m3 is not asked
        kept = t.cache_peek(t.members_key("p1", [m["id"] for m in MODULES]))
        self.assertEqual(kept["read"], ["m1", "m2"], kept)
        code, out = run("show", "DGO-12", keep_cache=True)
        self.assertIn("module: דיווח", out)
        self.assertEqual(module_reads(), [], "the second show read the modules again")

    def test_a_module_plane_does_not_answer_costs_that_module_not_the_verb(self):
        STATE["refuse"] = {"m1"}
        code, out = run("list", "--project", "DGO", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual({r["ref"]: r["module"] for r in json.loads(out)["tasks"]}["DGO-12"], "דיווח")
        kept = t.cache_peek(t.members_key("p1", [m["id"] for m in MODULES]))
        self.assertEqual(kept["read"], ["m2", "m3"], "the refused module must be asked again next time")
        STATE["refuse"] = set()
        run("list", "--project", "DGO", "--json", keep_cache=True)
        self.assertEqual([c.split("/modules/")[1].split("/")[0] for c in module_reads()], ["m1"], "only m1 is read again")
        STATE["refuse"] = {"m2"}
        code, out = run("show", "DGO-12")
        self.assertEqual(code, 0, out)
        self.assertIn("module: —", out)

    def test_a_complete_map_is_read_once_per_cache_window(self):
        run("list", "--project", "DGO", "--json")
        self.assertEqual(len(module_reads()), 3)
        code, out = run("show", "DGO-12", keep_cache=True)
        self.assertIn("module: דיווח", out)
        self.assertEqual(module_reads(), [])

    def test_plan_drops_the_map_after_it_places_items(self):
        run("list", "--project", "DGO", "--json")
        key = t.members_key("p1", [m["id"] for m in MODULES])
        self.assertIsNotNone(t.cache_peek(key))
        spec = importlib.util.spec_from_file_location("plan_forget_mod", os.path.join(HERE, "plan.py"))
        plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plan)
        plan.forget_module_members("p1")
        self.assertIsNone(t.cache_peek(key))
        self.assertIsNotNone(t.cache_peek("p1:modules"), "only the membership map is dropped")


if __name__ == "__main__":
    unittest.main()
