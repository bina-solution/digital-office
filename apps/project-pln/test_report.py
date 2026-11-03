"""test_report.py — report.py: the owner's report as a work item in a plan file of the office's own (DGO-948).

    python3 apps/project-pln/test_report.py

What is asked: the file is made on first use and reads as a plan; a key is never used twice; the title
and the body arrive exactly as the person wrote them, whatever their characters; what is in the file is
never rewritten; and a refused report leaves the file as it was (or no file at all).
"""
import datetime
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("report", os.path.join(HERE, "report.py"))
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)

NOW = datetime.datetime(2026, 10, 21, 18, 30, tzinfo=datetime.timezone.utc)
SOURCE = "מקור: דיווח דרך הסוכן של הלשכה hp, 2026-10-21 18:30 UTC\n"


class Report(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "plans", "reports-hp.yaml")

    def tearDown(self):
        self.dir.cleanup()

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def items(self):
        return [it for mod in yaml.safe_load(self.read())["modules"] for it in mod.get("items") or []]

    def test_first_report_makes_the_file_and_reads_as_a_plan(self):
        key, path = report.add("hp", "הקונסול לא נטען בטלפון", "", "high", self.path, NOW)
        self.assertEqual((key, path), ("rep-hp-261021-183000", self.path))
        doc = yaml.safe_load(self.read())
        self.assertEqual(doc["project"], {"identifier": "DGO"})
        self.assertIn({"name": "דיווח"}, doc["labels"])
        self.assertEqual([m["key"] for m in doc["modules"]], ["r-hp"])
        it = self.items()[0]
        self.assertEqual((it["key"], it["name"], it["priority"], it["labels"]),
                         ("rep-hp-261021-183000", "הקונסול לא נטען בטלפון", "high", ["דיווח"]))
        self.assertEqual(it["description"], "מה דווח: הקונסול לא נטען בטלפון\n" + SOURCE)

    def test_a_key_is_never_used_twice(self):
        for n in range(3):
            report.add("hp", f"report {n}", "", "high", self.path, NOW)
        report.add("hp", "a minute later", "", "high", self.path, NOW + datetime.timedelta(minutes=1))
        self.assertEqual([it["key"] for it in self.items()],
                         ["rep-hp-261021-183000", "rep-hp-261021-183000-2", "rep-hp-261021-183000-3",
                          "rep-hp-261021-183100"])

    def test_a_lost_file_cannot_repeat_an_earlier_key(self):
        first, _ = report.add("hp", "first", "", "high", self.path, NOW)
        os.remove(self.path)                       # untracked, and lost: a `git clean`, a fresh clone
        second, _ = report.add("hp", "second", "", "high", self.path, NOW + datetime.timedelta(seconds=1))
        self.assertNotEqual(first, second)

    def test_the_words_arrive_as_written(self):
        title = 'דו"ח: ה-`bbox` לא עובד # {לא} \'שלום\' ׳גרש׳ $HOME --- ...'
        body = "שורה ראשונה\n\n# לא הערה\n- לא רשימה\n  מוזח: כן\n\tטאב\n$(echo no)\n---\n..."
        report.add("hp", title, body, "urgent", self.path, NOW)
        it = self.items()[0]
        self.assertEqual(it["name"], title)
        self.assertEqual(it["description"],
                         "מה דווח: שורה ראשונה\n\n# לא הערה\n- לא רשימה\n  מוזח: כן\n\tטאב\n$(echo no)\n---\n...\n" + SOURCE)

    def test_characters_yaml_cannot_carry_do_not_refuse_the_report(self):
        report.add("hp", "\x1b[31mred\x1b[0m title", "nul \x00 del \x7f c1 \x9b end", "high", self.path, NOW)
        it = self.items()[0]
        self.assertEqual(it["name"], "�[31mred�[0m title")
        self.assertTrue(it["description"].startswith("מה דווח: nul � del � c1 � end\n"))

    def test_a_placeholder_bracket_the_model_kept_is_dropped(self):
        report.add("hp", "<tasks show מראה module: —", "הגוף>", "high", self.path, NOW)
        report.add("hp", "<script> נטען פעמיים", "a <b> c", "high", self.path, NOW + datetime.timedelta(seconds=1))
        first, second = self.items()
        self.assertEqual(first["name"], "tasks show מראה module: —")
        self.assertTrue(first["description"].startswith("מה דווח: הגוף\n"))
        self.assertEqual(second["name"], "<script> נטען פעמיים")             # a real pair stays
        self.assertTrue(second["description"].startswith("מה דווח: a <b> c\n"))

    def test_a_title_is_one_line(self):
        report.add("hp", "  שתי\n  שורות שלוש  ", "the body", "high", self.path, NOW)    # a title given
        self.assertEqual(self.items()[0]["name"], "שתי שורות שלוש")

    def test_an_office_name_is_made_a_key_part_not_refused(self):
        key, _ = report.add("HP_Office", "t", "", "high", self.path, NOW)
        self.assertEqual(key, "rep-hp-office-261021-183000")
        self.assertTrue(report.plan_path("HP_Office").endswith(os.path.join("plans", "reports-hp-office.yaml")))

    def test_the_persons_words_alone_make_the_title_and_the_body(self):
        cases = {
            "תדווח באג: tasks show מראה תמיד module: — גם לפריט שנמצא במודול. DGO-960 נמצא במודול":
                "tasks show מראה תמיד module: — גם לפריט שנמצא במודול.",
            "ותדווח על זה כבאג שלא נותן לייצר חיבור": "לא נותן לייצר חיבור",
            "report a bug: the console is slow": "the console is slow",
            "הקונסול לא נטען בטלפון": "הקונסול לא נטען בטלפון",
            "תדווח באג": "תדווח באג",
            "א " * 100: ("א " * 60).strip() + "…",               # 120 characters, cut at a word
        }
        for said, title in cases.items():
            self.assertEqual(report.title_of(said), title, said)
        report.add("hp", "תדווח באג: הקונסול לא נטען. כבר פעמיים היום", "", "high", self.path, NOW)
        it = self.items()[0]
        self.assertEqual(it["name"], "הקונסול לא נטען.")
        self.assertTrue(it["description"].startswith("מה דווח: תדווח באג: הקונסול לא נטען. כבר פעמיים היום\n"))

    def test_refusals_leave_no_file(self):
        for title, priority, said in (("   ", "high", "title"), ("x" * 201, "high", "200"), ("t", "soon", "priority")):
            with self.assertRaises(ValueError) as e:
                report.add("hp", title, "a body", priority, self.path, NOW)
            self.assertIn(said, str(e.exception))
        self.assertFalse(os.path.exists(self.path))

    def test_a_refusal_after_the_file_was_opened_leaves_no_empty_file(self):
        with patch.object(report, "item_text", return_value="  - [unclosed\n"):
            with self.assertRaises(ValueError):
                report.add("hp", "t", "", "high", self.path, NOW)
        self.assertFalse(os.path.exists(self.path))

    def test_a_full_disk_leaves_the_file_as_it_was(self):
        report.add("hp", "first", "", "high", self.path, NOW)
        before = self.read()
        full = OSError(28, "No space left on device")
        with patch.object(report.os, "write", side_effect=[10, full]):      # a part, then the disk is full
            with self.assertRaises(OSError) as e:
                report.add("hp", "second", "", "high", self.path, NOW + datetime.timedelta(seconds=1))
        self.assertIn("No space left on device", str(e.exception))
        self.assertEqual(self.read(), before)
        os.remove(self.path)
        with patch.object(report.os, "write", side_effect=full):
            with self.assertRaises(OSError):
                report.add("hp", "first again", "", "high", self.path, NOW)
        self.assertFalse(os.path.exists(self.path))

    def test_once_written_a_refused_chown_only_warns(self):
        err = io.StringIO()
        with patch.object(report.os, "geteuid", return_value=0, create=True), \
             patch.object(report.os, "chown", side_effect=PermissionError(1, "Operation not permitted"), create=True), \
             redirect_stderr(err):
            key, _ = report.add("hp", "made by root", "", "high", self.path, NOW)
        self.assertEqual(key, "rep-hp-261021-183000")
        self.assertEqual([it["key"] for it in self.items()], [key])
        self.assertIn("stays as root made it", err.getvalue())

    def test_what_is_in_the_file_is_never_rewritten(self):
        report.add("hp", "first", "", "high", self.path, NOW)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("  # a person's note, no newline at the end")
        before = self.read()
        report.add("hp", "second", "", "high", self.path, NOW + datetime.timedelta(seconds=5))
        after = self.read()
        self.assertTrue(after.startswith(before + "\n"))
        self.assertEqual([it["name"] for it in self.items()], ["first", "second"])

    def test_a_file_that_is_not_a_plan_is_left_as_it_was(self):
        os.makedirs(os.path.dirname(self.path))
        for text in ("modules: [unclosed\n", "just: a map\n"):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            with self.assertRaises(ValueError):
                report.add("hp", "t", "", "high", self.path, NOW)
            self.assertEqual(self.read(), text)

    def test_the_words_from_a_heredoc_or_split_by_a_stray_quote(self):
        said = "תדווח באג: מס' 5 לא נטען, דו\"ח $HOME `x`\nשורה שנייה"
        with redirect_stdout(io.StringIO()):
            rc = report.main(["add", "--office", "hp", "-", "--plan", self.path], stdin=io.StringIO(said + "\n"))
            self.assertEqual(rc, 0)
            # «… במודול 'דיווחים · hp', וגם …» with its quotes unescaped: bash hands over three words
            rc = report.main(["add", "--office", "hp", "במודול דיווחים", "·", "hp, וגם עוד", "--plan", self.path])
        self.assertEqual(rc, 0)
        first, second = self.items()
        self.assertEqual(first["name"], "מס' 5 לא נטען, דו\"ח $HOME `x`")      # the first line
        self.assertTrue(first["description"].startswith("מה דווח: " + said + "\n"))
        self.assertEqual(second["name"], "במודול דיווחים · hp, וגם עוד")

    def test_said_reads_the_persons_last_message_of_the_session(self):
        import http.server
        import json as js
        import threading
        records = [
            {"event": {"type": "user/message", "data": {"content": [{"type": "text", "text": "קודם"}], "source": {"kind": "user"}}}},
            {"event": {"type": "user/message", "data": {"content": [{"type": "text", "text": "תדווח באג: מס' 5 לא נטען, דו\"ח"}], "source": {"kind": "user"}}}},
            {"event": {"type": "user/message", "data": {"content": [{"type": "text", "text": "Current runtime context. …"}], "source": {"kind": "user"}}}},
            {"event": {"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "x"}]}}}},
        ]
        asked = []

        class Harness(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = js.loads(self.rfile.read(int(self.headers["content-length"])))
                req = body["payload"]["args"]["request"]
                asked.append((self.headers["authorization"], req["address"]["sessionId"], req["throughSeq"]))
                result = ({"ok": False, "error": {"message": "session page through seq 1000000000 is past cursor 4"}}
                          if req["throughSeq"] > 4 else {"ok": True, "value": {"records": records}})
                out = js.dumps({"result": result}).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Harness)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with open(os.path.join(self.dir.name, "api-token"), "w", encoding="utf-8") as f:
            f.write("tok\n")
        try:
            said = report.said_in_session("session-1", self.dir.name, str(server.server_address[1]))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(said, "תדווח באג: מס' 5 לא נטען, דו\"ח")
        self.assertEqual(asked, [("Bearer tok", "session-1", 10 ** 9), ("Bearer tok", "session-1", 4)])
        with patch.dict(os.environ, {"DSH_SESSION_ID": ""}):
            with self.assertRaises(ValueError) as e:
                report.said_in_session()
        self.assertIn("inside an agent's session", str(e.exception))

    def test_the_report_is_the_message_that_asks_for_it(self):
        # two messages sent while the agent was busy: the report is the one that asks for it
        self.assertEqual(report.the_report(["תדווח באג: הקונסול לא נטען", "ותבדוק את המייל"]),
                         "תדווח באג: הקונסול לא נטען")
        # only the order: what it is about came the message before
        self.assertEqual(report.the_report(["כל הממשק מופיע באנגלית", "Wtf ??? Report bug"]),
                         "כל הממשק מופיע באנגלית\n\nWtf ??? Report bug")
        self.assertEqual(report.the_report(["הכפתור לא לוחץ", "תדווח על זה כבאג"]), "הכפתור לא לוחץ\n\nתדווח על זה כבאג")
        self.assertEqual(report.the_report(["שלום"]), "שלום")                    # nothing reportish: the newest
        # the owner, 2026-10-21 21:48: a task named, then «create it in Plane»
        said = report.the_report(["תיצור משימת: משימת בדיקה123", "יצור את המשימה בפליין"])
        self.assertEqual(said, "תיצור משימת: משימת בדיקה123\n\nיצור את המשימה בפליין")
        self.assertEqual(report.title_of(said), "משימת בדיקה123")
        # the second reader's cases: opening an item to look at it is no report; «פליין» is content
        self.assertEqual(report.the_report(["תדווח באג: הקונסול לא נטען", "ותפתח את המשימה DGO-950 ותגיד מה הסטטוס"]),
                         "תדווח באג: הקונסול לא נטען")
        self.assertEqual(report.the_report(["מה המצב?", "תיצור משימה: שדרוג פליין"]), "תיצור משימה: שדרוג פליין")

    def test_the_order_is_taken_off_and_nothing_more(self):
        self.assertEqual(report.title_of("תדווח באג שרת המייל לא עונה"), "שרת המייל לא עונה")
        self.assertEqual(report.title_of("תדווח באג שהקונסול לא נטען"), "הקונסול לא נטען")
        self.assertEqual(report.title_of("תדווח באגים: שניים במייל"), "תדווח באגים: שניים במייל")

    def test_a_word_that_starts_with_a_dash_keeps_its_place(self):
        with redirect_stdout(io.StringIO()):
            rc = report.main(["add", "--office", "hp", "הקונסול", "-בטלפון", "לא", "נטען", "--plan", self.path])
        self.assertEqual(rc, 0)
        self.assertEqual(self.items()[0]["name"], "הקונסול -בטלפון לא נטען")

    def test_main_prints_the_key_and_the_file_and_reads_the_body_file(self):
        body = os.path.join(self.dir.name, "body.txt")
        with open(body, "w", encoding="utf-8") as f:
            f.write("מה שהבעלים אמר, כולו")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = report.main(["add", "--office", "hp", "כותרת", "--body", "@" + body, "--plan", self.path])
        self.assertEqual(rc, 0)
        key = out.getvalue().splitlines()[0]
        self.assertRegex(key, r"^KEY=rep-hp-\d{6}-\d{6}$")
        self.assertEqual(out.getvalue().splitlines()[1], "FILE=" + self.path)
        self.assertTrue(self.items()[0]["description"].startswith("מה דווח: מה שהבעלים אמר, כולו\n"))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = report.main(["add", "--office", "hp", "t", "--body", "@/no/such/file", "--plan", self.path])
        self.assertEqual(rc, 2)
        self.assertIn("No such file", err.getvalue())


if __name__ == "__main__":
    unittest.main()
