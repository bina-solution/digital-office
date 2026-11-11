"""The store and the audit trail: a link, a password gate, an expiry, and a chain one cannot edit.

Read before `esign-002` was written, per the item's rule (tests first). Every test here fails on the
behaviour the owner asked for, not on an implementation detail.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store import Store, canonical, iso, sha256_bytes, verify_password  # noqa: E402


class Clock:
    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)


@pytest.fixture()
def st(tmp_path):
    clock = Clock()
    s = Store(str(tmp_path / "esign.db"), clock=clock)
    s.clock = clock                       # the test keeps the handle
    yield s
    s.close()


def make(st, **kw):
    args = dict(doc_name="הסכם דוגמה.pdf", doc_path="/tmp/a.pdf", doc_sha256="a" * 64,
                doc_size=1234, signer_name="ברוך", sender="שלמה", days=14)
    args.update(kw)
    return st.create(**args)


def test_a_link_is_minted_once_and_found_by_its_token(st):
    env = make(st)
    assert len(env["token"]) >= 40                      # 32 random bytes, base64url
    found = st.by_token(env["token"])
    assert found["id"] == env["id"]
    assert "token" not in found                          # only the hash is stored
    assert st.by_token("x" * 43) is None
    assert st.by_token("") is None


def test_a_draft_link_is_not_yet_a_door(st):
    env = make(st)
    assert st.get(env["id"])["status"] == "draft"
    st.set(env["id"], status="sent")
    assert st.usable(st.get(env["id"])) is True


def test_password_gate_allows_five_attempts_then_locks(st):
    env = make(st, password="סודה-1234")
    st.set(env["id"], status="sent")
    assert st.unlock(st.get(env["id"]), "סודה-1234") == "ok"
    assert st.unlock(st.get(env["id"]), "wrong") == "bad"
    for _ in range(3):
        st.unlock(st.get(env["id"]), "wrong")
    assert st.unlock(st.get(env["id"]), "wrong") == "locked"
    assert st.unlock(st.get(env["id"]), "סודה-1234") == "locked"   # even the right one waits
    st.clock.advance(minutes=16)
    assert st.unlock(st.get(env["id"]), "סודה-1234") == "ok"
    assert verify_password(st.get(env["id"])["pw_hash"], "סודה-1234") is True
    assert verify_password(st.get(env["id"])["pw_hash"], "סודה-1235") is False


def test_no_password_means_no_unlock_step(st):
    env = make(st)
    st.set(env["id"], status="sent")
    assert st.unlock(st.get(env["id"]), "") == "none"


def test_expiry_closes_the_link_by_itself(st):
    env = make(st, days=1)
    st.set(env["id"], status="sent")
    assert st.usable(st.get(env["id"])) is True
    st.clock.advance(days=1, minutes=1)
    assert st.usable(st.get(env["id"])) is False


def test_a_cancelled_or_signed_link_is_closed(st):
    env = make(st)
    st.set(env["id"], status="cancelled")
    assert st.usable(st.get(env["id"])) is False
    env2 = make(st)
    st.set(env2["id"], status="signed")
    assert st.usable(st.get(env2["id"])) is False


def test_the_audit_trail_is_a_chain_and_a_tamper_breaks_it(st):
    env = make(st)
    st.append(env["id"], "envelope.created", {"doc": env["doc_name"]})
    st.append(env["id"], "envelope.opened", {"ip": "203.0.113.7"})
    st.append(env["id"], "envelope.signed", {"signer": "ברוך"})
    ok, bad, last = st.chain_ok(env["id"])
    assert ok and bad is None and len(last) == 64
    events = st.events(env["id"])
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[1]["prev"] == events[0]["hash"]

    st.conn.execute("UPDATE events SET data=? WHERE envelope_id=? AND seq=2",
                    (canonical({"ip": "198.51.100.9"}), env["id"]))
    st.conn.commit()
    ok, bad, _ = st.chain_ok(env["id"])
    assert ok is False and bad == 2

    # and a changed hash breaks the link AFTER it, not the event itself
    st.conn.execute("UPDATE events SET data=? WHERE envelope_id=? AND seq=2",
                    (canonical({"ip": "203.0.113.7"}), env["id"]))
    st.conn.execute("UPDATE events SET hash=? WHERE envelope_id=? AND seq=1",
                    ("0" * 64, env["id"]))
    st.conn.commit()
    ok, bad, _ = st.chain_ok(env["id"])
    assert ok is False and bad in (1, 2)


def test_two_envelopes_of_one_document_are_two_records(st):
    a = make(st)
    b = make(st)
    assert a["id"] != b["id"] and a["token"] != b["token"]
    assert len(st.list()) == 2


def test_only_one_signature_can_claim_an_envelope(st):
    """Two windows posting the same link at the same moment: the second claim loses, the first signs."""
    env = make(st)
    st.set(env["id"], status="sent")
    assert st.claim_signature(env["id"]) is True
    assert st.claim_signature(env["id"]) is False
    assert st.get(env["id"])["status"] == "signing"
    st.set(env["id"], status="signed")
    assert st.claim_signature(env["id"]) is False


def test_the_signed_fields_are_recorded_where_a_reader_looks(st):
    env = make(st)
    st.set(env["id"], status="signed", signed_path="/data/signed/x.pdf", signed_sha256="b" * 64,
           signer_ip="203.0.113.7", signer_ua="Mozilla/5.0", drive_path="/חתימות/2026-11-09/x — חתום.pdf")
    got = st.get(env["id"])
    assert got["signed_sha256"] == "b" * 64
    assert got["drive_path"].endswith("— חתום.pdf")
    assert got["signed_at"] is None
