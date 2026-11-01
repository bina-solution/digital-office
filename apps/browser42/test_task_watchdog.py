import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("task-watchdog.py")
SPEC = importlib.util.spec_from_file_location("browser42_task_watchdog", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_task(directory: str, slug: str, task: dict) -> Path:
    path = Path(directory) / slug / "task.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task))
    return path


class TaskWatchdogTests(unittest.TestCase):
    def setUp(self):
        self._spans = MODULE.SPANS_ENABLED
        MODULE.SPANS_ENABLED = False  # unit tests never touch the network (same as test_task_runner.py)

    def tearDown(self):
        MODULE.SPANS_ENABLED = self._spans

    def test_stale_active_task_gets_stall_timeout(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "slow", {"slug": "slow", "state": "active", "stage": "inspecting", "created_at": 0, "heartbeat_at": 10, "first_activity_at": 10})
            self.assertEqual(MODULE.sweep(current=10 + MODULE.STALL_SECONDS + 1), ["slow"])
            task = json.loads(path.read_text())
            self.assertEqual(task["state"], "stalled")
            self.assertEqual(task["failure"]["code"], "stall_timeout")

    def test_recent_stage_reentry_counts_as_activity(self):
        # Regression for incident 20260804-sub2: a task whose stage was entered long ago
        # but which keeps heartbeating / transitioning must NEVER be killed by a stage clock.
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            write_task(directory, "busy", {
                "slug": "busy", "state": "active", "stage": "inspecting",
                "created_at": 0, "heartbeat_at": 100,
                "first_activity_at": 10,
                "stage_timings": {"inspecting": {"entered_at": 100}},
            })
            self.assertEqual(MODULE.sweep(current=100 + MODULE.STALL_SECONDS - 1), [])

    def test_sweep_preserves_accepted_task(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "done", {"slug": "done", "state": "accepted", "heartbeat_at": 0})
            self.assertEqual(MODULE.sweep(current=999), [])
            self.assertEqual(json.loads(path.read_text())["state"], "accepted")

    def test_allocated_task_stalls_after_inactivity_budget(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "queued", {"slug": "queued", "state": "allocated", "stage": "allocated", "created_at": 100, "heartbeat_at": 100})
            # Inside the inactivity budget nothing happens...
            self.assertEqual(MODULE.sweep(current=100 + MODULE.ALLOCATED_STALL_SECONDS - 1), [])
            # ...but a silent queue (nothing heartbeats queued tasks) is stalled on the
            # short budget, not after the 30-minute total (0805c: 19 min of silence).
            self.assertEqual(MODULE.sweep(current=100 + MODULE.ALLOCATED_STALL_SECONDS + 1), ["queued"])
            self.assertEqual(json.loads(path.read_text())["failure"]["code"], "queue_timeout")

    def test_allocated_task_survives_while_heartbeating(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "busy", {"slug": "busy", "state": "allocated", "stage": "allocated", "created_at": 100, "heartbeat_at": 100 + MODULE.ALLOCATED_STALL_SECONDS + 50})
            self.assertEqual(MODULE.sweep(current=100 + MODULE.ALLOCATED_STALL_SECONDS + 60), [])
            self.assertEqual(json.loads(path.read_text())["state"], "allocated")

    def test_total_budget_runs_from_first_activity(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "long", {
                "slug": "long", "state": "active", "stage": "extracting",
                "created_at": 0, "heartbeat_at": MODULE.TOTAL_SECONDS + 50,
                "first_activity_at": 50,
            })
            current = 50 + MODULE.TOTAL_SECONDS + 1
            self.assertEqual(MODULE.sweep(current=current), ["long"])
            self.assertEqual(json.loads(path.read_text())["failure"]["code"], "task_timeout")

    def test_legacy_task_without_first_activity_anchors_on_created(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            write_task(directory, "legacy", {"slug": "legacy", "state": "active", "stage": "inspecting", "created_at": 100, "heartbeat_at": 100})
            # Inside both budgets -> survives, and no KeyError from the missing field.
            self.assertEqual(MODULE.sweep(current=150), [])

    def test_stall_closes_tab_group_and_span(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "slow", {"slug": "slow", "state": "active", "stage": "inspecting", "created_at": 10, "heartbeat_at": 10, "first_activity_at": 10})
            closed = []
            spans = []
            with patch.object(MODULE, "broker_command", side_effect=lambda command: closed.append(command) or {"ok": True, "closed": 1}), \
                    patch.object(MODULE, "span_close_tab", side_effect=lambda slug, opened_at, status: spans.append((slug, opened_at, status))):
                stalled = MODULE.sweep(current=10 + MODULE.STALL_SECONDS + 1)
            self.assertEqual(stalled, ["slow"])
            self.assertEqual(closed, [{"action": "close", "slug": "slow"}])
            self.assertEqual(spans, [("slow", 10, "error")])

    def test_stall_broker_failure_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            path = write_task(directory, "slow", {"slug": "slow", "state": "active", "stage": "inspecting", "created_at": 10, "heartbeat_at": 10, "first_activity_at": 10})
            with patch.object(MODULE, "broker_command", side_effect=RuntimeError("broker down")), \
                    patch.object(MODULE, "span_close_tab"):
                stalled = MODULE.sweep(current=10 + MODULE.STALL_SECONDS + 1)
            self.assertEqual(stalled, ["slow"])
            self.assertEqual(json.loads(path.read_text())["state"], "stalled")

    def _sweep_with_spans(self, task_payload: dict, current: int, spans_enabled: bool = True):
        """Run one sweep with urllib.request.urlopen mocked; returns (stalled, span POSTs)."""
        posts = []

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            posts.append({"url": request.full_url, "timeout": timeout, "body": json.loads(request.data.decode("utf-8"))})
            return _FakeResponse()

        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "TASKS", Path(directory)):
            write_task(directory, task_payload["slug"], task_payload)
            with patch.object(MODULE, "urlopen", side_effect=fake_urlopen), \
                    patch.object(MODULE, "broker_command", return_value={"ok": True}), \
                    patch.object(MODULE, "SPANS_ENABLED", spans_enabled):
                stalled = MODULE.sweep(current=current)
        watchdog_posts = [post for post in posts if post["body"]["id"].startswith("b42:watchdog:")]
        return stalled, watchdog_posts

    def _assert_stale_span(self, post, slug, reason, current, meta):
        self.assertEqual(post["url"], MODULE.SPANS_URL)
        self.assertEqual(post["timeout"], 1.5)
        body = post["body"]
        self.assertEqual(body["id"], f"b42:watchdog:{slug}:{reason}:{int(current)}")
        self.assertEqual(body["src"], "browser42")
        self.assertEqual(body["svc"], "watchdog")
        self.assertEqual(body["svcid"], slug)
        self.assertEqual(body["label"], f"stall:{reason}")
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["s"], int(current) * 1000)
        self.assertEqual(body["e"], int(current) * 1000)
        self.assertEqual(body["d"], 0)
        self.assertEqual(body["meta"], meta)

    def test_stale_stall_timeout_posts_span(self):
        current = 10 + MODULE.STALL_SECONDS + 1
        stalled, posts = self._sweep_with_spans(
            {"slug": "slow", "state": "active", "stage": "inspecting", "created_at": 10, "heartbeat_at": 10, "first_activity_at": 10},
            current)
        self.assertEqual(stalled, ["slow"])
        self.assertEqual(len(posts), 1)
        self._assert_stale_span(posts[0], "slow", "stall_timeout", current,
                                {"slug": "slow", "reason": "stall_timeout", "stage": "inspecting",
                                 "created_at": 10, "first_activity_at": 10, "last_activity_at": 10})

    def test_stale_queue_timeout_posts_span(self):
        current = 100 + MODULE.TOTAL_SECONDS + 1
        stalled, posts = self._sweep_with_spans(
            {"slug": "queued", "state": "allocated", "stage": "allocated", "created_at": 100, "heartbeat_at": 100},
            current)
        self.assertEqual(stalled, ["queued"])
        self.assertEqual(len(posts), 1)
        self._assert_stale_span(posts[0], "queued", "queue_timeout", current,
                                {"slug": "queued", "reason": "queue_timeout", "stage": "allocated",
                                 "created_at": 100, "first_activity_at": 0, "last_activity_at": 100})

    def test_stale_task_timeout_posts_span(self):
        current = 50 + MODULE.TOTAL_SECONDS + 1
        stalled, posts = self._sweep_with_spans(
            {"slug": "long", "state": "active", "stage": "extracting", "created_at": 0,
             "heartbeat_at": MODULE.TOTAL_SECONDS + 50, "first_activity_at": 50},
            current)
        self.assertEqual(stalled, ["long"])
        self.assertEqual(len(posts), 1)
        self._assert_stale_span(posts[0], "long", "task_timeout", current,
                                {"slug": "long", "reason": "task_timeout", "stage": "extracting",
                                 "created_at": 0, "first_activity_at": 50,
                                 "last_activity_at": MODULE.TOTAL_SECONDS + 50})

    def test_no_span_post_when_spans_disabled(self):
        current = 10 + MODULE.STALL_SECONDS + 1
        stalled, posts = self._sweep_with_spans(
            {"slug": "slow", "state": "active", "stage": "inspecting", "created_at": 10, "heartbeat_at": 10, "first_activity_at": 10},
            current, spans_enabled=False)
        self.assertEqual(stalled, ["slow"])
        self.assertEqual(posts, [])


if __name__ == "__main__":
    unittest.main()