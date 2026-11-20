"""esign — the office's signing service: one document goes out as a link, comes back signed, and the
signed copy lands in «קבצים».

Two halves on one host, and the split is the whole security design:

  * everything that is NOT `/s/` is the office's app: the screen, the JSON API, the downloads. It sits
    behind the office's sign-in (traefik `authentik@file`), like every other app.
  * `/s/<token>` is the signer's page. It is the ONLY public path, it is declared in the manifest
    (`auth_exclude: ["/s/"]`) and served by the app's own router in docker-compose.yml, and a token is
    not a session: it opens one envelope, it is refused everywhere else, and with a password set the
    document bytes are not served until it is given.

`/healthz` is the one other path the container answers to itself (its own healthcheck), and it says
nothing about the office.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, abort, current_app, make_response, redirect, render_template,
                   request, send_file, session, url_for)

import clients
import pdfsign
from store import Store, iso, sha256_bytes, utcnow

APP_ID = "esign"
MAX_UPLOAD = int(os.environ.get("ESIGN_MAX_UPLOAD", str(40 * 1024 * 1024)))
PUBLIC_PREFIX = "/s/"


# ── the app ────────────────────────────────────────────────────────────────────────────────────────
def create_app(*, data_dir: str | None = None, store: Store | None = None, clock=None) -> Flask:
    here = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, template_folder=os.path.join(here, "templates"),
                static_folder=os.path.join(here, "static"))
    data = data_dir or os.environ.get("ESIGN_DATA", "/data")
    os.makedirs(data, exist_ok=True)
    app.config["DATA_DIR"] = data
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
    app.config["STORE"] = store or Store(os.environ.get("ESIGN_DB", os.path.join(data, "esign.db")),
                                         clock=clock or utcnow)
    app.config["CLOCK"] = clock or utcnow
    key_file = os.path.join(data, "secret-key")
    if os.environ.get("ESIGN_SECRET_KEY"):
        app.secret_key = os.environ["ESIGN_SECRET_KEY"]
    else:
        if os.path.exists(key_file):
            app.secret_key = open(key_file, encoding="utf-8").read().strip()
        else:
            app.secret_key = secrets.token_urlsafe(48)
            with open(key_file, "w", encoding="utf-8") as fh:
                fh.write(app.secret_key)
            os.chmod(key_file, 0o600)
    for sub in ("docs", "signed"):
        os.makedirs(os.path.join(data, sub), exist_ok=True)
    return app


def store() -> Store:
    return current_app.config["STORE"]


def now() -> datetime:
    return current_app.config["CLOCK"]()


# The console's own screen for this app: a link RELATIVE to the console that shows it, the house form
# (dgo-extend, machine) — never a host guessed here (G95: a loopback console in a link opens nothing on
# any office but this one, and nothing at all from a phone).
CONSOLE_LINK = "/#/m/esign/"


def public_base() -> str:
    return os.environ.get("ESIGN_BASE_URL", "http://esign.localhost:8080").rstrip("/")


def link_for(token: str) -> str:
    return "%s/s/%s" % (public_base(), token)


def _ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def _ua() -> str:
    return (request.headers.get("User-Agent") or "")[:300]


def _json(payload: dict, code: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False, default=str), status=code,
                    mimetype="application/json")


def ok(op: str, **data):
    return _json({"ok": True, "op": op, "data": data})


def err(op: str, detail: str, code: int = 400):
    return _json({"ok": False, "op": op, "detail": detail}, code)


# ── the audit trail, written as things happen ─────────────────────────────────────────────────────
def event(eid: str, type_: str, data: dict | None = None) -> None:
    store().append(eid, type_, data)


def flow(type_: str, title: str, *, link: str = "", data: dict | None = None) -> None:
    cfg = clients.config()
    clients.publish(APP_ID, type_, title, link=link, data=data,
                    redis_url=cfg["redis_url"], password=cfg["redis_password"])


# ── the certificate, as the house style draws it ───────────────────────────────────────────────────
#: what each audit event says on the certificate
EVENT_WORDS = {
    "envelope.created": "המסמך הוכן לחתימה", "envelope.sent": "קישור החתימה נשלח",
    "envelope.relinked": "הקישור הונפק מחדש", "envelope.opened": "המסמך נפתח",
    "envelope.unlock": "הוזנה סיסמה", "envelope.consent": "החותם הסכים לחתום אלקטרונית",
    "envelope.sign_failed": "ניסיון חתימה נכשל", "envelope.cancelled": "המעטפה בוטלה",
}


def _local(at: str) -> str:
    """An audit timestamp (ISO, UTC) on the office's clock (TZ), as the certificate prints it."""
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return str(at)


def house_certificate(env: dict, *, typed_name: str, when: datetime, ip: str, chain_ok: bool) -> dict:
    """The SIGN_CERTIFICATE document (src/doc_gen/house in apitools) for this envelope: the document, its
    fingerprint, the signer and how the link was guarded, and every audit event in order."""
    events = []
    for ev in store().events(env["id"]):
        try:
            data = json.loads(ev.get("data") or "{}")
        except (TypeError, ValueError):
            data = {}
        what = EVENT_WORDS.get(ev["type"], ev["type"])
        if ev["type"] == "envelope.unlock":
            what += " — " + ("נכונה" if data.get("result") == "ok" else "שגויה")
        events.append({"when": _local(ev["at"]), "what": what, "ip": data.get("ip") or ""})
    events.append({"when": _local(iso(when)), "what": "נחתם", "who": typed_name, "ip": ip or ""})
    method = "קישור אישי" + (" + סיסמה שנמסרה בנפרד" if env.get("pw_hash") else "")
    n = len(events) - 1
    return {
        "doc_type": "SIGN_CERTIFICATE", "doc_id": env["id"], "doc_date": when.astimezone().strftime("%d/%m/%Y"),
        "certificate": {
            "envelope": env["id"], "title": env["doc_name"], "sender": env["sender"], "sha_before": env["doc_sha256"],
            "signers": [{"name": typed_name, "method": method, "when": _local(iso(when)), "ip": ip or ""}],
            "events": events,
            "verdict": ("שרשרת יומן החתימה שלמה (%d אירועים), והמסמך נחתם כפי שנשלח." % n) if chain_ok
            else "אימות שרשרת יומן החתימה נכשל — ראו את יומן החתימה המצורף.",
        },
    }


# ── signing: the whole chain, in one function, so a retry can run it again ────────────────────────
def sign_envelope(env: dict, *, typed_name: str, ip: str = "", ua: str = "") -> dict:
    """Stamp, add the certificate page, PAdES-sign, verify, store, and copy into drive."""
    st = store()
    cfg = clients.config()
    data_dir = current_app.config["DATA_DIR"]
    when = now()
    src = env["doc_path"]
    signed_path = os.path.join(data_dir, "signed", "%s.pdf" % env["id"])

    box = json.loads(env["box"]) if env.get("box") else None
    if not box:
        import pikepdf
        with pikepdf.open(src) as pdf:
            media = [float(v) for v in pdf.pages[min(env["page"], len(pdf.pages)) - 1].mediabox]
        width, height = media[2] - media[0], media[3] - media[1]
        box = [width - 250, 80, width - 60, 165]

    stamped = pdfsign.stamp(src, env["page"], tuple(box), signer_name=typed_name, when=when,
                            doc_sha256=env["doc_sha256"])
    chain_ok, bad, last = st.chain_ok(env["id"])
    lines = [
        "שם המסמך: %s" % env["doc_name"],
        "החותם: %s" % typed_name,
        "השולח: %s" % env["sender"],
        "מועד החתימה (UTC): %s" % iso(when),
        "מועד החתימה (שעון הלשכה): %s" % when.astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "כתובת IP: %s" % (ip or ""),
        "דפדפן: %s" % (ua or "")[:80],
        "SHA-256 של המסמך לפני החתימה: %s" % env["doc_sha256"],
        "מזהה המעטפה: %s" % env["id"],
        "סיסמה למסמך: %s" % ("כן, הוזנה לפני החתימה" if env.get("pw_hash") else "לא נדרשה"),
        "שרשרת יומן החתימה: %s אירועים, %s" % (len(st.events(env["id"])),
                                             "אימות תקין" if chain_ok else "אימות נכשל"),
        "חתימת השרשרת: %s" % (last or ""),
    ]
    # the key first: the certificate names whose key signs (DGO-2029, the third reader)
    office = os.environ.get("ESIGN_OFFICE_NAME", "")
    key_pem, cert_pem = pdfsign.load_or_create_cert(
        data_dir, os.environ.get("ESIGN_CERT_P12", ""), os.environ.get("ESIGN_CERT_PASS", ""), office=office)
    # the certificate in the office's house style (the documents renderer, DGO-2029); the plain page when
    # the renderer does not answer — a signature never waits on a look
    certificate = house_certificate(env, typed_name=typed_name, when=when, ip=ip, chain_ok=chain_ok)
    certificate["certificate"]["key_subject"] = pdfsign.subject(cert_pem)
    cert = clients.render_house(cfg["render_url"], certificate)
    if not cert:
        cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית", lines,
                                        footer="מסמך זה נחתם אלקטרונית בלשכה הדיגיטלית.\n"
                                               "החתימה מוצמדת למסמך כולו, ומזהה שינוי בכל בייט אחרי החתימה.")
    body = pdfsign.append_pages(stamped, cert)
    tmp_dir = tempfile.mkdtemp(prefix="esign-")
    try:
        staged = os.path.join(tmp_dir, "staged.pdf")
        with open(staged, "wb") as fh:
            fh.write(body)
        reason = "חתימה על %s" % env["doc_name"]
        location = office or "Digital Office"
        tsa_url = os.environ.get("ESIGN_TSA_URL", "")
        try:
            stamper = pdfsign.timestamper(tsa_url)
            pdfsign.sign(staged, signed_path, key_pem, cert_pem, reason=reason, location=location, stamper=stamper)
        except Exception:
            if not tsa_url:
                raise
            # the time-stamping authority did not answer: the signer's act is never lost to it — the file is
            # signed without the trusted time, and the event says so (pades.timestamped false)
            if os.path.exists(signed_path):
                os.remove(signed_path)
            pdfsign.sign(staged, signed_path, key_pem, cert_pem, reason=reason, location=location)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    with open(signed_path, "rb") as fh:
        signed_bytes = fh.read()
    checks = pdfsign.verify(signed_path)
    signed_sha = sha256_bytes(signed_bytes)

    st.set(env["id"], status="signed", signed_at=iso(when), signed_path=signed_path,
           signed_sha256=signed_sha, signer_ip=ip, signer_ua=ua)
    event(env["id"], "envelope.signed",
          {"signer": typed_name, "sha256": signed_sha, "doc_sha256": env["doc_sha256"],
           "pades": checks, "chain_last": last})
    env = st.get(env["id"])

    # the copy in «קבצים» — beside the day's own folder, never the drive root
    day = when.strftime("%Y-%m-%d")
    folder = "%s/%s" % (cfg["drive_folder"].strip("/"), day)
    name = re.sub(r"\.pdf$", "", env["doc_name"], flags=re.I)
    put = clients.drive_put(cfg["drive_url"], "/%s/%s — חתום.pdf" % (folder, name), signed_bytes)
    audit_pdf = pdfsign.certificate_page("יומן חתימה", [json.dumps(e, ensure_ascii=False)
                                                        for e in st.events(env["id"])],
                                         footer="יומן החתימה של %s" % env["id"])
    put_audit = clients.drive_put(cfg["drive_url"], "/%s/%s — יומן חתימה.pdf" % (folder, name),
                                  audit_pdf)
    st.set(env["id"], drive_path=put["path"] if put["ok"] else None,
           drive_state="ok" if put["ok"] else "pending:%s" % (put["detail"] or put["status"]))
    event(env["id"], "envelope.delivered",
          {"drive": put["ok"], "drive_status": put["status"], "audit_pdf": put_audit["ok"],
           "path": put["path"]})

    notice = notify_signed(st.get(env["id"]))
    st.set(env["id"], notice_state="ok" if notice["ok"] else "pending:%s" % (notice["detail"] or
                                                                             notice["status"]))
    flow("envelope.signed", "%s נחתם בידי %s" % (env["doc_name"], typed_name),
         link=CONSOLE_LINK,
         data={"envelope": env["id"], "drive_path": st.get(env["id"])["drive_path"]})
    return {"envelope": st.get(env["id"]), "pades": checks, "drive": put, "notice": notice}


def notify_signed(env: dict) -> dict:
    cfg = clients.config()
    title = "%s נחתם בידי %s" % (env["doc_name"], env.get("signer_name") or "")
    return clients.notify(cfg["notifications_url"], source_id="esign-%s" % env["id"],
                          title=title,
                          body="העותק החתום נשמר ב«קבצים»: %s" % (env.get("drive_path") or "—"),
                          link=CONSOLE_LINK, level="info",
                          actions=[{"id": "open", "label": "פתח את המסמך",
                                    "op": "esign.open", "args": {"envelope": env["id"]}}])


# ── the office's half ─────────────────────────────────────────────────────────────────────────────
def _gated(fn):
    """No identity of its own: the edge's sign-in is the gate, exactly like every other app's API."""
    @wraps(fn)
    def wrapper(*a, **kw):
        return fn(*a, **kw)
    return wrapper


def routes(app: Flask) -> Flask:
    @app.get("/healthz")
    def healthz():
        return _json({"ok": True, "app": APP_ID})

    @app.get("/")
    @_gated
    def index():
        rows = store().list(100)
        return render_template("index.html", rows=rows, base=public_base())

    @app.get("/api/envelopes")
    @_gated
    def api_list():
        limit = int(request.args.get("limit", 100))
        rows = [public_row(r) for r in store().list(limit)]
        return ok("list", items=rows, count=len(rows))

    @app.post("/api/envelopes")
    @_gated
    def api_create():
        up = request.files.get("file")
        if up is None:
            return err("create", "no file (multipart field `file`)", 400)
        raw = up.read()
        if not raw.startswith(b"%PDF"):
            return err("create", "the file is not a PDF", 415)
        form = request.form
        signer = (form.get("signer") or "").strip()
        if not signer:
            return err("create", "no signer name", 400)
        eid_dir = tempfile.mkdtemp(prefix="esign-upload-")
        doc_path = os.path.join(current_app.config["DATA_DIR"], "docs", "%s.pdf" % secrets.token_hex(8))
        with open(doc_path, "wb") as fh:
            fh.write(raw)
        shutil.rmtree(eid_dir, ignore_errors=True)
        box = None
        if form.get("box"):
            try:
                box = [float(v) for v in form["box"].split(",")]
            except ValueError:
                return err("create", "box must be x0,y0,x1,y1", 400)
        env = store().create(doc_name=form.get("name") or os.path.basename(up.filename or "document.pdf"),
                             doc_path=doc_path, doc_sha256=sha256_bytes(raw), doc_size=len(raw),
                             signer_name=signer, sender=form.get("sender") or "הלשכה",
                             days=int(form.get("days") or 14), page=int(form.get("page") or 1),
                             box=box, password=(form.get("password") or None),
                             signer_email=(form.get("email") or ""))
        store().set(env["id"], status="sent")
        event(env["id"], "envelope.created",
              {"doc_name": env["doc_name"], "signer": signer, "sha256": env["doc_sha256"],
               "password": bool(form.get("password")), "days": int(form.get("days") or 14)})
        flow("envelope.created", "מסמך מוכן לחתימה: %s" % env["doc_name"],
             data={"envelope": env["id"]})
        return ok("create", envelope=public_row(store().get(env["id"])), link=link_for(env["token"]))

    @app.post("/api/envelopes/<eid>/send")
    @_gated
    def api_send(eid: str):
        env = store().get(eid)
        if not env:
            return err("send", "no such envelope", 404)
        if env["status"] == "draft":
            store().set(eid, status="sent")
            event(eid, "envelope.sent", {"by": request.form.get("by") or "office"})
        return ok("send", envelope=public_row(store().get(eid)))

    @app.get("/api/envelopes/<eid>")
    @_gated
    def api_get(eid: str):
        env = store().get(eid)
        if not env:
            return err("get", "no such envelope", 404)
        chain_ok, bad, last = store().chain_ok(eid)
        return ok("get", envelope=public_row(env), events=store().events(eid),
                  chain={"ok": chain_ok, "first_bad": bad, "last_hash": last})

    @app.post("/api/envelopes/<eid>/cancel")
    @_gated
    def api_cancel(eid: str):
        env = store().get(eid)
        if not env:
            return err("cancel", "no such envelope", 404)
        if env["status"] == "signed":
            return err("cancel", "already signed", 409)
        store().set(eid, status="cancelled", closed_reason=request.form.get("reason") or "")
        event(eid, "envelope.cancelled", {"reason": request.form.get("reason") or ""})
        flow("envelope.cancelled", "הקישור בוטל: %s" % env["doc_name"], data={"envelope": eid})
        return ok("cancel", envelope=public_row(store().get(eid)))

    @app.post("/api/envelopes/<eid>/link")
    @_gated
    def api_link(eid: str):
        """Mint the signer's link again. The token is NOT kept in the clear, so this ROTATES it: the link
        handed out before stops working the moment a new one is minted, and the audit trail says so."""
        env = store().get(eid)
        if not env:
            return err("link", "no such envelope", 404)
        if env["status"] in ("signed", "cancelled"):
            return err("link", "the envelope is closed", 409)
        token = secrets.token_urlsafe(32)
        from store import token_hash as _th
        store().set(eid, token_hash=_th(token))
        event(eid, "envelope.relinked", {"by": request.form.get("by") or "office"})
        return ok("link", link=link_for(token), envelope=public_row(store().get(eid)))

    @app.get("/api/envelopes/<eid>/download")
    @_gated
    def api_download(eid: str):
        env = store().get(eid)
        if not env:
            return err("download", "no such envelope", 404)
        path = env.get("signed_path") or env.get("doc_path")
        if not path or not os.path.exists(path):
            return err("download", "no file", 404)
        return send_file(path, mimetype="application/pdf",
                         download_name=os.path.basename(path), as_attachment=True)

    @app.post("/api/envelopes/<eid>/retry")
    @_gated
    def api_retry(eid: str):
        env = store().get(eid)
        if not env:
            return err("retry", "no such envelope", 404)
        if env["status"] != "signed" or not env.get("signed_path"):
            return err("retry", "nothing to deliver yet", 409)
        cfg = clients.config()
        with open(env["signed_path"], "rb") as fh:
            data = fh.read()
        put = clients.drive_put(cfg["drive_url"], env.get("drive_path") or
                                "/%s/%s — חתום.pdf" % (cfg["drive_folder"], env["doc_name"]), data)
        notice = notify_signed(env)
        store().set(eid, drive_state="ok" if put["ok"] else "pending",
                    notice_state="ok" if notice["ok"] else "pending",
                    drive_path=put["path"] if put["ok"] else env.get("drive_path"))
        return ok("retry", drive=put, notice=notice)

    # ── the signer's half: the one public path ────────────────────────────────────────────────────
    # The signer pages' stylesheet lives on that path too: /static/ sits behind the office's sign-in, so a signer with
    # no session got the pages unstyled — and the office's mark beside its name (DGO-1846) as wide as the page (the
    # second reader). A rule with no variable wins over «<token>».
    @app.get(PUBLIC_PREFIX + "esign.css")
    def public_css():
        return send_file(os.path.join(current_app.static_folder, "esign.css"), mimetype="text/css", max_age=3600)

    @app.get(PUBLIC_PREFIX + "<token>")
    def signer_page(token: str):
        env, state = _public_env(token)
        if state != "ok":
            return _public_sentence(state), (410 if state == "expired" else 404)
        if env["status"] == "signed":
            # a signed envelope has nothing left to sign: opening the link again shows the receipt and
            # MUST NOT move the row back to a state a signature can be claimed from
            return redirect(url_for("signer_done", token=token))
        if _needs_unlock(env) and not _unlocked(env):
            return render_template("signer.html", env=env, mode="password", error="")
        event(env["id"], "envelope.opened", {"ip": _ip(), "ua": _ua()})
        store().set(env["id"], status="opened", opened_at=iso(now()), opened_ip=_ip(), opened_ua=_ua())
        flow("envelope.opened", "%s נפתח על ידי %s" % (env["doc_name"], env["signer_name"]),
             data={"envelope": env["id"]})
        return render_template("signer.html", env=env, mode="sign", error="")

    @app.post(PUBLIC_PREFIX + "<token>/unlock")
    def signer_unlock(token: str):
        env, state = _public_env(token)
        if state != "ok":
            return _public_sentence(state), (410 if state == "expired" else 404)
        verdict = store().unlock(env, request.form.get("password", ""))
        event(env["id"], "envelope.unlock", {"result": verdict, "ip": _ip()})
        if verdict == "ok":
            session["unlocked"] = token
            return redirect(url_for("signer_page", token=token))
        if verdict == "locked":
            return render_template("signer.html", env=env, mode="password",
                                   error="יותר מדי ניסיונות. נסו שוב בעוד %d דקות." % 15), 429
        return render_template("signer.html", env=env, mode="password",
                               error="הסיסמה אינה נכונה."), 403

    @app.get(PUBLIC_PREFIX + "<token>/doc")
    def signer_doc(token: str):
        env, state = _public_env(token)
        if state != "ok":
            return _public_sentence(state), (410 if state == "expired" else 404)
        if _needs_unlock(env) and not _unlocked(env):
            return _public_sentence("locked"), 403
        resp = send_file(env["doc_path"], mimetype="application/pdf",
                         download_name=env["doc_name"], as_attachment=False)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Disposition"] = "inline; filename*=UTF-8''%s" % \
            __import__("urllib.parse", fromlist=["quote"]).quote(env["doc_name"])
        return resp

    @app.post(PUBLIC_PREFIX + "<token>/sign")
    def signer_sign(token: str):
        env, state = _public_env(token)
        if state != "ok":
            return _public_sentence(state), (410 if state == "expired" else 404)
        if env["status"] == "signed":
            # signing twice is a second envelope, never a second signature on this one
            return render_template("done.html", env=env, pades={}), 409
        if _needs_unlock(env) and not _unlocked(env):
            return _public_sentence("locked"), 403
        typed = (request.form.get("name") or "").strip()
        consent = request.form.get("consent")
        if not typed or not consent:
            return render_template("signer.html", env=env, mode="sign",
                                   error="צריך למלא שם ולסמן את ההסכמה."), 400
        if not store().claim_signature(env["id"]):
            return render_template("done.html", env=store().get(env["id"]), pades={}), 409
        store().set(env["id"], signer_ip=_ip(), signer_ua=_ua(), signer_name=typed)
        event(env["id"], "envelope.consent", {"ip": _ip(), "ua": _ua(), "typed": typed})
        env = store().get(env["id"])
        try:
            result = sign_envelope(env, typed_name=typed, ip=_ip(), ua=_ua())
        except Exception as exc:                       # a failure is an ANSWER, never a silent page
            event(env["id"], "envelope.sign_failed", {"error": str(exc)[:300]})
            store().set(env["id"], status="opened")
            return _public_sentence("failed"), 500
        return render_template("done.html", env=result["envelope"], pades=result["pades"])

    @app.get(PUBLIC_PREFIX + "<token>/done")
    def signer_done(token: str):
        env, state = _public_env(token)
        if not env:
            return _public_sentence("expired"), 404
        if env["status"] != "signed":
            return redirect(url_for("signer_page", token=token))
        return render_template("done.html", env=env, pades={})

    return app


# ── public-side helpers ───────────────────────────────────────────────────────────────────────────
def public_row(env: dict) -> dict:
    keep = ("id", "status", "doc_name", "signer_name", "sender", "created_at", "expires_at",
            "opened_at", "signed_at", "doc_sha256", "signed_sha256", "drive_path", "drive_state",
            "notice_state", "page", "box", "doc_size")
    row = {k: env.get(k) for k in keep}
    row["link"] = None            # a link is minted where it is needed, never served from a listing
    return row


def _public_env(token: str) -> tuple[dict | None, str]:
    env = store().by_token(token)
    if not env:
        return None, "missing"
    if env["status"] == "cancelled":
        return env, "missing"
    if env["status"] == "signed":
        return env, "ok"
    if store().expired(env):
        return env, "expired"
    if env["status"] == "declined":
        return env, "missing"
    return env, "ok"


def _needs_unlock(env: dict) -> bool:
    return bool(env.get("pw_hash"))


def _unlocked(env: dict) -> bool:
    return session.get("unlocked") == _token_of(env)


def _token_of(env: dict) -> str:
    # the session keeps the token the visitor proved the password for; `_public_env` already resolved it
    return request.view_args.get("token", "") if request.view_args else ""


SENTENCES = {
    "missing": ("הקישור הזה אינו בתוקף", "ייתכן שהקישור בוטל, או שהחתימה כבר הושלמה."),
    "expired": ("פג התוקף של הקישור הזה", "אפשר לבקש קישור חדש מהלשכה."),
    "locked": ("המסמך נעול עד להזנת הסיסמה", "הסיסמה נשלחה אליכם בנפרד מהקישור."),
    "failed": ("החתימה לא הושלמה", "הלשכה קיבלה דיווח ותחזור אליכם עם קישור חדש."),
}


def _public_sentence(kind: str) -> Response:
    title, body = SENTENCES.get(kind, SENTENCES["missing"])
    return Response(render_template("sentence.html", title=title, body=body, kind=kind),
                    status=200, mimetype="text/html")


def build() -> Flask:
    return routes(create_app())


app = None


def main() -> None:
    global app
    app = build()
    port = int(os.environ.get("ESIGN_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
