#!/usr/bin/env python3
"""test_cli — «סלאק»'s CLI (tools/cli.py) end to end: the real adapter (adapter/server.py) in front of the fake
Slack Web API of adapter/test_server.py (DGO-1264).

What is asked: status says how to sign in; login reads the token from stdin and a wrong call exits 2; rooms
prints one line per conversation and a name holding a newline stays one line; Slack's own error (not_in_channel)
exits 1 with its name; a rate limit says how long to wait; the adapter down is exit 3.

Run: python3 apps/slack/tools/test_cli.py   (standard library only)
"""
import contextlib
import importlib.util
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("slack_adapter_tests", os.path.join(HERE, "..", "adapter", "test_server.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)            # starts the fake Web API and the real adapter, sets SLACK_STATE

os.environ["SLACK_ADAPTER_URL"] = fixture.AD_URL
spec = importlib.util.spec_from_file_location("slack_cli", os.path.join(HERE, "cli.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def run(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old
    return code, out.getvalue(), err.getvalue()


class Cli(unittest.TestCase):
    def setUp(self):
        fixture.srv.drop_session()
        fixture.RATE_LIMIT["on"] = False

    def login(self):
        code, out, err = run("login", "--token-stdin", stdin="xoxp-good\n")
        self.assertEqual(code, 0, err)
        return out

    def test_status_says_how_and_login_reads_stdin(self):
        code, out, _ = run("status")
        self.assertEqual(code, 0)
        self.assertIn("login --token-stdin", out)
        self.assertIn("המשרד", self.login())
        for argv in (("login", "xoxp-good"), ("rooms", "x"), ("read",), ("nope",)):
            self.assertEqual(run(*argv)[0], 2, argv)
        self.assertEqual(run("login", "--token-stdin", stdin="")[0], 2)

    def test_rooms_one_line_each(self):
        self.login()
        code, out, _ = run("rooms")
        self.assertEqual(code, 0)
        self.assertEqual([ln.split("\t") for ln in out.splitlines()],
                         [["C0000001", "general", "channel"], ["G0000002", "board", "private"], ["D0000003", "U9", "dm"]])
        self.assertEqual(cli.flat("a\nb\tc"), "a b c")

    def test_slacks_error_and_the_rate_limit_are_said(self):
        self.login()
        code, _, err = run("read", "C0000009")
        self.assertEqual(code, 1)
        self.assertIn("not_in_channel", err)
        fixture.RATE_LIMIT["on"] = True
        code, _, err = run("rooms")
        self.assertEqual(code, 1)
        self.assertIn("wait 7 s", err)

    def test_send_mark_read_logout_and_the_adapter_down(self):
        self.login()
        code, out, _ = run("send", "C0000001", "hi", "there")
        self.assertEqual((code, out.strip()), (0, "sent\t1700000003.000300"))
        self.assertEqual(run("mark-read", "C0000001", "1700000002.000200")[:2], (0, "ok\n"))
        self.assertEqual(run("mark-read", "C0000001", "yesterday")[0], 1)
        code, out, _ = run("logout", "--json")
        self.assertEqual(code, 0)
        self.assertIn('"forgotten": true', out)
        saved = cli.BASE
        cli.BASE = "http://127.0.0.1:9"
        try:
            self.assertEqual(run("status")[0], 3)
        finally:
            cli.BASE = saved


if __name__ == "__main__":
    unittest.main()
