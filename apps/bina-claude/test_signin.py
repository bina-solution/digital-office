"""«Continue with Google» through the office browser (DGO-1336) — the opener and the hop, no browser, no app.

    python3 -m unittest apps/bina-claude/test_signin.py

What these hold: the sign-in's query (its hop_nonce, Google's state, the answer's one-time code) is
never written to a log, and travels on stdin wherever the choice is ours; the person's screen is told how
it ended (the hand-off record `done` or `failed`, apps/browser42/handoff.py) — for THIS attempt's episode
only; «done» is said only when the app turned signed in after the code was handed to it; a newer press
retires every older worker and watcher without a word to the person; a plain link is not a hand-off.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent
NONCE = "POH4RqZ9nonce"
SIGNIN = f"https://claude.com/cai/login/app-google-auth?open_in_browser=1&hop_nonce={NONCE}"
STATE = f"desktop:2f0c7a1e-uuid.{NONCE}"
CODE = "4QXwCODEcode0123456789abcdefghijklmnopqrstu"
CALLBACK = f"https://claude.ai/login/popup-google-auth?code={CODE}&state={STATE}"
SECRETS = (NONCE, CODE, "hop_nonce=", "state=", "code=", "POH4Rq", "4QXw")


def load(name):
    loader = importlib.machinery.SourceFileLoader(f"bina_claude_{name.replace('-', '_')}", str(HERE / "desktop" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class Home:
    """A HOME of its own for each test: the log, the pid file and the current sign-in's fingerprint."""

    def __init__(self, module):
        self.module, self.dir = module, tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.patches = [patch.object(module, name, str(root / leaf)) for name, leaf in (
            ("LOG", ".claude-open-url.log"), ("CURRENT", ".bina-claude-hop.current"),
            ("PIDFILE", ".bina-claude-hop.pid"), ("OUT", ".bina-claude-hop.out"),
            ("COOKIES", "Cookies")) if hasattr(module, name)]
        if hasattr(module, "APP_LOGS"):                  # the app's own logs, never the test machine's
            self.patches.append(patch.object(module, "APP_LOGS", (str(root / ".claude-desktop.log"), str(root / "main.log"))))

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *_):
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def log(self):
        try:
            return Path(self.module.LOG).read_text(encoding="utf-8")
        except OSError:
            return ""


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class OpenerTests(unittest.TestCase):
    def setUp(self):
        self.m = load("open-url")

    def test_a_log_line_names_a_host_and_a_path_never_the_query(self):
        self.assertEqual(self.m.describe(SIGNIN), "claude.com/cai/login/app-google-auth (+2 query fields)")
        self.assertEqual(self.m.describe("https://docs.example/a"), "docs.example/a")

    def test_what_an_older_build_wrote_is_made_bare(self):
        old = (f"2026-11-04T10:54:50Z open-url open sign-in: {SIGNIN}\n"
               f"2026-11-04T10:54:58Z open-url hop watching for hop_nonce POH4Rq… (pid 7, group claude-signin)\n"
               f"2026-11-04T10:56:00Z hop the browser answered: code 4QXw…(43 chars); handing it to the app\n"
               f"2026-11-04T10:56:30Z hop ignoring an answer for hop_nonce Zx81kQ… — this sign-in is POH4Rq…\n"
               f"2026-11-04T10:57:00Z hop await: group 'x' await_timeout (url: {CALLBACK})\n"
               f"2026-11-04T10:58:00Z open-url not a web url, nothing opened: claude://login/google-auth?code={CODE}\n")
        clean = self.m.scrubbed(old)
        for secret in SECRETS + ("Zx81kQ",):
            self.assertNotIn(secret, clean)
        self.assertIn("claude.com/cai/login/app-google-auth?…", clean, "the line still says where it went")
        with Home(self.m) as home:
            Path(self.m.LOG).write_text(old, encoding="utf-8")
            self.m.scrub_logs()
            self.assertEqual(home.log(), clean)

    def test_the_apps_own_logs_keep_every_byte_but_a_sign_ins(self):
        """The app writes the link it is handed into its own logs (measured on the HP, 2026-11-05). Each secret
        is overwritten in place by dots of its own length: the file keeps its size, its inode and every other
        byte — `\\r\\n`, bytes that are not UTF-8, the app's own `code=139` — and the handle it holds keeps
        appending (the second reader of round 2)."""
        with Home(self.m):
            desktop_log, main_log = self.m.APP_LOGS
            history = b"x" * 300_000 + b"\r\n" + b"\xff\xfe not utf-8\n" + b"[main] exit code=139, window state=maximized\n"
            Path(desktop_log).write_bytes(history + f"open claude://login/google-auth?code={CODE}&hop_nonce={NONCE}\n".encode())
            Path(main_log).write_bytes(f"[info] auth state={STATE} hop_nonce={NONCE}\n[info] ready\n".encode())
            before = os.stat(desktop_log)
            with open(desktop_log, "ab") as the_apps_handle:
                self.assertEqual(self.m.mask_app_logs(), 3, "the link's query, the loose state and nonce")
                the_apps_handle.write(b"written after\n")
            data = Path(desktop_log).read_bytes()
            self.assertEqual(os.stat(desktop_log).st_ino, before.st_ino, "the same file, not a new one")
            self.assertEqual(len(data), before.st_size + len(b"written after\n"), "not a byte moved")
            self.assertTrue(data.startswith(history), "every other byte as it was")
            self.assertTrue(data.endswith(b"open claude://login/google-auth?" + b"." * (len(CODE) + len(NONCE) + 16)
                                          + b"\nwritten after\n"), "the query dotted, the app's handle still appending")
            masked = Path(main_log).read_bytes()
            self.assertEqual(len(masked), len(f"[info] auth state={STATE} hop_nonce={NONCE}\n[info] ready\n".encode()))
            for secret in SECRETS:
                self.assertNotIn(secret.encode(), data[len(history):] + masked)
            os.utime(main_log, ns=(1, 1))
            self.assertEqual(self.m.mask_app_logs(), 0)
            self.assertEqual(os.stat(main_log).st_mtime_ns, 1, "a masked file is not written again")

    def test_a_long_line_is_scanned_in_linear_time(self):
        """An unbounded scheme made every letter of a long word the start of a scan to its end (a 200 KB token
        took minutes), and a run of `http://a/,` was rescanned at every `://` (40 KB in 4 s, the second
        reader). Sized so that a regression fails in seconds instead of hanging."""
        import time as clock
        for run in ("A" * 40_000, "http://a/," * 4_000):
            started = clock.monotonic()
            self.assertEqual(self.m.scrubbed(run + " https://x.example/p?q=1"), run + " https://x.example/p?…")
            self.assertEqual(len(self.m.secret_spans((run + f" https://x.example/p?code={CODE}").encode())), 1)
            self.assertLess(clock.monotonic() - started, 1.5, run[:12])

    def test_the_scrub_is_a_verb_for_the_hop_and_a_sign_ins_worker_masks_a_links_does_not(self):
        with Home(self.m):
            app_log = Path(self.m.APP_LOGS[0])
            line = f"claude://login/google-auth?code={CODE}\n".encode()
            app_log.write_bytes(line)
            with patch.object(self.m, "bbox", return_value=done("{}")), \
                    patch.object(self.m.sys, "stdin", io.StringIO("https://docs.example/guide?page=2\n")):
                self.assertEqual(self.m.main(["bina-claude-open-url", "--deliver"]), 0)
            self.assertEqual(app_log.read_bytes(), line, "a plain link's worker leaves the app's logs alone")
            with patch.object(self.m, "deliver", return_value=0), \
                    patch.object(self.m.sys, "stdin", io.StringIO(SIGNIN + "\n")):
                self.assertEqual(self.m.main(["bina-claude-open-url", "--deliver"]), 0)
            dotted = b"claude://login/google-auth?" + b"." * (len(line) - 28) + b"\n"
            self.assertEqual(app_log.read_bytes(), dotted, "a sign-in's worker masks them, after its hand-off")
            app_log.write_bytes(line)
            self.assertEqual(self.m.main(["bina-claude-open-url", "--scrub"]), 0)
            self.assertEqual(app_log.read_bytes(), dotted)

    def test_a_sign_in_retires_the_old_watcher_and_hands_the_url_on_stdin(self):
        started = []

        class Proc:
            def __init__(self, argv, **kwargs):
                self.argv, self.kwargs, self.pid, self.written = argv, kwargs, 4242, b""
                self.stdin = types.SimpleNamespace(write=self.write, close=lambda: None)
                started.append(self)

            def write(self, data):
                self.written += data

        with Home(self.m) as home, patch.object(self.m.subprocess, "Popen", Proc), \
                patch.object(self.m, "stop_previous_hop") as stop:
            app_log = f"open claude://login/google-auth?code={CODE}\n"
            Path(self.m.APP_LOGS[0]).write_text(app_log, encoding="utf-8")
            self.assertEqual(self.m.main(["open-url", SIGNIN]), 0)
            self.assertEqual(Path(self.m.APP_LOGS[0]).read_text(encoding="utf-8"), app_log,
                             "the app's own logs are not read while the press waits (the worker scrubs them)")
            stop.assert_called_once()
            self.assertEqual(Path(self.m.CURRENT).read_text(), self.m.fingerprint(NONCE))
            worker = started[0]
            self.assertEqual(worker.argv[-1], "--deliver")
            self.assertNotIn(SIGNIN, " ".join(worker.argv), "the URL is never in an argv of ours")
            self.assertEqual(worker.written.decode().strip(), SIGNIN, "…it travels on stdin")
            for secret in SECRETS:
                self.assertNotIn(secret, home.log())
            self.assertIn("open sign-in: claude.com/cai/login/app-google-auth (+2 query fields)", home.log())
            self.assertEqual(self.m.main(["open-url", "claude://login/google-auth?code=x"]), 2)
            self.assertNotIn("code=x", home.log())

    def script(self, answers):
        """A fake `bbox` answering browser42 from a script; returns (bbox, calls)."""
        calls = []

        def bbox(*args, timeout=300, stdin=None):
            calls.append((args, stdin))
            for match, answer in answers:
                if args[:len(match)] == match:
                    return answer(args) if callable(answer) else answer
            return done("{}")

        return bbox, calls

    def test_the_hand_off_is_opened_verified_and_watched_with_its_episode(self):
        bbox, calls = self.script([
            (("b42", "open"), done(json.dumps({"ok": True, "slug": "claude-signin", "handoff": {"state": "needed", "id": "e1"}}))),
            (("b42", "await"), done(json.dumps({"ok": True, "state": "met",
                                                "url": f"https://accounts.google.com/o/oauth2/v2/auth?state={STATE}"})))])
        hops = []
        with Home(self.m) as home, patch.object(self.m, "bbox", side_effect=bbox), \
                patch.object(self.m, "hop", side_effect=lambda nonce, episode: hops.append((nonce, episode))), \
                patch.object(self.m.secrets, "token_hex", return_value="e1"), patch.object(self.m.time, "sleep"):
            self.assertEqual(self.m.deliver(SIGNIN), 0)
            opened = calls[0]
            self.assertEqual(opened[0], ("b42", "open", "bina-claude", "-", "--slug", "claude-signin", "--sentence",
                                         self.m.NEEDED, "--episode", "e1"), "the press's own episode, minted here")
            self.assertEqual(opened[1], SIGNIN + "\n", "the address reaches browser42 on stdin")
            self.assertEqual(hops, [(NONCE, "e1")])
            self.assertIn("opened in the office browser (group claude-signin, accounts.google.com/o/oauth2/v2/auth", home.log())
            for secret in SECRETS:
                self.assertNotIn(secret, home.log())

    def test_a_browser_that_never_opens_it_is_a_failed_hand_off_for_its_own_episode(self):
        bbox, calls = self.script([(("b42", "open"), done(json.dumps({
            "ok": False, "episode": "e1", "error": {"code": "browser_not_awake", "message": f"woke on {CALLBACK}"}}), 2))])
        with Home(self.m) as home, patch.object(self.m, "bbox", side_effect=bbox), \
                patch.object(self.m, "hop", side_effect=AssertionError("no hop for a sign-in that never opened")), \
                patch.object(self.m.secrets, "token_hex", return_value="e1"), patch.object(self.m.time, "sleep"):
            self.assertEqual(self.m.deliver(SIGNIN), 1)
            self.assertIn("open claude-signin (attempt 3): browser_not_awake", home.log(), "the code, never the message")
            for secret in SECRETS:
                self.assertNotIn(secret, home.log())
        self.assertEqual(sum(1 for a, _ in calls if a[:2] == ("b42", "open")), 3, "three tries")
        self.assertEqual(calls[-1][0], ("b42", "handoff", "claude-signin", "--failed", self.m.NOT_OPENED, "--episode", "e1"))

    def test_a_newer_press_retires_this_worker_without_a_word(self):
        # 1. superseded before the first open: nothing is opened, nothing is ended
        bbox, calls = self.script([])
        with Home(self.m) as home, patch.object(self.m, "bbox", side_effect=bbox), patch.object(self.m.time, "sleep"):
            Path(self.m.CURRENT).write_text(self.m.fingerprint("a-newer-nonce"))
            self.assertEqual(self.m.deliver(SIGNIN), 0)
            self.assertIn("a newer sign-in started", home.log())
        self.assertEqual(calls, [])
        # 2. browser42 says a newer attempt owns the hand-off, and a newer press DID start: no retry, no failed, no hop
        superseded = done(json.dumps({"ok": False, "episode": "e1", "error": {"code": "superseded", "message": "x"}}), 2)

        def newer_meanwhile(args):
            Path(self.m.CURRENT).write_text(self.m.fingerprint("a-newer-nonce"))
            return superseded

        bbox, calls = self.script([(("b42", "open"), newer_meanwhile)])
        with Home(self.m), patch.object(self.m, "bbox", side_effect=bbox), patch.object(self.m.time, "sleep"), \
                patch.object(self.m, "hop", side_effect=AssertionError("no hop for a superseded attempt")):
            self.assertEqual(self.m.deliver(SIGNIN), 0)
        self.assertEqual([a[:2] for a, _ in calls], [("b42", "open")])
        # 2b. …while this press is still the newest, browser42's «superseded» is an older press that wrote after
        #     it (a slower exec): this press asks again, and its sign-in goes on (the second reader of DGO-1336)
        answers = [superseded, done(json.dumps({"ok": True, "handoff": {"id": "e1"}}))]
        bbox, calls = self.script([
            (("b42", "open"), lambda args: answers.pop(0)),
            (("b42", "await"), done(json.dumps({"ok": True, "state": "met",
                                                "url": f"https://accounts.google.com/o/oauth2/v2/auth?state={STATE}"})))])
        hops = []
        with Home(self.m) as home, patch.object(self.m, "bbox", side_effect=bbox), patch.object(self.m.time, "sleep"), \
                patch.object(self.m, "hop", side_effect=lambda nonce, episode: hops.append(nonce)):
            Path(self.m.CURRENT).write_text(self.m.fingerprint(NONCE))
            self.assertEqual(self.m.deliver(SIGNIN), 0)
            self.assertIn("an older press wrote after this one — asking again", home.log())
        self.assertEqual(hops, [NONCE])
        # 3. superseded while its tab was being checked: no hop
        bbox, calls = self.script([(("b42", "open"), done(json.dumps({"ok": True, "handoff": {"id": "e1"}})))])
        with Home(self.m), patch.object(self.m, "bbox", side_effect=bbox), \
                patch.object(self.m.time, "sleep", side_effect=lambda s: Path(self.m.CURRENT).write_text("someone-else")), \
                patch.object(self.m, "hop", side_effect=AssertionError("no hop for a superseded attempt")):
            self.assertEqual(self.m.deliver(SIGNIN), 0)

    def test_a_plain_link_opens_in_its_own_group_and_is_no_hand_off(self):
        bbox, calls = self.script([])
        with Home(self.m) as home, patch.object(self.m, "bbox", side_effect=bbox), \
                patch.object(self.m, "hop", side_effect=AssertionError("nothing watches a link")):
            self.assertEqual(self.m.deliver("https://docs.example/guide?page=2"), 0)
            self.assertIn("link opened in the office browser (group claude-links): docs.example/guide (+1 query fields)", home.log())
        self.assertEqual(calls, [(("b42", "group", "claude-links", "-"), "https://docs.example/guide?page=2\n")],
                         "its own group, no hand-off, and the address on stdin too")

    def test_a_command_that_does_not_answer_is_an_answer_not_a_crash(self):
        with patch.object(self.m.subprocess, "run", side_effect=subprocess.TimeoutExpired(["bbox"], 300)):
            self.assertEqual(self.m.bbox("b42", "open").returncode, 124)
        with patch.object(self.m.subprocess, "run", side_effect=FileNotFoundError("bbox")):
            self.assertEqual(self.m.bbox("b42", "open").returncode, 124)

    def test_only_a_hop_is_stopped_and_the_log_says_what_happened(self):
        with Home(self.m) as home:
            Path(self.m.PIDFILE).write_text("99999")
            with patch.object(self.m, "cmdline", return_value=b"/usr/sbin/sshd\x00-D"), \
                    patch.object(self.m.os, "killpg") as kill:
                self.m.stop_previous_hop()
                kill.assert_not_called()
            self.assertFalse(Path(self.m.PIDFILE).exists(), "a stale pid file is gone either way")
            self.assertEqual(home.log(), "", "a reused pid is not a hop, and nothing is claimed about it")
            state = {"alive": True}
            Path(self.m.PIDFILE).write_text("4243")
            with patch.object(self.m, "cmdline", return_value=b"python3\x00/usr/local/bin/bina-claude-hop\x00-"), \
                    patch.object(self.m.os, "killpg", side_effect=lambda pid, sig: state.update(alive=False)), \
                    patch.object(self.m, "alive", side_effect=lambda pid: state["alive"]):
                self.m.stop_previous_hop()
            self.assertIn("the previous hop (pid 4243) stopped", home.log())
            Path(self.m.PIDFILE).write_text("4244")
            clock = FakeClock()
            with patch.object(self.m, "cmdline", return_value=b"python3\x00/usr/local/bin/bina-claude-hop\x00-"), \
                    patch.object(self.m.os, "killpg"), patch.object(self.m, "alive", return_value=True), \
                    patch.object(self.m.time, "monotonic", clock.monotonic), patch.object(self.m.time, "sleep", clock.sleep):
                self.m.stop_previous_hop()
            self.assertIn("the previous hop (pid 4244) did not stop within 5 s", home.log(), "said as it is, never «stopped»")


class HopTests(unittest.TestCase):
    def setUp(self):
        self.m = load("hop")
        self.clock = FakeClock()

    def run_hop(self, home, answers, signed_in=(), current=None, marks=(None,), newer_at=None, handoff_exit=0,
                scrub_exit=0):
        """Run the hop to its end against scripted browser42/bina-claude answers; return (exit, calls).
        `signed_in` scripts `./bbox bina-claude signed-in` (the first answer is the one before delivery);
        `marks` scripts the app's session cookie's creation time (the first before delivery, the last
        repeats); `newer_at` = a call number after which a newer press has replaced this sign-in."""
        calls, script, signed, made = [], list(answers), list(signed_in), list(marks)
        if current is not None:
            Path(self.m.CURRENT).write_text(current)

        def bbox(*args, timeout=600):
            calls.append(args)
            if newer_at is not None and len(calls) >= newer_at:
                Path(self.m.CURRENT).write_text("someone-else")
            if args[:2] == ("b42", "await"):
                self.clock.now += 5
                item = script.pop(0) if script else {"ok": False, "error": {"code": "await_timeout",
                                                                             "message": f"(url: {CALLBACK})"}}
                return done(json.dumps(item), 0 if item.get("ok") else 2)
            if args == ("bina-claude", "signed-in"):
                return done("", 0 if (signed.pop(0) if signed else False) else 3)
            if args[:3] == ("b42", "handoff", "claude-signin"):
                return done("{}", handoff_exit)
            return done("{}")

        lines = iter([NONCE + "\n", "e1\n"])
        with patch.object(self.m, "bbox", side_effect=bbox), patch.object(self.m, "window", return_value="0x1"), \
                patch.object(self.m, "session_mark", side_effect=lambda: made.pop(0) if len(made) > 1 else made[0]), \
                patch.object(self.m.subprocess, "run",
                             side_effect=lambda argv, **kw: done("", scrub_exit if argv[-1:] == ["--scrub"] else 0)) as app, \
                patch.object(self.m.time, "monotonic", self.clock.monotonic), \
                patch.object(self.m.time, "sleep", self.clock.sleep), \
                patch.object(self.m.sys, "stdin", types.SimpleNamespace(readline=lambda: next(lines, ""))):
            code = self.m.main(["hop", "-"])
        self.app_calls = [c.args[0] for c in app.call_args_list if c.args[0][0] == "claude-desktop"]
        self.scrubs = [c.args[0] for c in app.call_args_list if c.args[0] == [self.m.OPENER, "--scrub"]]
        for secret in SECRETS:
            self.assertNotIn(secret, home.log(), "no part of the sign-in's secrets in the log")
        return code, calls

    CLOSE = ("b42", "close", "claude-signin", "--episode", "e1")

    def test_an_answer_to_this_sign_in_signs_the_app_in_and_ends_its_episode_done(self):
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=[False, False, True],
                                       current=load("open-url").fingerprint(NONCE), marks=[None, 13300000000000000])
            self.assertIn("signed in — the app holds a claude.ai session it did not hold before", home.log())
        self.assertEqual(code, 0)
        self.assertIn(("b42", "handoff", "claude-signin", "--done", "--episode", "e1"), calls)
        self.assertEqual(calls[-1], self.CLOSE, "the tab holding the spent code is closed, by episode")
        link = self.app_calls[0][-1]
        self.assertTrue(link.startswith("claude://login/google-auth?"))
        self.assertEqual(self.app_calls[0][1:-1], self.m.APP_FLAGS)

    def test_leftover_bytes_or_another_cookie_are_not_this_sign_in(self):
        """`signed-in` already 0 before the code was handed over, and no NEW session cookie after: not done."""
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=[True] * 40,
                                       marks=[13300000000000000])
            self.assertIn("the app took the code but is not signed in", home.log())
        self.assertEqual(code, 1)
        self.assertIn(("b42", "handoff", "claude-signin", "--failed", self.m.NOT_SIGNED_IN, "--episode", "e1"), calls)
        with Home(self.m):
            code, calls = self.run_hop(Home(self.m), [{"ok": True, "state": "met", "url": CALLBACK}],
                                       signed_in=[True] * 40, marks=[13300000000000000, 13300000000000999])
        self.assertEqual(code, 0, "…while a session cookie made after the code was handed over is")
        with Home(self.m):            # the store unreadable: only the hook's own turn from 3 to 0 counts
            code, _ = self.run_hop(Home(self.m), [{"ok": True, "state": "met", "url": CALLBACK}],
                                   signed_in=[False, True], marks=[None])
        self.assertEqual(code, 0)

    def test_the_session_mark_is_read_from_the_apps_own_store(self):
        import sqlite3
        with Home(self.m):
            db = sqlite3.connect(self.m.COOKIES)
            db.execute("CREATE TABLE cookies (creation_utc INTEGER, host_key TEXT, name TEXT, value TEXT)")
            db.executemany("INSERT INTO cookies VALUES (?, ?, ?, ?)", [
                (5, ".claude.ai", "sessionKey", "x"), (9, ".claude.ai", "sessionKey", "y"),
                (99, ".claude.ai", "__cf_bm", "z"), (77, ".example.com", "sessionKey", "w")])
            db.commit()
            db.close()
            self.assertEqual(self.m.session_mark(), 9, "the newest claude.ai session cookie — nothing else")
            Path(self.m.COOKIES).write_text("not a database")
            self.assertIsNone(self.m.session_mark(), "an unreadable store is «not known»")

    def test_a_delivered_code_that_does_not_sign_the_app_in_is_failed_not_delivered(self):
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=[])
            self.assertNotIn("delivered", home.log())
        self.assertEqual(code, 1)
        self.assertIn(("b42", "handoff", "claude-signin", "--failed", self.m.NOT_SIGNED_IN, "--episode", "e1"), calls)
        self.assertFalse([c for c in calls if c[:4] == ("b42", "handoff", "claude-signin", "--done")])
        self.assertEqual(calls[-1], self.CLOSE, "a failed sign-in's tab (Google's state in its address) is closed too")

    def test_another_attempts_answer_is_not_ours_and_no_answer_in_time_is_failed(self):
        other = CALLBACK.replace(NONCE, "SomeoneElse9")
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": other}] * 3)
            self.assertIn("ANOTHER sign-in", home.log())
            self.assertIn("await says await_timeout", home.log(), "the error's code, never its message")
        self.assertEqual(code, 1)
        self.assertEqual(self.app_calls, [], "nothing handed to the app")
        self.assertEqual(calls[-2:], [("b42", "handoff", "claude-signin", "--failed", self.m.NO_ANSWER, "--episode", "e1"),
                                      self.CLOSE])

    def test_a_newer_sign_in_retires_this_watcher_without_a_word_to_the_person(self):
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}],
                                       current=load("open-url").fingerprint("a-newer-nonce"))
            self.assertIn("a newer sign-in started", home.log())
        self.assertEqual(code, 0)
        self.assertFalse([c for c in calls if c[:2] == ("b42", "handoff")], "the new attempt owns the hand-off")
        with Home(self.m):            # …and one that arrives while this one delivers: nothing ended, no tab closed
            code, calls = self.run_hop(Home(self.m), [{"ok": True, "state": "met", "url": CALLBACK}],
                                       signed_in=[False, True], newer_at=3, marks=[None, 7])
        self.assertFalse([c for c in calls if c[:2] in (("b42", "handoff"), ("b42", "close"))])

    def test_an_end_browser42_refuses_as_superseded_is_said_and_nothing_more(self):
        with Home(self.m) as home:
            code, calls = self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=[False, True],
                                       handoff_exit=3, marks=[None, 7])
            self.assertIn("the hand-off belongs to a newer attempt", home.log())
        self.assertEqual(code, 0)
        self.assertFalse([c for c in calls if c[:2] == ("b42", "close")], "the tab is the newer attempt's")

    def test_every_end_masks_the_apps_logs_and_a_scrub_that_fails_is_said(self):
        """The app has written the link it was handed; the opener masks its logs however the sign-in ended —
        superseded too, since the code may already have been handed over (the second reader of round 2)."""
        for signed, marks, handoff_exit in (([False, False, True], [None, 7], 0),     # done
                                            ([], [None], 0),                         # failed
                                            ([False, True], [None, 7], 3)):          # superseded, after delivery
            with Home(self.m) as home:
                self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=signed, marks=marks,
                             handoff_exit=handoff_exit)
            self.assertEqual(len(self.scrubs), 1, (handoff_exit, signed))
        with Home(self.m) as home:
            self.run_hop(home, [{"ok": True, "state": "met", "url": CALLBACK}], signed_in=[False, True], marks=[None, 7],
                         scrub_exit=1)
            self.assertIn("the app's logs were not masked after the sign-in (the opener's scrub exited 1)", home.log())

    def test_a_watcher_that_breaks_says_so_on_the_screen(self):
        with Home(self.m) as home, patch.object(self.m, "watch", side_effect=KeyError("boom")), \
                patch.object(self.m.subprocess, "run", return_value=done()), \
                patch.object(self.m, "bbox", return_value=done("{}")) as bbox, \
                patch.object(self.m.sys, "stdin", types.SimpleNamespace(readline=iter([NONCE + "\n", "e1\n"]).__next__)):
            self.assertEqual(self.m.main(["hop", "-"]), 1)
            self.assertIn("this watcher stopped on an error (KeyError)", home.log())
        self.assertEqual([c.args for c in bbox.call_args_list],
                         [("b42", "handoff", "claude-signin", "--failed", self.m.BROKE, "--episode", "e1"), self.CLOSE])

    def test_the_app_is_launched_with_its_own_start_flags(self):
        autostart = (HERE / "desktop" / "autostart").read_text(encoding="utf-8")
        line = next(l for l in autostart.splitlines() if l.strip().startswith("claude-desktop "))
        self.assertEqual(re.findall(r"--[a-z-]+(?:=[a-z-]+)?", line), self.m.APP_FLAGS,
                         "a launch that becomes the main instance keeps the keyring (DGO-1335)")

    def test_the_two_halves_are_mounted_so_a_fix_needs_no_image(self):
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("- ./desktop/open-url:/usr/local/bin/bina-claude-open-url:ro", compose)
        self.assertIn("- ./desktop/hop:/usr/local/bin/bina-claude-hop:ro", compose)
        for name in ("open-url", "hop"):
            self.assertTrue(os.access(HERE / "desktop" / name, os.X_OK), f"desktop/{name} is executable")


if __name__ == "__main__":
    unittest.main()
