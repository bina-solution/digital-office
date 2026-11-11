"""test_tasks_item.py — tasks.py `new`, `edit`, `rm` (DGO-1252) against a FAKE Plane (no network).

    python3 apps/project-pln/test_tasks_item.py

What is asked:
- `new DGO "name"` posts one item with the name, the description and the priority given. The words are
  escaped (a `<` in a request is text, not markup), and `item new` is the same verb.
- `edit` keeps the old description on the item, as a comment, BEFORE it replaces it (the owner's words are
  the brief); with nothing to change it refuses.
- `rm` never deletes: without a reason it refuses; with one it moves the item to the cancelled state and
  posts the reason. A project with no cancelled state changes nothing.
- A bad priority is refused before anything is sent.

Measured on the live office (2026-11-10): DGO-1733 was made, edited and cancelled the same way.
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(TASKS_CACHE=os.path.join(TMP, "cache.json"), PLANE_API_URL="http://127.0.0.1",
                  PLANE_LOCAL_API_TOKEN="fake", PLANE_WORKSPACE="bina")
SPEC = importlib.util.spec_from_file_location("tasks_item_mod", os.path.join(HERE, "tasks.py"))
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)

STATE = {}


def reset(cancelled=True):
    t._ISSUES.clear()
    STATE.clear()
    states = [{"id": "s_back", "group": "backlog", "name": "מלאי"}, {"id": "s_start", "group": "started", "name": "בתהליך"}]
    if cancelled:
        states.append({"id": "s_cancel", "group": "cancelled", "name": "בוטל"})
    STATE.update(calls=[], states=states,
                 issue={"id": "i12", "sequence_id": 12, "name": "t", "state": "s_back", "label_ids": [], "assignees": [],
                        "description_html": "<p>the owner's words</p>"})
    try:
        os.remove(os.environ["TASKS_CACHE"])
    except OSError:
        pass


def fake_page(self, path):
    if path == "/projects/":
        return [{"id": "p1", "identifier": "DGO", "name": "DGO"}]
    if path.endswith("/states/"):
        return list(STATE["states"])
    return []


def fake_call(self, method, path, body=None):
    STATE["calls"].append((method, path, body))
    if method == "POST" and path == "/projects/p1/issues/":
        return {"id": "i99", "sequence_id": 99, "name": body["name"], "state": "s_back"}
    return {}


def fake_http(method, url, body=None, headers=None, tries=6):
    if "/issues/i12/" in url and "read" in STATE:          # the item's own read, as a test sets it
        return STATE["read"]
    if "/work-items/DGO-12/" in url or "/issues/i12/" in url:
        return json.loads(json.dumps(STATE["issue"])), 200
    return {"error": "n/a"}, 404


t.Plane.page = fake_page
t.Plane.call = fake_call
t.http = fake_http


def run(*argv, cancelled=True, read=None):
    reset(cancelled)
    if read is not None:
        STATE["read"] = read
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = t.main(list(argv)) or 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            out.write(str(e.code))
    return code, out.getvalue(), STATE["calls"]


class Item(unittest.TestCase):
    def test_new_posts_one_item_escaped(self):
        code, out, calls = run("new", "DGO", "a name", "--comment", "line 1 <b>\nline 2", "--priority", "high")
        self.assertEqual(code, 0, out)
        posts = [c for c in calls if c[0] == "POST" and c[1] == "/projects/p1/issues/"]
        self.assertEqual(len(posts), 1)
        body = posts[0][2]
        self.assertEqual(body["name"], "a name")
        self.assertEqual(body["priority"], "high")
        self.assertEqual(body["description_html"], "<p>line 1 &lt;b&gt;</p><p>line 2</p>")
        self.assertIn("DGO-99", out)

    def test_item_new_is_the_same_verb(self):
        code, out, calls = run("item", "new", "--project", "DGO", "named", "here")
        self.assertEqual(code, 0, out)
        self.assertEqual([c[2]["name"] for c in calls if c[1] == "/projects/p1/issues/"], ["named here"])

    def test_new_refuses_without_a_name_or_project(self):
        for argv in (["new", "DGO"], ["new"], ["new", "dgo", "x"]):
            code, _, calls = run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertFalse([c for c in calls if c[0] == "POST"], argv)

    def test_edit_keeps_the_old_description_first(self):
        code, out, calls = run("edit", "DGO-12", "--name", "new name", "--comment", "new words")
        self.assertEqual(code, 0, out)
        writes = [(m, p) for m, p, _ in calls if m in ("POST", "PATCH")]
        self.assertEqual(writes[0], ("POST", "/projects/p1/issues/i12/comments/"), writes)
        self.assertIn("the owner's words", calls[[c[1] for c in calls].index("/projects/p1/issues/i12/comments/")][2]["comment_html"])
        patch = [b for m, p, b in calls if m == "PATCH"][0]
        self.assertEqual(patch["name"], "new name")
        self.assertEqual(patch["description_html"], "<p>new words</p>")

    def test_edit_with_nothing_refuses(self):
        code, _, calls = run("edit", "DGO-12")
        self.assertNotEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] in ("POST", "PATCH")])

    def test_rm_needs_a_reason_and_never_deletes(self):
        code, _, calls = run("rm", "DGO-12")
        self.assertNotEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] != "GET"])
        code, out, calls = run("rm", "DGO-12", "--comment", "a duplicate of DGO-1")
        self.assertEqual(code, 0, out)
        self.assertFalse([c for c in calls if c[0] == "DELETE"])
        self.assertIn(("PATCH", "/projects/p1/issues/i12/", {"state": "s_cancel"}), calls)
        self.assertTrue([c for c in calls if c[1].endswith("/comments/") and "duplicate" in c[2]["comment_html"]])

    def test_rm_without_a_cancelled_state_changes_nothing(self):
        code, _, calls = run("rm", "DGO-12", "--comment", "why", cancelled=False)
        self.assertNotEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] in ("POST", "PATCH")])

    def test_bad_priority_is_refused_before_anything(self):
        code, _, calls = run("new", "DGO", "x", "--priority", "soon")
        self.assertNotEqual(code, 0)
        self.assertFalse(calls)

    # ── the second reader's cases (DGO-1252) ──
    def test_edit_refuses_when_the_old_words_cannot_be_kept(self):
        for read in (({"error": "busy"}, 503), ({}, 200), ({"description_stripped": "x"}, 200)):
            code, _, calls = run("edit", "DGO-12", "--comment", "new", read=read)
            self.assertNotEqual(code, 0, read)
            self.assertFalse([c for c in calls if c[0] in ("POST", "PATCH")], read)

    def test_edit_keeps_an_image_only_description(self):
        img = '<p><img src="x.png"></p>'
        code, out, calls = run("edit", "DGO-12", "--comment", "new", read=({"id": "i12", "description_html": img}, 200))
        self.assertEqual(code, 0, out)
        self.assertTrue([c for c in calls if c[1].endswith("/comments/") and img in c[2]["comment_html"]])

    def test_rm_posts_the_reason_before_it_cancels(self):
        code, out, calls = run("rm", "DGO-12", "--comment", "why")
        self.assertEqual(code, 0, out)
        writes = [(m, p) for m, p, _ in calls if m in ("POST", "PATCH")]
        self.assertEqual(writes, [("POST", "/projects/p1/issues/i12/comments/"), ("PATCH", "/projects/p1/issues/i12/")])

    def test_stray_words_and_foreign_flags_are_refused(self):
        for argv in (["edit", "DGO-12", "--priority", "low", "a name"],      # a name without --name
                     ["rm", "DGO-12", "--comment", "why", "extra"],
                     ["start", "DGO-12", "--priority", "high"],               # a flag of another verb
                     ["comment", "DGO-12", "--name", "x"],
                     ["new", "DGO", "a", "--name", "b"],                      # the name twice
                     ["edit", "DGO-12", "--project", "EXF", "--name", "x"]):  # the ref names another project
            code, _, calls = run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertFalse([c for c in calls if c[0] in ("POST", "PATCH")], argv)

    def test_new_with_the_project_said_twice(self):
        code, out, calls = run("new", "DGO", "the name", "--project", "DGO")
        self.assertEqual(code, 0, out)
        self.assertEqual([c[2]["name"] for c in calls if c[1] == "/projects/p1/issues/"], ["the name"])

    def test_rm_in_a_batch(self):
        line = json.dumps({"verb": "rm", "ref": "DGO-12", "comment": "a duplicate"})
        code, out, calls = run("batch", line)
        self.assertEqual(code, 0, out)
        self.assertIn(("PATCH", "/projects/p1/issues/i12/", {"state": "s_cancel"}), calls)
        code, out, calls = run("batch", json.dumps({"verb": "rm", "ref": "DGO-12"}))
        self.assertNotEqual(code, 0)
        self.assertFalse([c for c in calls if c[0] == "PATCH"])


if __name__ == "__main__":
    unittest.main()
