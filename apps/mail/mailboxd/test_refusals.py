# -*- coding: utf-8 -*-
"""What mailboxd SAYS when it refuses — the sentence the mail's screen shows, word for word.

mailapi and mailview forward a refusal's `error` as it is (their rule: the reason, never "the request
failed"), so what is written in mailboxd.py is what a person in the office reads. Until 2026-10-09 it
was English — "invalid mailbox name", "password too short" — on a Hebrew screen. Every refusal the
daemon can give is asked for here, and each must keep its status (the callers decide by it) and say
itself in Hebrew: an address, a domain, a file's or a setting's name may stand in the sentence as
they are; an English sentence may not. And a refusal writes nothing.

No network, no doveadm, no volume: `python3 -m pytest apps/mail/mailboxd/test_refusals.py`.
"""
import os
import re
import sys
import tempfile

import pytest

os.environ.update(MAILBOXD_CFG=tempfile.mkdtemp(prefix="zz-mailboxd-"), MAIL_DOMAIN="acme.test",
                  LOCALMAIL_USER="office")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mailboxd  # noqa: E402

ACCOUNTS = "office@acme.test|{SHA512-CRYPT}one\ndana@acme.test|{SHA512-CRYPT}two\n"
PW = "long-enough-1"


def english(sentence):
    """The Latin words left once what may stand as it is has been taken out: an address, a domain, a
    file's name (they hold an @ or a dot) and a setting's NAME (capitals)."""
    return re.findall(r"[a-z]{2,}", " ".join(w for w in sentence.split() if not re.search(r"[@.]", w)))


@pytest.fixture(autouse=True)
def accounts(monkeypatch):
    def no_dovecot(_pw):
        raise RuntimeError("doveadm pw failed: no such binary")
    monkeypatch.setattr(mailboxd, "_hash", no_dovecot)
    with open(mailboxd.ACCOUNTS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ACCOUNTS)
    yield
    with open(mailboxd.ACCOUNTS, encoding="utf-8") as fh:
        assert fh.read() == ACCOUNTS, "a refusal wrote to the accounts file"


ASKS = [
    ("an address at another domain", lambda: mailboxd.create_mailbox({"address": "dana@other.test", "password": PW}), 400),
    ("a name that is not a mailbox's", lambda: mailboxd.create_mailbox({"local": "Dana Levi", "password": PW}), 400),
    ("a password too short", lambda: mailboxd.create_mailbox({"local": "noa", "password": "short"}), 400),
    ("an address that exists", lambda: mailboxd.create_mailbox({"local": "dana", "password": PW}), 409),
    ("a password that cannot be hashed", lambda: mailboxd.create_mailbox({"local": "noa", "password": PW}), 500),
    ("a new password too short", lambda: mailboxd.set_password("dana", {"password": "short"}), 400),
    ("a new password for nobody", lambda: mailboxd.set_password("nobody", {"password": PW}), 404),
    ("a new password that cannot be hashed", lambda: mailboxd.set_password("dana", {"password": PW}), 500),
    ("deleting nobody", lambda: mailboxd.delete_mailbox("nobody"), 404),
    ("deleting the primary mailbox", lambda: mailboxd.delete_mailbox("office"), 409),
]


def spoken(what, ask, status):
    payload, got = ask()
    assert got == status, (what, got, payload)
    for sentence in [payload[k] for k in ("error", "hint") if k in payload]:
        assert re.search("[א-ת]", sentence) and not english(sentence), (what, sentence)
    return payload


@pytest.mark.parametrize("what,ask,status", ASKS, ids=[a[0] for a in ASKS])
def test_a_refusal_keeps_its_status_and_is_said_in_hebrew(what, ask, status):
    spoken(what, ask, status)


def test_with_no_primary_declared_every_delete_is_refused_in_hebrew(monkeypatch):
    monkeypatch.setattr(mailboxd, "PRIMARY", None)
    assert "LOCALMAIL_USER" in spoken("deleting with no primary declared", lambda: mailboxd.delete_mailbox("dana"), 409)["hint"]


def test_the_engines_own_words_travel_beside_the_sentence_not_in_it():
    """a hash that fails is an engine's fault with an English reason: kept, as the detail"""
    payload = spoken("a password that cannot be hashed", ASKS[4][1], 500)
    assert payload["detail"].startswith("doveadm pw failed")
