# -*- coding: utf-8 -*-
"""A written account is watched until the server lets it in (DGO-1025).

docker-mailserver takes its change detector's baseline after it has read the accounts file, so a line
written in between is never applied: the account exists in the file and the server says `unknown
user`. mailboxd logs in as what it wrote, and when a server that answers keeps refusing, it rewrites
one comment line — a change the detector sees, and nothing the server reads.

No network, no doveadm, no volume: `python3 -m pytest apps/mail/mailboxd/test_confirm.py`.
"""
import itertools
import os
import sys
import tempfile

import pytest

os.environ.update(MAILBOXD_CFG=tempfile.mkdtemp(prefix="zz-mailboxd-"), MAIL_DOMAIN="acme.test",
                  LOCALMAIL_USER="office")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mailboxd  # noqa: E402

ACCOUNTS = "office@acme.test|{SHA512-CRYPT}one\ndana@acme.test|{SHA512-CRYPT}two\n"
LINE = "dana@acme.test|{SHA512-CRYPT}two"


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    with open(mailboxd.ACCOUNTS, "w", encoding="utf-8") as fh:
        fh.write(ACCOUNTS)
    clock = [0.0]
    monkeypatch.setattr(mailboxd.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(mailboxd.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(mailboxd, "CONFIRM_FOR", 120)


def read():
    with open(mailboxd.ACCOUNTS, encoding="utf-8") as fh:
        return fh.read()


def marks():
    return [ln for ln in read().splitlines() if ln.startswith(mailboxd.NUDGE_MARK)]


def test_a_live_account_is_left_alone(monkeypatch):
    monkeypatch.setattr(mailboxd, "_login", lambda a, p: True)
    mailboxd._confirm("dana@acme.test", "pw", LINE)
    assert read() == ACCOUNTS


def test_the_watched_usernames_are_exactly_dovecots_default_set():
    """The reader of d414664e: a set narrowed by a later edit (no `-`, no digits) would stop watching every
    account of an office whose domain holds one, with every other test still green."""
    accepted = {chr(c) for c in range(0x110000) if mailboxd.DOVECOT_USERNAME.match(chr(c))}
    assert accepted == set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01234567890.-_@")
    for refused in ("", "x@acme.test\n", "x y@acme.test"):
        assert not mailboxd.DOVECOT_USERNAME.match(refused), repr(refused)


def test_an_address_of_every_allowed_kind_is_watched(monkeypatch):
    tries = []
    monkeypatch.setattr(mailboxd, "_login", lambda a, p: tries.append(a) or True)
    mailboxd._confirm("person89_x-x@example.com", "pw", LINE)
    assert tries == ["person89_x-x@example.com"]


def test_a_silent_server_is_waited_for_never_nudged(monkeypatch):
    monkeypatch.setattr(mailboxd, "_login", lambda a, p: None)
    mailboxd._confirm("dana@acme.test", "pw", LINE)
    assert read() == ACCOUNTS


def test_a_refused_account_is_nudged_once_per_settle_and_the_accounts_kept(monkeypatch):
    tries = iter([False] * 5 + [True])
    monkeypatch.setattr(mailboxd, "_login", lambda a, p: next(tries))
    mailboxd._confirm("dana@acme.test", "pw", LINE)
    assert len(marks()) == 1                                  # replaced, never piled up
    assert [a for a, _h in mailboxd._entries()] == ["office@acme.test", "dana@acme.test"]
    assert read().startswith(ACCOUNTS)


def test_a_line_no_longer_in_the_file_stops_the_watch(monkeypatch):
    monkeypatch.setattr(mailboxd, "_login", lambda a, p: False)
    mailboxd._confirm("dana@acme.test", "pw", "dana@acme.test|{SHA512-CRYPT}rotated")
    assert read() == ACCOUNTS


class Server:
    """imaplib.IMAP4 as a server answers it: a greeting that never comes, or a login."""
    error = mailboxd.imaplib.IMAP4.error
    abort = mailboxd.imaplib.IMAP4.abort
    greets, accepts, said = True, True, []

    def __init__(self, host, port, timeout=None):
        if not Server.greets:
            raise self.abort("socket error: EOF")            # closed before its greeting

    def login(self, user, password):
        (user + password).encode("ascii")                    # what imaplib's LOGIN does to its command
        if "\r" in password or "\n" in password:             # …and a quoted string cannot carry these
            raise self.error("b'BAD Error in IMAP command: Unexpected line break'")
        Server.said.append(("LOGIN", user))
        if not Server.accepts:
            raise self.error("b'[AUTHENTICATIONFAILED] Authentication failed.'")

    def authenticate(self, mechanism, answer):
        Server.said.append((mechanism, answer(b"")))
        if not Server.accepts:
            raise self.error("b'[AUTHENTICATIONFAILED] Authentication failed.'")

    def logout(self):
        pass


@pytest.fixture
def server(monkeypatch):
    Server.greets, Server.accepts, Server.said = True, True, []
    monkeypatch.setattr(mailboxd.imaplib, "IMAP4", Server)
    return Server


def test_a_server_that_closes_before_its_greeting_is_silence_not_an_escape(server):
    """The second reader of DGO-1025: `IMAP4.abort` from the greeting ended the watch with a traceback."""
    server.greets = False
    assert mailboxd._login("dana@acme.test", "a-password") is None


def test_a_password_that_is_not_ascii_is_proved_over_sasl_plain(server):
    """imaplib's LOGIN sends ASCII only; a Hebrew password raised, on every try, and the watch died."""
    assert mailboxd._login("dana@acme.test", "סיסמה-ארוכה-1") is True
    (mechanism, answer), = server.said
    assert mechanism == "PLAIN" and answer == "\0dana@acme.test\0סיסמה-ארוכה-1".encode("utf-8")
    server.said, server.accepts = [], False
    assert mailboxd._login("dana@acme.test", "סיסמה-ארוכה-1") is False


def test_a_password_with_a_line_break_is_proved_over_sasl_plain(server):
    """The reader of rel12: LOGIN's quoted string cannot carry CR or LF — the command was cut short, the
    server answered BAD, and the account was never proved. Each of the two on its own."""
    for password in ("a-password\n", "a-pass\rword"):
        server.said = []
        assert mailboxd._login("dana@acme.test", password) is True, repr(password)
        (mechanism, answer), = server.said
        assert mechanism == "PLAIN" and answer == ("\0dana@acme.test\0" + password).encode("utf-8")


def test_an_address_the_servers_default_refuses_is_said_and_never_nudged(monkeypatch, capsys):
    """The readers of rel12: Dovecot's default refuses such a username by LOGIN and by PLAIN alike, and
    a watched refusal is a nudge every settle — 45 rewrites of the accounts file in one watch. Not only
    a Hebrew address: `+` and `'` are outside the default too."""
    for address in ("דנה@acme.test", "billing+in@acme.test", "o'brien@acme.test"):
        tries = []
        monkeypatch.setattr(mailboxd, "_login", lambda a, p: tries.append(a) or False)
        mailboxd._confirm(address, "pw", LINE)
        assert tries == [] and marks() == [], address
        assert "refuses in a username" in capsys.readouterr().out
    assert read() == ACCOUNTS


class Inline:
    """threading.Thread that runs its target on start(): the delete's watch, in the test's own time."""
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def nudges(monkeypatch):
    """Every nudge, at the (fake) second it was made: the marker is REPLACED, so the file shows one however
    many were made — and a nudge that comes 900 s late looks the same in the file."""
    made, nudge = [], mailboxd._nudge
    monkeypatch.setattr(mailboxd, "_nudge", lambda: made.append(int(mailboxd.time.monotonic())) or nudge())
    return made


def test_a_delete_is_nudged_once_after_the_server_answers(monkeypatch, capsys):
    """The mail race, for a delete (DGO-1025's follow-up): removed while the server starts, the account
    stayed in Dovecot's userdb and its person could still log in; no login can prove a delete."""
    greets = itertools.chain([False, False], itertools.repeat(True))
    monkeypatch.setattr(mailboxd, "_answers", lambda: next(greets), raising=False)
    monkeypatch.setattr(mailboxd.threading, "Thread", Inline)
    made = nudges(monkeypatch)
    payload, code = mailboxd.delete_mailbox("dana")
    assert code == 200 and payload["address"] == "dana@acme.test"
    assert [a for a, _h in mailboxd._entries()] == ["office@acme.test"]
    # ONCE, and when the server answered (two silent tries, then its greeting and SETTLE) — not a nudge every
    # try, nor one at the end of the watch
    assert made == [2 * mailboxd.CONFIRM_EVERY + mailboxd.SETTLE] and len(marks()) == 1
    assert read().startswith("office@acme.test|{SHA512-CRYPT}one\n")
    assert "stopped" not in capsys.readouterr().out


def test_a_delete_on_a_silent_server_is_nudged_once_at_the_end(monkeypatch):
    """The reader of this change: a server that never answered, later RESTARTED (not recreated), skips its
    setup and applies only a change it sees — so the delete is nudged all the same, once."""
    monkeypatch.setattr(mailboxd, "_answers", lambda: False, raising=False)
    monkeypatch.setattr(mailboxd.threading, "Thread", Inline)
    made = nudges(monkeypatch)
    mailboxd.delete_mailbox("dana")
    assert made == [mailboxd.CONFIRM_FOR] and read().startswith("office@acme.test|{SHA512-CRYPT}one\n")


def test_a_delete_never_makes_a_file_of_the_marker_alone(monkeypatch):
    monkeypatch.setattr(mailboxd, "_answers", lambda: True, raising=False)
    made = nudges(monkeypatch)
    os.remove(mailboxd.ACCOUNTS)
    mailboxd._settle_delete("dana@acme.test")
    assert made == [] and not os.path.exists(mailboxd.ACCOUNTS)


def test_the_server_answers_when_it_greets(server):
    assert mailboxd._answers() is True
    server.greets = False
    assert mailboxd._answers() is False


def test_a_watch_that_fails_says_so_and_never_raises(monkeypatch, capsys):
    def broken(address, password):
        raise RuntimeError("anything at all")
    monkeypatch.setattr(mailboxd, "_login", broken)
    mailboxd._confirm_safely("dana@acme.test", "pw", LINE)
    said = capsys.readouterr().out
    assert "the watch stopped: RuntimeError" in said and "pw" not in said.replace("dana", "")
    assert read() == ACCOUNTS
