#!/usr/bin/env python3
"""test_cli — «אלמנט»'s CLI (tools/cli.py) end to end: the real adapter (adapter/server.py) in front of the fake
homeserver of adapter/test_server.py (DGO-1264).

What is asked, of the standard's exits and of what a line may hold:
- status answers 0 signed out and says how to sign in; `--json` is the adapter's own answer;
- login reads the password from stdin (never an argument) and refuses a terminal; a wrong call exits 2;
- rooms prints one line per room, id · name · encrypted|plain · unread, and a name holding a newline stays
  one line;
- read marks an encrypted message instead of printing nothing; send into an encrypted room exits 1 with the
  adapter's reason;
- the adapter down is exit 3.

Run: python3 apps/element/tools/test_cli.py   (standard library only)
"""
import contextlib
import importlib.util
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "adapter"))
spec = importlib.util.spec_from_file_location("element_adapter_tests", os.path.join(HERE, "..", "adapter", "test_server.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)            # starts the fake homeserver and the real adapter, sets ELEMENT_STATE

os.environ["ELEMENT_ADAPTER_URL"] = fixture.AD_URL
spec = importlib.util.spec_from_file_location("element_cli", os.path.join(HERE, "cli.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class Tty(io.StringIO):
    def isatty(self):
        return True


def run(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    sys.stdin = stdin if isinstance(stdin, io.StringIO) else io.StringIO(stdin)
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

    def login(self):
        code, out, err = run("login", fixture.HS_URL, "owner", "--password-stdin", stdin="right\n")
        self.assertEqual(code, 0, err)
        return out

    def test_status_signed_out_says_how(self):
        code, out, _ = run("status")
        self.assertEqual(code, 0)
        self.assertIn("not signed in", out)
        code, out, _ = run("status", "--json")
        self.assertIn('"signed_in": false', out)

    def test_login_reads_stdin_refuses_a_terminal_and_wrong_calls_exit_2(self):
        self.assertIn("@owner:hs.test", self.login())
        code, _, err = run("login", fixture.HS_URL, "owner", "--password-stdin", stdin=Tty("x"))
        self.assertEqual(code, 2)
        self.assertIn("terminal", err)
        for argv in (("login", fixture.HS_URL, "owner", "right"), ("rooms", "x"), ("read",), ("nope",)):
            self.assertEqual(run(*argv)[0], 2, argv)

    def test_a_wrong_password_exits_1_with_the_homeservers_reason(self):
        code, _, err = run("login", fixture.HS_URL, "owner", "--password-stdin", stdin="wrong\n")
        self.assertEqual(code, 1)
        self.assertIn("M_FORBIDDEN", err)

    def test_rooms_one_line_each(self):
        self.login()
        code, out, _ = run("rooms")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0].split("\t"), [fixture.SECRET, "#secret:hs.test", "encrypted", "0"])
        self.assertEqual(cli.flat("a\nFrom: ceo\tx"), "a From: ceo x")

    def test_read_marks_encrypted_and_send_into_one_exits_1(self):
        self.login()
        code, out, _ = run("read", fixture.PLAIN, "5")
        self.assertEqual(code, 0)
        self.assertIn("שלום", out)
        self.assertIn("[encrypted — read it on the screen]", out)
        code, _, err = run("send", fixture.SECRET, "hi", "there")
        self.assertEqual(code, 1)
        self.assertIn("encrypted-room", err)
        code, out, _ = run("send", fixture.PLAIN, "hi", "there")
        self.assertEqual((code, out.strip()), (0, "sent\t$sent"))

    def test_the_adapter_down_is_exit_3(self):
        saved = cli.BASE
        cli.BASE = "http://127.0.0.1:9"
        try:
            self.assertEqual(run("status")[0], 3)
        finally:
            cli.BASE = saved


if __name__ == "__main__":
    unittest.main()
