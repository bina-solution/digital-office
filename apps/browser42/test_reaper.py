import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("reaper.py")
SPEC = importlib.util.spec_from_file_location("browser42_reaper", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_task(directory: str, slug: str, task: dict) -> Path:
    path = Path(directory) / slug / "task.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task))
    return path


class ReaperLaneReconciliationTests(unittest.TestCase):
    """R-lane: a task that dies before finish must not leave its any-concurrency
    tab lane open forever. The reaper closes lanes for terminal (or zombie-allocated)
    tasks that have no live tagged tab."""

    def setUp(self):
        self._spans = MODULE.SPANS_ENABLED
        self._closed = set(MODULE.LANE_CLOSED)
        MODULE.SPANS_ENABLED = True
        MODULE.LANE_CLOSED.clear()

    def tearDown(self):
        MODULE.SPANS_ENABLED = self._spans
        MODULE.LANE_CLOSED.clear()
        MODULE.LANE_CLOSED.update(self._closed)

    def reconcile(self, directory, live, closed, now=1_000_000):
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "TASKS_DIR", Path(tmp)), \
                patch.object(MODULE, "span_close_tab", closed):
            for slug, task in directory.items():
                write_task(tmp, slug, task)
            MODULE.reconcile_lanes(set(live), now=now)

    def test_terminal_task_without_live_tab_closes_lane(self):
        closed = []
        now = 1_000_000
        self.reconcile({"old": {"slug": "old", "state": "finished", "created_at": now - 5000}}, [],
                       lambda slug, opened_at, status: closed.append((slug, status)))
        self.assertEqual(closed, [("old", "reaped")])
        self.assertIn("old", MODULE.LANE_CLOSED)

    def test_live_tagged_tab_spares_lane(self):
        closed = []
        now = 1_000_000
        self.reconcile({"live": {"slug": "live", "state": "active", "created_at": now - 10}}, ["live"],
                       lambda slug, opened_at, status: closed.append(slug))
        self.assertEqual(closed, [])

    def test_allocated_zombie_closes_lane_after_timeout(self):
        closed = []
        now = 1_000_000
        self.reconcile({"zombie": {"slug": "zombie", "state": "allocated", "created_at": now - MODULE.ALLOC_LANE_TIMEOUT - 1}}, [],
                       lambda slug, opened_at, status: closed.append(slug))
        self.assertEqual(closed, ["zombie"])

    def test_allocated_recent_task_spares_lane(self):
        closed = []
        now = 1_000_000
        self.reconcile({"queued": {"slug": "queued", "state": "allocated", "created_at": now - 5}}, [],
                       lambda slug, opened_at, status: closed.append(slug))
        self.assertEqual(closed, [])

    def test_active_task_without_tagged_tab_still_spares_lane(self):
        # An actively-working task may momentarily have no tagged tab (between
        # allocate and claim); only terminal states and zombie-allocated are closed.
        closed = []
        now = 1_000_000
        self.reconcile({"busy": {"slug": "busy", "state": "active", "created_at": now - 60}}, [],
                       lambda slug, opened_at, status: closed.append(slug))
        self.assertEqual(closed, [])

    def test_unknown_slug_spares_lane(self):
        closed = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "TASKS_DIR", Path(tmp)), \
                patch.object(MODULE, "span_close_tab", lambda *a: closed.append(a)):
            MODULE.reconcile_lanes(set())
        self.assertEqual(closed, [])

    def test_lane_closed_once_per_process(self):
        closed = []
        now = 1_000_000
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "TASKS_DIR", Path(tmp)), \
                patch.object(MODULE, "span_close_tab", lambda slug, opened_at, status: closed.append(slug)):
            write_task(tmp, "done", {"slug": "done", "state": "finished", "created_at": now - 9000})
            MODULE.reconcile_lanes(set())
            MODULE.reconcile_lanes(set())
        self.assertEqual(closed, ["done"])


if __name__ == "__main__":
    unittest.main()
