"""test_tasks_batch.py — tasks.py `batch`: many verbs in one run against a FAKE Plane (no network).

    python3 apps/project-pln/test_tasks_batch.py

What is asked: the project's items are paged ONCE for the whole batch; two actions on the same item see
each other's writes (a second label does not drop the first); a comment action without text posts
nothing (never the `--as` slug); a line that is not an action is skipped and the rest still run; a file
that was never read (`@…`), a BOM, a ref with a newline are refused or handled; and a single verb run
after another in the same process still finds an item the first did not page.
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
SPEC = importlib.util.spec_from_file_location("tasks_batch_mod", os.path.join(HERE, "tasks.py"))
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)

STATE = {}


def reset():
    t._ISSUES.clear()
    STATE.clear()
    STATE.update(calls=[], pages=0,
                 labels=[{"id": "l_owner", "name": "בעלים"}, {"id": "l_seen", "name": "נותח"}, {"id": "l_x", "name": "x"}],
                 issue={"id": "i12", "sequence_id": 12, "name": "t", "state": "s_start", "label_ids": ["l_x"], "assignees": []})
    try:
        os.remove(os.environ["TASKS_CACHE"])
    except OSError:
        pass


def fake_page(self, path):
    if path == "/projects/":
        return [{"id": "p1", "identifier": "DGO", "name": "DGO"}]
    if path.endswith("/states/"):
        return [{"id": "s_start", "group": "started", "name": "Doing"}, {"id": "s_done", "group": "completed", "name": "Done"}]
    if path.endswith("/labels/"):
        return list(STATE["labels"])
    if path.endswith("/modules/"):
        return []
    if "/issues/?expand" in path:
        STATE["pages"] += 1
        return [json.loads(json.dumps(STATE["issue"]))]
    return []


def fake_call(self, method, path, body=None):
    STATE["calls"].append((method, path, body))
    if method == "PATCH" and path == "/projects/p1/issues/i12/" and body and "labels" in body:
        STATE["issue"]["label_ids"] = list(body["labels"])          # what Plane holds afterwards
    if method == "POST" and path.endswith("/labels/"):
        nid = "l_new%d" % len(STATE["labels"])
        STATE["labels"].append({"id": nid, "name": body["name"]})
        return {"id": nid}
    return {}


def fake_http(method, url, body=None, headers=None, tries=6):
    if "/issues/i12/" in url:
        return json.loads(json.dumps(STATE["issue"])), 200
    return {"error": "n/a"}, 404


t.Plane.page = fake_page
t.Plane.call = fake_call
t.http = fake_http


def batch(*lines):
    reset()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return t.main(["batch", "\n".join(lines)])
        except SystemExit as e:
            return e


def comments():
    return [b["comment_html"] for m, p, b in STATE["calls"] if m == "POST" and p.endswith("/comments/")]


class Batch(unittest.TestCase):
    def test_two_labels_on_one_item_keep_both(self):
        self.assertEqual(batch('{"verb":"label","ref":"DGO-12","words":["נותח"]}',
                               '{"verb":"label","ref":"DGO-12","words":["בעלים"]}'), 0)
        self.assertEqual(STATE["issue"]["label_ids"], ["l_x", "l_seen", "l_owner"])

    def test_label_then_unlabel_another(self):
        batch('{"verb":"label","ref":"DGO-12","words":["נותח"]}', '{"verb":"unlabel","ref":"DGO-12","words":["x"]}')
        self.assertEqual(STATE["issue"]["label_ids"], ["l_seen"])

    def test_a_comment_without_text_posts_nothing(self):
        self.assertEqual(batch('{"verb":"comment","ref":"DGO-12","text":"hello"}'), 1)
        self.assertEqual(comments(), [])

    def test_a_comment_from_words(self):
        batch('{"verb":"comment","ref":"DGO-12","words":["hello"]}')
        self.assertEqual(comments(), ["<p>hello</p>"])

    def test_a_line_that_is_not_an_action_is_skipped_and_the_rest_run(self):
        self.assertEqual(batch('{"verb":"start","ref":"DGO-12"}', '[{"verb":"done","ref":"DGO-12"}]',
                               'not json', '{"verb":"label","ref":"DGO-12","words":"נותח"}',
                               '{"verb":"done","ref":"DGO-12"}'), 1)
        states = [b.get("state") for m, p, b in STATE["calls"] if m == "PATCH" and b and "state" in b]
        self.assertEqual(states, ["s_start", "s_done"])

    def test_the_project_is_paged_once_for_the_whole_batch(self):
        batch('{"verb":"start","ref":"DGO-12"}', '{"verb":"comment","ref":"DGO-12","comment":"x"}',
              '{"verb":"done","ref":"DGO-12","comment":"y"}')
        self.assertEqual(STATE["pages"], 1)
        self.assertEqual(comments(), ["<p>x</p>", "<p>y</p>"])

    def test_an_unread_file_a_bom_and_a_ref_with_a_newline(self):
        self.assertIsInstance(batch("@actions.jsonl"), SystemExit)
        self.assertEqual(batch('﻿{"verb":"start","ref":"DGO-12"}'), 0)
        self.assertEqual(batch('{"verb":"start","ref":"DGO-12\\n"}'), 1)

    def test_a_later_run_in_the_same_process_finds_an_item_made_since(self):
        reset()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            t.main(["start", "DGO-12"])
            STATE["issue"]["sequence_id"] = 13
            self.assertEqual(t.main(["start", "DGO-13"]), 0)
        self.assertEqual(STATE["pages"], 2)


if __name__ == "__main__":
    unittest.main()
