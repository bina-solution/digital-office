#!/usr/bin/env python3
"""test_cli — the mail CLI's reads `thread` and `labels` and its writes `mark` and `tag` (DGO-1255), with
the mail API replaced.

What is asked:
- `thread <id>` asks for headers only (`bodies=false`, so no message is marked \\Seen) on the mailbox
  named;
- a thread id that is not hex is refused before anything is sent;
- `labels` prints one label per line, so a name holding a newline cannot forge a second line;
- a labels answer that is not a list is said, never printed as «no labels»;
- a write without -p is refused before anything is sent (the default may be a client's real Gmail);
- `mark` states its intent once (/api/mark), `--off` takes it away, and an unknown mark or a non-hex id is
  refused before anything is sent;
- `tag` adds +names and removes -names, and a bare word is refused.

Measured on vps1's mail through the link (2026-11-10): `thread 32` printed its 4 messages, and `labels`
printed the mailbox's labels.

Run: python3 apps/mail/test_cli.py   (standard library only)
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mail_cli", os.path.join(HERE, "cli.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
CALLS = []
ANSWER = {"text": "{}"}


def fake_get(path, params=None):
    CALLS.append((path, dict(params or {})))
    return ANSWER["text"]


def fake_post(path, body):
    CALLS.append((path, dict(body)))
    return {"ok": True, "count": len(body.get("ids") or [1])}


REAL_POST = cli.post
cli.get = fake_get
cli.post = fake_post
cli.mailbox = lambda flags: "mail_imap_local-1"     # the mailbox the flags named (resolving it is not this test's)


def fake_pick(word):                                # -p <word> names conn-<word> (resolving it is not this test's)
    CALLS.append(("pick", {"word": word}))
    return "conn-" + word


cli.pick = fake_pick


def run(*argv, text="{}"):
    CALLS.clear()
    ANSWER["text"] = text
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            cli.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), list(CALLS)


class Reads(unittest.TestCase):
    def test_thread_asks_for_headers_only_on_the_named_mailbox(self):
        code, out, calls = run("thread", "32", text='{"messages": []}')
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("/api/thread/32", {"bodies": "false", "connection_id": "mail_imap_local-1"})])

    def test_a_thread_id_that_is_not_hex_is_refused_before_anything_is_sent(self):
        for bad in ("x;y", "1&meta=false", "../labels"):
            code, _, calls = run("thread", bad)
            self.assertNotEqual(code, 0, bad)
            self.assertEqual(calls, [], bad)

    def test_labels_one_per_line_and_flattened(self):
        code, out, _ = run("labels", text=json.dumps({"labels": ["INBOX", "a\nFrom: ceo", "  two  words "]}))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["INBOX", "a From: ceo", "two words"])

    def test_labels_that_did_not_answer_are_said(self):
        code, out, _ = run("labels", text="upstream timeout")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")


class Writes(unittest.TestCase):
    def test_a_write_without_a_named_mailbox_is_refused_before_anything_is_sent(self):
        for argv in (("mark", "1a", "starred"), ("tag", "1a", "+Work")):
            code, _, calls = run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertEqual(calls, [], argv)

    def test_a_blank_or_a_second_mailbox_flag_is_refused_before_anything_is_asked(self):
        # an empty word would match every mailbox by prefix; a second -p would move the write elsewhere
        for argv in (("mark", "1a", "starred", "-p"), ("-p", "", "mark", "1a", "starred"),
                     ("-p", " ", "tag", "1a", "+Work"), ("-p", "office", "tag", "1a", "+Work", "-p", "gmail")):
            code, _, calls = run(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertEqual([c for c in calls if c[0] != "pick"], [], argv)
        self.assertEqual(run("mark", "1a", "starred", "-p")[2], [])           # nothing was resolved at all

    def test_mark_states_the_intent_once_on_the_named_mailbox(self):
        code, out, calls = run("-p", "office", "mark", "1a", "2b", "starred")
        self.assertEqual(code, 0)
        self.assertEqual(calls[1:], [("/api/mark", {"ids": ["1a", "2b"], "mark": "starred", "on": True,
                                                    "connection_id": "conn-office"})])
        self.assertEqual(out.split("\t")[:3], ["asked", "starred on", "2 message(s)"])

    def test_mark_off_takes_the_mark_away(self):
        code, _, calls = run("mark", "1a", "archived", "--off", "-p", "office")
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1][1]["on"], False)
        self.assertEqual(calls[-1][1]["mark"], "archived")

    def test_mark_refuses_an_unknown_mark_an_id_that_is_not_hex_or_too_many(self):
        many = [format(i, "x") for i in range(cli.MAX_IDS + 1)]
        for argv in (("mark", "1a", "trash"), ("mark", "1a&x=1", "starred"), ("mark", "starred"),
                     ("mark", *many, "starred")):
            code, _, calls = run("-p", "office", *argv)
            self.assertNotEqual(code, 0, argv[:3])
            self.assertEqual([c for c in calls if c[0] != "pick"], [], argv[:3])

    def test_tag_adds_and_removes_by_name_as_the_screen_would_save_it(self):
        code, _, calls = run("-p", "office", "tag", "1a", "+לקוחות", "-INBOX", "+ Work  now")
        self.assertEqual(code, 0)
        self.assertEqual(calls[1:], [("/api/tag", {"id": "1a", "add": ["לקוחות", "Work now"], "remove": ["INBOX"],
                                                   "connection_id": "conn-office"})])

    def test_tag_refuses_a_bare_word_or_a_label_both_added_and_removed(self):
        for argv in (("tag", "1a", "Work"), ("tag", "1a", "+"), ("tag", "zz", "+Work"), ("tag", "1a", "+X", "-X")):
            code, _, calls = run("-p", "office", *argv)
            self.assertNotEqual(code, 0, argv)
            self.assertEqual([c for c in calls if c[0] != "pick"], [], argv)


class Post(unittest.TestCase):
    """post() itself, with urlopen replaced: every answer that is not {"ok": true} fails with a message."""

    def answer(self, body=None, exc=None):
        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body

        def opener(req, timeout=None):
            if exc:
                raise exc
            return R()
        real, cli.urllib.request.urlopen = cli.urllib.request.urlopen, opener
        try:
            REAL_POST("/api/mark", {"ids": ["1a"]})
            return 0, ""
        except SystemExit as e:
            return 1, str(e.code)
        finally:
            cli.urllib.request.urlopen = real

    def test_ok_passes_and_everything_else_fails_with_a_message(self):
        self.assertEqual(self.answer(b'{"ok": true, "count": 1}')[0], 0)
        for body in (b"[]", b'"ok"', b'{"ok": false}', b"{}", b"<html>"):
            code, msg = self.answer(body)
            self.assertEqual(code, 1, body)
            self.assertIn("unknown", msg, body)

    def test_a_broken_answer_says_the_change_may_be_partly_made(self):
        code, msg = self.answer(exc=cli.http.client.BadStatusLine("HELLO"))
        self.assertEqual(code, 1)
        self.assertIn("unknown", msg)
        code, msg = self.answer(exc=cli.urllib.error.URLError("refused"))
        self.assertEqual(code, 1)
        self.assertIn("nothing was changed", msg)


if __name__ == "__main__":
    unittest.main()
