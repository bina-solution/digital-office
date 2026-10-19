# -*- coding: utf-8 -*-
"""Regression guard for the `label:` search vocabulary (issues/mail-label-registry-split.yaml).

WHAT WENT WRONG, and why a guard has to exist at all: `POST /search` with `label:SYNCED_DOC`
answered `200 {"total": 0}` on a mailbox where 15,575 messages carried that label. Nothing was
broken in a way anything could see — 0 is also the correct answer for a drained pipe, so the
endpoint's failure mode was to produce a believable, unfalsifiable lie. A lane very nearly used
exactly this to conclude the gmail pipes were empty, and this project has already had one outage of
the same class (59,630 structurally invisible messages).

THIS FILE DRIVES `GmailBackend.search` ITSELF — not a re-implementation of it, not just the pure
helper — through a fake IMAP client, and asserts on the CRITERION THAT REACHES THE WIRE. That is
deliberate: a guard that only exercised `rewrite_label_terms` would pass even if `search` forgot to
call it, which is the "gate that scans nothing reports green" trap this repo just paid for. Every
test below has been run against the pre-fix `search` and observed to FAIL there:

    test_key_is_resolved_to_the_name_gmail_matches   pre-fix: sent `label:SYNCED_DOC` verbatim
    test_spaces_are_hyphenized                       pre-fix: sent the raw name with spaces
    test_trailing_space_in_a_rule_name_is_trimmed    pre-fix: sent a token ending in '-'
    test_unknown_label_is_refused_not_zeroed         pre-fix: returned 200 total=0
    test_zero_carries_its_provenance                 pre-fix: no label_terms field at all
    test_unsolicited_fetch_rows_are_not_matches      pre-fix: count=3 for a 2-match search

No network, no stack, no /data volume: `python3 -m pytest apps/mail/mailapi/test_label_vocabulary.py`.
"""
import contextlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as mailapp  # noqa: E402


# The vocabulary this deployment actually has, abbreviated. The names are the ones the label ENGINE
# stamps (mailapi /organizer/settings), which is the registry the client's own mailbox proves is
# authoritative — 15,575 messages on the organizer's SYNCED_DOC name vs 70 on tag_rules'.
RULES = [
    {"KEY": "SYNCED_DOC", "LABEL": "אוטומציה-שמירת-מסמכים-טופל"},
    {"KEY": "DOC_TO_SYNC", "LABEL": "לטיפול-אוטומציה-שמירת-מסמכים"},
    {"KEY": "IN_PROGRESS", "LABEL": "באמצע-טיפול-אוטומציה"},
    {"KEY": "ACTION_DONE", "LABEL": "אינדוקס - פעולה בוצעה"},       # a name WITH spaces
    {"KEY": "SUPPLIER_MAIL", "LABEL": "מייל-מספק "},                 # a name with a TRAILING space
    {"KEY": "ARCHIVE_PROMO", "LABEL": "-INBOX"},                     # a directive, not a name
]

# What `GET /labels` reports for that mailbox.
MAILBOX_LABELS = [
    "INBOX", "אוטומציה-שמירת-מסמכים-טופל", "לטיפול-אוטומציה-שמירת-מסמכים",
    "באמצע-טיפול-אוטומציה", "אינדוקס - פעולה בוצעה", "מייל-מספק",
    "DOC_LINK_TO_SYNC",           # the stray, literally named after a KEY
    "היסטורי/ספקים/כתר",           # nested
]


class FakeIMAP:
    """Just enough IMAPClient for `search`. Records every criterion it is handed."""

    def __init__(self, uids, extra_fetch_uids=()):
        self.uids = list(uids)
        self.extra_fetch_uids = list(extra_fetch_uids)
        self.criteria = []
        self.charsets = []
        self._cached_capabilities = (b"IMAP4REV1", b"X-GM-EXT-1", b"LITERAL+")

    def capabilities(self):
        return self._cached_capabilities

    def folder_status(self, folder, keys):
        return {b"UIDVALIDITY": 7, b"UIDNEXT": 999}

    def search(self, criteria, charset=None):
        self.criteria.append(list(criteria))
        self.charsets.append(charset)
        return list(self.uids)

    def fetch(self, uids, parts):
        out = {}
        for u in list(uids) + self.extra_fetch_uids:
            out[u] = {
                b"BODY[HEADER]": b"From: a@b.c\r\nSubject: s\r\n\r\n",
                b"X-GM-MSGID": 1000 + u,
                b"X-GM-THRID": 2000 + u,
                b"FLAGS": (),
                b"INTERNALDATE": None,
            }
        return out


def tok(name):
    """The spec, restated in the test rather than imported from the code under test: the form
    Gmail's `label:` operator actually matches is the name TRIMMED, then spaces -> '-'."""
    return str(name or "").strip().replace(" ", "-")


def make_backend(uids=(11, 12), extra_fetch_uids=(), labels=MAILBOX_LABELS, rules=RULES,
                 monkeypatch=None):
    be = mailapp.GmailBackend("tester@example.com", password="x")
    fake = FakeIMAP(uids, extra_fetch_uids)

    @contextlib.contextmanager
    def _read_conn(op="op", wait=None):     # the real signature: (op label, bounded wait)
        yield fake

    be._read_conn = _read_conn
    be._select = lambda c, folder, readonly=False: None
    be.labels_list = lambda: {"labels": list(labels)}
    # raising=False on purpose: these six tests must run — and FAIL on the wire contract — against
    # a build that has no vocabulary resolution at all. A guard that errored out with
    # "module has no attribute" would prove only that a symbol is missing, not that the search is
    # wrong, and this repo has already been burned once by a gate that scanned nothing.
    monkeypatch.setattr(mailapp, "_label_name_by_key",
                        lambda cid=None: {r["KEY"]: r["LABEL"].strip()
                                          for r in rules
                                          if r["LABEL"] and not r["LABEL"].startswith("-")},
                        raising=False)
    return be, fake


def label_index():
    return {tok(n): n for n in MAILBOX_LABELS}


def key_map():
    return {r["KEY"]: r["LABEL"].strip() for r in RULES if not r["LABEL"].startswith("-")}


def raw_query(fake):
    """The X-GM-RAW argument that actually reached the server."""
    for crit in fake.criteria:
        for i, part in enumerate(crit):
            if part == b"X-GM-RAW":
                return crit[i + 1]
    raise AssertionError("no X-GM-RAW criterion was sent: %r" % (fake.criteria,))


# ── the six regressions ───────────────────────────────────────────────────────────────────────
def test_key_is_resolved_to_the_name_gmail_matches(monkeypatch):
    """`label:SYNCED_DOC` — the KEY every sync_registry row stores — must reach Gmail as the
    label NAME. Pre-fix this went out verbatim and matched a label that does not exist."""
    be, fake = make_backend(monkeypatch=monkeypatch)
    r = be.search({"query": "label:SYNCED_DOC", "folder": "[Gmail]/All Mail"})
    assert raw_query(fake) == "label:אוטומציה-שמירת-מסמכים-טופל"
    assert r["total"] == 2
    assert r.get("label_terms", [{}])[0].get("status") == "matched"


def test_spaces_are_hyphenized(monkeypatch):
    """Gmail's `label:` matches the hyphenized form ONLY — quoting a name with spaces returns 0
    over X-GM-RAW (measured live, both directions). Both the KEY route and a caller who already
    passes the full name must end up on the hyphenized token."""
    be, fake = make_backend(monkeypatch=monkeypatch)
    be.search({"query": "label:ACTION_DONE"})
    assert raw_query(fake) == "label:אינדוקס---פעולה-בוצעה"

    be2, fake2 = make_backend(monkeypatch=monkeypatch)
    be2.search({"query": 'label:"אינדוקס - פעולה בוצעה"'})
    assert raw_query(fake2) == "label:אינדוקס---פעולה-בוצעה"


def test_trailing_space_in_a_rule_name_is_trimmed(monkeypatch):
    """SUPPLIER_MAIL's rule really does carry a trailing space in this deployment. Hyphenizing
    without trimming yields `מייל-מספק-`, which matches nothing — a silent zero from a typo in a
    settings grid."""
    be, fake = make_backend(monkeypatch=monkeypatch)
    r = be.search({"query": "label:SUPPLIER_MAIL"})
    assert raw_query(fake) == "label:מייל-מספק"
    assert r.get("label_terms", [{}])[0].get("status") == "matched"


def test_unknown_label_is_refused_not_zeroed(monkeypatch):
    """THE CORE GUARANTEE. A term that cannot match must not come back as a 200 with total:0,
    because that is indistinguishable from 'this pipe is drained'."""
    be, fake = make_backend(monkeypatch=monkeypatch)
    out = be.search({"query": "label:NO_SUCH_THING has:attachment"})
    assert isinstance(out, tuple), "unknown label answered as a normal result: %r" % (out,)
    payload, status = out
    assert status == 422
    assert payload["unknown_labels"] == ["NO_SUCH_THING"]
    assert not fake.criteria, "the search must not even run when it cannot match"

    # ...and the opt-out still exists for a caller that genuinely wants the probe.
    be2, fake2 = make_backend(monkeypatch=monkeypatch)
    r = be2.search({"query": "label:NO_SUCH_THING", "allow_unknown_labels": True})
    assert not isinstance(r, tuple) and r["total"] == 2
    assert r["label_terms"][0]["status"] == "unknown"


def test_zero_carries_its_provenance(monkeypatch):
    """A genuinely empty result must still say what it searched for, so 'drained' is checkable
    after the fact instead of only at the moment someone thinks to ask."""
    be, fake = make_backend(uids=(), monkeypatch=monkeypatch)
    r = be.search({"query": "label:DOC_TO_SYNC"})
    assert r["total"] == 0
    assert "label_terms" in r, "a zero with no provenance is the whole bug: %r" % (sorted(r),)
    term = r["label_terms"][0]
    assert term["raw"] == "DOC_TO_SYNC"
    assert term["resolved"] == "לטיפול-אוטומציה-שמירת-מסמכים"
    assert term["status"] == "matched"


def test_unsolicited_fetch_rows_are_not_matches(monkeypatch):
    """RFC 3501 §5.2 lets a server volunteer FETCH responses for messages we never asked about,
    and imapclient returns them in the same dict. Measured live: a `total: 70` search came back
    with 74 message rows. `messages` must contain matches only."""
    be, fake = make_backend(uids=(11, 12), extra_fetch_uids=(99,), monkeypatch=monkeypatch)
    r = be.search({"query": "label:SYNCED_DOC"})
    assert r["count"] == r["total"] == 2
    assert 99 not in [m["uid"] for m in r["messages"]]


# ── vocabulary invariants that do not need a backend ──────────────────────────────────────────
def test_system_labels_pass_through_untouched(monkeypatch):
    """The mail UI's own views are `label:STARRED` / `-label:INBOX` / `label:SENT`. Gmail pseudo
    labels never appear in LIST output, so an existence check that did not exempt them would
    refuse every screen in the reader."""
    idx = label_index()
    q, terms = mailapp.rewrite_label_terms("label:STARRED -label:INBOX label:SENT", {}, idx)
    assert q == "label:STARRED -label:INBOX label:SENT"
    assert [t["status"] for t in terms] == ["system", "system", "system"]
    assert terms[1]["negated"] is True


def test_the_rule_wins_over_a_stray_label_named_after_the_key(monkeypatch):
    """This mailbox has a stray label literally named `DOC_LINK_TO_SYNC` carrying 1 message, while
    the KEY's real label carries 1,917. Deferring to the literal name — which the first cut of
    this fix did — turns `label:DOC_LINK_TO_SYNC` into a confident `1`, which is worse than the
    zero this guard exists to abolish because it looks like an answer. The rule wins; the stray is
    reported on the term instead of silently preferred."""
    idx = dict(label_index())
    idx["לטיפול-אוטומציה-קישור-למסמך"] = "לטיפול-אוטומציה-קישור-למסמך"
    q, terms = mailapp.rewrite_label_terms(
        "label:DOC_LINK_TO_SYNC", {"DOC_LINK_TO_SYNC": "לטיפול-אוטומציה-קישור-למסמך"}, idx)
    assert q == "label:לטיפול-אוטומציה-קישור-למסמך"
    assert terms[0]["status"] == "matched"
    assert terms[0]["shadowed_literal_label"] == "DOC_LINK_TO_SYNC"


def test_negation_and_nesting_survive_the_rewrite(monkeypatch):
    """The real sync query shape: one positive to_sync term and three negative state terms, plus
    a nested label. Losing a `-label:` exclusion does not return 0 — it returns EVERYTHING, and
    re-processes mail that was already done."""
    idx, keys = label_index(), key_map()
    q, terms = mailapp.rewrite_label_terms(
        "has:attachment newer_than:6m label:DOC_TO_SYNC -label:IN_PROGRESS "
        "-label:SYNCED_DOC label:היסטורי/ספקים/כתר", keys, idx)
    assert q == ("has:attachment newer_than:6m label:לטיפול-אוטומציה-שמירת-מסמכים "
                 "-label:באמצע-טיפול-אוטומציה -label:אוטומציה-שמירת-מסמכים-טופל "
                 "label:היסטורי/ספקים/כתר")
    assert [t["status"] for t in terms] == ["matched"] * 4
    assert [t["negated"] for t in terms] == [False, True, True, False]


def test_non_label_operators_are_never_touched(monkeypatch):
    idx = label_index()
    src = 'from:a@b.c subject:"label: not a label" has:attachment newer_than:6m'
    q, terms = mailapp.rewrite_label_terms(src, {"SYNCED_DOC": "x"}, idx)
    assert terms == [] and q == src


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
