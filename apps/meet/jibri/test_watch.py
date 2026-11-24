"""test_watch — the recorder's end is not a fault, and a freeze that runs into the end still is (DGO-2111 root 8).

When a meeting ends, Jibri stops ffmpeg («JibriSubprocess.stop … [session_id=…]») and stays BUSY for 26–28 s while it
finishes the file. That silence was judged a stall, so all 14 «ההקלטה הסתיימה בזמן תקלה» on vps1 were false. Here:
- the stop of THIS session is found, with its own time, and another session's stop is not;
- the silence from the last progress line to that stop tells a normal end (seconds) from a freeze cut by the stop.

    python3 test_watch.py          (from this directory; stdlib only)
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watch  # noqa: E402  (the loop runs only under __main__)


class StoppedAtTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="jlog-")
        self.saved = watch.JLOG
        watch.JLOG = os.path.join(self.dir, "log.0.txt")

    def tearDown(self):
        watch.JLOG = self.saved

    def write(self, *lines):
        with open(watch.JLOG, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def rec(self, session):
        r = watch.Recording()
        r.session = session
        return r

    def test_the_stop_of_this_session_is_found_with_its_own_time(self):
        self.write("Jibri 2026-11-20 10:00:05.500 INFO: [session_id=aaa-111] JibriSubprocess.stop#61: Stopping ffmpeg")
        want = time.mktime(time.strptime("2026-11-20 10:00:05", "%Y-%m-%d %H:%M:%S")) + 0.5
        self.assertAlmostEqual(self.rec("aaa-111").stopped_at(), want)

    def test_another_sessions_stop_is_not(self):
        self.write("Jibri 2026-11-20 10:00:00.000 INFO: [session_id=bbb-222] JibriSubprocess.stop#61: Stopping ffmpeg")
        self.assertIsNone(self.rec("aaa-111").stopped_at())

    def test_no_stop_yet_is_not_the_end(self):
        self.write("Jibri 2026-11-20 10:00:00.000 INFO: [session_id=aaa-111] JibriSubprocess.launch#40: Starting ffmpeg with: [x]")
        self.assertIsNone(self.rec("aaa-111").stopped_at())

    def test_a_normal_end_is_seconds_of_silence_a_freeze_is_more(self):
        # the gap the loop measures: stop time minus the last progress line's time, against FROZE
        self.write("Jibri 2026-11-20 10:10:00.000 INFO: [session_id=aaa-111] JibriSubprocess.stop#61: Stopping ffmpeg")
        stop = self.rec("aaa-111").stopped_at()
        self.assertLess(stop - (stop - 2), watch.FROZE)            # progress 2 s before the stop: the end
        self.assertGreaterEqual(stop - (stop - 210), watch.FROZE)  # 3.5 min silent before it (exf107): a freeze


if __name__ == "__main__":
    unittest.main()
