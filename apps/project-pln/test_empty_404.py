"""test_empty_404.py — the Plane clients that cross a linked office's door (tasks.py, plan.py) ask a READ again when a
404 comes back with NO body, and only then (no network).

    python3 apps/project-pln/test_empty_404.py

Why: Plane says what it did not find, in JSON; an empty 404 is the door of the office that runs Plane, whose route
table did not hold Plane for a moment (`X-Dgo-Door: no-app`, tasks.py EMPTY_404_TRIES). One of them used to end
`tasks show` and `tasks batch` for every session. What is asked: an empty 404 on a GET is asked again, over the
door's refresh period, and the answer that follows is returned; Plane's own 404 (a body) is returned at once; a write
is never sent twice; the tries end, and then tasks.py stops waiting for the rest of the process and names the door's
reason; a connection failure after an empty 404 still gets its second try; plan.py retries a 5xx without reading
its body.
"""
import email.message
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
ENV = dict(TASKS_CACHE=os.path.join(TMP, "cache.json"), PLANE_API_URL="http://127.0.0.1",
           PLANE_LOCAL_API_TOKEN="fake", PLANE_WORKSPACE="bina")


def load(name):
    with mock.patch.dict(os.environ, ENV):
        spec = importlib.util.spec_from_file_location(f"{name}_empty404", os.path.join(HERE, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


TASKS, PLAN = load("tasks"), load("plan")


class Answer:
    def __init__(self, doc):
        self.raw, self.status = json.dumps(doc).encode(), 200

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CutShort(io.BytesIO):
    def read(self, *a):
        raise ConnectionResetError("the body was cut short")


def scripted(*answers):
    """urlopen that gives the answers in order (the last one again when they run out):
    an int is an HTTP error with an empty body; ("door", reason) an empty 404 carrying X-Dgo-Door; (code, bytes) an
    error with that body; (code, "cut") an error whose body cannot be read; "lost" a refused connection; a dict a 200."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.get_method())
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, dict):
            return Answer(a)
        if a == "lost":
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        hdrs = email.message.Message()
        if isinstance(a, int):
            code, fp = a, io.BytesIO(b"")
        elif a[0] == "door":
            code, fp = 404, io.BytesIO(b"")
            hdrs["X-Dgo-Door"] = a[1]
        elif a[1] == "cut":
            code, fp = a[0], CutShort()
        else:
            code, fp = a[0], io.BytesIO(a[1])
        raise urllib.error.HTTPError(req.full_url, code, "error", hdrs, fp)
    return urlopen, calls


class EmptyNotFound(unittest.TestCase):
    MODS = (TASKS, PLAN)

    def setUp(self):
        self.waits = []
        self.patches = [mock.patch.object(m.time, "sleep", side_effect=self.waits.append) for m in self.MODS]
        for p in self.patches:
            p.start()
        for m in self.MODS:
            m.DOWN = ""
        TASKS.NO_APP = ""

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_with(self, mod, method, *answers):
        self.waits.clear()
        fake, calls = scripted(*answers)
        with mock.patch.object(urllib.request, "urlopen", fake):
            out, code = mod.http(method, "http://127.0.0.1/api/v1/x/", body={"a": 1} if method != "GET" else None)
        return out, code, calls

    def test_an_empty_404_on_a_read_is_asked_again_and_the_answer_returned(self):
        for m in self.MODS:
            out, code, calls = self.run_with(m, "GET", 404, 404, {"results": [1]})
            self.assertEqual((code, out), (200, {"results": [1]}), m.__name__)
            self.assertEqual(len(calls), 3, m.__name__)
            self.assertEqual(self.waits, [5, 10], m.__name__)

    def test_planes_own_404_is_returned_at_once(self):
        for m in self.MODS:
            out, code, calls = self.run_with(m, "GET", (404, b'{"error": "Issue not found"}'), {"results": []})
            self.assertEqual(code, 404, m.__name__)
            self.assertIn("not found", out["error"], m.__name__)
            self.assertEqual((len(calls), self.waits), (1, []), m.__name__)

    def test_a_write_is_never_sent_twice(self):
        for m in self.MODS:
            out, code, calls = self.run_with(m, "POST", 404, {"id": "made"})
            self.assertEqual(code, 404, m.__name__)
            self.assertEqual(calls, ["POST"], m.__name__)

    def test_the_tries_end_over_the_doors_refresh_and_name_its_reason(self):
        for m, n in ((TASKS, TASKS.EMPTY_404_TRIES), (PLAN, 6)):
            TASKS.NO_APP = ""
            out, code, calls = self.run_with(m, "GET", ("door", "no-app"))
            self.assertEqual((code, len(calls)), (404, n), m.__name__)
            self.assertGreaterEqual(sum(self.waits), 30, m.__name__)     # the door reads its table every 30 s
        self.assertIn("X-Dgo-Door: no-app", self.run_with(TASKS, "GET", ("door", "no-app"))[0]["error"])

    def test_after_one_read_used_up_its_tries_the_rest_do_not_wait(self):
        self.run_with(TASKS, "GET", 404)
        out, code, calls = self.run_with(TASKS, "GET", 404, {"results": []})
        self.assertEqual((code, len(calls), self.waits), (404, 1, []))
        out, code, calls = self.run_with(TASKS, "GET", {"results": [2]})       # the door is still asked
        self.assertEqual((code, out), (200, {"results": [2]}))

    def test_a_refused_connection_after_an_empty_404_still_gets_its_second_try(self):
        for m in self.MODS:
            out, code, calls = self.run_with(m, "GET", 404, "lost", {"results": [3]})
            self.assertEqual((code, len(calls)), (200, 3), m.__name__)
            self.assertEqual(m.DOWN, "", m.__name__)

    def test_plan_retries_a_5xx_without_reading_its_body(self):
        out, code, calls = self.run_with(PLAN, "GET", (502, "cut"), {"results": [4]})
        self.assertEqual((code, len(calls)), (200, 2))

    def test_a_502_on_a_read_is_asked_again_and_a_write_is_not(self):
        for m in self.MODS:
            out, code, calls = self.run_with(m, "GET", 502, (503, "cut"), {"results": [5]})
            self.assertEqual((code, out, len(calls)), (200, {"results": [5]}, 3), m.__name__)
            out, code, calls = self.run_with(m, "PATCH", 502, {"id": "x"})
            self.assertEqual((code, calls), (502, ["PATCH"]), m.__name__)

    def test_a_502_that_does_not_end_ends_the_waiting_too(self):
        out, code, calls = self.run_with(TASKS, "GET", 502)
        self.assertEqual((code, len(calls), TASKS.NO_APP), (502, TASKS.EMPTY_404_TRIES, "HTTP 502"))
        out, code, calls = self.run_with(TASKS, "GET", 502, {"results": []})
        self.assertEqual((code, len(calls)), (502, 1))


if __name__ == "__main__":
    unittest.main()
