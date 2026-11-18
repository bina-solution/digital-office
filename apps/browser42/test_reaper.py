import importlib.util
import json
import tempfile
import types
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


class DeadArtifactsTests(unittest.TestCase):
    def test_a_new_reaper_removes_what_a_dead_one_left_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as base, patch.object(MODULE.tempfile, "gettempdir", return_value=base):
            (Path(base) / "playwright-artifacts-dead1").mkdir()
            (Path(base) / "playwright-artifacts-dead2" / "x").mkdir(parents=True)
            (Path(base) / "other").mkdir()
            self.assertEqual(MODULE.remove_dead_artifacts(), 2)
            self.assertEqual(sorted(p.name for p in Path(base).iterdir()), ["other"])


class LiveTaskTests(unittest.TestCase):
    """Only a task being driven keeps the browser awake (DGO-1921)."""

    def live(self, *states):
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "TASKS_DIR", Path(tmp)):
            for i, state in enumerate(states):
                write_task(tmp, f"t{i}", {"slug": f"t{i}", "state": state})
            return MODULE.live_task_exists()

    def test_a_driven_task_holds_the_browser(self):
        for state in ("allocated", "active", "verifying"):
            self.assertTrue(self.live("finished", state), state)

    def test_a_verified_task_nobody_finished_does_not(self):
        """nf36-marketingweek sat in `accepted` from 2026-11-05 and the browser never slept again."""
        self.assertFalse(self.live("accepted", "finished", "stalled", "closed", "rejected"))


class SavedTabsTests(unittest.TestCase):
    """The tabs a sleep writes down (DGO-1336): a sign-in's state or one-time code never reaches the volume."""

    def test_a_sign_in_tab_is_saved_by_host_and_path_and_every_other_tab_whole(self):
        pages = [types.SimpleNamespace(url=u) for u in (
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=desktop:u.n",
            "https://claude.ai/login/popup-google-auth?code=4/abc&scope=email",
            "https://claude.com/cai/login/app-google-auth?open_in_browser=1&hop_nonce=n",
            "https://docs.example/guide?page=2", "about:blank", "https://docs.example/guide?page=2")]
        browser = types.SimpleNamespace(contexts=[types.SimpleNamespace(pages=pages)])
        with tempfile.TemporaryDirectory() as tmp, patch.object(MODULE, "LAST_TABS", Path(tmp) / "last-tabs.json"):
            self.assertEqual(MODULE.save_tabs(browser), 4)
            saved = json.loads((Path(tmp) / "last-tabs.json").read_text())["urls"]
        self.assertEqual(saved, ["https://accounts.google.com/o/oauth2/v2/auth", "https://claude.ai/login/popup-google-auth",
                                 "https://claude.com/cai/login/app-google-auth", "https://docs.example/guide?page=2"])
        self.assertNotRegex(json.dumps(saved), r"code=|state=|hop_nonce=")


class SurvivingTests(unittest.TestCase):
    """What failed on 2026-11-06 and cost three days (the office browser's own item).

    The reaper's driver grew into its container's ceiling and was killed; the python half then sat
    on a call that never returned, wrote no tab list, and every other playwright caller hung 30 s.
    These are the parts that make that impossible to repeat silently."""

    def test_an_empty_set_never_overwrites_the_saved_tabs(self):
        """A browser that has just started holds nothing but its own new tab. Writing that over the
        list is how six tab addresses were lost at 06:01:48 on 2026-11-09."""
        browser = types.SimpleNamespace(contexts=[types.SimpleNamespace(
            pages=[types.SimpleNamespace(url="chrome://newtab/"), types.SimpleNamespace(url="about:blank")])])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last-tabs.json"
            path.write_text(json.dumps({"saved_at": 1, "urls": ["https://example.com/kept"]}))
            with patch.object(MODULE, "LAST_TABS", path):
                self.assertEqual(MODULE.save_tabs(browser), 0)
            self.assertEqual(json.loads(path.read_text())["urls"], ["https://example.com/kept"])

    def test_a_tab_a_restore_could_not_open_stays_in_the_list(self):
        """A restore that fails on one address must not lose it: `goto` may time out with the tab
        open (kept, and counted) or with no tab at all (kept in the file for next time)."""
        opened = []

        class Context:
            def new_page(self):
                if len(opened) == 1:
                    raise RuntimeError("no tab for this one")
                page = types.SimpleNamespace(url="about:blank", goto=lambda u, **k: opened.append(u))
                return page

        browser = types.SimpleNamespace(contexts=[types.SimpleNamespace(pages=[], new_page=None)], pages=[])
        browser.contexts[0].new_page = Context().new_page
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last-tabs.json"
            path.write_text(json.dumps({"saved_at": 1, "urls": ["https://one.example/", "https://two.example/"]}))
            with patch.object(MODULE, "LAST_TABS", path):
                self.assertEqual(MODULE.restore_tabs(browser), 1)
            self.assertEqual(json.loads(path.read_text())["urls"], ["https://two.example/"])

    def test_the_watchdog_clock_is_armed_only_while_driver_work_runs(self):
        """A sweep in flight past SWEEP_TIMEOUT is a dead driver; the idle-sleep wait must never look
        like one (that wait is hours long and legitimate)."""
        MODULE._SWEEPING["since"] = 0.0
        seen = {}
        MODULE._under_deadline(lambda: seen.update(since=MODULE._SWEEPING["since"]))
        self.assertEqual(MODULE._SWEEPING["since"], 0.0)
        self.assertGreater(seen["since"], 0.0)


if __name__ == "__main__":
    unittest.main()
