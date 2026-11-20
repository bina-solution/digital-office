"""test_snapshot.py — «מצב» / «קדימה»'s table (snapshot.py, DGO-1339), against fakes (no network).

    python3 apps/dashboard/test_snapshot.py

What is asked: every part of the table is built from its own read; a part that fails or does not come back in time
is its own line «לא ענה», never the end of the table; the herd line names each office that is not connected and
since when; observe mode is said as «צופה בלבד»; a second ask within SNAP_KEEP seconds is the same build.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot  # noqa: E402

TMP = tempfile.mkdtemp()
STATE = os.path.join(TMP, "state.json")
HERD = os.path.join(TMP, "herd.yaml")
NOW = 1_793_880_000

ROWS = [{"office": "hp-laptop", "group": "העדר שלנו", "name": "HP", "state": "up", "home": True},
        {"office": "macbook", "group": "העדר שלנו", "name": "MacBook", "state": "half"},
        {"office": "vps1", "group": "העדר שלנו", "name": "vps1", "state": "down", "since_ts": NOW - 3600,
         "why": "הלשכה לא ענתה דרך הקישור (HTTP 502)"},
        {"office": "exf", "group": "לקוחות", "name": "EXF", "state": "up"}]


def write_state(**over):
    doc = {"at": NOW, "computers": ROWS, "totals": {"all": 900, "completed": 700, "started": 63, "owner": 42},
           "topics": [{"name": "השלמת המלאי בפיקוח", "done": 57, "started": 9, "total": 123}],
           "feed": [{"ts": NOW - 60, "kind": "open", "ref": "DGO-1400", "text": "נפתח: x"},
                    {"ts": NOW - 50, "kind": "done", "ref": "DGO-1300", "text": "נסגר: y"},
                    {"ts": NOW - 40, "kind": "bad", "ref": "", "text": "vps1 נפל מהקישור"}], "errors": {}}
    doc.update(over)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def at_once(fn, items, default, deadline, what=""):
    return [fn(i) for i in items]


class Snapshot(unittest.TestCase):
    def setUp(self):
        write_state()
        with open(HERD, "w", encoding="utf-8") as fh:
            fh.write("apps:\n  project-pln: hp-laptop\n  meet: vps1\n")
        with open(os.path.join(TMP, "remote.vps1.security.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.answers = {
            "/api/queue": {"available": True, "queues": {"jobs": {"wait": 2, "active": 1, "delayed": 0}}},
            "/api/executions?hours=1": [{"status": "success"}, {"status": "error"}, {"status": "running"}],
            "/api/notifications?unread=1&level=error&limit=50": {"notifications": [{"title": "n8n לא עונה"}]},
            "/flow/api/meetings": {"meetings": [{"title": "bs101 · תכנון", "room": "bs101", "started": "2026-11-04T09:30"}]},
            "/api/bans": {"mode": "observe", "active": [{"ip": "93.184.216.11", "until": NOW * 10}], "history": []},
        }
        snapshot._last.update(at=0.0, doc=None)

    def get(self, url, timeout=8):
        for path, ans in self.answers.items():
            if url.endswith(path):
                return ans
        return {"_error": "HTTP 404: not here"}

    def door(self, office, alias):
        return f"http://{alias}.{office}:9100"

    def build(self):
        return snapshot.build(STATE, self.get, self.door, HERD, TMP, {"vps1": "vps1"}, now=lambda: NOW, at_once=at_once)

    def test_every_part_is_a_line(self):
        doc = self.build()
        self.assertEqual(sorted(doc["parts"]), ["concurrency", "herd", "meetings", "security", "stability", "work"])
        text = "\n".join(snapshot.lines(doc, {"vps1": "vps1"}, tz_offset=7200))
        self.assertIn("🐑 העדר: 2 מתוך 3 מחוברים", text)         # the client's office is the page's, not this line
        self.assertIn("vps1: לא עונה (מ-", text)
        self.assertIn("HTTP 502", text)
        self.assertIn("🗂 משימות: 63 בעבודה · 42 מחכות לך · ב-24 השעות האחרונות נפתחו 1, נסגרו 1", text)
        self.assertIn("השלמת המלאי בפיקוח 46%", text)
        self.assertIn("📅 פגישות: bs101 · תכנון (4.11)", text)            # the day first, as Israel reads a date
        self.assertIn("⚙️ כל מקביל: n8n — 1 רצות עכשיו, 2 ממתינות · בשעה האחרונה 3 ריצות, 1 נכשלו", text)
        self.assertIn("🛡 שליטה ובקרה: vps1 — צופה בלבד (לא חוסם בפועל), 1 חסומים", text)
        self.assertIn("🔔 יציבות: 1 שגיאות שלא נקראו — n8n לא עונה", text)

    def test_a_part_that_fails_is_its_own_line_and_the_rest_stand(self):
        self.answers.pop("/api/queue")
        doc = self.build()
        self.assertIn("concurrency", doc["silent"])
        text = "\n".join(snapshot.lines(doc))
        self.assertIn("⚙️ כל מקביל: לא ענה — מה שנשאל לא נמצא שם (HTTP 404: not here)", text)
        self.assertIn("🐑 העדר:", text)

    def test_a_silent_part_is_one_short_line_never_a_page(self):
        self.answers["/flow/api/meetings"] = {"_error": 'HTTP 401: <!doctype html>\n<html lang="he" dir="rtl">\n<head>'}
        text = "\n".join(snapshot.lines(self.build()))
        self.assertIn("📅 פגישות: לא ענה — אין הרשאה (HTTP 401)", text)
        self.assertNotIn("<", text)
        for raw, said in (("HTTP 502: Bad Gateway", "ענה בשגיאה (HTTP 502: Bad Gateway)"),
                          ('HTTP 503: {"error": "redis is away"}', 'ענה בשגיאה (HTTP 503: {"error": "redis is away"})'),
                          ('HTTP 429: {"error_code":5900}', "Plane ביקש להאט — המפתח של הלשכה מוצה לדקה (HTTP 429)"),
                          ("TimeoutError('timed out')", "לא ענה בזמן"),
                          ("Plane has not been read yet", "עוד לא נקרא מאז שהאוסף עלה"),
                          # urllib's own words, as they really come (the second reader): unwrapped, never cut away
                          ("<urlopen error [Errno 111] Connection refused>",
                           "השירות לא מקבל חיבור — כנראה לא רץ (החיבור נדחה)"),
                          ("<urlopen error [Errno -2] Name or service not known>",
                           "השירות לא מנותב לכאן (השם שלו לא ידוע ברשת של הלשכה)"),
                          ("<urlopen error [Errno 113] No route to host>", "אין דרך אל השירות ברשת"),
                          ("<urlopen error something new>", "something new")):
            self.assertEqual(snapshot.why_silent(raw), said)

    def test_problems_are_counted_by_their_whole_title_and_a_titleless_row_is_not_one(self):
        same = "א" * 75
        got = {"notifications": [{"title": same + " ב"}, {"title": same + " ג"}, {"title": ""}, {"title": same + " ב"}]}
        part = snapshot.stability_part(lambda url, timeout=8: got)
        self.assertEqual(part["errors"], 4)
        self.assertEqual(part["top"], [same[:70] + " (×2)", same[:70]])

    def test_one_problem_repeated_is_counted_once_in_the_stability_line(self):
        self.answers["/api/notifications?unread=1&level=error&limit=50"] = {"notifications": [
            {"title": "הריפוי העצמי לא פועל"}, {"title": "n8n לא עונה"}, {"title": "הריפוי העצמי לא פועל"},
            {"title": "הריפוי העצמי לא פועל"}]}
        text = "\n".join(snapshot.lines(self.build()))
        self.assertIn("🔔 יציבות: 4 שגיאות שלא נקראו — הריפוי העצמי לא פועל (×3) · n8n לא עונה", text)

    def test_a_part_not_back_in_time_is_said_so(self):
        def late(fn, items, default, deadline, what=""):
            return [default if i[0] == "meetings" else fn(i) for i in items]
        doc = snapshot.build(STATE, self.get, self.door, HERD, TMP, at_once=late)
        self.assertEqual(doc["silent"]["meetings"], f"לא ענה תוך {snapshot.SNAP_DEADLINE} שניות")

    def test_plane_not_read_yet_is_said_not_zero(self):
        write_state(totals=None, errors={"plane": "HTTP 401: no key"})
        doc = self.build()
        self.assertEqual(doc["silent"]["work"], "אין הרשאה (HTTP 401: no key)")

    def test_meet_not_routed_here_is_said(self):
        doc = snapshot.build(STATE, self.get, lambda o, a: "" if a == "meet" else self.door(o, a), HERD, TMP,
                             at_once=at_once)
        self.assertIn("vps1", doc["silent"]["meetings"])

    def test_israels_time_without_a_zone_database(self):
        def at(s):
            return snapshot.datetime.datetime.fromisoformat(s).timestamp()
        self.assertEqual(snapshot.israel_offset(at("2026-11-05T12:00:00+00:00")), 7200)    # winter
        self.assertEqual(snapshot.israel_offset(at("2026-07-01T12:00:00+00:00")), 10800)   # summer
        self.assertEqual(snapshot.israel_offset(at("2026-03-26T23:59:00+00:00")), 7200)    # the eve of Friday 27.3
        self.assertEqual(snapshot.israel_offset(at("2026-03-27T00:00:00+00:00")), 10800)   # 02:00 local, Friday
        self.assertEqual(snapshot.israel_offset(at("2026-10-24T22:59:00+00:00")), 10800)   # 01:59 local, Sunday 25.10
        self.assertEqual(snapshot.israel_offset(at("2026-10-24T23:00:00+00:00")), 7200)

    def test_a_second_ask_within_the_window_is_the_same_build(self):
        n = []
        make = lambda: n.append(1) or {"at": len(n)}              # noqa: E731
        t = [100.0]
        a = snapshot.cached(make, now=lambda: t[0])
        t[0] += snapshot.SNAP_KEEP - 1
        b = snapshot.cached(make, now=lambda: t[0])
        t[0] += 2
        c = snapshot.cached(make, now=lambda: t[0])
        self.assertEqual((a, b, len(n)), ({"at": 1}, {"at": 1}, 2))
        self.assertEqual(c, {"at": 2})


if __name__ == "__main__":
    unittest.main()
