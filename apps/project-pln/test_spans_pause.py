"""test_spans_pause.py — the timeline feed (spans.py) pauses after a rebuild in proportion to how long the rebuild
took, so it cannot keep Plane busy (no network).

    python3 apps/project-pln/test_spans_pause.py

Why: one rebuild reads every item of every project through Plane's API. On the HP (2026-11-17) it took 231 s and the
next one started 30 s after it ended, so Plane served this feed ~88% of the time and every `tasks show` queued behind
it (DGO-1340). What is asked: the first call builds; a call inside the pause is served the snapshot and starts
nothing; the pause is REBUILD_SPACING times the last build's length, never under CACHE_SECONDS; a failed build pauses
the same way and keeps the previous snapshot; a build that raises pauses too and does not lock the next one out; a
first build that failed pauses before the next try; a caller that arrives while the first build runs starts no
second one; with no snapshot yet the answer is NotReady (503), never an empty list — the timeline takes its first
200 as its seed; a rebuild thread that cannot start does not lock the next one out; `since` still filters the
snapshot without a rebuild.
"""
import importlib.util
import os
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location("spans_under_test", os.path.join(HERE, "spans.py"))
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"PLANE_SPANS_CACHE": "30", "PLANE_SPANS_SPACING": "4"}):
        spec.loader.exec_module(mod)
    return mod


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class SpansPause(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.clock = Clock()
        self.builds = []
        self.result = [{"id": "a", "s": 1, "e": None}]
        self.cost = 200.0                       # seconds one build takes on the fake clock

        def build(since):
            self.builds.append(self.clock.now)
            self.clock.now += self.cost
            return self.result

        self.m.build = build
        p = mock.patch.object(self.m.time, "time", self.clock)
        p.start()
        self.addCleanup(p.stop)
        # the background rebuild runs inline, so each test reads one deterministic order
        t = mock.patch.object(self.m.threading, "Thread",
                              lambda target, daemon: mock.Mock(start=target))
        t.start()
        self.addCleanup(t.stop)

    def test_first_call_builds_and_serves(self):
        self.assertEqual(self.m.cached(None), self.result)
        self.assertEqual(len(self.builds), 1)

    def test_no_rebuild_inside_the_pause(self):
        self.m.cached(None)
        self.clock.now += 4 * self.cost - 1     # one second short of 4 × 200 s
        self.m.cached(None)
        self.assertEqual(len(self.builds), 1)
        self.clock.now += 1
        self.m.cached(None)
        self.assertEqual(len(self.builds), 2)

    def test_pause_never_under_cache_seconds(self):
        self.cost = 1.0                         # a fast office: 4 × 1 s < 30 s
        self.m.cached(None)
        self.clock.now += 29
        self.m.cached(None)
        self.assertEqual(len(self.builds), 1)
        self.clock.now += 1
        self.m.cached(None)
        self.assertEqual(len(self.builds), 2)

    def test_failed_build_pauses_and_keeps_snapshot(self):
        self.m.cached(None)
        self.clock.now += 4 * self.cost
        self.result = None                      # Plane could not be read
        self.assertEqual(self.m.cached(None), [{"id": "a", "s": 1, "e": None}])
        self.assertEqual(len(self.builds), 2)
        self.clock.now += 10                    # retrying at once is the same load
        self.m.cached(None)
        self.assertEqual(len(self.builds), 2)
        self.assertEqual(self.m._cache["spans"], [{"id": "a", "s": 1, "e": None}])

    def test_build_that_raises_pauses_and_does_not_freeze(self):
        self.m.cached(None)
        self.clock.now += 4 * self.cost

        def boom(since):
            self.builds.append(self.clock.now)
            self.clock.now += self.cost
            raise KeyError("id")

        self.m.build = boom
        self.assertEqual(self.m.cached(None), [{"id": "a", "s": 1, "e": None}])
        self.assertFalse(self.m._refreshing.is_set())   # the next rebuild is not locked out for good
        self.clock.now += 4 * self.cost
        self.m.cached(None)
        self.assertEqual(len(self.builds), 3)

    def test_failed_first_build_pauses(self):
        self.result = None                      # Plane unreadable from the first call after a restart
        with self.assertRaises(self.m.NotReady):    # 503, never an empty 200 the timeline would seed from
            self.m.cached(None)
        self.clock.now += 10
        with self.assertRaises(self.m.NotReady):
            self.m.cached(None)
        self.assertEqual(len(self.builds), 1)
        self.result = [{"id": "b", "s": 1, "e": None}]
        self.clock.now += 4 * self.cost
        self.assertEqual(self.m.cached(None), self.result)
        self.assertEqual(len(self.builds), 2)

    def test_one_first_build_however_many_pollers(self):
        inner = []

        def slow_first(since):
            self.builds.append(self.clock.now)
            try:                                # the timeline gave up and asked again mid-build
                inner.append(self.m.cached(None))
            except self.m.NotReady:
                inner.append("not ready")
            self.clock.now += self.cost
            return self.result

        self.m.build = slow_first
        self.assertEqual(self.m.cached(None), self.result)
        self.assertEqual(inner, ["not ready"])  # the second caller was answered, not built for
        self.assertEqual(len(self.builds), 1)
        self.assertFalse(self.m._refreshing.is_set())

    def test_rebuild_thread_that_cannot_start(self):
        self.m.cached(None)
        self.clock.now += 4 * self.cost

        def no_thread(target, daemon):
            raise RuntimeError("can't start new thread")

        with mock.patch.object(self.m.threading, "Thread", no_thread):
            self.assertEqual(self.m.cached(None), self.result)   # the snapshot, not a 500
        self.assertFalse(self.m._refreshing.is_set())            # and the next rebuild is not locked out
        self.m.cached(None)
        self.assertEqual(len(self.builds), 2)

    def test_since_filters_without_rebuild(self):
        self.result = [{"id": "old", "s": 5, "e": 6}, {"id": "new", "s": 50, "e": None}]
        self.m.cached(None)
        got = self.m.cached(40)
        self.assertEqual([s["id"] for s in got], ["new"])
        self.assertEqual(len(self.builds), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
