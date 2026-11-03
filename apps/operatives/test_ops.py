"""The Operative Collective's engine (DGO-948): reading an operative, judging it, where it runs, and
matching the owner's real requests (2026-10-21) to the right one.

    python3 apps/operatives/test_ops.py
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("ops", os.path.join(HERE, "ops.py"))
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)

GOOD = """---
id: tasks.comment
title: Comment on a work item
title_he: הערה על פריט עבודה
when:
  - הוסף הערה ל-DGO-123
  - comment on DGO-123
inputs: {ref: "the item", text: "the comment"}
reaches_people: false
check: 'the command prints "commented on DGO-<n>"'
---
1. ./bbox project-pln tasks comment <ref> --comment "<text>"
"""


def op_from(text, path="apps/project-pln/operatives/tasks.comment.md", app="project-pln"):
    meta, body = ops.front_matter(text)
    return {**meta, "app": app, "path": path, "steps": body.strip(), "bytes": len(text.encode())}


class Reading(unittest.TestCase):
    def test_front_matter_with_pyyaml(self):
        meta, body = ops.front_matter(GOOD)
        self.assertEqual(meta["id"], "tasks.comment")
        self.assertEqual(meta["when"][0], "הוסף הערה ל-DGO-123")
        self.assertEqual(meta["inputs"]["ref"], "the item")
        self.assertIs(meta["reaches_people"], False)
        self.assertTrue(body.startswith("1. ./bbox"))

    def test_front_matter_without_pyyaml(self):
        real = __import__
        def no_yaml(name, *a, **k):
            if name == "yaml":
                raise ImportError(name)
            return real(name, *a, **k)
        with patch("builtins.__import__", side_effect=no_yaml):
            meta, _ = ops.front_matter(GOOD)
        self.assertEqual(meta["id"], "tasks.comment")
        self.assertEqual(meta["when"], ["הוסף הערה ל-DGO-123", "comment on DGO-123"])
        self.assertEqual(meta["inputs"], {"ref": "the item", "text": "the comment"})
        self.assertIs(meta["reaches_people"], False)
        self.assertEqual(meta["check"], 'the command prints "commented on DGO-<n>"')

    def test_no_front_matter(self):
        self.assertEqual(ops.front_matter("just text")[0], {})

    def test_every_real_operative_reads_the_same_without_pyyaml(self):
        """The fallback parser (a container without PyYAML) reads each of the office's operatives as
        PyYAML does — an apostrophe inside a double-quoted value is not a quote."""
        real = __import__

        def no_yaml(name, *a, **k):
            if name == "yaml":
                raise ImportError(name)
            return real(name, *a, **k)

        for op in ops.operatives():
            with open(os.path.join(ops.ROOT, op["path"]), encoding="utf-8") as f:
                text = f.read()
            with_yaml, _ = ops.front_matter(text)
            with patch("builtins.__import__", side_effect=no_yaml):
                without, _ = ops.front_matter(text)
            self.assertEqual(without, with_yaml, op["path"])


class Judging(unittest.TestCase):
    def test_a_good_operative_has_no_problem(self):
        self.assertEqual(ops.problems([op_from(GOOD)]), [])

    def test_each_problem_is_named(self):
        cases = {
            "no `check`": GOOD.replace("check: 'the command prints \"commented on DGO-<n>\"'\n", ""),
            "is not <group>.<action>": GOOD.replace("id: tasks.comment", "id: Tasks-Comment"),
            "not named after its id": GOOD.replace("id: tasks.comment", "id: tasks.note"),
            "`when` is a list": GOOD.replace("when:\n  - הוסף הערה ל-DGO-123\n  - comment on DGO-123", "when: comment"),
            "no steps": GOOD.split("---\n1.")[0] + "---\n",
            "holds a secret": GOOD + "token=abcdef1234567890\n",
            "a recipe, not a manual": GOOD + "x" * ops.MAX_BYTES,
            "does not read": GOOD.replace("check: 'the command", "check: the: command"),
        }
        for want, text in cases.items():
            got = ops.problems([op_from(text)])
            self.assertTrue(any(want in g for g in got), f"{want}: {got}")

    def test_a_duplicate_id_is_named(self):
        got = ops.problems([op_from(GOOD), op_from(GOOD, path="apps/x/operatives/tasks.comment.md")])
        self.assertTrue(any("is also" in g for g in got), got)

    def test_inputs_must_be_a_map(self):
        got = ops.problems([op_from(GOOD.replace('inputs: {ref: "the item", text: "the comment"}', "inputs: [ref, text]"))])
        self.assertTrue(any("inputs is a map" in g for g in got), got)

    def test_a_malformed_operative_is_not_served_and_breaks_nothing(self):
        bad = op_from(GOOD.replace("when:\n  - הוסף הערה ל-DGO-123\n  - comment on DGO-123", "when: comment")
                      .replace("id: tasks.comment", "id: tasks.note"), path="apps/project-pln/operatives/tasks.note.md")
        good = op_from(GOOD)
        self.assertEqual([o["id"] for o in ops.usable([bad, good])], ["tasks.comment"])
        self.assertEqual(ops.score("comment on DGO-123", bad), ops.score("comment on DGO-123", bad))  # no crash


class Where(unittest.TestCase):
    def test_here_via_a_link_or_nowhere(self):
        enabled = {"project-pln": True, "mail": False}
        linked = {"mail": [("vps1", "mailview")]}
        self.assertEqual(ops.where({"app": "project-pln"}, enabled, linked), "here")
        self.assertEqual(ops.where({"app": "mail"}, enabled, linked), "via vps1 (mailview)")
        self.assertEqual(ops.where({"app": "n8n"}, enabled, linked), "not reachable from this office")
        self.assertEqual(ops.where({"app": "operatives"}, {}, {}), "here")
        # steps that work only where the app runs: a linked office's copy is no way to run them
        self.assertEqual(ops.where({"app": "browser42", "link": False}, {}, {"browser42": [("hp-laptop", "browser42")]}),
                         "not reachable from this office")
        self.assertEqual(ops.where({"app": "browser42", "link": False}, {"browser42": True}, {}), "here")

    def test_steps_keep_only_the_way_that_works_here(self):
        op = {"app": "mail", "steps": "1. Ask:\n   - here: `curl -s http://mailview:8976/x`\n"
                                      "   - linked: `./bbox remote <office> <alias> /x`\n2. Answer."}
        via = ops.steps_for(op, {"mail": False}, {"mail": [("vps1", "mailview")]})
        self.assertIn("./bbox remote vps1 mailview /x", via)
        self.assertNotIn("curl", via)
        self.assertNotIn("linked:", via)
        here = ops.steps_for(op, {"mail": True}, {"mail": [("vps1", "mailview")]})
        self.assertIn("curl -s http://mailview:8976/x", here)
        self.assertNotIn("bbox remote", here)
        self.assertIn("2. Answer.", here)
        numbered = {"app": "mail", "steps": "1. here: `curl local`\n1. linked: `./bbox remote <office> <alias> /x`\n+ here: `b`"}
        self.assertNotIn("curl local", ops.steps_for(numbered, {}, {"mail": [("vps1", "mailview")]}))
        self.assertNotIn("+ here", ops.steps_for(numbered, {}, {"mail": [("vps1", "mailview")]}))

    def test_an_operative_that_cannot_run_here_has_no_broken_steps(self):
        op = {"id": "mail.inbox", "title": "t", "app": "mail", "steps": "linked: `./bbox remote <office> <alias> /x`",
              "check": "c"}
        text = ops.show_text(op, {}, {})
        self.assertIn("not reachable", text)
        self.assertNotIn("<office>", text)

    def test_enabled_apps_reads_both_spellings(self):
        # a sample of the state file's two shapes, under another name: the office's own state file has
        # one writer (gate G33), and this test is not it
        with tempfile.TemporaryDirectory() as d:
            sample = os.path.join(d, "state-sample.yaml")
            with open(sample, "w", encoding="utf-8") as f:
                f.write("apps:\n  mail:        { state: disabled, by: cli }\n  project-pln:      { state: enabled, by: user }\n"
                        "  traefik:          { enabled: true }   # the edge\n")
            self.assertEqual(ops.enabled_apps(sample), {"mail": False, "project-pln": True, "traefik": True})


class Matching(unittest.TestCase):
    """The office's own operatives, against the owner's own requests."""

    @classmethod
    def setUpClass(cls):
        cls.ops = ops.operatives()

    def best(self, request):
        hits = ops.find(request, self.ops)
        return hits[0][1]["id"] if hits else None

    def test_the_owners_requests(self):
        cases = {
            "היי פתח את הדפדפן לשכה על google.com ושלח לי צילום מסך": "browser.shot",
            "מה המצב? מה נשאר לשחרור?": "tasks.open",
            "הוסף הערה לפריט העבודה DGO-908 בשם azaria עם הטקסט: עובד": "tasks.comment",
            "שלח מייל ל-shlomo שמסביר מי אתה": "mail.send",
            "מה מצב הלשכה, הכל עובד?": "office.status",
            "יש מיילים חדשים?": "mail.inbox",
            "תסגור את DGO-950, בוצע": "tasks.done",
            "אילו לשכות מחוברות אליי?": "office.reach",
        }
        for request, want in cases.items():
            self.assertEqual(self.best(request), want, request)

    def test_a_status_read_takes_no_report_and_no_shell_command(self):
        # a status recipe's words are in every report (the CLI round's second reader, DGO-1039):
        # «יש בעיה באתר» took «יש בעיה במייל», «… לא עובדת» took «… לא עובדת, תפתח באג», and a bare
        # `git status` took the command
        for request in ("האתר לא עובד, תפתח פריט", "האפליקציה לא עובדת, תפתח באג", "האתר נפל, תפתח באג",
                        "האפליקציות לא עובדות, תפתח באג", "האתרים לא למעלה, תפתח פריט",
                        "הסנכרון של הטלגרם תקוע, תפתח באג", "הוואטסאפ לא מחובר, תפתח באג",
                        "הפייסבוק לא מחובר, תפתח באג",
                        # an order to report outranks the read its words also carry (ops.ordered)
                        "יש הרצות תקועות ב-n8n, תפתח באג", "מה מצב הצ׳אט? הוא לא נטען, תפתח באג",
                        "הדריין של אינדוקס לא רץ, תפתח באג", "the chat accounts are broken, open a bug"):
            self.assertEqual(self.best(request), "tasks.report", request)
        for request in ("אל תפתח באג על זה", "did you report a bug?", "תפתח באג?"):   # no order to report
            self.assertIsNone(self.best(request), request)
        for request in ("יש בעיה במייל", "יש בעיה באפליקציה", "תריץ git status", "run git status in the repo",
                        "כמה לקוחות יש", "מה נכשל בבנייה האחרונה"):
            self.assertIsNone(self.best(request), request)
        # another app's question is not a status read of this one (the second reader of the ops round)
        for request, never in {"מה רץ עכשיו במחשב": "n8n.runs", "כמה קבצים יש": "git.status",
                               "are the websites down, open a bug": "sites.status",
                               "מה הקבצים האחרונים בדרייב": "docs.recent", "מה השגיאות האחרונות": "docs.recent",
                               "מה המסמכים האחרונים בדרייב": "indox.pipeline",
                               "האם הקונסול עובד": "speech.status", "כמה מיילים בתור": "speech.status",
                               "האם המודל טעון": "speech.status"}.items():
            self.assertNotEqual(self.best(request), never, request)
        for request, want in {"מה מצב האתרים": "sites.status", "מה מצב המראות של הגיט": "git.status",
                              "מה מצב האפליקציות": "apps.state", "יש הרצות תקועות ב-n8n?": "n8n.runs",
                              "איזה תרשימים יש": "diagrams.list", "מה מצב הטלגרם": "tv.status",
                              "אילו רשתות חברתיות מחוברות?": "social.accounts", "מה החשבוניות האחרונות": "docs.recent",
                              "כמה מסמכים ממתינים באינדוקס": "indox.pipeline", "הוואטסאפ מחובר?": "chat.accounts",
                              "מה מצב ה-n8n": "n8n.status"}.items():
            self.assertEqual(self.best(request), want, request)

    def test_requests_no_operative_covers(self):
        # one shared word is chance; a tie at the top is a question, not a choice
        for request in ("תן לי 1000 מילים על אהבה", "send it", "שלח לי את זה", "open DGO-950", "close the browser"):
            self.assertIsNone(self.best(request), request)

    def test_saying_no_or_asking_gets_no_recipe_that_acts(self):
        # matched by words alone these got close / send / photograph (the operatives' second reader)
        for request in ("אל תסגור את DGO-950", "don't send an email to shlomo", "did you send the email to shlomo?",
                        "אל תצלם את האתר", "לא לשלוח מייל לשלמה"):
            hit = self.best(request)
            acting = [op for op in self.ops if op.get("id") == hit and op.get("acts")]
            self.assertEqual(acting, [], f"{request} → {hit}")
        self.assertEqual(self.best("יש מיילים חדשים?"), "mail.inbox")      # a question that reads still does

    def test_a_report_says_what_does_not_work_and_is_still_made(self):
        # the owner's own reports to Azaria (2026-10-11 … 10-21): long, with «לא» and «??» in them —
        # held back by «any negation or ?», and diluted by their length, none got the recipe before
        for request in ("תדווח באג מה זה החרא הזה שהוא אומר כל הזמן שהוא לא יכול ?? הוא יכול!! ותמיד שיעשה מה שאני אומר",
                        "תדווח באג שאתה לא יכול לתפעל את הדפדפן זה שטויות עשית את זה מליון פעם",
                        "ותדווח על זה כבאג שלא נותן לייצר חיבור", "Wtf ??? Report bug",
                        "הקונסול לא נטען בטלפון, תפתח באג", "תיצור משימה חדשה: משימת בדיקה ותן לי קישור לכרטיס בפליין"):
            self.assertEqual(self.best(request), "tasks.report", request)

    def test_a_long_message_is_no_errand_by_two_common_words(self):
        # a status note and the office's pulse: «הלשכה», «מצב», «הפריט» are words of every message
        for request in ("DGO-56 (הפריט הבא בלוח): המדידה החיה חסומה ב-DEPLOY ולא במדידה — ה-VPS על checkout ישן",
                        "הדופק של הלשכה: המטרה שלך במצב blocked — ההרנס הפסיק להמשיך אותך, ולכן השיחה עמדה",
                        "בפרט כשאני נותן לך צילום מסך בהצגת הבעיה, אני מצפה להדמייה שכוללת את המסך הקיים"):
            self.assertIsNone(self.best(request), request)

    def test_not_done_is_no_order_to_close_and_sent_is_none_to_send(self):
        # the second reader's cases (2026-10-21): with a report's «לא» let through, these drew tasks.done /
        # mail.send; an operative that only ADDS may take them, one that closes or sends may not
        for request in ("הפריט DGO-950 לא בוצע", "work item DGO-950 is not done", "לא תסגור את הפריט DGO-950",
                        "לא צריך לסגור את הפריט DGO-950", "אין צורך לשלוח מייל ל dana@example.com",
                        "תדאג שלא תשלח מייל לדנה", "סגרת את הפריט DGO-950?!", "שלחת מייל ל dana@example.com?!",
                        "סגרת את הפריט DGO-950", "did you send an email to dana@example.com",
                        "did you close work item DGO-950 as done", "don’t close work item DGO-950 as done",
                        "stop, do not send an email to dana@example.com",
                        "DGO-56: הפריט לא בוצע עדיין — המדידה החיה חסומה ב-DEPLOY, אני ממשיך מחר בבוקר",
                        "To send an email to customers n8n uses the SMTP credential and the workflow failed "
                        "yesterday at 14:00 with error 535 see the log below"):
            hit = self.best(request)
            self.assertIn(hit, (None, "tasks.report") + tuple(op["id"] for op in self.ops if not op.get("acts")),
                          f"{request} → {hit}")
        self.assertEqual(self.best("תשלח מייל ל dana@example.com שהפגישה נדחתה"), "mail.send")   # an order still is
        self.assertEqual(self.best("תסגור את DGO-950, בוצע"), "tasks.done")

    def test_forbidding_is_not_describing(self):
        self.assertTrue(ops.holds_back("אל תפתח באג על זה"))
        self.assertTrue(ops.holds_back("לא לשלוח את המייל לדנה"))
        self.assertTrue(ops.holds_back("please do not close DGO-950"))
        self.assertTrue(ops.holds_back("שלחת את המייל?"))
        self.assertTrue(ops.holds_back("האם שלחת? תבדוק"))
        self.assertTrue(ops.holds_back("did you send the email to dana"))
        self.assertFalse(ops.holds_back("הקונסול לא נטען בטלפון, תפתח באג"))
        self.assertFalse(ops.holds_back("it is not loading, report a bug"))
        self.assertFalse(ops.holds_back("תדווח באג שהוא לא יכול ?? הוא יכול!!"))
        self.assertFalse(ops.holds_back("זה לא לגמרי עובד, תפתח באג"))
        self.assertFalse(ops.holds_back("the console never loads, report a bug"))
        self.assertTrue(ops.wary("הפריט DGO-950 לא בוצע"))
        self.assertTrue(ops.wary("סגרת את הפריט DGO-950"))
        self.assertFalse(ops.wary("תסגור את DGO-950"))
        self.assertFalse(ops.wary("שלח מייל ל dana@example.com"))

    def test_a_huge_paste_is_measured_in_linear_time(self):
        # about 1 s on an idle HP (0.94 s, 2026-10-22); inside gates.sh, under load 5 on 6 cores, it passed
        # 3 s once. A quadratic matcher would take minutes on these 60,000 words, so 10 s still tells.
        import time
        text = " ".join(f"מילה{i} word{i}" for i in range(30000))           # ~340 KB, all distinct
        t = time.time()
        ops.find(text, self.ops)
        self.assertLess(time.time() - t, 10.0)

    def test_match_many_in_one_call(self):
        got = ops.match_many(["יש מיילים חדשים?", "תן לי 1000 מילים על אהבה"], self.ops,
                             {"mail": False}, {"mail": [("vps1", "mailview")]})
        # the relay's recipe names no operative id: a small model took `assets.show` for a file to cat
        self.assertTrue(got[0].startswith("# The latest mail in the inbox"), got[0][:80])
        self.assertNotIn("mail.inbox", got[0])
        self.assertIn("./bbox remote vps1 mailview", got[0])
        self.assertEqual(got[1], "")
        # a person's `show` keeps it
        inbox = [o for o in self.ops if o.get("id") == "mail.inbox"][0]
        self.assertTrue(ops.show_text(inbox, {"mail": False}, {"mail": [("vps1", "mailview")]}).startswith("# mail.inbox — "))

    def test_a_tie_at_the_top_is_no_match(self):
        a = op_from(GOOD)
        b = op_from(GOOD.replace("id: tasks.comment", "id: tasks.note"), path="apps/project-pln/operatives/tasks.note.md")
        self.assertEqual(ops.find("comment on DGO-123", [a, b]), [])
        self.assertEqual(len(ops.rank("comment on DGO-123", [a, b])), 2)

    def test_every_operative_of_the_office_is_well_formed(self):
        self.assertEqual(ops.problems(self.ops), [])


if __name__ == "__main__":
    unittest.main()
