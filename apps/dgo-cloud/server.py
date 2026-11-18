#!/usr/bin/env python3
"""dgo-cloud — DGO net's first product: a managed DGO of your own in a minute (DGO-1893).

The owner, 2026-11-14: sign up (Google or e-mail) → pay ₪99 a month (Cardcom) → a secured DGO on a Hostinger server
in seconds, with ₪24 a month of tokens in our LLM router on any model → Bina manages every client DGO and the network
from one admin screen, «examplex level».

ONE SERVICE, FOUR DOORS (the modules are the seams the generic apps will be cut along: accounts, payments, compute, ai):
  the site      `/`  — the offer, sign-up, «my DGO», billing, and the admin («ניהול») — one page, Hebrew, RTL
  the API       `/api/…` — {"ok": true, "data": …} | {"ok": false, "error": "<a sentence for a person>"}; a write
                from a browser carries X-DGO: 1 (a cross-site form cannot)
  the nodes     `/api/node/…`, `/api/acme/…`, `/node/install.sh|agent.py` — the client servers' agents (provision.py)
  the router    any path on a host named in DGOCLOUD_LLM_HOSTS (llm.<domain>), or `/llm/…` here (router.py)
and, beside them, an authoritative DNS server for the client servers' zone (dnsd.py) when DGOCLOUD_DNS_PORT is set.
Standard library only; one SQLite file in /data.
"""
import base64
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import accounts as acc_mod  # noqa: E402
import billing as bill_mod  # noqa: E402
import cardcom  # noqa: E402
import dnsd  # noqa: E402
import hostinger  # noqa: E402
import provision as prov_mod  # noqa: E402
from accounts import Accounts, sha, throttle  # noqa: E402
from billing import Billing  # noqa: E402
from provision import Provisioner  # noqa: E402
import router as router_mod  # noqa: E402
from router import Router, RouterError, load_prices  # noqa: E402
from store import (NODE_HE, PAY_HE, SUB_HE, NotFound, Refused, Store, now, later, shekels)  # noqa: E402

PORT = int(os.environ.get("DGOCLOUD_PORT", "8080"))
DATA = os.environ.get("DGOCLOUD_DATA", "/data")
STATIC = os.path.join(HERE, "static")
PUBLIC_URL = os.environ.get("DGOCLOUD_PUBLIC_URL", "http://localhost:8080").rstrip("/")
LLM_URL = os.environ.get("DGOCLOUD_LLM_URL", PUBLIC_URL + "/llm").rstrip("/")
LLM_HOSTS = [h.strip().lower() for h in os.environ.get("DGOCLOUD_LLM_HOSTS", "llm.,dgo-llm.").split(",") if h.strip()]
COOKIE = "dgc_session"
SECURE = PUBLIC_URL.startswith("https://")
JSON_MAX = 1048576

store = Store(os.path.join(DATA, "dgo-cloud.db"))
accounts = Accounts(store)
provider = hostinger.provider()


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


prov = Provisioner(store, provider, PUBLIC_URL, LLM_URL, log=log)
billing = Billing(store, PUBLIC_URL, on_paid=prov.on_paid, on_stopped=prov.on_stopped, log=log)
router = Router(store, billing, log=log)


class Out:
    """The router writes a streamed answer through this."""

    def __init__(self, h):
        self.h = h
        self.started = False
        self.gone = False

    def start(self, status, headers):
        self.started = True
        try:
            self.h.send_response(status)
            for k, v in headers.items():
                self.h.send_header(k, v)
            self.h.send_header("Connection", "close")
            self.h.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.gone = True

    def write(self, b):
        """Never raises: a client that hung up only stops the writing — the router keeps reading upstream to the
        final usage, so the call is still metered (the second reader's #4)."""
        if self.gone:
            return
        try:
            self.h.wfile.write(b)
            self.h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.gone = True

    def done(self):
        self.h.close_connection = True


def node_view(n, full=False):
    if not n:
        return None
    v = {"id": n["id"], "name": n["name"], "state": n["state"], "state_he": NODE_HE.get(n["state"], n["state"]),
         "progress": n["progress"], "console": prov_mod.console_url(n) if n["ip"] else "",
         "domain": prov_mod.node_domain(n["name"], n["ip"]), "admin_user": n["admin_user"],
         "password_waiting": bool(n["admin_pw"]), "claimed_at": n["claimed_at"], "created_at": n["created_at"],
         "datacenter": n["datacenter"], "last_seen": n["last_seen"]}
    if full:
        v.update({"ip": n["ip"], "provider": n["provider"], "provider_id": n["provider_id"], "plan": n["plan"],
                  "account_id": n["account_id"], "subscription_id": n["subscription_id"], "ready_at": n["ready_at"],
                  "last_error": n["last_error"], "health": _json(n["health"]), "version": n["version"]})
    return v


def _json(s):
    try:
        return json.loads(s or "{}")
    except ValueError:
        return {}


def sub_view(s):
    if not s:
        return None
    return {"id": s["id"], "plan": s["plan"], "plan_name": bill_mod.PLANS.get(s["plan"], {}).get("name", s["plan"]),
            "status": s["status"], "status_he": SUB_HE.get(s["status"], s["status"]), "price": s["price"],
            "price_he": shekels(s["price"]), "credit_he": shekels(s["credit"]), "period": s["period"],
            "period_start": s["period_start"], "period_end": s["period_end"], "next_charge_at": s["next_charge_at"],
            "cancel_at_end": bool(s["cancel_at_end"]), "card_last4": s["card_last4"], "last_error": s["last_error"],
            "failures": s["failures"], "account_id": s["account_id"]}


PAY_KIND_HE = {"first": "חודש ראשון", "renewal": "חידוש חודשי", "topup": "טעינת קרדיט"}


def pay_view(p):
    return {"id": p["id"], "kind": p["kind"], "kind_he": PAY_KIND_HE.get(p["kind"], p["kind"]),
            "amount": p["amount"], "amount_he": shekels(p["amount"]),
            "status": p["status"], "status_he": PAY_HE.get(p["status"], p["status"]), "doc_number": p["doc_number"],
            "doc_url": p["doc_url"], "created_at": p["created_at"], "paid_at": p["paid_at"],
            "card_last4": p["card_last4"], "error": p["error"], "account_id": p["account_id"]}


def dashboard(aid):
    a = accounts.get(aid)
    sub = billing.current(aid)
    node = store.one("SELECT * FROM nodes WHERE account_id=? AND state NOT IN ('destroyed') ORDER BY id DESC LIMIT 1",
                     aid)
    bal = store.balance(aid)
    month = now()[:7]
    by_model = store.all("SELECT model, COUNT(*) calls, SUM(in_tokens) tin, SUM(out_tokens) tout, SUM(cost) cost "
                         "FROM usage WHERE account_id=? AND created_at >= ? GROUP BY model ORDER BY cost DESC", aid,
                         month + "-01")
    pays = store.all("SELECT * FROM payments WHERE account_id=? AND status<>'abandoned' ORDER BY id DESC LIMIT 24", aid)
    waiting = bool(sub and sub["status"] in ("active", "past_due") and not node)
    return {"account": accounts.public(a), "subscription": sub_view(sub), "node": node_view(node), "waiting": waiting,
            "wallet": {"plan": bal["plan"], "topup": bal["topup"], "total": bal["total"],
                       "total_he": shekels(bal["total"]), "plan_he": shekels(bal["plan"]),
                       "topup_he": shekels(bal["topup"])},
            "usage": [dict(r, cost_he=shekels(r["cost"] or 0)) for r in by_model],
            "payments": [pay_view(p) for p in pays], "llm_url": LLM_URL,
            "topups": [{"amount": t, "amount_he": shekels(t)} for t in bill_mod.TOPUPS]}


def admin_overview():
    subs = store.all("SELECT status, COUNT(*) n, SUM(price) p FROM subscriptions GROUP BY status")
    month = now()[:7] + "-01"
    rev = store.one("SELECT COALESCE(SUM(amount),0) a, COUNT(*) n FROM payments WHERE status='paid' AND paid_at>=?",
                    month)
    llm = store.one("SELECT COALESCE(SUM(cost),0) c, COALESCE(SUM(usd_micros),0) u, COUNT(*) n FROM usage WHERE "
                    "created_at>=?", month)
    nodes = store.all("SELECT state, COUNT(*) n FROM nodes GROUP BY state")
    accounts_n = store.one("SELECT COUNT(*) n FROM accounts")["n"]
    mrr = sum(r["p"] or 0 for r in subs if r["status"] in ("active", "past_due"))
    price = provider.price_of() if provider and provider.configured() and provider.name == "simulate" else None
    return {"accounts": accounts_n, "subs": {r["status"]: r["n"] for r in subs}, "mrr": mrr, "mrr_he": shekels(mrr),
            "revenue_month": rev["a"], "revenue_month_he": shekels(rev["a"]), "payments_month": rev["n"],
            "llm_month": {"calls": llm["n"], "charged_he": shekels(llm["c"]), "cost_usd": round(llm["u"] / 1e6, 2)},
            "nodes": {r["state"]: r["n"] for r in nodes}, "pool": {"target": prov.pool_target(),
                                                                   "paused": bool(store.setting("pool_paused", False))},
            "waiting": len(prov.waiting()),
            "to_refund": store.one("SELECT COUNT(*) n FROM payments WHERE status='paid' AND error LIKE '%להחזיר%'")["n"],
            "pool_paused_why": _json((store.one("SELECT detail FROM audit WHERE action='pool.paused' ORDER BY id DESC "
                                                "LIMIT 1") or {}).get("detail")).get("why", ""),
            "config": {"payments": cardcom.mode(), "compute": provider.name if provider and provider.configured()
                       else "off", "zone": prov_mod.zone(), "llm_providers": router.providers(),
                       "ops_key": bool(os.environ.get("DGOCLOUD_OPS_KEY")),
                       "google": acc_mod.google_configured(), "price": price, "prices": _prices_public()},
            "audit": store.all("SELECT * FROM audit ORDER BY id DESC LIMIT 40")}


def _prices_public():
    p = load_prices(store)
    return {"usd_ils": p["usd_ils"], "margin": p["margin"], "updated": p["updated"],
            "models": [{"id": k, **v} for k, v in p["models"].items()]}


def admin_accounts(q=""):
    like = f"%{q.strip()}%"
    rows = store.all("SELECT * FROM accounts WHERE email LIKE ? OR name LIKE ? OR company LIKE ? ORDER BY id DESC "
                     "LIMIT 500", like, like, like)
    out = []
    for a in rows:
        s = billing.current(a["id"])
        n = store.one("SELECT * FROM nodes WHERE account_id=? AND state<>'destroyed' ORDER BY id DESC LIMIT 1", a["id"])
        out.append(dict(accounts.public(a), last_seen=a["last_seen"], subscription=sub_view(s), node=node_view(n),
                        balance_he=shekels(store.balance(a["id"])["total"])))
    return out


def admin_account(aid):
    a = accounts.get(aid)
    return {"account": dict(accounts.public(a), last_seen=a["last_seen"], last_ip=a["last_ip"]),
            "subscriptions": [sub_view(s) for s in billing.subs(aid)],
            "payments": [pay_view(p) for p in store.all("SELECT * FROM payments WHERE account_id=? ORDER BY id DESC",
                                                        aid)],
            "nodes": [node_view(n, True) for n in store.all("SELECT * FROM nodes WHERE account_id=? ORDER BY id DESC",
                                                            aid)],
            "wallet": [dict(w, delta_he=shekels(w["delta"])) for w in
                       store.all("SELECT * FROM wallet WHERE account_id=? ORDER BY id DESC LIMIT 200", aid)],
            "balance": store.balance(aid),
            "usage": store.all("SELECT model, COUNT(*) calls, SUM(in_tokens) tin, SUM(out_tokens) tout, SUM(cost) cost,"
                               " SUM(usd_micros) usd FROM usage WHERE account_id=? GROUP BY model", aid),
            "audit": store.all("SELECT * FROM audit WHERE target=? OR actor=? ORDER BY id DESC LIMIT 100", f"a:{aid}",
                               f"a:{aid}")}


def index_html():
    """The one page, its script and sheet named by their version: they are cached, so a new deploy must change their
    address or a browser keeps yesterday's screen for the cache's five minutes."""
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        page = f.read()
    for name in ("app.css", "app.js"):
        v = int(os.path.getmtime(os.path.join(STATIC, name)))
        page = page.replace(f"/static/{name}\"", f"/static/{name}?v={v}\"")
    return page


# ── the handler ──────────────────────────────────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    server_version = "dgo-cloud/1"
    sys_version = ""

    def log_message(self, fmt, *a):
        if os.environ.get("DGOCLOUD_ACCESS_LOG") == "1":
            log(self.address_string(), fmt % a)

    # ── plumbing ─────────────────────────────────────────────────────────────────────────────────────
    def ip(self):
        xf = self.headers.get("X-Forwarded-For", "")
        return (xf.split(",")[0].strip() if xf else self.client_address[0])[:64]

    def body(self, limit=JSON_MAX):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise Refused("הבקשה גדולה מדי.")
        return self.rfile.read(n) if n else b""

    def jbody(self):
        raw = self.body()
        if not raw:
            return {}
        try:
            d = json.loads(raw)
        except ValueError:
            raise Refused("הבקשה לא תקינה.")
        if not isinstance(d, dict):
            raise Refused("הבקשה לא תקינה.")
        return d

    def send(self, status, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' "
                             "'unsafe-inline'; frame-ancestors 'none'; form-action 'self' https://secure.cardcom.solutions")
            self.send_header("Cache-Control", "no-cache")
        for k, v in (headers or {}).items():
            if isinstance(v, list):
                for one in v:
                    self.send_header(k, one)
            else:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def ok(self, data=None, headers=None):
        self.send(200, {"ok": True, "data": data}, headers=headers)

    def redirect(self, to, headers=None):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        for k, v in (headers or {}).items():
            for one in (v if isinstance(v, list) else [v]):
                self.send_header(k, one)
        self.end_headers()

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def set_cookie(self, name, value, max_age):
        return (f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}" + ("; Secure" if SECURE else ""))

    def session(self):
        return accounts.by_session(self.cookie(COOKIE))

    def me(self, need=True):
        """→ (actor account, effective account id, viewing?) — the effective one is the target while VIEW AS."""
        s = self.session()
        if not s:
            if need:
                raise PermissionError("צריך להיכנס.")
            return None, None, False
        a = accounts.get(s["account_id"])
        target = accounts.viewing(a["id"]) if a["admin"] else None
        return a, (target or a["id"]), bool(target)

    def admin(self):
        a, _, _ = self.me()
        if not a["admin"]:
            raise PermissionError("למנהלי DGO Cloud בלבד.")
        return a

    def browser_write(self):
        if self.headers.get("X-DGO") != "1":
            raise PermissionError("בקשה בלי הכותרת של האתר.")

    def node_auth(self):
        tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        n = prov.node_by_secret(tok)
        if not n:
            raise PermissionError("unknown node")
        return n

    def acme_auth(self):
        h = self.headers.get("Authorization") or ""
        if not h.startswith("Basic "):
            raise PermissionError("basic auth required")
        try:
            name, _, secret = base64.b64decode(h[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            raise PermissionError("bad credentials")
        n = prov.node_by_secret(secret)
        if not n or n["name"] != name:
            raise PermissionError("bad credentials")
        return n

    # ── dispatch ─────────────────────────────────────────────────────────────────────────────────────
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        u = urlparse(self.path)
        path = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        host = (self.headers.get("Host") or "").lower()
        try:
            if any(host.startswith(h) for h in LLM_HOSTS) or path.startswith("/llm/"):
                return self._router(method, path[4:] if path.startswith("/llm/") else path)
            if path.startswith("/api/"):
                return self._api(method, path, q)
            return self._page(method, path, q)
        except PermissionError as e:
            self.send(401 if "להיכנס" in str(e) or "node" in str(e) or "auth" in str(e) else 403,
                      {"ok": False, "error": str(e)})
        except Refused as e:
            self.send(400, {"ok": False, "error": str(e)})
        except NotFound as e:
            self.send(404, {"ok": False, "error": str(e) or "לא נמצא"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log("ERROR", method, path, traceback.format_exc())
            try:
                self.send(500, {"ok": False, "error": "משהו השתבש אצלנו. נסו שוב בעוד רגע."})
            except OSError:
                pass

    # ── the router ───────────────────────────────────────────────────────────────────────────────────
    def _router(self, method, path):
        if method == "GET" and path in ("/v1/models", "/models"):
            return self.send(200, router.models())
        if method == "GET" and path in ("/", "/healthz"):
            return self.send(200, {"ok": True, "service": "dgo-cloud llm router"})
        if method != "POST" or path not in ("/v1/chat/completions", "/chat/completions", "/v1/messages"):
            return self.send(404, {"error": {"message": "not found", "type": "not_found_error"}})
        out = Out(self)
        try:
            # the body is read only once the key is good: an anonymous 16 MB POST costs a header check, not memory
            router.handle(path, self.headers, lambda: self.body(limit=router_mod.MAX_BODY), out)
        except RouterError as e:
            if not out.started:
                self.send(e.status, {"type": "error", "error": {"message": str(e), "type": e.kind}})
        except Refused as e:
            if not out.started:
                self.send(413, {"error": {"message": str(e), "type": "invalid_request_error"}})

    # ── pages ────────────────────────────────────────────────────────────────────────────────────────
    def _page(self, method, path, q):
        if path == "/healthz":
            store.one("SELECT 1 AS ok")
            return self.send(200, {"ok": True})
        if path in ("/node/install.sh", "/node/agent.py"):
            with open(os.path.join(HERE, "node", path.rsplit("/", 1)[1]), "rb") as f:
                return self.send(200, f.read(), "text/plain; charset=utf-8")
        if path.startswith("/dev/cardcom/") and cardcom.simulated():
            return self._sim_cardcom(method, path.rsplit("/", 1)[1])
        if path.startswith("/static/"):
            name = os.path.normpath(path[len("/static/"):]).lstrip("/")
            full = os.path.join(STATIC, name)
            if ".." in name or not os.path.isfile(full):
                return self.send(404, "not found", "text/plain")
            ctype = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png",
                     "html": "text/html", "json": "application/json", "webmanifest": "application/manifest+json"}.get(
                name.rsplit(".", 1)[-1], "application/octet-stream")
            with open(full, "rb") as f:
                return self.send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""),
                                 {"Cache-Control": "public, max-age=300"})
        if path in ("/favicon.ico", "/favicon.svg"):
            with open(os.path.join(STATIC, "favicon.svg"), "rb") as f:
                return self.send(200, f.read(), "image/svg+xml")
        if path == "/robots.txt":
            return self.send(200, "User-agent: *\nDisallow: /api/\nDisallow: /pay/\n", "text/plain")
        return self.send(200, index_html(), "text/html; charset=utf-8")

    def _sim_cardcom(self, method, lp):
        p = cardcom.sim_page(lp)
        if not p:
            return self.send(404, "no such page", "text/plain")
        if method == "POST":
            ok = b"ok=1" in self.body()
            cardcom.sim_pay(lp, ok)
            return self.redirect(p["ok"] if ok else p["fail"])
        html = (f'<!doctype html><html dir="rtl" lang="he"><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>Cardcom (סימולציה)</title>'
                f'<link rel="stylesheet" href="/static/app.css"><body class="sim"><main class="sheet">'
                f'<h1>דף תשלום — סימולציה</h1><p>זה לא Cardcom: CARDCOM_SIMULATE=1 במשרד בדיקות.</p>'
                f'<p class="big">₪{p["amount"]}</p><form method="post"><input type="hidden" name="ok" value="1">'
                f'<button class="btn primary">לשלם</button></form><form method="post"><input type="hidden" '
                f'name="ok" value="0"><button class="btn">הכרטיס סורב</button></form></main></body></html>')
        return self.send(200, html, "text/html; charset=utf-8")

    # ── the API ──────────────────────────────────────────────────────────────────────────────────────
    def _api(self, method, path, q):
        p = path[len("/api/"):].strip("/")
        # the doors that are not a browser's: nodes, lego, Cardcom
        if p.startswith("node/") or p.startswith("acme/") or p == "cardcom/webhook":
            return self._machine(method, p, q)
        if method == "GET":
            return self._get(p, q)
        self.browser_write()
        return self._post(p, q)

    def _machine(self, method, p, q):
        if method != "POST":
            return self.send(405, {"ok": False, "error": "POST"})
        if p == "cardcom/webhook":
            raw = self.body()
            d = {}
            try:
                d = json.loads(raw) if raw[:1] in (b"{", b"[") else {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            except (ValueError, UnicodeDecodeError):
                pass
            lp = str(d.get("LowProfileId") or d.get("lowprofilecode") or q.get("lowprofilecode") or "")
            rv = str(d.get("ReturnValue") or d.get("returnvalue") or "")
            pay = store.one("SELECT id FROM payments WHERE lp_id=?", lp) if lp else None
            if not pay and re.fullmatch(r"p\d+", rv):
                pay = store.one("SELECT id FROM payments WHERE id=?", int(rv[1:]))
            if pay:
                billing.verify(pay["id"])       # the webhook is a trigger; GetLpResult decides
            return self.send(200, {"ok": True})
        if p == "node/hello":
            d = self.jbody()
            throttle("hello:" + self.ip(), limit=20, window=600)
            return self.ok(prov.hello(d.get("boot"), d))
        if p.startswith("acme/"):
            n = self.acme_auth()
            d = self.jbody()
            if p == "acme/present":
                prov.acme_present(n, d.get("fqdn"), d.get("value"))
            elif p == "acme/cleanup":
                prov.acme_cleanup(n, d.get("fqdn"), d.get("value"))
            else:
                raise NotFound()
            return self.ok()
        n = self.node_auth()
        d = self.jbody()
        if p == "node/poll":
            return self.ok(prov.poll(n, d.get("health")))
        if p == "node/progress":
            prov.progress(n, d.get("step"), bool(d.get("ok", True)), d.get("detail", ""))
            return self.ok()
        m = re.fullmatch(r"node/job/(\d+)", p)
        if m:
            prov.job_done(n, int(m.group(1)), bool(d.get("ok")), d.get("result") or {})
            return self.ok()
        raise NotFound()

    def _get(self, p, q):
        if p == "me":
            a, eff, viewing = self.me(need=False)
            cfg = {"google": acc_mod.google_configured(), "payments": cardcom.mode(), "plans": bill_mod.public_plans(),
                   "llm_url": LLM_URL}
            if not a:
                return self.ok({"account": None, "config": cfg})
            target = accounts.public(accounts.get(eff)) if viewing else None
            return self.ok({"account": accounts.public(a), "viewing": target, "config": cfg})
        if p == "plans":
            return self.ok(bill_mod.public_plans())
        if p == "auth/google":
            if not acc_mod.google_configured():
                raise Refused("הכניסה עם Google עוד לא פתוחה — היכנסו עם מייל.")
            state = secrets.token_urlsafe(24)
            return self.redirect(acc_mod.google_url(PUBLIC_URL + "/api/auth/google/callback", state),
                                 {"Set-Cookie": self.set_cookie("dgc_g", state, 600)})
        if p == "auth/google/callback":
            want = self.cookie("dgc_g")
            if not want or q.get("state") != want or not q.get("code"):
                return self.redirect("/#/signin?error=google")
            try:
                info = acc_mod.google_exchange(q["code"], PUBLIC_URL + "/api/auth/google/callback")
                a = accounts.google_account(info, self.ip())
            except Refused:
                return self.redirect("/#/signin?error=google")
            tok = accounts.open_session(a["id"], self.ip(), self.headers.get("User-Agent", ""))
            return self.redirect("/#/app", {"Set-Cookie": [self.set_cookie(COOKIE, tok, 30 * 86400),
                                                           self.set_cookie("dgc_g", "", 0)]})
        a, eff, viewing = self.me()
        if p == "dashboard":
            return self.ok(dashboard(eff))
        if p == "usage":
            days = max(1, min(int(q.get("days") or 30), 365))
            return self.ok(store.all("SELECT substr(created_at,1,10) day, model, COUNT(*) calls, SUM(in_tokens) tin, "
                                     "SUM(out_tokens) tout, SUM(cost) cost FROM usage WHERE account_id=? AND "
                                     "created_at >= ? GROUP BY day, model ORDER BY day DESC", eff,
                                     later(days=-days)))
        if p.startswith("admin/"):
            self.admin()
            return self._admin_get(p[6:], q)
        raise NotFound()

    def _admin_get(self, p, q):
        if p == "overview":
            return self.ok(admin_overview())
        if p == "accounts":
            return self.ok(admin_accounts(q.get("q", "")))
        m = re.fullmatch(r"account/(\d+)", p)
        if m:
            return self.ok(admin_account(int(m.group(1))))
        if p == "nodes":
            rows = store.all("SELECT n.*, a.email FROM nodes n LEFT JOIN accounts a ON a.id=n.account_id "
                             "ORDER BY n.id DESC LIMIT 500")
            return self.ok([dict(node_view(n, True), email=n["email"]) for n in rows])
        m = re.fullmatch(r"node/(\d+)/jobs", p)
        if m:
            return self.ok(store.all("SELECT id, verb, state, result, created_at, done_at, by FROM jobs WHERE node_id=? "
                                     "ORDER BY id DESC LIMIT 50", int(m.group(1))))
        if p == "payments":
            rows = store.all("SELECT p.*, a.email FROM payments p JOIN accounts a ON a.id=p.account_id "
                             "ORDER BY p.id DESC LIMIT 500")
            return self.ok([dict(pay_view(r), email=r["email"]) for r in rows])
        if p == "usage":
            return self.ok(store.all("SELECT u.model, u.provider, COUNT(*) calls, SUM(u.in_tokens) tin, "
                                     "SUM(u.out_tokens) tout, SUM(u.cost) cost, SUM(u.usd_micros) usd FROM usage u "
                                     "WHERE u.created_at >= ? GROUP BY u.model, u.provider ORDER BY cost DESC",
                                     now()[:7] + "-01"))
        if p == "audit":
            return self.ok(store.all("SELECT * FROM audit ORDER BY id DESC LIMIT 300"))
        raise NotFound()

    def _post(self, p, q):
        ip = self.ip()
        d = self.jbody()
        if p == "auth/signup":
            a = accounts.signup(d.get("email"), d.get("name"), d.get("password"), ip)
            tok = accounts.open_session(a["id"], ip, self.headers.get("User-Agent", ""))
            link = f"{PUBLIC_URL}/#/verify/{accounts.link(a['id'], 'verify')}"
            acc_mod.send_mail(a["email"], "ברוכים הבאים ל-DGO Cloud — אישור המייל",
                              f"שלום {a['name']}, נשאר רק לאשר שהמייל שלך.", link, "לאישור המייל",
                              "הקישור תקף שלושה ימים.")
            return self.ok(accounts.public(a), {"Set-Cookie": self.set_cookie(COOKIE, tok, 30 * 86400)})
        if p == "auth/login":
            a = accounts.login(d.get("email"), d.get("password"), ip)
            tok = accounts.open_session(a["id"], ip, self.headers.get("User-Agent", ""))
            return self.ok(accounts.public(a), {"Set-Cookie": self.set_cookie(COOKIE, tok, 30 * 86400)})
        if p == "auth/logout":
            s = self.session()
            if s:
                accounts.stop_view(s["account_id"])
            accounts.close_session(self.cookie(COOKIE))
            return self.ok(None, {"Set-Cookie": self.set_cookie(COOKIE, "", 0)})
        if p == "auth/forgot":
            throttle("forgot:" + ip, limit=10, window=3600)
            a = store.one("SELECT * FROM accounts WHERE email=? AND status='active'", (d.get("email") or "").strip())
            if a:
                link = f"{PUBLIC_URL}/#/reset/{accounts.link(a['id'], 'reset')}"
                acc_mod.send_mail(a["email"], "סיסמה חדשה ל-DGO Cloud", "ביקשת סיסמה חדשה.", link,
                                  "לבחירת סיסמה חדשה", "הקישור תקף שעתיים. לא ביקשת? אפשר להתעלם.")
            return self.ok()               # the same answer either way: nobody learns who has an account
        if p == "auth/reset":
            a = accounts.use_link(d.get("token"), "reset")
            accounts.set_password(a["id"], d.get("password"))
            tok = accounts.open_session(a["id"], ip, self.headers.get("User-Agent", ""))
            return self.ok(accounts.public(a), {"Set-Cookie": self.set_cookie(COOKIE, tok, 30 * 86400)})
        if p == "auth/verify":
            return self.ok(accounts.public(accounts.use_link(d.get("token"), "verify")))
        a, eff, viewing = self.me()
        if p == "view-as/stop":
            accounts.stop_view(a["id"])
            return self.ok()
        if viewing:
            raise Refused("במצב «צפייה בתור» אי אפשר לשנות כלום. חזרו לחשבון שלכם קודם.")
        if p.startswith("admin/"):
            self.admin()
            return self._admin_post(a, p[6:], d)
        actor = f"a:{a['id']}"
        if p == "account":
            return self.ok(accounts.public(accounts.update(a["id"], d)))
        if p == "account/password":
            if a.get("pw") and not acc_mod.check_password(d.get("current") or "", a["pw"]):
                raise Refused("הסיסמה הנוכחית לא נכונה.")
            accounts.set_password(a["id"], d.get("password"), keep_session=sha(self.cookie(COOKIE)))
            return self.ok()
        if p == "account/verify-again":
            link = f"{PUBLIC_URL}/#/verify/{accounts.link(a['id'], 'verify')}"
            sent = acc_mod.send_mail(a["email"], "אישור המייל ל-DGO Cloud", "לאישור המייל שלך:", link, "לאישור")
            return self.ok({"sent": sent})
        if p == "checkout":
            return self.ok(billing.checkout(a, d.get("plan") or "basic"))
        if p == "topup":
            return self.ok(billing.topup(a, d.get("amount")))
        if p == "subscription/pay-now":
            return self.ok(billing.pay_overdue(a))
        m = re.fullmatch(r"pay/(\d+)/verify", p)
        if m:
            pay = store.one("SELECT * FROM payments WHERE id=? AND account_id=?", int(m.group(1)), a["id"])
            if not pay:
                raise NotFound("אין תשלום כזה")
            return self.ok(pay_view(billing.verify(pay["id"])))
        if p == "subscription/cancel":
            s = billing.current(a["id"])
            return self.ok(sub_view(billing.cancel(a["id"], s["id"] if s else 0, actor)))
        if p == "subscription/resume":
            s = billing.current(a["id"])
            return self.ok(sub_view(billing.resume(a["id"], s["id"] if s else 0, actor)))
        if p == "my-dgo/reveal":
            n = store.one("SELECT * FROM nodes WHERE account_id=? AND state IN ('claimed','claiming') ORDER BY id DESC "
                          "LIMIT 1", a["id"])
            if not n:
                raise NotFound("עוד אין לך שרת.")
            return self.ok(prov.reveal_password(a["id"], n["id"]))
        if p == "my-dgo/new-password":
            n = store.one("SELECT * FROM nodes WHERE account_id=? AND state='claimed' ORDER BY id DESC LIMIT 1", a["id"])
            if not n:
                raise NotFound("עוד אין לך שרת פעיל.")
            prov.job(n["id"], "password", {"email": a["email"], "name": a["name"]}, actor)
            return self.ok()
        raise NotFound()

    def _admin_post(self, me, p, d):
        actor = f"a:{me['id']}"
        if p == "view-as":
            accounts.view(me["id"], int(d.get("account") or 0))
            return self.ok()
        m = re.fullmatch(r"account/(\d+)/(status|credit|admin|cancel)", p)
        if m:
            aid, what = int(m.group(1)), m.group(2)
            accounts.get(aid)
            if what == "status":
                st = "disabled" if d.get("status") == "disabled" else "active"
                with store.tx() as c:
                    c.execute("UPDATE accounts SET status=? WHERE id=?", (st, aid))
                    if st == "disabled":
                        c.execute("DELETE FROM sessions WHERE account_id=?", (aid,))
                    store.audit(actor, "admin.account.status", f"a:{aid}", {"status": st}, "", c)
            elif what == "credit":
                amt = int(round(float(d.get("amount") or 0) * 100))
                if not amt or abs(amt) > 100000:
                    raise Refused("סכום בין ₪-1,000 ל-₪1,000, לא אפס.")
                with store.tx() as c:
                    c.execute("INSERT INTO wallet(account_id,bucket,delta,kind,ref,note,created_at) VALUES "
                              "(?,?,?,?,?,?,?)", (aid, "topup", amt, "adjust", actor,
                                                  (d.get("note") or "התאמה ידנית")[:200], now()))
                    store.audit(actor, "admin.wallet.adjust", f"a:{aid}", {"amount": amt, "note": d.get("note")}, "", c)
            elif what == "admin":
                if aid == me["id"]:
                    raise Refused("אי אפשר לשנות את ההרשאה של עצמך.")
                store.run("UPDATE accounts SET admin=? WHERE id=?", 1 if d.get("admin") else 0, aid)
                store.audit(actor, "admin.account.admin", f"a:{aid}", {"admin": bool(d.get("admin"))})
            elif what == "cancel":
                s = billing.current(aid)
                billing.cancel(aid, s["id"] if s else 0, actor)
            return self.ok(admin_account(aid))
        if p == "nodes/order":
            return self.ok(node_view(prov.order(actor), True))
        m = re.fullmatch(r"nodes/(\d+)/(job|release|retry)", p)
        if m:
            nid, what = int(m.group(1)), m.group(2)
            n = store.one("SELECT * FROM nodes WHERE id=?", nid)
            if not n:
                raise NotFound("אין שרת כזה")
            if what == "job":
                prov.job(nid, d.get("verb"), {"email": d.get("email")} if d.get("email") else {}, actor)
            elif what == "release":
                if n["account_id"] and n["state"] in ("claimed", "claiming") and d.get("confirm") != n["name"]:
                    raise Refused(f"השרת הזה של לקוח. כדי לשחרר אותו כתבו את שמו: {n['name']}")
                prov.release(nid, actor, d.get("why", ""))
            elif what == "retry":
                if n["state"] != "failed":
                    raise Refused("אפשר לנסות שוב רק שרת בתקלה.")
                store.run("UPDATE nodes SET state='installing', last_error='', created_at=? WHERE id=?", now(), nid)
                store.audit(actor, "admin.node.retry", f"n:{nid}")
            return self.ok(node_view(store.one("SELECT * FROM nodes WHERE id=?", nid), True))
        if p == "pool":
            if "size" in d:
                size = int(d["size"])
                if not 0 <= size <= 10:
                    raise Refused("גודל המאגר בין 0 ל-10.")
                store.set_setting("pool", size)
            if "paused" in d:
                store.set_setting("pool_paused", bool(d["paused"]))
            store.audit(actor, "admin.pool", "pool", d)
            return self.ok(admin_overview()["pool"])
        if p == "pricing":
            fx, margin = float(d.get("usd_ils") or 0), float(d.get("margin") if d.get("margin") is not None else -1)
            if not 2.5 <= fx <= 6 or not 0 <= margin <= 1:
                raise Refused("שער בין 2.5 ל-6, מרווח בין 0 ל-1 (0.10 = 10%).")
            store.set_setting("usd_ils", fx)
            store.set_setting("margin", margin)
            store.audit(actor, "admin.pricing", "prices", {"usd_ils": fx, "margin": margin})
            return self.ok(_prices_public())
        m = re.fullmatch(r"payments/(\d+)/refund", p)
        if m:
            pid = int(m.group(1))
            # taken FIRST, in one statement: a second click finds it refunded and asks Cardcom nothing
            with store.tx() as c:
                took = c.execute("UPDATE payments SET status='refunded' WHERE id=? AND status='paid'", (pid,)).rowcount
            if took != 1:
                raise Refused("אפשר להחזיר רק תשלום ששולם (ואולי ההחזר כבר נשלח).")
            pay = store.one("SELECT * FROM payments WHERE id=?", pid)
            try:
                cardcom.refund(pay["tran_id"])
            except cardcom.PayError as e:
                store.run("UPDATE payments SET status='paid' WHERE id=?", pid)
                raise Refused(f"Cardcom לא ביצע את ההחזר: {e}")
            with store.tx() as c:
                if pay["kind"] == "topup":      # the credit it bought goes with it
                    c.execute("INSERT INTO wallet(account_id,bucket,delta,kind,ref,note,created_at) VALUES "
                              "(?,?,?,?,?,?,?)", (pay["account_id"], "topup", -pay["amount"], "adjust", f"p:{pid}",
                                                  "החזר טעינה", now()))
                c.execute("UPDATE payments SET error='' WHERE id=? AND error LIKE '%להחזיר%'", (pid,))
                store.audit(actor, "admin.refund", f"p:{pid}", {"amount": pay["amount"]}, "", c)
            return self.ok()
        if p == "keys/new":
            # a router key bound to an account directly (an admin's test key, a client's own tool)
            aid = int(d.get("account") or me["id"])
            accounts.get(aid)
            key = "dk_" + secrets.token_urlsafe(30)
            store.run("INSERT INTO keys(prefix,hash,account_id,name,created_at) VALUES (?,?,?,?,?)", key[:10], sha(key),
                      aid, (d.get("name") or "admin key")[:80], now())
            store.audit(actor, "admin.key.new", f"a:{aid}", {"prefix": key[:10]})
            return self.ok({"key": key})
        raise NotFound()


# ── the scheduler ────────────────────────────────────────────────────────────────────────────────────────
def scheduler():
    last_bill = 0
    while True:
        try:
            prov.tick()
        except Exception:
            log("tick:", traceback.format_exc())
        if time.time() - last_bill > int(os.environ.get("DGOCLOUD_BILL_EVERY_S", "300")):
            last_bill = time.time()
            try:
                billing.sweep_pending()
                billing.renew_due()
            except Exception:
                log("billing:", traceback.format_exc())
        time.sleep(int(os.environ.get("DGOCLOUD_TICK_S", "20")))


def first_admin():
    """DGOCLOUD_ADMINS names who administers DGO Cloud — granted to an account whose mailbox is PROVEN only (a verify or
    reset link, or Google): here at start, for one proven before the address was named."""
    for e in acc_mod.admin_emails():
        store.run("UPDATE accounts SET admin=1 WHERE email=? AND admin=0 AND proven=1", e)


def main():
    first_admin()
    if int(os.environ.get("DGOCLOUD_DNS_PORT", "0") or 0):
        try:
            dnsd.serve(dnsd.Zone(store), int(os.environ["DGOCLOUD_DNS_PORT"]), log)
        except OSError as e:
            log("dns: could not listen:", e)
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    log(f"dgo-cloud on :{PORT} — public {PUBLIC_URL}, router {LLM_URL}, payments {cardcom.mode()}, "
        f"compute {provider.name if provider and provider.configured() else 'off'}, zone {prov_mod.zone()}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
