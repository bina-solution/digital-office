"""A link to LOOK at a document (DGO-2047, «מסמכים חיים»): the same door as a signature — one token, one envelope,
an expiry, a password if wanted, a revoke — and never a signature. Its file is replaced while it is open, so the link
follows a document that is still being written; a document out for SIGNATURE is never replaced under its signer.
"""
import io
import os
import sqlite3
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as server_mod  # noqa: E402
from store import Store, utcnow  # noqa: E402


def pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(72, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture()
def clock():
    now = {"t": utcnow()}
    return now


@pytest.fixture()
def app(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("ESIGN_BASE_URL", "http://esign.test")
    monkeypatch.setenv("ESIGN_RENDER_URL", "")
    monkeypatch.setenv("DRIVE_URL", "http://127.0.0.1:9")          # nothing answers: a view link never writes there
    monkeypatch.setenv("NOTIFICATIONS_URL", "http://127.0.0.1:9")
    return server_mod.routes(server_mod.create_app(data_dir=str(tmp_path), clock=lambda: clock["t"]))


@pytest.fixture()
def cl(app):
    return app.test_client()


def share(cl, *, body=b"", kind="view", ref="doc_abc", password=None, days=30, signer="קבוצת אורן"):
    data = {"file": (io.BytesIO(body or pdf("quote v1")), "QT-2026-00031.pdf"), "kind": kind, "ref": ref,
            "signer": signer, "sender": "בינה סולושנס", "days": str(days), "name": "QT-2026-00031 — קבוצת אורן.pdf"}
    if password:
        data["password"] = password
    r = cl.post("/api/envelopes", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    return r.get_json()["data"]


def tok(link: str) -> str:
    return link.rsplit("/", 1)[-1]


def test_a_view_link_is_made_and_listed_by_its_document(cl):
    d = share(cl)
    assert d["link"].startswith("http://esign.test/s/") and len(tok(d["link"])) > 30
    assert d["envelope"]["kind"] == "view" and d["envelope"]["ref"] == "doc_abc"
    share(cl, ref="doc_other")
    rows = cl.get("/api/envelopes?ref=doc_abc").get_json()["data"]["items"]
    assert [r["ref"] for r in rows] == ["doc_abc"]
    assert rows[0]["link"] is None                      # a listing never carries a link
    assert rows[0]["password"] is False


def test_a_view_link_needs_no_signer_but_a_signature_does(cl):
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(pdf("x")), "x.pdf"), "kind": "view"},
                content_type="multipart/form-data")
    assert r.status_code == 200
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(pdf("x")), "x.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 400
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(pdf("x")), "x.pdf"), "kind": "edit", "signer": "a"},
                content_type="multipart/form-data")
    assert r.status_code == 400


def test_the_view_page_answers_a_stranger_and_offers_no_signature(cl):
    t = tok(share(cl)["link"])
    page = cl.get("/s/" + t)
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and "מסמך לצפייה" in html
    assert "/sign" not in html and 'name="consent"' not in html
    assert "/s/%s/doc?dl=1" % t in html
    doc = cl.get("/s/%s/doc" % t)
    assert doc.status_code == 200 and doc.data.startswith(b"%PDF")
    assert doc.headers["Content-Disposition"].startswith("inline")
    assert cl.get("/s/%s/doc?dl=1" % t).headers["Content-Disposition"].startswith("attachment")


def test_a_view_link_signs_nothing_whatever_is_posted(cl, app):
    d = share(cl)
    t = tok(d["link"])
    r = cl.post("/s/%s/sign" % t, data={"name": "דנה לוי", "consent": "1"})
    assert r.status_code == 404
    env = cl.get("/api/envelopes/" + d["envelope"]["id"]).get_json()["data"]["envelope"]
    assert env["status"] != "signed" and not env["signed_at"]
    with app.app_context():
        assert server_mod.store().claim_signature(d["envelope"]["id"]) is False
    assert cl.get("/s/%s/done" % t).status_code == 302          # nothing to be done: back to the page


def test_opening_is_written_in_the_trail(cl):
    d = share(cl)
    cl.get("/s/" + tok(d["link"]))
    got = cl.get("/api/envelopes/" + d["envelope"]["id"]).get_json()["data"]
    assert got["envelope"]["status"] == "opened" and got["envelope"]["opened_at"]
    assert [e["type"] for e in got["events"]] == ["envelope.created", "envelope.opened"]
    assert got["chain"]["ok"] is True


def test_a_revoked_view_link_answers_one_sentence_and_no_bytes(cl):
    d = share(cl)
    t = tok(d["link"])
    assert cl.post("/api/envelopes/%s/cancel" % d["envelope"]["id"], data={"reason": "בוטל"}).status_code == 200
    page = cl.get("/s/" + t)
    assert page.status_code == 404 and "%PDF" not in page.get_data(as_text=True)
    assert not cl.get("/s/%s/doc" % t).data.startswith(b"%PDF")


def test_an_expired_view_link_serves_nothing(cl, clock):
    t = tok(share(cl, days=1)["link"])
    clock["t"] = clock["t"] + timedelta(days=2)
    assert cl.get("/s/" + t).status_code == 410
    assert not cl.get("/s/%s/doc" % t).data.startswith(b"%PDF")


def test_a_password_view_link_serves_no_bytes_until_it_is_given(cl):
    t = tok(share(cl, password="אורן2026")["link"])
    page = cl.get("/s/" + t).get_data(as_text=True)
    assert "מוגן בסיסמה" in page and 'class="doc"' not in page and "dl=1" not in page
    assert not cl.get("/s/%s/doc" % t).data.startswith(b"%PDF")
    assert cl.post("/s/%s/unlock" % t, data={"password": "לא"}).status_code == 403
    assert cl.post("/s/%s/unlock" % t, data={"password": "אורן2026"}).status_code == 302
    assert cl.get("/s/%s/doc" % t).data.startswith(b"%PDF")


def test_the_link_follows_its_document_while_it_is_open(cl):
    v1, v2 = pdf("quote v1"), pdf("quote v2 - edited")
    d = share(cl, body=v1)
    t, eid = tok(d["link"]), d["envelope"]["id"]
    r = cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(v2), "v2.pdf"), "name": "QT — v2.pdf"},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    assert cl.get("/s/%s/doc" % t).data == v2                    # the same link, the new bytes
    got = cl.get("/api/envelopes/" + eid).get_json()["data"]
    assert got["envelope"]["doc_name"] == "QT — v2.pdf"
    assert got["events"][-1]["type"] == "envelope.updated" and got["chain"]["ok"] is True


def test_a_file_replaced_while_it_is_read_serves_the_new_one(cl, monkeypatch):
    """The request looked the envelope up a moment before its file was replaced (and the old one removed): it reads
    the envelope again and serves the new file — a 500 (FileNotFoundError) before (the second reader of DGO-2047)."""
    v1, v2 = pdf("quote v1"), pdf("quote v2 - while read")
    d = share(cl, body=v1)
    t, eid = tok(d["link"]), d["envelope"]["id"]
    with cl.application.app_context():
        stale = server_mod._public_env(t)                         # looked up with v1's path
    assert cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(v2), "v2.pdf")},
                  content_type="multipart/form-data").status_code == 200
    real, calls = server_mod._public_env, []

    def first_stale(token):                                       # the first lookup was taken before the swap
        calls.append(token)
        return stale if len(calls) == 1 else real(token)
    monkeypatch.setattr(server_mod, "_public_env", first_stale)
    r = cl.get("/s/%s/doc" % t)
    assert r.status_code == 200 and r.data == v2
    assert len(calls) == 2                                        # read again once, with its state


def test_a_link_closed_while_its_file_is_swapped_serves_no_bytes(cl, monkeypatch):
    """Read again after the swap, the link is checked again: one cancelled meanwhile serves its sentence, not the file."""
    d = share(cl, body=pdf("v1"))
    t, eid = tok(d["link"]), d["envelope"]["id"]
    with cl.application.app_context():
        stale = server_mod._public_env(t)
    assert cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(pdf("v2")), "v2.pdf")},
                  content_type="multipart/form-data").status_code == 200
    assert cl.post("/api/envelopes/%s/cancel" % eid).status_code == 200
    real, calls = server_mod._public_env, []

    def first_stale(token):
        calls.append(token)
        return stale if len(calls) == 1 else real(token)
    monkeypatch.setattr(server_mod, "_public_env", first_stale)
    r = cl.get("/s/%s/doc" % t)
    assert not r.data.startswith(b"%PDF")


def test_two_replacements_that_meet_on_the_old_file_both_answer(cl, monkeypatch):
    """Two replacements at once both remove the same old file: the second finds it gone after its row is written —
    done, not a 500."""
    d = share(cl)
    eid = d["envelope"]["id"]
    real = os.remove

    def gone(path):
        real(path)
        raise FileNotFoundError(path)                             # the other request removed it first
    monkeypatch.setattr(server_mod.os, "remove", gone)
    r = cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(pdf("v2")), "v2.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.data


def test_a_document_out_for_signature_is_never_replaced(cl):
    d = share(cl, kind="sign", signer="דנה לוי")
    r = cl.put("/api/envelopes/%s/file" % d["envelope"]["id"], data={"file": (io.BytesIO(pdf("other")), "o.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 409


def test_a_closed_view_link_takes_no_new_file_and_a_non_pdf_is_refused(cl):
    d = share(cl)
    eid = d["envelope"]["id"]
    r = cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(b"hello"), "x.txt")},
               content_type="multipart/form-data")
    assert r.status_code == 415
    cl.post("/api/envelopes/%s/cancel" % eid)
    r = cl.put("/api/envelopes/%s/file" % eid, data={"file": (io.BytesIO(pdf("v3")), "v3.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 409


def test_minting_again_kills_the_old_view_link(cl):
    d = share(cl)
    old = tok(d["link"])
    r = cl.post("/api/envelopes/%s/link" % d["envelope"]["id"])
    new = tok(r.get_json()["data"]["link"])
    assert new != old
    assert cl.get("/s/" + old).status_code == 404 and cl.get("/s/" + new).status_code == 200


def test_a_volume_from_before_kinds_opens_and_its_envelopes_are_signatures(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE envelopes (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        status TEXT NOT NULL, doc_name TEXT NOT NULL, doc_path TEXT NOT NULL, doc_sha256 TEXT NOT NULL,
        doc_size INTEGER NOT NULL, signer_name TEXT NOT NULL, signer_email TEXT, sender TEXT NOT NULL,
        page INTEGER NOT NULL DEFAULT 1, box TEXT, pw_hash TEXT, token_hash TEXT NOT NULL UNIQUE,
        attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT, opened_at TEXT, opened_ip TEXT, opened_ua TEXT,
        signed_at TEXT, signed_path TEXT, signed_sha256 TEXT, signer_ip TEXT, signer_ua TEXT, drive_path TEXT,
        drive_state TEXT, notice_state TEXT, closed_reason TEXT);
      INSERT INTO envelopes (id, created_at, expires_at, status, doc_name, doc_path, doc_sha256, doc_size,
        signer_name, sender, token_hash) VALUES ('e1', '2026-11-01T00:00:00Z', '2026-12-01T00:00:00Z', 'sent',
        'old.pdf', '/x', 'h', 1, 'ישראל', 'שלמה', 'th');
    """)
    con.commit()
    con.close()
    st = Store(path)
    assert st.get("e1")["kind"] == "sign" and st.get("e1")["ref"] is None
    new = st.create(doc_name="n.pdf", doc_path="/y", doc_sha256="h2", doc_size=1, signer_name="",
                    sender="שלמה", kind="view", ref="doc_1")
    assert [r["id"] for r in st.list(ref="doc_1")] == [new["id"]]
    with pytest.raises(ValueError):
        st.create(doc_name="n.pdf", doc_path="/y", doc_sha256="h3", doc_size=1, signer_name="a", sender="b",
                  kind="other")


def test_a_notice_opens_the_signature_in_my_docs_never_the_gone_tile():
    """This app's tile left the home (DGO-2169): a notice opens the document in «מסמכים», or «חתימות» there — never
    /#/m/esign/, which opens nothing now. Relative to the console (G95)."""
    import fill
    assert server_mod.console_link("doc_1") == "/#/m/my-docs/doc/doc_1"
    assert server_mod.console_link(None) == server_mod.CONSOLE_LINK == "/#/m/my-docs/signatures"
    assert fill._screen({"ref": "doc 2/x"}) == "/#/m/my-docs/doc/doc%202%2Fx"      # one segment, whatever the id
    assert fill._screen({"ref": None}) == fill._screen() == "/#/m/my-docs/signatures"
