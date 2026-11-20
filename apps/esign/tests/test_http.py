"""The two halves of the app over HTTP, and the rule the owner set: the link opens nothing else.

The public half is driven with Flask's test client, no office identity anywhere — which is the point:
`/s/<token>` must answer a stranger, and every other path must not answer a document.
"""
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clients  # noqa: E402
import server as server_mod  # noqa: E402
from store import Store  # noqa: E402


def tiny_pdf() -> bytes:
    """A one-page PDF with real Hebrew text in it, written by reportlab — the document under test."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(72, 700, "BINA Solutions - services agreement (test)")
    c.drawString(72, 680, "30 hours x 200 NIS = 6,000 NIS")
    c.showPage()
    c.save()
    return buf.getvalue()


class Stub:
    """A stand-in for drive and notifications: records what the app sent, answers the shape it must."""

    def __init__(self, status: int = 200):
        self.calls = []
        self.status = status
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _read(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_GET(self):
                outer.calls.append(("GET", self.path, dict(self.headers), b""))
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"files":[]}')

            def do_PUT(self):
                body = self._read()
                outer.calls.append(("PUT", self.path, dict(self.headers), body))
                self.send_response(outer.status)
                self.end_headers()
                self.wfile.write(b"{}")

            def do_POST(self):
                body = self._read()
                outer.calls.append(("POST", self.path, dict(self.headers), body))
                self.send_response(outer.status)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()


@pytest.fixture()
def stub(monkeypatch):
    s = Stub()
    monkeypatch.setenv("DRIVE_URL", s.url)
    monkeypatch.setenv("NOTIFICATIONS_URL", s.url)
    monkeypatch.setenv("ESIGN_BASE_URL", "http://esign.test")
    monkeypatch.setenv("ESIGN_RENDER_URL", "")          # no documents renderer: the plain certificate page
    yield s
    s.stop()


@pytest.fixture()
def app(tmp_path, stub):
    return server_mod.routes(server_mod.create_app(data_dir=str(tmp_path)))


@pytest.fixture()
def cl(app):
    return app.test_client()


def create(cl, *, signer="ישראל", password=None, days=14, name="הסכם דוגמה.pdf"):
    data = {"file": (io.BytesIO(tiny_pdf()), name), "signer": signer, "days": str(days),
            "sender": "שלמה"}
    if password:
        data["password"] = password
    r = cl.post("/api/envelopes", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    return r.get_json()["data"]


def token_of(link: str) -> str:
    return link.rsplit("/", 1)[-1]


# ── the office half ───────────────────────────────────────────────────────────────────────────────
def test_health_is_open_and_says_nothing(cl):
    r = cl.get("/healthz")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_creating_an_envelope_from_a_pdf_gives_a_link(cl):
    got = create(cl)
    assert got["envelope"]["doc_name"] == "הסכם דוגמה.pdf"
    assert got["envelope"]["status"] == "sent"
    assert got["link"].startswith("http://esign.test/s/")
    assert len(token_of(got["link"])) >= 40


def test_a_new_envelope_is_already_sent_and_its_link_works(cl):
    """The CLI hands the link out at creation, so creation IS the send — no second step to forget."""
    got = create(cl)
    assert got["envelope"]["status"] == "sent"
    assert cl.get("/s/%s" % token_of(got["link"])).status_code == 200


def test_a_non_pdf_is_refused(cl):
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(b"not a pdf"), "x.pdf"), "signer": "ישראל"},
                content_type="multipart/form-data")
    assert r.status_code == 415


def test_no_signer_is_refused(cl):
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(tiny_pdf()), "x.pdf")},
                content_type="multipart/form-data")
    assert r.status_code == 400


def test_the_listing_never_carries_a_link(cl):
    create(cl)
    items = cl.get("/api/envelopes").get_json()["data"]["items"]
    assert items and all(i["link"] is None for i in items)


# ── the signer half: reachable without a sign-in, and only for this link ─────────────────────────
def test_the_link_answers_a_stranger(cl):
    tok = token_of(create(cl)["link"])
    r = cl.get("/s/%s" % tok)
    assert r.status_code == 200 and "הסכם דוגמה" in r.get_data(as_text=True)


def test_the_signer_pages_take_their_stylesheet_from_the_public_path(cl):
    """/static/ sits behind the office's sign-in; a stranger's pages must load their look from /s/ (DGO-1846: without
    it the pages were unstyled, and the office's mark beside its name as wide as the page)."""
    tok = token_of(create(cl)["link"])
    for page in (cl.get("/s/%s" % tok), cl.get("/s/%s" % ("A" * 43))):          # the signer page, and a sentence
        html = page.get_data(as_text=True)
        assert 'href="/s/esign.css"' in html and "/static/" not in html and "dgo-mark" in html
    css = cl.get("/s/esign.css")
    assert css.status_code == 200 and css.mimetype == "text/css" and b".dgo-mark" in css.get_data()


def test_an_unknown_or_disabled_link_answers_one_sentence_and_no_document(cl):
    got = create(cl)
    tok = token_of(got["link"])
    eid = got["envelope"]["id"]
    assert cl.get("/s/%s" % ("A" * 43)).status_code == 404
    cl.post("/api/envelopes/%s/cancel" % eid)
    r = cl.get("/s/%s" % tok)
    assert r.status_code == 404
    assert cl.get("/s/%s/doc" % tok).status_code == 404


def test_an_expired_link_says_so_and_serves_nothing(cl):
    tok = token_of(create(cl, days=0)["link"])
    r = cl.get("/s/%s" % tok)
    assert r.status_code == 410
    assert cl.get("/s/%s/doc" % tok).status_code == 410


def test_a_password_link_serves_no_bytes_until_the_password_is_right(cl):
    tok = token_of(create(cl, password="סודה-1234")["link"])
    page = cl.get("/s/%s" % tok)
    assert page.status_code == 200 and "password" in page.get_data(as_text=True)
    assert cl.get("/s/%s/doc" % tok).status_code == 403
    bad = cl.post("/s/%s/unlock" % tok, data={"password": "nope"})
    assert bad.status_code == 403
    assert cl.get("/s/%s/doc" % tok).status_code == 403
    good = cl.post("/s/%s/unlock" % tok, data={"password": "סודה-1234"})
    assert good.status_code == 302
    doc = cl.get("/s/%s/doc" % tok)
    assert doc.status_code == 200 and doc.data.startswith(b"%PDF")


def test_five_wrong_passwords_lock_the_link(cl):
    tok = token_of(create(cl, password="סודה-1234")["link"])
    codes = [cl.post("/s/%s/unlock" % tok, data={"password": "x"}).status_code for _ in range(5)]
    assert codes[-1] == 429
    assert cl.get("/s/%s/doc" % tok).status_code == 403


# ── signing, end to end, with the office's own services stubbed ─────────────────────────────────
def test_signing_produces_a_pades_pdf_copies_it_to_drive_and_notifies(cl, stub):
    got = create(cl)
    tok, eid = token_of(got["link"]), got["envelope"]["id"]
    assert cl.post("/s/%s/sign" % tok, data={"name": "ישראל"}).status_code == 400   # no consent yet
    r = cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"})
    assert r.status_code == 200, r.data
    body = r.get_data(as_text=True)
    assert "נחתם" in body

    detail = cl.get("/api/envelopes/%s" % eid).get_json()["data"]
    env = detail["envelope"]
    assert env["status"] == "signed" and env["drive_path"]
    assert detail["chain"]["ok"] is True
    kinds = [e["type"] for e in detail["events"]]
    assert kinds[0] == "envelope.created" and "envelope.signed" in kinds

    # the copy really went to drive, and the notice really went to notifications
    puts = [c for c in stub.calls if c[0] == "PUT"]
    posts = [c for c in stub.calls if c[0] == "POST"]
    assert puts and "mode=" not in puts[0][1] and "path=" in puts[0][1]
    assert puts[0][3].startswith(b"%PDF")
    assert posts and json.loads(posts[0][3].decode("utf-8"))["source_id"] == "esign-%s" % eid

    pdf = cl.get("/api/envelopes/%s/download" % eid)
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert len(pdf.data) > len(tiny_pdf())


class RendererStub:
    """The office's documents renderer (apitools' POST /docGen/house): answers a one-page PDF, keeps what it got."""

    def __init__(self):
        self.docs = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.docs.append((self.path, json.loads(self.rfile.read(n).decode("utf-8"))))
                from reportlab.pdfgen import canvas
                buf = io.BytesIO()
                c = canvas.Canvas(buf)
                c.drawString(72, 700, "HOUSE CERTIFICATE PAGE")
                c.showPage()
                c.save()
                self.send_response(200)
                self.send_header("content-type", "application/pdf")
                self.end_headers()
                self.wfile.write(buf.getvalue())

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def test_the_certificate_is_drawn_in_the_house_style_when_the_renderer_answers(cl, monkeypatch):
    """DGO-2029: the certificate is the office's own page — the documents renderer draws it from the envelope's
    facts (the document, its fingerprint, the signer, every audit event); the plain page is only the fallback."""
    r = RendererStub()
    monkeypatch.setenv("ESIGN_RENDER_URL", r.url)
    monkeypatch.setenv("ESIGN_OFFICE_NAME", "משרד בדיקה")    # the office's own key, made at its first signing
    got = create(cl, password="סודה")
    tok, eid = token_of(got["link"]), got["envelope"]["id"]
    assert cl.post("/s/%s/unlock" % tok, data={"password": "סודה"}).status_code in (302, 303)
    assert cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"}).status_code == 200
    path, doc = r.docs[0]
    assert path.startswith("/docGen/house") and "format=pdf" in path
    assert doc["doc_type"] == "SIGN_CERTIFICATE" and doc["doc_id"] == eid
    cert = doc["certificate"]
    assert cert["envelope"] == eid and cert["title"] == "הסכם דוגמה.pdf"
    assert len(cert["sha_before"]) == 64
    assert cert["signers"][0]["name"] == "ישראל" and "סיסמה" in cert["signers"][0]["method"]
    # the certificate names the key that signs — this office's, in its name, never «BINA Solutions» (the third reader);
    # a Hebrew name stands alone in it (a certificate's name may not mix Hebrew with Latin words)
    assert cert["key_subject"] == "משרד בדיקה"
    whats = [e["what"] for e in cert["events"]]
    assert whats[0] == "המסמך הוכן לחתימה" and "הוזנה סיסמה — נכונה" in whats and whats[-1] == "נחתם"
    import pypdfium2 as pdfium
    pdf = cl.get("/api/envelopes/%s/download" % eid).data
    doc_pdf = pdfium.PdfDocument(pdf)
    assert len(doc_pdf) == 2                                    # the document, then the house certificate
    assert "HOUSE CERTIFICATE PAGE" in doc_pdf[1].get_textpage().get_text_range()


def test_signing_twice_is_refused(cl):
    got = create(cl)
    tok = token_of(got["link"])
    assert cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"}).status_code == 200
    again = cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"})
    assert again.status_code == 409
    detail = cl.get("/api/envelopes/%s" % got["envelope"]["id"]).get_json()["data"]
    kinds = [e["type"] for e in detail["events"]]
    assert kinds.count("envelope.signed") == 1


def test_reopening_a_signed_link_cannot_produce_a_second_signature(cl):
    """The bug this test exists for: the page used to re-open a signed envelope and put it back to
    'opened', which made a second POST /sign possible."""
    got = create(cl, password="סודה-1234")
    tok = token_of(got["link"])
    cl.post("/s/%s/unlock" % tok, data={"password": "סודה-1234"})
    assert cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"}).status_code == 200
    reopened = cl.get("/s/%s" % tok)
    assert reopened.status_code == 302
    again = cl.post("/s/%s/sign" % tok, data={"name": "ישראל", "consent": "1"})
    assert again.status_code == 409
    detail = cl.get("/api/envelopes/%s" % got["envelope"]["id"]).get_json()["data"]
    assert detail["envelope"]["status"] == "signed"
    assert [e["type"] for e in detail["events"]].count("envelope.signed") == 1


def test_a_drive_outage_keeps_the_signature_and_marks_it_pending(monkeypatch, tmp_path):
    broken = Stub(status=500)
    monkeypatch.setenv("DRIVE_URL", broken.url)
    monkeypatch.setenv("NOTIFICATIONS_URL", broken.url)
    monkeypatch.setenv("ESIGN_BASE_URL", "http://esign.test")
    app = server_mod.routes(server_mod.create_app(data_dir=str(tmp_path)))
    cl = app.test_client()
    got = create(cl)
    r = cl.post("/s/%s/sign" % token_of(got["link"]), data={"name": "ישראל", "consent": "1"})
    assert r.status_code == 200                       # the signature IS the product
    env = cl.get("/api/envelopes/%s" % got["envelope"]["id"]).get_json()["data"]["envelope"]
    assert env["status"] == "signed"
    assert env["drive_state"].startswith("pending")
    broken.stop()


# ── the public half is a prefix, not a host ──────────────────────────────────────────────────────
def test_every_other_path_is_the_office_half_not_the_document(cl):
    got = create(cl)
    eid, tok = got["envelope"]["id"], token_of(got["link"])
    # nothing outside /s/ serves a document, and nothing inside /s/ reaches the office API
    assert cl.get("/s/%s/api/envelopes" % tok).status_code == 404
    assert cl.get("/s/../api/envelopes").status_code in (404, 308)
    assert cl.get("/doc/%s" % eid).status_code == 404
    assert cl.get("/s/%s/../../etc/passwd" % tok).status_code in (400, 404)


def test_clients_speak_the_documented_contracts(stub):
    d = clients.drive_put(stub.url, "/חתימות/2026-11-09/x — חתום.pdf", b"%PDF-1.4", "application/pdf")
    assert d["ok"] and d["path"].endswith("— חתום.pdf")
    n = clients.notify(stub.url, source_id="esign-1", title="נחתם", level="info")
    assert n["ok"]
    put = [c for c in stub.calls if c[0] == "PUT"][0]
    assert put[1].startswith("/api/fs/content?path=")
    assert "%D7%97" in put[1]                        # the Hebrew folder is URL-encoded
    assert put[2]["Content-Type"].startswith("application/pdf")
