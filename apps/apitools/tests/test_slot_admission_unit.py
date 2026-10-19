"""Admission control must never let a request sleep in a gunicorn worker it doesn't need.

Two live incidents, same shape, both on 2026-08-06/07:

  1. Unbounded waiting inside `_expensive_request_slot` let /documentOcr occupy 5 of 6 sync
     workers (4 computing, >=1 asleep). /docExists — 0.2 % of worker-seconds, 33 ms p50 —
     stopped being accepted at all and n8n aborted it 375 times at its 15 s node timeout.
  2. The first fix added a SECOND gate counting REQUESTS in front of a pool counting WEIGHT.
     Four weight-2 requests took all four budget tokens but only two could hold slots; the
     other two camped for the full 600 s slot wait holding a token, and everything behind them
     was shed in ~1 ms. 4 385 429s vs 694 successes; 1.2 real OCRs/min on a half-idle server.

The resolution was to delete the second gate and remove the waiting: the weighted slot pool
already bounds worker occupancy, because a running request holds at least one weight unit.
These tests pin the properties that make that true.
"""
import os
import tempfile
import threading
import time
import unittest

from src.api.ocr_api import _expensive_request_slot


class TestSlotAdmission(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("APITOOLS_CONCURRENCY_LOCK_DIR")
        os.environ["APITOOLS_CONCURRENCY_LOCK_DIR"] = self._tmp.name

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("APITOOLS_CONCURRENCY_LOCK_DIR", None)
        else:
            os.environ["APITOOLS_CONCURRENCY_LOCK_DIR"] = self._prev
        self._tmp.cleanup()

    def test_zero_wait_makes_exactly_one_attempt(self):
        # THE regression guard. wait_timeout=0 must shed immediately, not camp — a token or
        # slot held across a long wait is what took the endpoint down twice.
        with _expensive_request_slot("t_zero", 1, weight=1) as first:
            self.assertTrue(first)
            t0 = time.monotonic()
            with _expensive_request_slot("t_zero", 1, weight=1, wait_timeout=0) as second:
                self.assertFalse(second)
            self.assertLess(time.monotonic() - t0, 0.5, "wait_timeout=0 must not block")

    def test_zero_wait_still_admits_when_free(self):
        with _expensive_request_slot("t_free", 2, weight=1, wait_timeout=0) as got:
            self.assertTrue(got)

    def test_explicit_wait_is_honoured_and_bounded(self):
        with _expensive_request_slot("t_bounded", 1, weight=1):
            t0 = time.monotonic()
            with _expensive_request_slot("t_bounded", 1, weight=1, wait_timeout=1.0) as second:
                self.assertFalse(second)
            elapsed = time.monotonic() - t0
            self.assertGreaterEqual(elapsed, 0.9)
            self.assertLess(elapsed, 3.0)

    def test_running_requests_cannot_exceed_the_pool(self):
        # The worker-occupancy guarantee, stated as the invariant it actually is: every
        # admitted request holds >=1 weight unit, so at most max_slots can be running, so
        # GUNICORN_WORKERS - max_slots workers are always free for the cheap endpoints.
        held = []
        for _ in range(3):
            cm = _expensive_request_slot("t_cap", 3, weight=1, wait_timeout=0)
            self.assertTrue(cm.__enter__())
            held.append(cm)
        with _expensive_request_slot("t_cap", 3, weight=1, wait_timeout=0) as overflow:
            self.assertFalse(overflow, "a 4th request must not be admitted to a 3-slot pool")
        for cm in held:
            cm.__exit__(None, None, None)

    def test_weight_is_all_or_nothing(self):
        with _expensive_request_slot("t_weight", 4, weight=3, wait_timeout=0) as big:
            self.assertTrue(big)
            with _expensive_request_slot("t_weight", 4, weight=2, wait_timeout=0) as other:
                self.assertFalse(other, "only 1 unit is free; a weight-2 must not half-acquire")
            with _expensive_request_slot("t_weight", 4, weight=1, wait_timeout=0) as small:
                self.assertTrue(small, "the last free unit must still be usable")

    def test_second_whole_pool_request_does_not_block_on_the_drain_lock(self):
        # The drain holder lock used to be a BLOCKING flock. A second whole-pool request then
        # slept on the kernel wait list holding a worker for the whole drain. It must now lose
        # the race and time out instead, so whole-pool requests borrow at most one worker.
        os.environ["APITOOLS_SLOT_FAIRNESS_GRACE_S"] = "0"
        try:
            blocker = _expensive_request_slot("t_drain", 2, weight=1, wait_timeout=0)
            self.assertTrue(blocker.__enter__())

            results = {}

            def whole_pool(tag, budget):
                t0 = time.monotonic()
                with _expensive_request_slot("t_drain", 2, weight=2,
                                             wait_timeout=budget) as got:
                    results[tag] = (got, time.monotonic() - t0)

            a = threading.Thread(target=whole_pool, args=("a", 2.0))
            b = threading.Thread(target=whole_pool, args=("b", 2.0))
            a.start(); time.sleep(0.4); b.start()
            a.join(15); b.join(15)
            blocker.__exit__(None, None, None)

            self.assertEqual(set(results), {"a", "b"})
            for tag, (got, elapsed) in results.items():
                self.assertFalse(got, f"{tag} should have timed out, not acquired")
                self.assertLess(elapsed, 8.0,
                                f"{tag} blocked for {elapsed:.1f}s — the drain lock is blocking again")
        finally:
            os.environ.pop("APITOOLS_SLOT_FAIRNESS_GRACE_S", None)

    def test_default_wait_timeout_still_reads_the_env(self):
        os.environ["APITOOLS_SLOT_WAIT_TIMEOUT"] = "1"
        try:
            with _expensive_request_slot("t_env", 1, weight=1):
                t0 = time.monotonic()
                with _expensive_request_slot("t_env", 1, weight=1) as second:
                    self.assertFalse(second)
                self.assertGreaterEqual(time.monotonic() - t0, 0.9)
        finally:
            os.environ.pop("APITOOLS_SLOT_WAIT_TIMEOUT", None)


if __name__ == "__main__":
    unittest.main()
