# -*- coding: utf-8 -*-
"""The Gmail backend's latency work (RELEASE-DECISIONS N11, backend half) — no network, no stack:

  * IDLE_NOOP_S is honoured: a checkout NOOPs only a connection idle beyond the window, and a
    command that fails clears the stamp so the next checkout reconnects;
  * the interactive read path waits a bounded time for the one connection and raises
    MailboxBusy (service.py: 503 {"error": "mailbox busy", "busy_with": ...}) — the full fetch the
    sync deliveries use keeps waiting;
  * probe()/healthz() take the lock non-blocking and report a busy mailbox as healthy;
  * the body cache: written by the full fetch, the thread read and the meta read (attachment META
    only, never bytes), served by the meta read with `cached: true`, bounded oldest-first.

    python3 -m pytest apps/mail/mailapi/test_latency_cache.py -q
"""
import base64
import contextlib
import email.message
import os
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import app as mailapp    # noqa: E402
import bodycache         # noqa: E402


# ── fakes ───────────────────────────────────────────────────────────────────────────────────────
class FakeClient:
    """Enough of IMAPClient for `_conn`, `probe`, `message` and `thread`."""

    def __init__(self, store=None, fail_noop=False):
        self.noops = 0
        self.fetches = []
        self.selects = []
        self.searches = []
        self.logged_out = False
        self.fail_noop = fail_noop
        self.store = store or {}       # uid -> fetch dict
        self._last_ok = time.time()
        self._cached_capabilities = (b"IMAP4REV1", b"X-GM-EXT-1")

    def noop(self):
        self.noops += 1
        if self.fail_noop:
            raise OSError("socket closed")

    def logout(self):
        self.logged_out = True

    def select_folder(self, folder):
        self.selects.append(folder)

    def search(self, crit, charset=None):
        self.searches.append(list(crit))
        if crit and crit[0] == b"X-GM-MSGID":
            return [u for u, d in self.store.items() if d.get(b"X-GM-MSGID") == crit[1]]
        if crit and crit[0] == "X-GM-THRID":
            return [u for u, d in self.store.items() if str(d.get(b"X-GM-THRID")) == crit[1]]
        return list(self.store)

    def fetch(self, uids, parts):
        self.fetches.append((list(uids), list(parts)))
        return {u: dict(self.store[u]) for u in uids if u in self.store}

    def list_folders(self):
        return [((), b"/", "INBOX")]


def rfc822(subject="hello", text="first line of the body", attachment=b"PDFBYTES"):
    m = email.message.EmailMessage()
    m["From"] = "a@b.c"
    m["To"] = "d@e.f"
    m["Subject"] = subject
    m["Date"] = "Tue, 01 Sep 2026 10:00:00 +0300"
    m.set_content(text)
    m.add_alternative("<p>%s</p>" % text, subtype="html")
    if attachment is not None:
        m.add_attachment(attachment, maintype="application", subtype="pdf", filename="חשבונית.pdf")
    return m.as_bytes()


def gmail_row(uid, msgid, thrid, labels=(b"INBOX",), raw=None):
    return {b"RFC822": raw or rfc822(), b"X-GM-MSGID": msgid, b"X-GM-THRID": thrid,
            b"X-GM-LABELS": list(labels), b"INTERNALDATE": None, b"FLAGS": ()}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    c = bodycache.BodyCache(root=str(tmp_path / "bodycache"))
    monkeypatch.setattr(bodycache, "_shared", c)
    return c


@pytest.fixture
def backend(cache, monkeypatch):
    monkeypatch.setattr(mailapp, "LOCK_WAIT_S", 0.2)
    monkeypatch.setattr(mailapp, "CACHE_LABELS_WAIT_S", 0.2)
    be = mailapp.GmailBackend("tester@example.com", password="x")
    fake = FakeClient()
    be._client = fake
    monkeypatch.setattr(be, "_make_conn", lambda: fake)
    return be, fake


def hold_lock(be, seconds):
    """Hold the backend's lock from another thread, as a 300 s sync fetch would."""
    grabbed = threading.Event()

    def run():
        with be._read_conn("message:full", wait=None):
            grabbed.set()
            time.sleep(seconds)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    grabbed.wait(2)
    return t


# ── IDLE_NOOP_S ─────────────────────────────────────────────────────────────────────────────────
def test_checkout_skips_the_noop_while_the_connection_is_fresh(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(mailapp, "IDLE_NOOP_S", 240)
    fake._last_ok = time.time()
    with be._read_conn("search"):
        pass
    with be._read_conn("search"):
        pass
    assert fake.noops == 0


def test_checkout_noops_an_idle_connection_and_reconnects_a_dead_one(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(mailapp, "IDLE_NOOP_S", 240)
    fake._last_ok = time.time() - 300
    with be._read_conn("search") as c:
        assert c is fake
    assert fake.noops == 1 and time.time() - fake._last_ok < 5

    dead = FakeClient(fail_noop=True)
    dead._last_ok = time.time() - 300
    fresh = FakeClient()
    be._client = dead
    monkeypatch.setattr(be, "_make_conn", lambda: fresh)
    with be._read_conn("search") as c:
        assert c is fresh
    assert dead.logged_out


def test_a_failed_command_clears_the_stamp_so_the_retry_checks_liveness(backend, monkeypatch):
    be, fake = backend
    monkeypatch.setattr(mailapp, "IDLE_NOOP_S", 240)
    fake._last_ok = time.time()
    with pytest.raises(OSError):
        with be._read_conn("search"):
            raise OSError("EOF")
    assert fake._last_ok == 0.0
    with be._read_conn("search"):
        pass
    assert fake.noops == 1


def test_instrument_stamps_last_ok_on_every_successful_command():
    class Raw:
        def noop(self):
            return b"OK"

        def search(self, *a, **k):
            raise OSError("boom")
    c = mailapp._instrument(Raw())
    c._last_ok = 0.0
    c.noop()
    assert time.time() - c._last_ok < 5
    c._last_ok = 0.0
    with pytest.raises(OSError):
        c.search()
    assert c._last_ok == 0.0


# ── the bounded read path ───────────────────────────────────────────────────────────────────────
def test_interactive_read_answers_mailbox_busy_and_names_the_holder(backend):
    be, fake = backend
    hold_lock(be, 1.0)
    t0 = time.time()
    with pytest.raises(mailapp.MailboxBusy) as e:
        be.search({"query": "from:x", "limit": 5})
    assert time.time() - t0 < 0.9
    p = e.value.payload()
    assert p["error"] == "mailbox busy" and p["busy_with"] == "message:full"
    assert p["waited_s"] == 0.2 and p["mailbox"] == "tester@example.com"
    assert be.stats()["lock"]["busy"] is True


def test_the_full_fetch_waits_for_the_connection(backend):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    hold_lock(be, 0.6)
    t0 = time.time()
    r = be.message(0, {"id": "abc", "attachments": "true"})
    assert time.time() - t0 >= 0.5
    assert r["subject"] == "hello" and r["attachments"][0]["data_base64"]


def test_max_wait_s_overrides_per_call(backend):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    hold_lock(be, 0.6)
    r = be.message(0, {"id": "abc", "meta": "true", "max_wait_s": "0"})     # 0 = wait
    assert r["meta"] is True and "cached" not in r
    hold_lock(be, 0.6)
    with pytest.raises(mailapp.MailboxBusy):
        be.message(0, {"id": "abc", "attachments": "true", "max_wait_s": "0.1"})


def test_meta_busy_never_falls_through_to_the_unbounded_full_fetch(backend):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    hold_lock(be, 0.8)
    t0 = time.time()
    with pytest.raises(mailapp.MailboxBusy):
        be.message(0, {"id": "abc", "meta": "true"})
    assert time.time() - t0 < 0.7


def test_busy_with_names_the_outermost_op_and_clears_after(backend):
    be, fake = backend
    with be._read_conn("thread"):
        with be._read_conn("labels_list"):          # re-entry on the same thread
            assert be._busy_with[0] == "thread"
    assert be._busy_with is None and be._depth == 0


# ── health ──────────────────────────────────────────────────────────────────────────────────────
def test_probe_and_healthz_report_a_busy_mailbox_as_healthy_without_waiting(backend):
    be, fake = backend
    hold_lock(be, 0.6)
    t0 = time.time()
    p, code = be.probe()
    h, hcode = be.healthz()
    assert time.time() - t0 < 0.3
    assert code == 200 and p["status"] == "ok" and p["busy_with"] == "message:full"
    assert hcode == 200 and h["busy_with"] == "message:full"
    assert fake.noops == 0


def test_probe_reports_a_dead_account(backend, monkeypatch):
    be, fake = backend
    fake.fail_noop = True
    fake._last_ok = 0.0
    monkeypatch.setattr(be, "_make_conn", lambda: (_ for _ in ()).throw(OSError("login failed")))
    p, code = be.probe()
    assert code == 503 and p["status"] == "error" and "login failed" in p["error"]
    h, hcode = be.healthz()
    assert hcode == 500


# ── the body cache ──────────────────────────────────────────────────────────────────────────────
def test_cache_round_trip_never_stores_bytes(cache):
    msg = {"uid": 7, "id": "abc", "threadId": "def", "from": "a@b.c", "subject": "s",
           "body_text": "t", "body_html": "<p>t</p>", "labels": ["INBOX"],
           "attachments": [{"filename": "f.pdf", "mimeType": "application/pdf", "size": 3,
                            "content_id": "", "data_base64": base64.b64encode(b"xyz").decode()}]}
    assert cache.put("Tester@Example.com", "ABC", msg) is True
    hit = cache.get("tester@example.com", "abc")               # account + id are case-insensitive
    assert hit["v"] == 1 and hit["source"] == "full"
    assert hit["message"]["attachments"] == [{"filename": "f.pdf", "mimeType": "application/pdf",
                                              "size": 3, "content_id": ""}]
    assert "data_base64" not in open(cache.path("tester@example.com", "abc"), encoding="utf-8").read()
    assert cache.get("other@example.com", "abc") is None       # another mailbox never sees it
    assert cache.put("tester@example.com", "../etc", msg) is False
    assert cache.get("tester@example.com", "not hex") is None
    assert cache.stats()["count"] == 1 and cache.stats()["hits"] == 1


def test_cache_bounds_evict_oldest_first(tmp_path):
    c = bodycache.BodyCache(root=str(tmp_path / "bc"), max_count=4, max_bytes=10 ** 9)
    for i in range(6):
        assert c.put("u@x", "%x" % (100 + i), {"id": "%x" % (100 + i), "body_text": "b"})
        os.utime(c.path("u@x", "%x" % (100 + i)), (1000 + i, 1000 + i))
    st = c.stats()
    assert st["count"] <= 4 and st["evicted"] >= 2
    assert c.get("u@x", "64") is None and c.get("u@x", "69") is not None   # 0x64 oldest, 0x69 newest

    big = bodycache.BodyCache(root=str(tmp_path / "bc2"), max_count=10 ** 6, max_bytes=600)
    for i in range(8):
        big.put("u@x", "%x" % (200 + i), {"id": "%x" % (200 + i), "body_text": "x" * 100})
    assert big.stats()["bytes"] <= 600

    small = bodycache.BodyCache(root=str(tmp_path / "bc3"), max_entry_bytes=200)
    assert small.put("u@x", "1", {"id": "1", "body_text": "x" * 500}) is False


def test_full_fetch_and_thread_fill_the_cache(backend, cache):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    fake.store[8] = gmail_row(8, 0xabd, 0xdef, raw=rfc822(subject="re: hello", attachment=None))
    r = be.message(0, {"id": "abc", "attachments": "true"})
    assert r["attachments"][0]["data_base64"]
    hit = cache.get("tester@example.com", "abc")
    assert hit["source"] == "full" and hit["message"]["uid"] == 7
    assert hit["message"]["attachments"] == [{"filename": "חשבונית.pdf", "mimeType": "application/pdf",
                                              "size": 8, "content_id": ""}]
    assert hit["message"]["body_text"].startswith("first line")
    # a folder-relative uid is not stored as if it were an All Mail uid
    be.message(7, {"folder": "INBOX", "attachments": "true"})
    assert cache.get("tester@example.com", "abc")["message"]["uid"] is None
    # attachments=false is not a delivery and does not write
    cache_before = cache.stats()["count"]
    be.message(0, {"id": "abd", "attachments": "false"})
    assert cache.stats()["count"] == cache_before

    t = be.thread("abc")
    assert t["count"] == 2
    assert cache.get("tester@example.com", "abd")["source"] == "thread"


def test_a_thread_read_without_bodies_answers_with_summaries(backend, cache):
    """`bodies=false` called a function this file never had (`_summary`), so every headers-only
    thread read was a NameError — a 500 on the one branch nothing in the tree asks for."""
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    fake.store[8] = gmail_row(8, 0xabd, 0xdef, raw=rfc822(subject="re: hello", attachment=None))
    t = be.thread("abc", {"bodies": "false"})
    assert [m["subject"] for m in t["messages"]] == ["hello", "re: hello"] and t["count"] == 2
    assert fake.fetches[-1][1][0] == b"BODY.PEEK[HEADER]"      # headers were asked for, not bodies
    assert "body_text" not in t["messages"][0] and t["text"] == ""
    assert cache.stats()["count"] == 0                         # a summary is not cached as a body


def test_meta_read_is_served_from_the_cache_with_live_labels_when_cheap(backend, cache):
    be, fake = backend
    from imapclient import imap_utf7
    hebrew = imap_utf7.encode("לטיפול")                         # X-GM-LABELS arrive modified-UTF-7
    fake.store[7] = gmail_row(7, 0xabc, 0xdef, labels=(b"INBOX", hebrew))
    be.message(0, {"id": "abc", "attachments": "true"})          # the delivery fills the cache
    fake.fetches.clear()
    r = be.message(0, {"id": "abc", "meta": "true"})
    assert r["cached"] is True and r["meta"] is True and r["cache_source"] == "full"
    assert r["labels_live"] is True and r["labels"] == ["INBOX", "לטיפול"]
    assert r["attachments"] == [{"filename": "חשבונית.pdf", "mimeType": "application/pdf",
                                 "size": 8, "content_id": ""}]
    # exactly one cheap FETCH of the labels by the CACHED uid — no SEARCH, no body
    assert len(fake.fetches) == 1 and fake.fetches[0] == ([7], [b"X-GM-LABELS", b"X-GM-MSGID"])
    assert not [s for s in fake.searches if s and s[0] == b"X-GM-MSGID" and len(fake.fetches) == 0]


def test_meta_read_from_cache_does_not_queue_behind_a_busy_mailbox(backend, cache):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    be.message(0, {"id": "abc", "attachments": "true"})
    hold_lock(be, 1.0)
    fake.fetches.clear()
    t0 = time.time()
    r = be.message(0, {"id": "abc", "meta": "true"})
    assert time.time() - t0 < 0.6
    assert r["cached"] is True and r["labels_live"] is False and r["labels"] == ["INBOX"]
    assert fake.fetches == []                                     # zero IMAP commands


def test_stale_uid_falls_back_to_cached_labels(backend, cache):
    be, fake = backend
    fake.store[7] = gmail_row(7, 0xabc, 0xdef)
    be.message(0, {"id": "abc", "attachments": "true"})
    # UIDVALIDITY moved: uid 7 now names a different message
    fake.store[7] = gmail_row(7, 0x999, 0xdef)
    be._uid_cache.clear()
    r = be.message(0, {"id": "abc", "meta": "true"})
    assert r["cached"] is True and r["labels_live"] is False


def test_meta_read_writes_the_cache_too(backend, cache):
    be, fake = backend
    bs = ([(b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 5, 1),
           (b"application", b"pdf", (b"name", b"a.pdf"), None, None, b"base64", 100, None, None,
            (b"attachment", (b"filename", b"a.pdf")))], b"mixed")
    fake.store[7] = {b"BODYSTRUCTURE": bs, b"BODY[HEADER]": b"From: a@b.c\r\nSubject: s\r\n\r\n",
                     b"BODY[1]": b"hello", b"X-GM-MSGID": 0xabc, b"X-GM-THRID": 0xdef,
                     b"X-GM-LABELS": [b"INBOX"], b"INTERNALDATE": None}
    r = be.message(0, {"id": "abc", "meta": "true"})
    assert "cached" not in r and r["body_text"] == "hello"
    hit = cache.get("tester@example.com", "abc")
    assert hit["source"] == "meta" and hit["message"]["attachments"][0]["filename"] == "a.pdf"
    r2 = be.message(0, {"id": "abc", "meta": "true"})
    assert r2["cached"] is True and r2["body_text"] == "hello"


def test_stats_expose_the_cache_and_the_lock(backend):
    be, _ = backend
    s = be.stats()
    assert s["body_cache"]["count"] == 0 and s["lock"]["busy"] is False
    assert s["lock"]["read_wait_s"] == 0.2 and s["lock"]["idle_noop_s"] == mailapp.IDLE_NOOP_S


# ── the HTTP shape of "busy" ────────────────────────────────────────────────────────────────────
def test_service_answers_503_mailbox_busy(monkeypatch):
    import profiles
    profiles._started = True
    import service
    service.app.testing = True

    class Busy:
        protocol = "mail_imap_app_password"

        def search(self, b):
            raise mailapp.MailboxBusy("u@x", ("POST /message/0 [message:full]", time.time() - 42), 30)
    monkeypatch.setattr(service, "_backend", lambda cid=None, *, require_explicit: ("cid", Busy()))
    r = service.app.test_client().post("/search", json={"connection_id": "cid", "query": "x"})
    assert r.status_code == 503 and r.headers["Retry-After"] == "5"
    body = r.get_json()
    assert body["error"] == "mailbox busy" and body["busy_with"] == "POST /message/0 [message:full]"
    assert 41 <= body["busy_for_s"] <= 43 and body["waited_s"] == 30
