import importlib.util
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PATH = Path(__file__).with_name("task-runner.py")
SPEC = importlib.util.spec_from_file_location("browser42_task_runner", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        MODULE.STATE = MODULE.RunnerState(MODULE.MAX_CONCURRENT)

    def test_accepts_declared_task_commands(self):
        self.assertEqual(
            MODULE.validate_arguments(["start", "task-1", "https://example.com", "3"]),
            ["start", "task-1", "https://example.com", "3"],
        )
        self.assertEqual(MODULE.validate_arguments(["inspect", "task-1"]), ["inspect", "task-1"])
        self.assertEqual(MODULE.validate_arguments(["goal", "task-1", "https://example.com", "ai"]),
                         ["goal", "task-1", "https://example.com", "ai"])

    def test_rejects_shell_like_or_malformed_requests(self):
        for arguments in ([], ["shell", "whoami"], ["start", "task-1"], ["status", ""], "status task-1", ["goal", "only-slug"]):
            with self.assertRaises(ValueError):
                MODULE.validate_arguments(arguments)

    def test_rejects_unknown_command(self):
        with self.assertRaises(ValueError):
            MODULE.validate_arguments(["rm", "-rf", "/"])

    def test_rebuilds_response_includes_request_id(self):
        status, payload = MODULE.build_response({"argv": ["status", "test"]})
        self.assertEqual(status, 200)
        self.assertIn("requestId", payload)
        self.assertEqual(len(payload["requestId"]), 32)

    def test_returns_passed_request_id(self):
        status, payload = MODULE.build_response({"argv": ["status", "test"], "requestId": "wave1-ai"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["requestId"], "wave1-ai")

    def test_rejects_invalid_json_argv(self):
        status, payload = MODULE.build_response({"argv": []})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_rejects_unknown_command_in_response(self):
        status, payload = MODULE.build_response({"argv": ["destroy", "x"]})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_slot_queue_acquire_and_release(self):
        MODULE.STATE = MODULE.RunnerState(max_concurrent=1)
        acquired, depth = MODULE.STATE.acquire("r1", 0)
        self.assertTrue(acquired)
        self.assertEqual(MODULE.STATE.snapshot()["active"], 1)
        # Second acquire with zero wait fails immediately but reports cleanly.
        acquired, _ = MODULE.STATE.acquire("r2", 0)
        self.assertFalse(acquired)
        MODULE.STATE.release("r1")
        self.assertEqual(MODULE.STATE.snapshot()["active"], 0)

    def test_work_command_queues_until_slot_frees(self):
        MODULE.STATE = MODULE.RunnerState(max_concurrent=1)
        self.assertTrue(MODULE.STATE.acquire("hold", 0)[0])

        def free_later():
            import time
            time.sleep(0.2)
            MODULE.STATE.release("hold")

        thread = threading.Thread(target=free_later, daemon=True)
        thread.start()
        # The work command waits for the slot instead of failing instantly.
        status, payload = MODULE.build_response({"argv": ["inspect", "x"], "requestId": "q1"})
        thread.join(timeout=5)
        self.assertEqual(status, 200)  # protocol-error payload is fine; the slot queue worked
        self.assertEqual(payload["requestId"], "q1")
        self.assertEqual(MODULE.STATE.snapshot()["active"], 0)

    def test_work_command_busy_when_queue_wait_exhausted(self):
        MODULE.STATE = MODULE.RunnerState(max_concurrent=1)
        self.assertTrue(MODULE.STATE.acquire("hold", 0)[0])
        with patch.object(MODULE, "QUEUE_WAIT_SECONDS", 0.05):
            status, payload = MODULE.build_response({"argv": ["inspect", "x"], "requestId": "q2"})
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["code"], "runner_busy")
        MODULE.STATE.release("hold")

    def test_read_commands_bypass_slots_entirely(self):
        MODULE.STATE = MODULE.RunnerState(max_concurrent=1)
        self.assertTrue(MODULE.STATE.acquire("hold", 0)[0])
        # Monitoring reads must never contend with owning agents.
        status, payload = MODULE.build_response({"argv": ["status", "x"], "requestId": "mon1"})
        self.assertEqual(status, 200)
        self.assertEqual(MODULE.STATE.snapshot()["active"], 1)  # only "hold"
        MODULE.STATE.release("hold")

    def test_health_returns_state(self):
        health = MODULE.build_health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "browser42-task-runner")
        self.assertIn("maxConcurrent", health)
        self.assertIn("active", health)
        self.assertIn("queueWaitSeconds", health)


if __name__ == "__main__":
    unittest.main()