#!/usr/bin/env python3
"""The meeting page's steps (DGO-1325): what meet-start says is being done to a meeting, why, and until when.

bs101 (2026-11-03) is the case: recorded 1:36:01 on vps1's two cores, no live captions (the watchdog: «auto: 2 cores
< 4», said only in its log), the ivrit pass 97 minutes at the transcriber's own pace, the whisper pass queued behind
it. The page said «עיבוד ראשון» with no reason and no time. These tests hold the answers it gives now, on bs101's
measured numbers; they need nothing but this file and server.py (run: python3 test_flow_status.py, or pytest).
"""
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TMP = tempfile.mkdtemp(prefix="meet-flow-status-")
os.environ["MEET_RECORDINGS"] = TMP
os.environ.pop("MEET_SPEECH_URL", None)
os.environ["MEET_LIVE_CAPTIONS"] = "auto"
os.environ["MEET_LIVE_CAPTIONS_MIN_CORES"] = "4"
sys.path.insert(0, str(HERE))
import server  # noqa: E402

AUDIO = "bs101_2026-11-03-12-08-14.ogg"
DUR = 5761.02


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def job(model, status, created, started=None, ended=None, done=0.0, audio=DUR, name=AUDIO, usage=None, error=None, segments=None):
    p = {"audio_seconds": audio, "processed_seconds": done, "percent": round(100 * done / audio, 1) if audio else 0}
    if segments:
        p["segments"] = segments
    return {"id": f"tr_{model}_{created:.0f}", "status": status, "created": iso(created), "started": iso(started) if started else None,
            "ended": iso(ended) if ended else None, "source": {"name": name}, "options": {"model": model, "language": "he" if model == "ivrit" else "auto"},
            "progress": p, "usage": usage or {}, "error": error}


def rec_of(session="b2abec86-d5ff-40ac-8f4d-18dc01ef7ece", done=True, mtime=None, capture=None):
    folder = os.path.join(TMP, session)
    os.makedirs(folder, exist_ok=True)
    if capture is not None:
        with open(os.path.join(folder, AUDIO[:-4] + ".capture.json"), "w", encoding="utf-8") as f:
            json.dump(capture, f)
    return {"session": session, "file": AUDIO[:-4] + ".mp4", "done": done, "bytes": 312e6, "mtime": mtime or time.time() - 600, "holes": {}}


def by_key(stages):
    return {s["key"]: s for s in stages}


class Title(unittest.TestCase):
    def test_one_title_and_no_state_in_it(self):
        self.assertEqual(server.meeting_title("bs101"), "bs101")
        self.assertEqual(server.meeting_title("bs101", {"title": "bs101 · תוכנית"}), "bs101 · תוכנית")
        self.assertEqual(server.meeting_title("bs101", None, {"title": "מהנתונים"}), "מהנתונים")
        self.assertEqual(server.meeting_title("bs101", {"title": "  "}, {"title": ""}), "bs101")

    def test_the_old_title_is_written_nowhere(self):
        src = (HERE / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("· עיבוד ראשון\"", src)
        self.assertNotIn("כתוביות חיות — לפני העיבוד המלא", src)       # a list tag that claimed captions it did not have


class OnePage(unittest.TestCase):
    def test_the_v1_pages_and_their_switch_are_gone(self):
        # no office served them (meet runs on vps1 alone, at v2): parked in legacy/, and MEET_FLOW_UI with them
        for name in ("index.html", "app.js", "app.css", "live.html", "live.js", "list.html"):
            self.assertFalse((HERE / "flow" / name).exists(), name)
        self.assertTrue((HERE / "flow" / "app.html").exists())
        self.assertFalse(hasattr(server, "flow_v2"))
        self.assertNotIn("MEET_FLOW_UI\"", (HERE / "server.py").read_text(encoding="utf-8"))


class Captions(unittest.TestCase):
    def test_the_watchdogs_own_reason(self):
        rec = rec_of(capture={"captions": 0, "captions_live": {"on": False, "why": "cores", "cores": 2, "min_cores": 4, "mem_mb": 2232, "min_mb": 1536}})
        self.assertEqual(server.captions_why(rec), ("cores", "לשרת המשרד יש 2 ליבות, וכתוביות חיות צריכות 4"))
        rec = rec_of(capture={"captions_live": {"on": False, "why": "memory", "cores": 8, "min_cores": 4, "mem_mb": 900, "min_mb": 1536}})
        self.assertEqual(server.captions_why(rec)[1], "לשרת היו 900 MB פנויים, וכתוביות חיות צריכות 1536")

    def test_a_recording_from_before_the_reason_was_written(self):
        # bs101's capture.json has `"captions": 0` and no reason: the office's switch and cores, the watchdog's rule
        rec = rec_of(capture={"captions": 0})
        key, why = server.captions_why(rec)
        if (os.cpu_count() or 1) < 4:
            self.assertEqual(key, "cores")
            self.assertIn("ליבות", why)
        else:
            self.assertEqual((key, why), ("", "לא נרשמה סיבה"))

    def test_the_step_says_why(self):
        rec = rec_of(capture={"captions": 0, "captions_live": {"on": False, "why": "cores", "cores": 2, "min_cores": 4}})
        st = by_key(server.flow_stages("first", None, {"live": False, "words": 0}, rec, True, [], time.time()))
        self.assertEqual(st["captions"]["state"], "off")
        self.assertEqual(st["captions"]["why"], "לשרת המשרד יש 2 ליבות, וכתוביות חיות צריכות 4")
        st = by_key(server.flow_stages("first", None, {"live": False, "words": 812}, rec, True, [], time.time()))
        self.assertEqual((st["captions"]["state"], st["captions"]["detail"]), ("done", "812 מילים"))


class Transcription(unittest.TestCase):
    """bs101's two passes on vps1, at the moments the page could have been opened."""
    t0 = 1793700352.0                                       # 2026-11-03T11:45:52Z, the ivrit job created and started
    done_ivrit = {"audio_seconds": DUR, "inference_seconds": 5798.4, "wall_seconds": 5829.9, "rtf": 0.99}

    def test_transcribing_says_how_far_and_until_when(self):
        now = self.t0 + 2400                               # his screenshot: 40 minutes in
        jobs = [job("whisper", "queued", self.t0), job("ivrit", "processing", self.t0, self.t0, done=2424.0)]
        st = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, jobs, now))
        iv = st["ivrit"]
        self.assertEqual(iv["state"], "running")
        self.assertAlmostEqual(iv["pct"], 42.1, places=1)
        self.assertEqual(iv["detail"], "40:24 מתוך 1:36:01")
        # its own pace: 2424 s of audio in 2400 s → the rest (3337 s) in ~3304 s
        self.assertAlmostEqual(iv["eta"] - now, (DUR - 2424.0) * 2400 / 2424.0, delta=2)
        wh = st["whisper"]
        self.assertEqual((wh["state"], wh["ahead"]), ("waiting", 1))
        self.assertGreater(wh["eta"], iv["eta"])            # after the ivrit pass ends, at the measured pace
        self.assertIn("לפניה 1", wh["detail"])

    def test_queued_counts_who_is_before_it(self):
        now = self.t0 + 60
        other = job("ivrit", "processing", self.t0 - 600, self.t0 - 600, done=600.0, audio=2400.0, name="dgo-tour-2_2026-11-03-11-00-00.ogg")
        jobs = [job("whisper", "queued", self.t0), job("ivrit", "queued", self.t0), other]
        iv = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, jobs, now))["ivrit"]
        self.assertEqual((iv["state"], iv["ahead"]), ("waiting", 1))
        self.assertIn("dgo-tour-2", iv["detail"])
        # the other's rest at ITS pace (600 s of audio in 660 s: 1800 s more take 1980 s), then its own at the measured one
        self.assertAlmostEqual(iv["eta"], now + 1800 * 660 / 600 + DUR * 1.0, delta=5)

    def test_done_says_what_it_made(self):
        jobs = [job("ivrit", "completed", self.t0, self.t0, self.t0 + 5830, done=DUR, usage=self.done_ivrit, segments=935),
                job("whisper", "processing", self.t0, self.t0 + 5830, done=1062.0)]
        st = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, jobs, self.t0 + 5830 + 1020))
        self.assertEqual(st["ivrit"]["state"], "done")
        self.assertEqual(st["ivrit"]["detail"], "935 קטעים · 1:36:01 תומללו ב-1:37:09")
        self.assertEqual(st["whisper"]["state"], "running")
        self.assertEqual(st["speakers"]["detail"], "אחרי «קדימה» — העיבוד המלא")

    def test_the_pace_is_measured(self):
        self.assertEqual(server.wall_per_audio([]), 1.0)
        jobs = [job("ivrit", "completed", 1, 1, 2, done=DUR, usage=self.done_ivrit)]
        self.assertAlmostEqual(server.wall_per_audio(jobs), 5829.9 / DUR, places=3)

    def test_a_failure_says_why_and_when_again(self):
        bad = job("ivrit", "error", self.t0, self.t0, self.t0 + 30, error={"code": "queue_full", "message": "queue is full (8)"})
        iv = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, [bad], self.t0 + 60))["ivrit"]
        self.assertEqual(iv["state"], "failed")
        self.assertIn("התור של המתמלל היה מלא", iv["why"])
        self.assertIn("בסבב הבא", iv["why"])
        three = [dict(bad, id=f"e{i}") for i in range(3)]
        iv = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, three, self.t0 + 60))["ivrit"]
        self.assertIn("נכשל 3 פעמים", iv["why"])

    def test_no_job_yet_and_no_answer(self):
        fresh = rec_of(mtime=time.time() - 60)
        st = by_key(server.flow_stages("first", None, {"live": False}, fresh, True, [], time.time()))
        self.assertEqual(st["ivrit"]["state"], "waiting")
        self.assertIn("תוך דקות", st["ivrit"]["detail"])
        st = by_key(server.flow_stages("first", None, {"live": False}, fresh, True, None, time.time()))
        self.assertIn("לא ענה", st["ivrit"]["detail"])
        old = rec_of(mtime=time.time() - 3 * 86400)
        st = by_key(server.flow_stages("first", None, {"live": False}, old, True, [], time.time()))
        self.assertEqual(st["ivrit"]["state"], "off")

    def test_a_closing_recording_is_after_the_meeting(self):
        st = server.flow_stages("first", None, {"live": False}, rec_of(done=False), False, [], time.time())
        self.assertEqual(by_key(st)["record"], {"key": "record", "state": "running", "detail": "ההקלטה נסגרת"})
        self.assertEqual(by_key(st)["ivrit"]["detail"], "כשההקלטה תיסגר")

    def test_a_processed_meeting_keeps_its_own_steps(self):
        flow = {"stages": {"best": {"state": "done", "detail": "934 שורות, 13200 מילים"}, "speakers": {"state": "done", "detail": "שלמה בולוטין"},
                           "summary": {"state": "done", "detail": "11 נושאים"}}}
        st = by_key(server.flow_stages("ready", flow, {"live": False}, rec_of(), False, [], time.time()))
        self.assertEqual(st["ivrit"], {"key": "ivrit", "state": "done", "detail": "934 שורות, 13200 מילים"})
        self.assertNotIn("whisper", st)                     # its job is not listed any more, and the flow does not say
        self.assertEqual(st["summary"]["state"], "done")
        self.assertEqual(st["review"]["state"], "waiting")
        self.assertEqual([s["key"] for s in server.flow_stages("ready", flow, {"live": False}, rec_of(), False, [], time.time())],
                         ["record", "captions", "ivrit", "speakers", "summary", "review"])


class SecondReader(unittest.TestCase):
    """What the second reader of DGO-1325 found, held."""

    def test_the_transcript_key_only_grows(self):
        # a service that does not answer, or a job that fell out of its newest 100, is not a change: an open page
        # would reload into less than it shows
        done = job("ivrit", "completed", 1, 1, 2, done=DUR)
        real = server.speech_jobs
        try:
            server.speech_jobs = lambda max_age=10.0: [done]
            first = server.transcript_key("bs101")
            self.assertEqual(first, (done["id"],))
            server.speech_jobs = lambda max_age=10.0: None
            self.assertEqual(server.transcript_key("bs101"), first)
            server.speech_jobs = lambda max_age=10.0: []
            self.assertEqual(server.transcript_key("bs101"), first)
        finally:
            server.speech_jobs = real

    def test_a_finished_pass_wins_over_a_later_failed_try(self):
        ok = job("ivrit", "completed", 100, 100, 200, done=DUR, segments=935)
        bad = job("ivrit", "error", 300, 300, 310, error={"code": "timeout"})
        jobs = [bad, ok]                                    # newest first, as the service lists them
        iv = by_key(server.flow_stages("first", None, {"live": False}, rec_of(), True, jobs, 400))["ivrit"]
        self.assertEqual(iv["state"], "done")

    def test_a_processed_meeting_without_its_recording_or_best(self):
        st = by_key(server.flow_stages("ready", {"stages": {}}, None, None, False, [], time.time()))
        self.assertNotIn("ivrit", st)                       # not «waiting» for ever: it was processed
        best = {"stages": {"best": {"state": "running", "detail": None}}}
        st = by_key(server.flow_stages("ready", best, None, None, False, [], time.time()))
        self.assertEqual(st["ivrit"], {"key": "ivrit", "state": "running", "detail": "התמלול המלא"})

    def test_why_a_pass_waits_is_coded(self):
        fresh = rec_of(mtime=time.time() - 60)
        codes = lambda rec, jobs: {k: s.get("code") for k, s in by_key(server.flow_stages("first", None, {"live": False}, rec, True, jobs, time.time())).items() if k in ("ivrit", "whisper")}
        self.assertEqual(codes(fresh, []), {"ivrit": "not-sent", "whisper": "not-sent"})
        self.assertEqual(codes(fresh, None), {"ivrit": "no-answer", "whisper": "no-answer"})
        self.assertEqual(codes(rec_of(mtime=time.time() - 3 * 86400), []), {"ivrit": "missing", "whisper": "not-sent"})
        self.assertEqual(codes(rec_of(done=False), []), {"ivrit": "recording", "whisper": "recording"})
        quiet = dict(fresh, initiator=next(iter(server.QUIET)))
        self.assertEqual(codes(quiet, []), {"ivrit": "quiet", "whisper": "quiet"})


class Watchdog(unittest.TestCase):
    """jibri/watch.py names the reason in the words the page maps (CAPTIONS_WHY)."""

    def test_reasons_map_to_the_pages_words(self):
        sys.path.insert(0, str(HERE.parent / "jibri"))
        import watch                                        # noqa: E402 — the watchdog's own module, nothing started
        cases = {(False, "off"): "off", (False, "auto: 2 cores < 4"): "cores", (False, "auto: the recorder is not healthy"): "recorder",
                 (False, "memory available 900 MB < 1536 MB (the transcriber's model is 1.6 GB)"): "memory",
                 (False, "memory pressure 12.0 % ≥ 10 % (available 700 MB)"): "pressure", (False, "paused: memory calm for 20 of 60 s"): "pressure",
                 (True, "auto: 8 cores, recorder healthy"): "on"}
        for (want, reason), why in cases.items():
            got = watch.captions_live(want, reason)
            self.assertEqual(got["why"], why, reason)
            self.assertIn(got["why"], set(server.CAPTIONS_WHY) | {"on"})
            self.assertEqual(got["raw"], reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
