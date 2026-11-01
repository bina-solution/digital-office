"""domains — the office's domain accounts and the domains inside them.

The model, and it is two levels on purpose
-----------------------------------------
    account  ──►  the domains of that account  ──►  one domain's settings

An **account** is a connection in the credential plane (`accounts.py`): either an API account
(GoDaddy, Cloudflare, Plesk, Porkbun, …) or a BROWSER account — a session the owner logged into once
in the office's own Chromium, which is the only door a registrar that publishes no API has
(`ai/context/browser-session-connection.md`). Nothing above `accounts.py` knows or cares which kind
it is talking to; that is the whole point of the abstraction, and it is what makes this the same
screen whether the control behind it is an HTTP endpoint or a button in someone's panel.

Three rules the layout encodes
------------------------------
1. **A refusal names the missing piece** — a capability, a credential, or the provider itself.
   Never a button that fails later.
2. **Money and irreversible operations need a human** (`MONEY_OPS`): the confirmation is an exact
   string (`"<domain>:<op>"`), not `true`, so a call made by accident cannot buy a domain.
3. **A write is proved by reading it back** — from the provider, and for DNS also from a public
   resolver that is not the provider's.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import accounts
import browser_session
import dnsq
import portal as portal_mod
import webengine
import providers
import registry
import whois as whoisq
from providers import DomainError, adapter_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("domains")

DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "bina-deployment")
SITES_URL = os.environ.get("SITES_URL", "http://sites:8979").rstrip("/")
NOTIFICATIONS_URL = os.environ.get("NOTIFICATIONS_URL", "http://notifications:8977").rstrip("/")
WHOIS_HOURS = float(os.environ.get("DOMAINS_WHOIS_HOURS", "12"))
EXPIRY_WARN_DAYS = int(os.environ.get("DOMAINS_EXPIRY_WARN_DAYS", "60"))
EXPIRY_URGENT_DAYS = int(os.environ.get("DOMAINS_EXPIRY_URGENT_DAYS", "14"))
#: provider id → the portal script it drives through the office browser
PORTAL_PROVIDERS = {"portal": "internic"}
_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="domains", docs_url=None, redoc_url=None, openapi_url=None)


def _err(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


async def _json_body(request: Request) -> dict:
    """The request body as a dict, never an exception — an empty or malformed body is `{}`.

    Every mutating route here parses its body on the event loop and then hands the BLOCKING part to
    the threadpool. That split is deliberate: parsing is `await`-able, while a vault call, a
    provider's HTTP API and a browser driving a registrar's panel are not, and running those on the
    loop freezes the whole app — including the progress stream that reports them.
    """
    try:
        raw = await request.body()
        if not raw:
            return {}
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:                                    # noqa: BLE001
        return {}


def _json(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except DomainError as e:
        return JSONResponse(e.body(), status_code=e.status)
    except whoisq.WhoisError as e:
        return _err(e.message, 502, detail=e.detail)
    except KeyError as e:
        return _err(f"לא נמצא: {e}", 404)


# ── meta ─────────────────────────────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "domains"}


@app.get("/readyz")
def readyz():
    """Ready = accounts resolve and at least one domain is watched. No provider account is required:
    watching expiry needs nothing but the public registry, and demanding a token to be "ready" would
    make a working installation report itself broken."""
    insts, err = accounts.vault_list()
    if err:
        return JSONResponse({"ready": False, "reason": err}, status_code=503)
    domains = registry.list_domains()
    if not domains:
        return JSONResponse({"ready": False,
                             "reason": "לא הוגדר אף דומיין למעקב — חבר חשבון או הוסף דומיין."},
                            status_code=503)
    return {"ready": True, "domains": len(domains), "accounts": len(insts)}


@app.get("/manifest")
def manifest():
    return {"service": "domains", "interface": "domains.v1",
            "protocols": accounts.ALL_PROTOCOLS,
            "providers": [p["id"] for p in accounts.PROVIDERS_CATALOG],
            "ops": sorted(OPS),
            "connection": {"active": accounts.active_id()},
            "capabilities": {"multi_connection": True, "accounts": True, "browser_accounts": True,
                             "registry_watch": True, "dns_snapshot": True,
                             "domains": len(registry.list_domains()),
                             "vault_available": accounts.vault_list()[1] is None}}


@app.get("/ops")
def ops_index():
    return {"service": "domains", "interface": "domains.v1", "ops": sorted(OPS),
            "accounts": "GET /api/accounts",
            "domains": "GET /api/accounts/{account}/domains"}


@app.get("/providers")
def providers_catalog():
    """The catalogue the "add account" screen is built from: who can be connected, how, and what the
    office gets from it. Provider-first, never protocol-first (§4b of the service contract)."""
    connected = {r.get("provider"): r for r in _accounts_payload(probe=False)["connections"]}
    out = []
    for p in accounts.PROVIDERS_CATALOG:
        out.append({"id": p["id"], "name": p["name"], "icon": p.get("icon"),
                    "access": p.get("access"), "reads": p.get("reads", ""),
                    "description": p.get("description", ""),
                    "auth_methods": p.get("auth_methods") or [],
                    "flow": "browser" if p["id"] in PORTAL_PROVIDERS else "api",
                    "connected": bool(connected.get(p["id"])),
                    "state": (connected.get(p["id"]) or {}).get("state"),
                    "account": (connected.get(p["id"]) or {}).get("id")})
    out.sort(key=lambda p: (p["access"] != "browser", not p["connected"], p["name"]))
    return {"providers": out, "browser": browser_session.available()}


def _decorate(d: dict) -> dict:
    """Add the derived expiry fields (date, days left, state) to a stored domain row.

    ONE place, because these three numbers are read by the list, the account view and the settings
    screen; computing them at each call site is how one of them ends up rendering "—" for a domain
    whose expiry is perfectly well known (which is exactly what happened after the rewrite).
    """
    exp = d.get("expiry")
    if exp:
        d["expiry_date"] = time.strftime("%Y-%m-%d", time.localtime(exp))
        d["days_left"] = int((exp - time.time()) / 86400)
    d["expiry_state"] = _expiry_state(d.get("days_left"))
    return d


# ── the engine: slow reads never block, slow actions are jobs, change is announced ───────────────
@app.get("/api/events")
def api_events(request: Request):
    """Server-sent events: `resource` (this key changed), `invalidate` (prefix), `job` (progress).

    One connection per open screen; the screen refreshes exactly what changed instead of polling
    everything. Heartbeat comments keep proxies from closing an idle stream.
    """
    def gen():
        q = webengine.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        except GeneratorExit:
            return
        finally:
            webengine.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@app.get("/api/jobs")
def api_jobs(limit: int = 25, active: int = 0):
    return {"jobs": webengine.jobs(limit=limit, active_only=bool(active))}


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    j = webengine.job(jid)
    return j if j else _err("לא נמצאה עבודה כזו", 404)


@app.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    j = webengine.cancel(jid)
    return j if j else _err("לא נמצאה עבודה כזו", 404)


@app.get("/api/jobs/{jid}/events")
def api_job_events(jid: str):
    """Progress of ONE job, as SSE — the 30-second action's answer to "is it stuck?"."""
    def gen():
        last = None
        for _ in range(1800):                       # 15 minutes at 0.5s, then it gives up politely
            j = webengine.job(jid)
            if not j:
                yield "data: {\"state\": \"missing\"}\n\n"
                return
            snap = {k: j.get(k) for k in ("state", "progress", "message", "error", "ended_at")}
            if snap != last:
                yield f"data: {json.dumps({**snap, 'id': jid, 'log': j.get('log') or []}, ensure_ascii=False)}\n\n"
                last = snap
            if j["state"] in ("ok", "error", "cancelled"):
                return
            time.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/accounts/{aid}/domains/{domain}/health")
def api_domain_health(aid: str, domain: str, fresh: int = 0):
    """The propagation view: the AUTHORITY first, then the public resolvers, then the drift.

    Three data layers, in the order that makes them readable, and none of them optional:

      1. **authoritative** — the zone's own nameservers, asked directly by IP. This is the truth about
         what was published; a panel's answer is only a belief about it.
      2. **observed** — 1.1.1.1 / 8.8.8.8 / 9.9.9.9, each with the TTL of what it just handed us.
         Disagreement here means "a cache is still counting down", and the TTL is the number of
         seconds left, not a guess.
      3. **drift** — what the panel holds at the apex versus what the world answers.

    Cached for 45 seconds: it is ~20 network round trips and nothing in it changes faster than a TTL.
    """
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    key = f"health:{name}"
    out = webengine.get(key, lambda: _health_payload(aid, name), ttl=45, force=bool(fresh),
                        want="fresh" if fresh else "cache")
    value = out.get("value") or {}
    return {**value, "_cache": {"age": out.get("age"), "stale": out.get("stale"),
                                "refreshing": out.get("refreshing"), "error": out.get("error")}}


def _health_payload(aid: str, name: str) -> dict:
    auth = dnsq.authoritative(name)
    dnsq_out = dnsq.snapshot_multi(name)
    # Reuse the domain payload that is ALREADY cached instead of re-reading the panel: this screen
    # must never be the reason a browser session is opened.
    cached = (webengine.peek(f"domain:{aid}:{name.lower()}") or {}).get("value") or {}
    records = cached.get("records") or []
    source = cached.get("records_source") or ("none" if not records else "unknown")
    expected: dict[str, list[str]] = {}
    for r in records:
        rn = (r.get("name") or "@").rstrip(".").lower()
        if rn not in ("@", name.lower(), ""):
            continue
        t = (r.get("type") or "").upper()
        v = _norm_value(r)
        if not t or not v:
            continue
        if v not in expected.setdefault(t, []):
            expected[t].append(v)
    for t in expected:
        expected[t] = sorted(expected[t])

    observed = {t: list((auth.get("records") or {}).get(t) or []) for t in auth.get("records") or {}}
    # NS is deliberately NOT compared here: the panel's zone editor does not render the apex NS
    # RRset, and the question "do the delegated nameservers match the ones the zone answers with"
    # is answered directly below, from the delegation and the zone itself.
    observed.pop("NS", None)
    expected.pop("NS", None)
    types = sorted(set(expected) | set(observed))
    drift, world_only, panel_only = [], [], []
    for t in types:
        exp, obs = expected.get(t, []), observed.get(t, [])
        if exp and obs:
            missing = [v for v in exp if v not in obs]
            extra = [v for v in obs if v not in exp]
            if missing or extra:
                drift.append({"type": t, "expected": exp, "observed": obs,
                              "missing": missing, "extra": extra})
        elif obs and not exp:
            # The world answers a type the panel does not show. That is not a fault, and calling it
            # "the zone is missing a record" would be a false alarm: the record exists, this panel
            # just does not render it (the registrar's editor is not the whole zone).
            world_only.append({"type": t, "observed": obs})
        elif exp and not obs:
            panel_only.append({"type": t, "expected": exp})

    ttl_values = [v for t, ttls in (auth.get("ttls") or {}).items() for v in ttls.values()
                  if isinstance(v, int)]
    min_ttl = min(ttl_values) if ttl_values else None
    issues: list[dict] = []
    reg_ns = sorted((cached.get("registry") or {}).get("nameservers") or [])
    auth_ns = sorted(auth.get("nameservers") or [])
    if reg_ns and auth_ns and set(reg_ns) != set(auth_ns):
        issues.append({"level": "warn", "title": "שרתי השמות ברישום אינם אלה שמשיבים",
                       "detail": f"ברישום: {', '.join(reg_ns)} · בפועל: {', '.join(auth_ns)}",
                       "fix": "אם זה עתה שינית delegation — זו ההמתנה של ה-TLD, עד 24 שעות."})
    # The NS the PARENT delegates to versus the NS the CHILD zone publishes: the most common way a
    # live domain stops answering, and it is invisible in every single-source view — the registrar
    # looks right, the zone looks right, and part of the world reaches nothing.
    apex_ns = sorted(auth.get("apex_ns") or [])
    if apex_ns and auth_ns and set(apex_ns) != set(auth_ns):
        issues.append({
            "level": "error", "title": "ה-zone מצהיר על שרתי שמות אחרים מאלה שאליהם מפנה הרישום",
            "detail": f"delegation: {', '.join(auth_ns)} · בתוך ה-zone: {', '.join(apex_ns)}",
            "fix": "אחד הצדדים שגוי — רשומת ה-NS בתוך האזור, או ה-delegation אצל הרשם."})
    if not any(observed.get(t) for t in ("A", "AAAA", "CNAME")):
        issues.append({"level": "error", "title": "לדומיין אין כתובת",
                       "detail": "אף אחד מהמאחזרים לא קיבל A/AAAA/CNAME עבור שם הדומיין עצמו.",
                       "fix": "הוסף רשומת A (או CNAME) לשם @ באזור."})
    if drift:
        issues.append({"level": "warn",
                       "title": f"{len(drift)} סוגי רשומות אינם תואמים בין האזור לעולם",
                       "detail": "מה שהאזור מפרסם מול מה שהמאחזרים משיבים: " +
                                 "; ".join(f"{dd['type']}: חסר {', '.join(dd['missing']) or '—'} / "
                                           f"עודף {', '.join(dd['extra']) or '—'}" for dd in drift),
                       "fix": "אם כתבת עכשיו — המתן ל-TTL. אחרת זו רשומה שלא נשמרה."})
    if panel_only:
        issues.append({"level": "warn",
                       "title": f"{len(panel_only)} סוגי רשומות מופיעים בפאנל ואינם נענים מהעולם",
                       "detail": "; ".join(f"{dd['type']}: {', '.join(dd['expected'])}"
                                           for dd in panel_only),
                       "fix": "הרשומה שמורה אצל הספק אבל לא יוצאת החוצה — בדוק שה-delegation "
                              "מצביע לשרתי השמות הנכונים."})
    if auth.get("errors"):
        issues.append({"level": "warn", "title": "חלק מהשאילתות לשרתים המוסמכים לא צלחו",
                       "detail": "; ".join(f"{k}: {v}" for k, v in auth["errors"].items())[:400],
                       "fix": "בדוק שוב; אם זה נמשך, אחד משרתי השמות של האזור אינו עונה."})
    disagree = [t for t, a in (dnsq_out.get("agreement") or {}).items() if a.get("values")
                and not a.get("consistent")]
    if disagree:
        issues.append({"level": "warn", "title": f"המאחזרים חלוקים לגבי {', '.join(disagree)}",
                       "detail": "חלק מהמאחזרים עוד מגישים ערך ישן מהמטמון שלהם.",
                       "fix": f"המתנה של עד {min_ttl} שניות (ה-TTL שנקרא כרגע) תסגור את הפער."
                       if min_ttl else "המתן עד שהמטמון יפוג."})
    return {"domain": name, "checked_at": int(time.time()),
            "authority": auth, "resolvers": dnsq_out, "expected": expected,
            "records_source": source, "records_count": len(records), "drift": drift,
            "world_only": world_only, "panel_only": panel_only,
            "issues": issues,
            "caching": {"min_ttl": min_ttl, "negative": min_ttl is None,
                        "note": ("ה-TTL הוא הזמן המרבי שבו מאחזר עדיין יציג את הערך הקודם."
                                 if min_ttl else "לא נקרא TTL — אין תשובה מהאזור.")}}


def _norm_value(r: dict) -> str:
    """One record's value, in the shape a resolver would answer it — so a comparison is possible."""
    v = str(r.get("content") or "").strip()
    t = (r.get("type") or "").upper()
    if not v:
        return ""
    if t in ("MX", "SRV") and r.get("priority") not in (None, ""):
        prio = str(r["priority"]).strip()
        if not v.startswith(prio + " "):
            v = f"{prio} {v}"
    return v.rstrip(".")


@app.get("/api/accounts/{aid}/domains/{domain}/dns")
def api_domain_dns(aid: str, domain: str, fresh: int = 0):
    """What every public resolver answers for this domain, and whether they agree.

    Cached (TTL 60s) because it is three network round trips per record type — and served stale
    while it refreshes, like every other slow read here.
    """
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    key = f"dns:{name}"
    out = webengine.get(key, lambda: dnsq.snapshot_multi(name), ttl=60, force=bool(fresh),
                        want="fresh" if fresh else "cache")
    return {**(out.get("value") or {}),
            "_cache": {"age": out.get("age"), "stale": out.get("stale"),
                       "refreshing": out.get("refreshing")}}


@app.get("/api/resources")
def api_resources():
    """What is cached right now, how old it is, and whether a refresh is in flight.

    Shown in the UI's "מה נטען ומתי" panel — a screen that says how old its data is can be trusted;
    one that pretends everything is live cannot.
    """
    rows = webengine.conn().execute(
        "SELECT key, fetched_at, ttl, state, error FROM resources ORDER BY key").fetchall()
    return {"resources": [{"key": r["key"], "age": webengine.now() - r["fetched_at"], "ttl": r["ttl"],
                           "stale": (webengine.now() - r["fetched_at"]) > r["ttl"],
                           "state": r["state"], "error": r["error"]} for r in rows]}


# ── ACCOUNTS ─────────────────────────────────────────────────────────────────────────────────────
def _accounts_payload(probe: bool = True) -> dict:
    insts, err = accounts.vault_list()
    if err:
        return {"active": None, "connections": [], "reason": err}
    rows = [accounts.account_row(i) for i in insts] if probe else [
        {"id": i.get("id"), "label": i.get("label"),
         "provider": providers.PROVIDER_OF.get(i.get("protocol") or "", ""),
         "protocol": i.get("protocol"), "account_hint": i.get("account_hint") or "",
         "state": "unknown", "ok": None} for i in insts]
    for r in rows:
        r["access"] = next((p.get("access") for p in accounts.PROVIDERS_CATALOG
                            if p["id"] == r.get("provider")), None)
        r["domains_watched"] = len([d for d in registry.list_domains()
                                    if d.get("account") == r.get("id")])
    rows.sort(key=lambda r: (not r.get("ok"), r.get("label") or ""))
    active = accounts.active_id()
    if active and not any(r["id"] == active for r in rows):
        active = None
    return {"active": active, "connections": rows}


@app.get("/connections")
def connections(probe: int = 1):
    return _accounts_payload(probe=bool(probe))


@app.post("/connections/select")
async def connections_select(request: Request):
    body = await _json_body(request)
    return api_account_activate((body or {}).get("id") or "")


@app.post("/connections")
async def connections_add(request: Request):
    return await run_in_threadpool(_accounts_post, await _json_body(request))


@app.delete("/connections/{cid}")
def connections_delete(cid: str):
    return api_account_delete(cid)


@app.post("/connections/{cid}/probe")
def connections_probe(cid: str):
    return api_account_probe(cid)


@app.get("/api/accounts")
def api_accounts(probe: int = 1, fresh: int = 0):
    """Every account with its live state — CACHED and revalidated behind the request.

    Probing an account whose control is a browser panel takes tens of seconds; a screen that waited
    for it would be unusable. So the answer is served from the cache however old it is (and says how
    old), while a refresh runs in the background and the change feed tells the screen when it lands.
    """
    def loader():
        return _accounts_payload(probe=bool(probe))
    res = webengine.get("accounts", loader, ttl=30, force=bool(fresh),
                        want="fresh" if fresh else "cache")
    return {**(res.get("value") or {"active": None, "connections": []}),
            "_cache": {"age": res.get("age"), "stale": res.get("stale"),
                       "refreshing": res.get("refreshing"), "error": res.get("error")}}


@app.post("/api/accounts")
async def api_accounts_post(request: Request):
    """Connect an API account: provider + method → the secret → VERIFY → store.

    Verified BEFORE it is stored: a connection is never "added", it is proven. A token that cannot
    answer is rejected here with the provider's own words, instead of becoming a red row that fails
    later in the middle of a change.
    """
    # Verification is a network call to the provider; it runs in the threadpool so a slow provider
    # cannot stop the process from answering anything else (see the module docstring's third rule).
    return await run_in_threadpool(_accounts_post, await _json_body(request))


def _accounts_post(body: dict):
    body = body or {}
    provider = (body.get("provider") or "").strip()
    if not accounts.protocol_for(provider):
        return _err(f"ספק לא מוכר: {provider!r}")
    method_id = (body.get("method") or "").strip() or next(
        (m["id"] for p in accounts.PROVIDERS_CATALOG if p["id"] == provider
         for m in (p.get("auth_methods") or [])), "api_key")
    method = accounts.auth_method(provider, method_id)
    if not method:
        return _err(f"שיטת חיבור לא מוכרת: {method_id!r}")
    secret = {k: (body.get(k) or "").strip() for k in
              ("token", "key", "secret", "account_id", "shopper_id") if (body.get(k) or "").strip()}
    if body.get("ote"):
        secret["ote"] = True
    for field in method.get("needs") or []:
        if not secret.get(field):
            return _err(f"חסר שדה חובה: {field}")
    if not secret:
        secret = {"auth": "public",
                  "note": "אין סוד — הספק הזה נקרא מהרישום הציבורי (WHOIS/DNS)"}
    try:
        who = adapter_for(provider, secret).whoami()
    except DomainError as e:
        return JSONResponse({"verified": False, **e.body()}, status_code=e.status)
    hint = who.get("login") or provider
    stored, status = accounts.vault_add(accounts.protocol_for(provider),
                                        (body.get("label") or "").strip() or f"{provider}: {hint}",
                                        secret, hint)
    if status >= 300:
        return JSONResponse({"verified": True, "stored": False,
                             "error": stored.get("error") or "שמירת החשבון בוולט נכשלה",
                             "detail": stored}, status_code=status)
    cid = stored.get("id")
    if not accounts.active_id():
        accounts.set_active(cid)
    accounts.forget_probe(cid)
    registry.event(None, "account_connected", f"חובר חשבון {provider}", {"id": cid, "login": hint})
    return {"ok": True, "verified": True, "stored": True, "id": cid, "login": who.get("login"),
            "capabilities": who.get("capabilities") or {}, "active": accounts.active_id()}


@app.post("/api/accounts/browser")
async def api_account_browser(request: Request):
    """The BROWSER flow, in one call: check the session → hand over ONE login link when a human is
    needed → and once they are in, PROVE control by reading the account's own domain list.

    Called repeatedly by the screen (it polls); `step` says exactly where it is. No password is typed
    into this app and no cookie is copied — the account stores a POINTER to the office's own browser
    plus the site it speaks for.

    This is the LONGEST call in the app by far (a panel navigation, up to the 150s budget in
    browser_ops), and the screen polls it — so it MUST NOT run on the event loop, or the app would
    stop answering its own health check while a human logs in.
    """
    return await run_in_threadpool(_account_browser, await _json_body(request))


def _account_browser(body: dict):
    body = body or {}
    pid = (body.get("provider") or "portal").strip()
    if pid not in PORTAL_PROVIDERS:
        return _err(f"לספק {pid} אין מסלול דפדפן")
    res = _json(portal_mod.connect_check, PORTAL_PROVIDERS[pid])
    if isinstance(res, JSONResponse):
        return res
    if res.get("step") != "connected":
        return JSONResponse(res, status_code=200)              # a state, not an error
    origin = portal_mod.SCRIPTS[PORTAL_PROVIDERS[pid]]["origin"]
    existing = [i for i in (accounts.vault_list()[0] or [])
                if i.get("protocol") == "domain_portal_session"]
    if existing:
        accounts.set_active(existing[0]["id"])
        return {**res, "stored": True, "id": existing[0]["id"], "already": True}
    secret = {"auth": "browser", "portal": PORTAL_PROVIDERS[pid], "origin": origin,
              "endpoint": browser_session.DEFAULT_ENDPOINT,
              "token_connection": "browser42-mcp-token",
              "note": "סשן בדפדפן הלשכה — אין כאן סיסמה ואין cookies"}
    stored, status = accounts.vault_add("domain_portal_session",
                                        body.get("label") or f"פורטל {res.get('name') or pid}",
                                        secret, f"browser@{origin}")
    if status >= 300:
        return JSONResponse({"step": "error", "error": stored.get("error") or "שמירה נכשלה",
                             "detail": stored, **res}, status_code=status)
    accounts.set_active(stored.get("id"))
    accounts.forget_probe(stored.get("id"))
    registry.event(None, "account_connected", f"חובר חשבון {pid} דרך הדפדפן",
                   {"id": stored.get("id"), "evidence": res.get("evidence")})
    return {**res, "stored": True, "id": stored.get("id")}


@app.get("/api/accounts/{aid}/probe")
def api_account_probe(aid: str):
    inst, sec, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    accounts.forget_probe(aid)
    return {"id": aid, **accounts.probe_instance(inst, sec or {}, max_age=0)}


@app.post("/api/accounts/{aid}/activate")
def api_account_activate(aid: str):
    inst, _sec, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    accounts.set_active(inst["id"])
    return {"ok": True, "active": inst["id"]}


@app.delete("/api/accounts/{aid}")
def api_account_delete(aid: str):
    """Disconnect an account. The CREDENTIAL leaves the vault; the domains it introduced stay watched
    — their expiry is public information, and losing the watch on disconnect would be a regression."""
    inst, _sec, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    out, status = accounts.vault_delete(aid)
    if status < 300:
        accounts.forget_probe(aid)
        if accounts.active_id() == aid:
            rest, _ = accounts.vault_list()
            accounts.set_active(rest[0]["id"] if rest else None)
    return JSONResponse(out or {"ok": status < 300}, status_code=status)


# ── THE ACCOUNT'S DOMAINS ────────────────────────────────────────────────────────────────────────
def _record_conflicts(records: list[dict]) -> list[dict]:
    """The conflicts a DNS panel must catch BEFORE a save, because the zone will not accept them.

    Written from the rules, not from a vendor's error message: a name may not hold a CNAME together
    with any other record (RFC 1034 §3.6.2 — the CNAME IS the name), a name may not hold two CNAMEs,
    MX and SRV need a priority, and a duplicate (name, type, value) is a mistake that looks like a
    feature. Every one of these is a *warning with the offending rows named*, never a blocked save
    the owner cannot explain.
    """
    by_name: dict[str, list[dict]] = {}
    for r in records or []:
        n = (r.get("name") or "").rstrip(".").lower() or "@"
        by_name.setdefault(n, []).append(r)
    out: list[dict] = []
    for n, rows in by_name.items():
        types = {(r.get("type") or "").upper() for r in rows}
        if "CNAME" in types and len(types) > 1:
            out.append({"code": "cname_exclusive", "severity": "error", "name": n,
                        "title": f"‏{n} מכיל CNAME יחד עם {', '.join(sorted(types - {'CNAME'}))}",
                        "why": "רשומת CNAME תופסת את השם כולו — אסור שתתקיים לצד רשומה אחרת באותו שם.",
                        "fix": "הסר את ה-CNAME, או העבר את שאר הרשומות לשם אחר."})
        if sum(1 for r in rows if (r.get("type") or "").upper() == "CNAME") > 1:
            out.append({"code": "duplicate_cname", "severity": "error", "name": n,
                        "title": f"‏{n} מכיל יותר מ-CNAME אחד",
                        "why": "לשם יכול להיות CNAME אחד בלבד.",
                        "fix": "השאר יעד אחד."})
        seen = {}
        for r in rows:
            k = ((r.get("type") or "").upper(), str(r.get("content") or "").strip().lower())
            if k[1] and k in seen:
                out.append({"code": "duplicate_record", "severity": "warn", "name": n,
                            "title": f"רשומה כפולה: {k[0]} {k[1]}",
                            "why": "אותה רשומה מופיעה פעמיים באותו שם.",
                            "fix": "מחק אחת מהן."})
            seen[k] = True
        for r in rows:
            if (r.get("type") or "").upper() in ("MX", "SRV") and not r.get("priority"):
                out.append({"code": "missing_priority", "severity": "warn", "name": n,
                            "title": f"לרשומת {(r.get('type') or '').upper()} ב-{n} אין עדיפות",
                            "why": "MX ו-SRV מחייבות עדיפות; בלעדיה חלק מהשרתים מתעלמים מהרשומה.",
                            "fix": "הוסף עדיפות (מספר קטן = עדיפות גבוהה)."})
    return out


def account_domains(aid: str, sync: bool = False) -> dict:
    """Every domain this account has, in ONE shape, whether it came from an HTTP API or from a panel
    read through the browser. `sync=1` mirrors them into the office's watch list."""
    inst, secret, err = accounts.resolve(aid)
    if err:
        return {"error": err, "domains": []}
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "")
    if provider == "portal":
        res = portal_mod.read_domains(PORTAL_PROVIDERS.get("portal", "internic"))
        if not res.get("ok"):
            return {"error": res.get("error") or res.get("reason") or "הקריאה מהפורטל נכשלה",
                    "state": res.get("state"), "authenticated": res.get("authenticated"),
                    "how": res.get("how"), "domains": []}
        rows, source = res["domains"], "browser"
    elif provider == "registry":
        rows = [{"name": d["name"], "expiry_iso": d.get("expiry_date"),
                 "days_left": d.get("days_left"), "nameservers": d.get("nameservers") or [],
                 "status": d.get("status")} for d in (_decorate(x) for x in registry.list_domains())]
        source = "registry"
    else:
        try:
            rows = adapter_for(provider, secret or {}).list_domains()
        except DomainError as e:
            return {"error": e.he_message, "detail": e.detail, "domains": []}
        source = "api"
        for r in rows:
            if r.get("expiry") and not r.get("expiry_iso"):
                r["expiry_iso"] = time.strftime("%Y-%m-%d", time.localtime(r["expiry"]))
                r["days_left"] = int((r["expiry"] - time.time()) / 86400)
    for r in rows:
        known = registry.get(r.get("name") or "") or {}
        r["watched"] = bool(known)
        days = r.get("days_left")
        if days is None:
            days = known.get("days_left")
        r["expiry_state"] = _expiry_state(days)
    if sync:
        added, updated = [], []
        for r in rows:
            name = _json(_norm_name, r.get("name") or "")
            if isinstance(name, JSONResponse):
                continue
            was = registry.get(name)
            registry.upsert(name, provider=provider, account=inst["id"], watched=True,
                            nameservers=r.get("nameservers") or [],
                            expiry=(whoisq.parse_date(r.get("expiry_iso"))
                                    if r.get("expiry_iso") else None),
                            status=r.get("status") or "מהספק")
            (updated if was else added).append(name)
        registry.event(None, "sync", f"סונכרנו {len(rows)} דומיינים מ-{provider}",
                       {"added": added, "account": inst["id"]})
        return {"account": inst["id"], "provider": provider, "source": source, "domains": rows,
                "count": len(rows), "synced": {"added": added, "updated": updated}}
    return {"account": inst["id"], "provider": provider, "source": source, "domains": rows,
            "count": len(rows)}


@app.get("/api/accounts/{aid}/domains")
def api_account_domains(aid: str, sync: int = 0, fresh: int = 0):
    """The account's domains, through the cache. `?fresh=1` forces the slow read; `?sync=1` mirrors
    them into the watch list (and always reads fresh, because mirroring stale data is pointless)."""
    if sync:
        res = account_domains(aid, sync=True)
        webengine.invalidate(f"domains:{aid}")
        return JSONResponse(res, status_code=200 if "error" not in res else 502)
    key = f"domains:{aid}"

    def loader():
        # A read that FAILED must not be cached as "this account has no domains": raising here makes
        # the engine keep the last successful list and mark it stale-with-error, which the screen
        # shows as an old answer plus the reason — instead of an empty account that looks real.
        res = account_domains(aid, sync=False)
        if res.get("error"):
            raise DomainError(res["error"], status=502, kind="source",
                              detail=res.get("how") or res.get("state"))
        return res

    out = webengine.get(key, loader, ttl=180,
                        force=bool(fresh), want="fresh" if fresh else "cache")
    value = out.get("value") or {"domains": [], "error": out.get("error")}
    if isinstance(value, dict):
        value = {**value, "_cache": {"age": out.get("age"), "stale": out.get("stale"),
                                     "refreshing": out.get("refreshing"),
                                     "error": out.get("error")}}
    return JSONResponse(value, status_code=200 if "error" not in (value or {}) else 502)


@app.get("/api/accounts/{aid}/domains/{domain}")
def api_account_domain(aid: str, domain: str, fresh: int = 0):
    """ONE domain — the settings payload, through the cache (the panel read is the slow part)."""
    key = f"domain:{aid}:{domain.lower()}"
    out = webengine.get(key, lambda: _domain_payload(aid, domain, key), ttl=180,
                        force=bool(fresh), want="fresh" if fresh else "cache")
    value = out.get("value")
    if not value:
        return _err(out.get("error") or "לא ניתן לקרוא את הדומיין", 502)
    return {**value, "_cache": {"age": out.get("age"), "stale": out.get("stale"),
                                "refreshing": out.get("refreshing"), "error": out.get("error")}}


def _domain_payload(aid: str, domain: str, cache_key: str = ""):
    inst, secret, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "")
    watched = registry.get(name) or {}
    judged_records: list[dict] = []                     # what the panel holds, for the conflict rules
    out = {"account": {"id": inst.get("id"), "label": inst.get("label"), "provider": provider,
                       "access": next((p.get("access") for p in accounts.PROVIDERS_CATALOG
                                       if p["id"] == provider), None)},
           "domain": name, "watched": bool(watched),
           "registry": {k: _decorate(dict(watched)).get(k) for k in
                        ("expiry", "expiry_date", "days_left", "expiry_state", "registrar",
                         "status", "nameservers", "last_whois", "last_error")},
           "provider_facts": None, "records": [], "records_source": None, "records_error": None,
           "records_read_only": False,
           "world_dns": dnsq.snapshot(name), "zone_holder": zone_analysis(name), "ops": [],
           "conflicts": [], "write": {}}
    # Whether writing is possible AT ALL is a fact about the source, not about the record the owner
    # happened to click — so it travels with the payload and the screen can state it before anything
    # is attempted. A refusal that only appears after a click is a refusal the owner reads as a bug.
    if provider == "portal":
        out["write"] = portal_mod.write_state(PORTAL_PROVIDERS.get("portal", "internic"))
    else:
        try:
            _adapter = adapter_for(provider, secret or {})
            ro = bool(getattr(_adapter, "read_only", False))
        except Exception:                                    # noqa: BLE001
            ro = True
        out["write"] = {"enabled": not ro, "state": "api" if not ro else "read_only",
                        "actions": {"create": not ro, "update": not ro, "delete": not ro},
                        "title": "" if not ro else "החשבון הזה לקריאה בלבד",
                        "why": "" if not ro else
                               "החיבור הזה קורא מהרישום הציבורי ואינו מחזיק באזור ה-DNS.",
                        "how": "" if not ro else
                               "חבר את מי שמחזיק בפועל באזור (למשל Plesk של הספק) כדי לכתוב מכאן.",
                        "portal_url": ""}
    if not watched:
        out["note"] = "הדומיין אינו במעקב — „סנכרן” מהחשבון יוסיף אותו."
    if provider == "portal":
        zone = portal_mod.read_zone(PORTAL_PROVIDERS["portal"], name)
        out["records"] = zone.get("records") if zone.get("ok") else []
        judged_records = out["records"]
        out["records_source"] = "portal(panel)" if zone.get("ok") else None
        out["records_error"] = None if zone.get("ok") else (zone.get("error") or "הקריאה נכשלה")
        out["zone_id"] = zone.get("zone_id")
        if not zone.get("ok") and not out["records"]:
            # A read that FAILED is not a zone with no records. The browser is shared and sometimes
            # busy (see the handoff note): caching "0 records" as the truth about somebody's zone is
            # the one wrong answer that looks completely normal on screen. So the last payload that
            # was read successfully is carried forward and clearly marked as not fresh.
            prev = (webengine.peek(cache_key) or {}).get("value") or {}
            if prev.get("records"):
                out["records"] = prev["records"]
                judged_records = out["records"]
                out["records_source"] = prev.get("records_source")
                out["zone_id"] = prev.get("zone_id")
                out["records_stale"] = True
    elif provider not in ("registry", ""):
        try:
            out["records"] = adapter_for(provider, secret or {}).list_records(name)
            judged_records = out["records"]
            out["records_source"] = provider
        except DomainError as e:
            out["records_error"] = e.he_message
    else:
        out["records"] = adapter_for("registry", {}).list_records(name)
        judged_records = out["records"]
        out["records_source"] = "dns-public"
        out["records_read_only"] = True
    for op in providers.DOMAIN_OPS:
        out["ops"].append({"id": op["id"], "label": op["label"], "kind": op["kind"],
                           "he": op.get("he", ""),
                           **providers.op_support(op["id"], provider, True)})
    # Conflicts are judged on the records we just read, so they are computed HERE and not in the
    # payload literal above (where the list does not exist yet — that was a 502 on every domain).
    out["conflicts"] = _record_conflicts(judged_records)
    return out


@app.post("/api/accounts/{aid}/domains/{domain}/records")
async def api_account_domain_records(aid: str, domain: str, request: Request):
    """create | update | delete ONE record, through whichever door this account has."""
    body = (await request.json()) if await request.body() else {}
    body = body or {}
    # The work below is BLOCKING (vault HTTP, a provider's API, and for a portal account a browser
    # page). Running it on the event loop would freeze the whole app — including /healthz and the
    # progress stream this very write reports on — so it is handed to the threadpool.
    return await run_in_threadpool(_records_endpoint, aid, domain, body)


def _records_endpoint(aid: str, domain: str, body: dict):
    inst, secret, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "")
    action = (body.get("action") or "create").lower()
    if action not in ("create", "update", "delete"):
        return _err("פעולה לא מוכרת (create|update|delete)")
    rec = {"id": body.get("id"), "type": (body.get("type") or "").upper() or None,
           "name": body.get("name"), "content": body.get("content"), "ttl": body.get("ttl"),
           "priority": body.get("priority"), "proxied": body.get("proxied")}
    if action in ("create", "update"):
        for field in ("type", "name", "content"):
            if not rec.get(field):
                return _err(f"חסר שדה: {field}")
    # The state BEFORE the write, so the change can be shown as a diff and UNDONE. A caller that
    # edits a row knows the old value (it just rendered it) and sends it as `before`; when it does
    # not, only a create is safely revertible — deleting and updating are not guessed.
    before = body.get("before") if isinstance(body.get("before"), dict) else None
    if provider == "portal" and not body.get("sync"):
        # A panel write is slow and interactive: run it as a JOB so the screen can show steps, and
        # return immediately. `sync: true` keeps the blocking behaviour for callers that want an
        # answer in one round trip (scripts, tests).
        job = webengine.submit(
            "portal_write", lambda progress, params: _portal_write_job(progress, name, action, rec,
                                                                       params),
            {"domain": name, "action": action, "record": rec},
            title=f"{action} רשומה ב-{name}",
            invalidates=[f"domain:{aid}:{name.lower()}", f"health:{name}"],
            client=body.get("client"))
        return JSONResponse({"ok": True, "job": job["id"], "queued": True, "deduped": job.get("deduped"),
                             "domain": name, "action": action}, status_code=202)
    if provider == "portal":
        # `sync: true` keeps the blocking behaviour for a caller that wants one round trip (a script
        # or a test) — but it must still go through the PANEL path. Falling through to the adapter
        # here is how a panel write used to be answered with "this provider does not support it".
        return _portal_write(name, action, rec, body)
    adapter = _json(adapter_for, provider, secret or {})
    if isinstance(adapter, JSONResponse):
        return adapter
    if getattr(adapter, "read_only", False):
        return _err("לחשבון הזה אין אפשרות כתיבה (רישום ציבורי בלבד). "
                    "חבר את מי שמחזיק בפועל באזור ה-DNS.", 409)
    fn = {"create": adapter.create_record, "update": adapter.update_record,
          "delete": adapter.delete_record}[action]
    try:
        res = fn(name, rec)
    except DomainError as e:
        return JSONResponse(e.body(), status_code=e.status)
    eid = registry.event(name, f"dns_{action}", f"{action} {rec.get('type')} {rec.get('name')}",
                         {"provider": provider, "before": before, "after": rec,
                          "result": res if isinstance(res, dict) else str(res),
                          "revertible": action == "create" or bool(before)})
    after_records = _read_records(provider, secret or {}, name)
    webengine.invalidate(f"health:{name}")
    return {"ok": True, "action": action, "provider": provider, "result": res, "event": eid,
            "records": after_records if not isinstance(after_records, JSONResponse) else []}


# ── the change log, and the undo that makes a delete survivable ──────────────────────────────────
@app.get("/api/accounts/{aid}/domains/{domain}/activity")
def api_domain_activity(aid: str, domain: str, limit: int = 40):
    """Every change the office made to this domain, newest first, with the exact before/after."""
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    rows = registry.events(name, limit=min(200, max(1, limit)))
    out = []
    for r in rows:
        try:
            meta = json.loads(r.get("meta") or "{}")
        except ValueError:
            meta = {}
        out.append({**r, "meta": meta,
                    "revertible": bool(meta.get("revertible")),
                    "reverted_by": meta.get("reverted_by")})
    return {"domain": name, "events": out, "count": len(out)}


@app.post("/api/accounts/{aid}/domains/{domain}/activity/{eid}/revert")
async def api_domain_activity_revert(aid: str, domain: str, eid: int, request: Request):
    """Undo ONE logged change — the real answer to "a delete has no undo".

    What it does, and only what it can prove: a `create` is undone by deleting exactly that record;
    a `delete`/`update` is undone by writing back the `before` the caller recorded at the time. The
    revert is itself an event, so the log reads as a history rather than as a set of current facts.
    """
    body = (await request.json()) if await request.body() else {}
    return await run_in_threadpool(_revert_endpoint, aid, domain, eid, body or {})


def _revert_endpoint(aid: str, domain: str, eid: int, body: dict):
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    ev = None
    for r in registry.events(name, limit=200):
        if int(r.get("id") or 0) == int(eid):
            ev = r
            break
    if not ev:
        return _err("לא נמצא שינוי כזה ביומן", 404)
    try:
        meta = json.loads(ev.get("meta") or "{}")
    except ValueError:
        meta = {}
    kind = ev.get("kind") or ""
    action = {"dns_create": "create", "dns_update": "update", "dns_delete": "delete"}.get(kind)
    if not action:
        return _err("אפשר לבטל רק שינוי ברשומות DNS", 409)
    after, before = meta.get("after") or {}, meta.get("before") or {}
    if action == "create":
        if not after:
            return _err("אין תיעוד של הרשומה שנוצרה — אי אפשר לבטל", 409)
        return _records_endpoint(aid, name, {"action": "delete", "type": after.get("type"),
                                            "name": after.get("name"), "content": after.get("content"),
                                            "id": after.get("id"), "ttl": after.get("ttl"),
                                            "revert_of": eid})
    if not before:
        return _err("לא נשמר המצב הקודם של הרשומה — אי אפשר לבטל את השינוי הזה", 409)
    payload = {"action": "create" if action == "delete" else "update",
               "type": before.get("type"), "name": before.get("name"),
               "content": before.get("content"), "ttl": before.get("ttl"),
               "priority": before.get("priority"), "id": before.get("id"),
               "revert_of": eid}
    res = _records_endpoint(aid, name, payload)
    if isinstance(res, dict) and res.get("ok"):
        registry.event(name, "revert", f"בוטל שינוי #{eid} ({kind})", {"reverted_by": eid})
    return res


def _portal_write_job(progress, name: str, action: str, rec: dict, params: dict) -> dict:
    """The worker half of a panel write. Reports each step, and finishes by READING THE ZONE BACK —
    the same rule as everywhere else: a write is proved by what the source says afterwards."""
    progress(5, "פותח את הפורטל בדפדפן של הלשכה")
    # WHICH operation writes a record is the SCRIPT's business, not a name this app guesses: this
    # panel has one zone form for create and update, and no delete at all. Asking the script keeps
    # the app free of provider detail and turns "not scripted" into a sentence that names the gap.
    res = portal_mod.run_write(PORTAL_PROVIDERS["portal"], action,
                               {"domain": name, "type": rec.get("type"), "name": rec.get("name"),
                                "value": rec.get("content"), "ttl": rec.get("ttl")},
                               None, bool(params.get("allow_draft_write")))
    progress(70, "קורא את האזור חזרה")
    if not res.get("ok"):
        raise DomainError(res.get("error") or "הפעולה בפורטל נכשלת",
                          status=409 if res.get("state") in ("needs_verification", "not_scripted")
                          else 502,
                          detail=res.get("why") or res.get("how"), kind="portal",
                          refusal={k: v for k, v in res.items()
                                   if k in ("title", "why", "how", "state", "portal_url", "missing")})
    records = _read_records("portal", {}, name)
    progress(100, f"בוצע · {len(records)} רשומות באזור")
    return {"domain": name, "action": action, "records": len(records), "portal": res}


def _op_job(progress, op_id: str, name: str, provider: str, secret: dict, params: dict) -> dict:
    progress(10, f"מריץ {op_id}")
    fn = {"renewDomain": "_op_renew", "registerDomain": "_op_register",
          "transferDomain": "_op_transfer", "setNameservers": "_op_nameservers",
          "setAutoRenew": "_op_autorenew", "setLock": "_op_lock",
          "getAuthCode": "_op_authcode"}.get(op_id)
    if fn is None:
        raise DomainError(f"הפעולה {op_id} אינה ממומשת עדיין", status=501)
    out = globals()[fn](name, provider, secret or {}, params)
    progress(100, "הושלם")
    return out


def _read_records(provider: str, secret: dict, name: str):
    if provider == "portal":
        res = portal_mod.read_zone(PORTAL_PROVIDERS["portal"], name)
        return res.get("records") if res.get("ok") else []
    return adapter_for(provider, secret).list_records(name)


def _portal_write(name: str, action: str, rec: dict, body: dict):
    """A write through the PANEL — and therefore through the human gate.

    The script that performs it is still a `draft` (the flow PAST the login was observed on
    2026-09-23; the write itself has not been watched end to end), and `portal.run` refuses a draft
    write on purpose: the office does not drive the owner's registrar with an unverified script.
    `allow_draft_write: true` is the owner watching it once.
    """
    res = _json(portal_mod.run_write, PORTAL_PROVIDERS["portal"], action,
                {"domain": name, "type": rec.get("type"), "name": rec.get("name"),
                 "value": rec.get("content"), "ttl": rec.get("ttl")},
                None, bool(body.get("allow_draft_write")))
    if isinstance(res, JSONResponse):
        return res
    if not res.get("ok"):
        return JSONResponse({"ok": False, "op": action, "provider": "portal", **res},
                            status_code=409)
    return {"ok": True, "action": action, "provider": "portal", "result": res,
            "records": _read_records("portal", {}, name)}


@app.post("/api/accounts/{aid}/domains/{domain}/op")
async def api_account_domain_op(aid: str, domain: str, request: Request):
    """The operations that are not records: nameservers, auto-renew, lock, renew, transfer, auth code."""
    return await run_in_threadpool(_domain_op, aid, domain, await _json_body(request))


def _domain_op(aid: str, domain: str, body: dict):
    body = body or {}
    inst, secret, err = accounts.resolve(aid)
    if err:
        return _err(err, 404)
    name = _json(_norm_name, domain)
    if isinstance(name, JSONResponse):
        return name
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "")
    op_id = (body.get("op") or "").strip()
    params = body.get("params") or {}
    confirm = body.get("confirm")
    support = providers.op_support(op_id, provider, True)
    browser_only = provider == "portal" and op_id in (
        "registerDomain", "renewDomain", "setNameservers", "setAutoRenew", "setLock", "getAuthCode")
    if not support.get("supported") and not browser_only:
        return JSONResponse({"ok": False, "op": op_id, "provider": provider, **support},
                            status_code=409)
    if op_id in MONEY_OPS and confirm != f"{name}:{op_id}":
        return JSONResponse({
            "ok": False, "op": op_id, "needs": "human_confirmation",
            "error": ("זו פעולה בתשלום. כדי לבצע אותה שלח confirm בדיוק "
                      + repr(f"{name}:{op_id}") + " — האישור הוא מחרוזת מדויקת ולא true, "
                      "כדי שקריאה במקרה לא תקנה דומיין.")}, status_code=409)
    registry.event(name, f"op_{op_id}", f"פעולה: {op_id}", {"params": params,
                                                            "provider": provider})
    if op_id not in ("setAutoRenew", "setLock") and not body.get("sync"):
        job = webengine.submit("domain_op", lambda progress, params_: _op_job(
            progress, op_id, name, provider, secret or {}, params_), params,
            title=f"{op_id} · {name}", invalidates=[f"domain:{aid}:{name.lower()}"])
        return JSONResponse({"ok": True, "job": job["id"], "queued": True, "op": op_id},
                            status_code=202)
    res = _json(_op_job, lambda pct, msg: None, op_id, name, provider, secret or {}, params)
    if isinstance(res, JSONResponse):
        return res
    return {"ok": True, "op": op_id, "provider": provider, "result": res}


# ── THE OFFICE'S OWN LIST (flat: what is watched, whatever account introduced it) ────────────────
@app.get("/api/domains")
def api_domains():
    rows = []
    for d in registry.list_domains():
        account = None
        if d.get("account"):
            inst, _s, _e = accounts.resolve(d["account"])
            account = {"id": inst.get("id"), "label": inst.get("label")}
        rows.append(_decorate({**d, "account": account,
                               "zone_holder": zone_analysis(d["name"])}))
    rows.sort(key=lambda d: (d.get("days_left") is None, d.get("days_left") or 0))
    return {"domains": rows, "thresholds": {"warn_days": EXPIRY_WARN_DAYS,
                                            "urgent_days": EXPIRY_URGENT_DAYS}}


@app.post("/api/domains/{name}/refresh")
def api_domain_refresh(name: str):
    n = _json(_norm_name, name)
    if isinstance(n, JSONResponse):
        return n
    if not registry.get(n):
        return _err("הדומיין אינו במעקב", 404)
    res = _json(_refresh_whois, n, False)
    return res if isinstance(res, JSONResponse) else {"ok": True, "domain": res}


@app.delete("/api/domains/{name}")
def api_domain_delete(name: str):
    n = _json(_norm_name, name)
    if isinstance(n, JSONResponse):
        return n
    if not registry.get(n):
        return _err("הדומיין אינו במעקב", 404)
    registry.delete(n)
    registry.event(None, "remove", f"הדומיין {n} הוסר מהמעקב")
    return {"ok": True, "removed": n, "note": "הדומיין עצמו לא נגע — רק המעקב הוסר."}


@app.post("/api/availability")
async def api_availability(request: Request):
    return await run_in_threadpool(_availability, await _json_body(request))


def _availability(body: dict):
    body = body or {}
    n = _json(_norm_name, body.get("name") or "")
    if isinstance(n, JSONResponse):
        return n
    inst, secret, err = accounts.resolve(body.get("account"))
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "registry") if not err \
        else "registry"
    return _json(adapter_for(provider, secret or {}).check_availability, n)


# ── internals: monitoring, zone analysis, provider operations ────────────────────────────────
# ---- recon/ops impl ----
# ── the domain API: one surface for everything a domain needs ────────────────────────────────────
# "Manage a domain" is not one thing: it is availability, registration, renewal, transfer, locks,
# nameservers, DNSSEC and the zone — and WHICH of those the office can do depends on who holds the
# registration and who holds the zone. So the app publishes a MATRIX (`GET /api/domain-ops`) and a
# single dispatcher (`POST /api/domains/{name}/op`) that either performs the operation or refuses it
# by naming the missing piece. Two rules are enforced here rather than in the UI:
#
#   * **money and irreversibility need a human.** `registerDomain`, `renewDomain` and
#     `transferDomain` are refused unless the caller passes an explicit confirmation, and every one
#     of them is written to the event log with its parameters. An agent must not be able to buy a
#     domain by calling an endpoint that looked like the others.
#   * **no silent provider substitution.** If the connected provider cannot do the op, the answer
#     names the capability and the provider — it never quietly tries a different one.

MONEY_OPS = ("registerDomain", "renewDomain", "transferDomain")
IRREVERSIBLE_OPS = ("deleteRecord", "setNameservers", "setLock", "transferDomain")



# ---- providers helpers ----
def _effective_provider(d: dict) -> str:
    """Which provider can ACT on this domain — not which one is written on its row.

    A domain's registrar and the host of its ZONE are routinely two companies (this office: InterSpace
    registers, InterVision/Plesk hosts), and every operation that matters — every DNS write — belongs
    to whoever holds the zone. Reading the row alone told the owner "no provider can do this" about
    domains whose zone is perfectly reachable; the zone analysis says who really holds it.
    """
    stored = (d.get("provider") or "registry").strip()
    if stored and stored != "registry":
        return stored
    try:
        return zone_analysis(d["name"]).get("provider") or stored or "registry"
    except Exception:                                        # noqa: BLE001
        return stored or "registry"


def _spec_ops(provider: str, secret: dict) -> dict:
    spec = providers.SPECS.get(provider) or {}
    return spec.get("ops") or {}


def _api_call(provider: str, secret: dict, op: str, **kwargs):
    """Call an optional provider operation through the spec adapter, or refuse it clearly."""
    if provider not in providers.SPECS or op not in _spec_ops(provider, secret):
        raise providers.DomainError(
            f"ל-{provider} אין את הפעולה {op} דרך ה-API", status=409, kind="unsupported")
    return providers.adapter_for(provider, secret)._call(op, params=kwargs)  # noqa: SLF001


def _op_renew(name: str, provider: str, secret: dict, params: dict) -> dict:
    if provider == "godaddy":
        return providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "POST", f"/v1/domains/{name}/renew", json={"period": int(params.get("years") or 1)})
    if provider == "portal":
        return portal_mod.run("internic", "renew", {"domain": name})
    res = _api_call(provider, secret, "renew", domain=name,
                    years=int(params.get("years") or 1))
    _refresh_whois(name, notify=False)
    return {"renewed": True, "provider": provider, "raw": res}


def _op_register(name: str, provider: str, secret: dict, params: dict) -> dict:
    if provider == "godaddy":
        body = {"domain": name, "consent": {"agreementKeys": params.get("agreements") or [],
                                            "agreedBy": params.get("agreed_by") or "owner",
                                            "agreedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
                "period": int(params.get("years") or 1),
                "nameServers": params.get("nameservers") or []}
        res = providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "POST", "/v1/domains/purchase", json=body)
    elif provider == "portal":
        res = portal_mod.run("internic", "register", {"domain": name,
                                                      "years": params.get("years") or 1})
    else:
        res = _api_call(provider, secret, "register", domain=name,
                        years=int(params.get("years") or 1))
    registry.upsert(name, provider=provider, account=None, watched=True)
    _refresh_whois(name, notify=False)
    return {"registered": True, "provider": provider, "raw": res}


def _op_transfer(name: str, provider: str, secret: dict, params: dict) -> dict:
    code = (params.get("auth_code") or "").strip()
    if not code:
        return _err("העברה דורשת קוד העברה (auth_code) מהרשם הנוכחי")
    if provider == "godaddy":
        return providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "POST", f"/v1/domains/{name}/transfer", json={"authCode": code,
                                                          "period": int(params.get("years") or 1)})
    return _api_call(provider, secret, "transfer", domain=name, auth_code=code)


def _op_nameservers(name: str, provider: str, secret: dict, params: dict) -> dict:
    ns = [s.strip() for s in (params.get("nameservers") or []) if s.strip()]
    if not ns:
        return _err("חסרה רשימת nameservers")
    if provider == "godaddy":
        providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "PATCH", f"/v1/domains/{name}", json={"nameServers": ns})
    elif provider == "portal":
        return portal_mod.run("internic", "set_nameservers", {"domain": name, "nameservers": ns})
    else:
        _api_call(provider, secret, "set_nameservers", domain=name, nameservers=ns)
    registry.event(name, "nameservers", "שינוי שרתי שמות", {"to": ns})
    _refresh_whois(name, notify=False)
    return {"ok": True, "nameservers": ns, "note": "ההעברה עשויה להתפשט בדקות עד שעות."}


def _op_autorenew(name: str, provider: str, secret: dict, params: dict) -> dict:
    on = bool(params.get("enabled", True))
    if provider == "godaddy":
        providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "PATCH", f"/v1/domains/{name}", json={"renewAuto": on})
    elif provider == "portal":
        return portal_mod.run("internic", "set_autorenew", {"domain": name, "enabled": on})
    else:
        _api_call(provider, secret, "set_auto_renew", domain=name, enabled=on)
    registry.upsert(name, auto_renew=on)
    return {"ok": True, "auto_renew": on}


def _op_lock(name: str, provider: str, secret: dict, params: dict) -> dict:
    on = bool(params.get("locked", True))
    if provider == "godaddy":
        providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "PATCH", f"/v1/domains/{name}", json={"locked": on})
    elif provider == "portal":
        return portal_mod.run("internic", "set_lock", {"domain": name, "locked": on})
    else:
        _api_call(provider, secret, "set_lock", domain=name, locked=on)
    return {"ok": True, "locked": on}


def _op_authcode(name: str, provider: str, secret: dict, params: dict) -> dict:
    if provider == "portal":
        return portal_mod.run("internic", "get_auth_code", {"domain": name})
    if provider == "godaddy":
        return providers.adapter_for(provider, secret)._call(  # noqa: SLF001
            "GET", f"/v1/domains/{name}/transfer")
    return _api_call(provider, secret, "auth_code", domain=name)


# ── THE provider flow: one door, three answers ───────────────────────────────────────────────────
# The owner's flow, exactly: pick a provider → the office CHECKS the connection → if a human login is
# needed it says so and hands over ONE link → once they are in, the office VERIFIES it has control by
# reading the account's own domain list → and only then is the connection created.
#
# Deliberately one endpoint and one status endpoint. Every extra option here is a way for the flow to
# end somewhere other than "connected" or "here is what to do next".
PORTAL_PROVIDERS = {"portal": "internic"}





# ---- helpers ----
def _norm_name(raw: str) -> str:
    name = (raw or "").strip().lower().rstrip(".")
    name = re.sub(r"^https?://", "", name).split("/")[0]
    if name.startswith("www."):
        name = name[4:]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,250}\.[a-z]{2,20}", name):
        raise DomainError("שם דומיין לא תקין", status=400, kind="input")
    return name


def _expiry_state(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days < 0:
        return "expired"
    if days <= EXPIRY_URGENT_DAYS:
        return "urgent"
    if days <= EXPIRY_WARN_DAYS:
        return "warn"
    return "ok"





def _refresh_whois(name: str, notify: bool = True) -> dict:
    """Ask the REGISTRY (never the provider) and store what it says. Expiry is the whole point."""
    info = whoisq.lookup(name)
    previous = registry.get(name) or {}
    if not info.get("found"):
        registry.upsert(name, last_whois=registry.now(), last_error="הדומיין אינו רשום")
        return {"domain": name, "found": False}
    saved = registry.upsert(
        name, expiry=info.get("expiry"), registered=info.get("registered"),
        status=info.get("status"), registrar=info.get("registrar"),
        nameservers=info.get("nameservers") or [], last_whois=registry.now(), last_error=None)
    days = saved.get("days_left")
    if notify and previous.get("expiry") != saved.get("expiry"):
        registry.event(name, "whois", f"תוקף הדומיין עודכן",
                       {"to": saved.get("expiry"), "from": previous.get("expiry")})
        _notify_expiry(saved)
    elif notify:
        _notify_expiry(saved)
    return {"domain": name, **{k: saved.get(k) for k in
                               ("expiry", "expiry_date", "days_left", "status", "registrar",
                                "nameservers", "expiry_state")}}


def _notify_expiry(d: dict) -> None:
    """One notification per state change, not per check: a domain 30 days out must not produce a
    notification every twelve hours, because that is how the one that matters gets ignored."""
    days = d.get("days_left")
    state = _expiry_state(days)
    if state in ("ok", "unknown"):
        return
    key = f"expiry_notified:{d['name']}"
    last = registry.conn().execute(
        "SELECT value FROM events WHERE domain=? AND kind='expiry_notice' ORDER BY ts DESC LIMIT 1",
        (d["name"],)).fetchone()
    if last and (registry.now() - last["ts"]) < 86400:
        return
    level = "error" if state in ("urgent", "expired") else "warn"
    title = (f"הדומיין {d['name']} פג בעוד {days} ימים" if state == "urgent"
             else f"הדומיין {d['name']} עומד לפוג ({days} ימים)")
    registry.event(d["name"], "expiry_notice", title, {"days": days})
    _notify(title, f"רשם: {d.get('registrar') or '—'} · חידוש אצל הרשם (Internic: בפורטל שלהם).",
            level, d["name"])


def _notify(title: str, body: str, level: str = "info", domain: str | None = None) -> None:
    try:
        import requests
        requests.post(f"{NOTIFICATIONS_URL}/api/notifications",
                      json={"source": "domains", "title": title, "body": body, "level": level,
                            "source_id": domain or "", "meta": {"app": "domains"}}, timeout=10)
    except Exception as e:                                   # noqa: BLE001
        log.warning("notification not delivered: %s", type(e).__name__)





# ---- zone analysis ----
NS_HINTS = (
    ("cloudflare.com", "cloudflare", "Cloudflare"),
    ("ns.cloudflare.com", "cloudflare", "Cloudflare"),
    ("domaincontrol.com", "godaddy", "GoDaddy"),
    ("godaddy.com", "godaddy", "GoDaddy"),
    ("porkbun.com", "porkbun", "Porkbun"),
    ("digitalocean.com", "digitalocean", "DigitalOcean"),
    ("gandi.net", "gandi", "Gandi"),
    ("vercel-dns.com", "vercel", "Vercel"),
    ("hetzner.com", "hetzner", "Hetzner"),
    ("hetzner-online.de", "hetzner", "Hetzner"),
    ("namecheaphosting.com", "namecheap", "Namecheap"),
    ("registrar-servers.com", "namecheap", "Namecheap"),
    ("awsdns", "route53", "Amazon Route 53"),
    # The zone of this office's domains is a Plesk server run by InterVision (the InterSpace group);
    # its REST API is LIVE and refuses callers by IP — so the actionable next step is a support
    # request, not a migration. Evidence and the full chain: apps/domains/AGENT.md.
    ("sitesdepot.com", "plesk", "SitesDepot — Plesk של InterVision"),
    ("internic.co.il", None, "Internic"),
    ("impervasecuredns.net", None, "InterVision (DNS מנוהל)"),
    ("isoc.org.il", None, "ISOC-IL"),
)


def zone_analysis(name: str) -> dict:
    """Where the zone lives, whether we can write to it, and what to do if we cannot."""
    d = registry.get(name) or {}
    ns = d.get("nameservers") or []
    match, label = None, None
    for suffix, provider, human in NS_HINTS:
        if any(ns_name.endswith(suffix) for ns_name in ns):
            match, label = provider, human
            break
    out = {"domain": name, "nameservers": ns, "zone_holder": label or (ns[0] if ns else None),
           "provider": match, "can_write": False, "how": "", "action": ""}
    connected = [r for r in _accounts_payload(probe=False).get("connections") or []
                 if r.get("provider")]
    connected_ids = {r.get("provider") for r in connected}
    if match and match in connected_ids:
        out.update({"can_write": True, "how": f"רשומות נכתבות דרך {label} (חשבון מחובר)",
                    "action": ""})
    elif match:
        hint = {
            "plesk": ("ה-API של השרת פעיל אבל חסום לפי כתובת IP. בקש מהספק (InterVision / "
                      "sitesdepot) מפתח API והוספה של כתובת הלשכה לרשימת ההרשאות — ואז כל "
                      "הרשומות נקראות ונכתבות מכאן."),
            "cloudflare": "חבר טוקן API של Cloudflare (Zone:Read + DNS:Edit).",
            "godaddy": "חבר מפתח API של GoDaddy (domains.domain:read + dns:update).",
        }.get(match, f"חבר חשבון {label} כדי שנוכל לקרוא ולעדכן רשומות.")
        out.update({"how": f"ה-zone מתארח אצל {label}, שאינו מחובר ללשכה", "action": hint})
    else:
        out.update({
            "how": (f"ה-zone מתארח אצל {label or ns[0] if ns else 'לא ידוע'} — לפי שרתי השמות "
                    f"שהרישום מפרסם, ולא בהכרח אצל הרשם."),
            "action": ("אם אין לספק הזה API, אפשר (א) לחבר אותו ידנית, או (ב) להעביר את ניהול "
                       "ה-DNS ל-Cloudflare ולהשאיר את הרישום אצל הרשם — אז כל הפעולות כאן "
                       "הופכות לאוטומטיות."),
        })
    return out





# ---- watch ----
_state: dict = {"started": False, "last_run": None, "checked": 0, "errors": []}


def watch_pass() -> dict:
    due = registry.due_for_whois(WHOIS_HOURS)
    checked, errors = 0, []
    for d in due:
        try:
            _refresh_whois(d["name"], notify=True)
            checked += 1
        except Exception as e:                               # noqa: BLE001
            log.warning("whois failed for %s: %s", d["name"], type(e).__name__)
            registry.upsert(d["name"], last_error="בדיקת הרישום נכשלה")
            errors.append(d["name"])
        time.sleep(1.5)          # WHOIS is a shared public service; a polite pace is not optional
    _state.update({"last_run": registry.now(), "checked": checked,
                   "errors": (_state["errors"] + errors)[-10:]})
    return {"due": len(due), "checked": checked, "errors": errors}


def start_watch() -> None:
    if _state["started"]:
        return
    _state["started"] = True

    def loop():
        while True:
            try:
                res = watch_pass()
                if res.get("due"):
                    log.info("whois watch: %s", res)
            except Exception as e:                           # noqa: BLE001
                log.exception("watch pass failed: %s", e)
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="domains-watch").start()
    log.info("whois watch started (every hour, each domain at most every %sh)", WHOIS_HOURS)


@app.get("/api/watch")
def api_watch():
    return {**_state, "whois_hours": WHOIS_HOURS,
            "due": len(registry.due_for_whois(WHOIS_HOURS))}


# ── the domain API: one surface for everything a domain needs ────────────────────────────────────
# "Manage a domain" is not one thing: it is availability, registration, renewal, transfer, locks,
# nameservers, DNSSEC and the zone — and WHICH of those the office can do depends on who holds the
# registration and who holds the zone. So the app publishes a MATRIX (`GET /api/domain-ops`) and a
# single dispatcher (`POST /api/domains/{name}/op`) that either performs the operation or refuses it
# by naming the missing piece. Two rules are enforced here rather than in the UI:
#
#   * **money and irreversibility need a human.** `registerDomain`, `renewDomain` and
#     `transferDomain` are refused unless the caller passes an explicit confirmation, and every one
#     of them is written to the event log with its parameters. An agent must not be able to buy a
#     domain by calling an endpoint that looked like the others.
#   * **no silent provider substitution.** If the connected provider cannot do the op, the answer
#     names the capability and the provider — it never quietly tries a different one.
MONEY_OPS = ("registerDomain", "renewDomain", "transferDomain")
IRREVERSIBLE_OPS = ("deleteRecord", "setNameservers", "setLock", "transferDomain")





# ── the canonical op surface (platform-service.v1 — what other apps call) ────────────────────────
def _op_domain(body: dict):
    raw = body.get("domain") or body.get("name")
    if not raw:
        return "", _err("חסר שדה: domain")
    n = _json(_norm_name, raw)
    return ("", n) if isinstance(n, JSONResponse) else (n, None)


def _op_account(body: dict):
    aid = body.get("account")
    if aid:
        inst, _s, err = accounts.resolve(aid)
        if err:
            return "", _err(err, 404)
        return inst["id"], None
    inst, _s, err = accounts.resolve(None)
    if err:
        return "", _err(err, 502)
    return inst.get("id") or "", None


def _op_sync(fn):
    """Register a body-taking SYNC implementation as an HTTP endpoint.

    FastAPI runs a sync endpoint in its threadpool, which is exactly what these need: every one of
    them resolves an account (vault HTTP) and most of them then talk to a provider or drive the
    office browser. Written as `async def` they would each block the event loop for the whole call.
    """
    @functools.wraps(fn)
    async def endpoint(request: Request):
        return await run_in_threadpool(fn, await _json_body(request))
    return endpoint


@app.post("/listAccounts")
def _op_list_accounts(body: dict):
    return {"ok": True, "data": api_accounts(probe=bool((body or {}).get("probe", 1)))}


@app.post("/listDomains")
def _op_list_domains(body: dict):
    body = body or {}
    if body.get("account"):
        inst, _s, err = accounts.resolve(body["account"])
        if err:
            return _err(err, 404)
        return {"ok": True, "data": account_domains(inst["id"], sync=bool(body.get("sync")))}
    return {"ok": True, "data": {"domains": api_domains()["domains"]}}


@app.post("/getDomain")
def _op_get_domain(body: dict):
    body = body or {}
    name, bad = _op_domain(body)
    if bad:
        return bad
    aid, bad2 = _op_account(body)
    if bad2:
        return bad2
    return {"ok": True, "data": api_account_domain(aid, name)}


@app.post("/whois")
def _op_whois(body: dict):
    name, bad = _op_domain(body or {})
    if bad:
        return bad
    return {"ok": True, "data": _json(whoisq.lookup, name)}


@app.post("/listRecords")
def _op_list_records(body: dict):
    body = body or {}
    name, bad = _op_domain(body)
    if bad:
        return bad
    aid, bad2 = _op_account(body)
    if bad2:
        return bad2
    inst, secret, _e = accounts.resolve(aid)
    provider = providers.PROVIDER_OF.get(inst.get("protocol") or "", "registry")
    return {"ok": True, "data": {"domain": name, "provider": provider,
                                 "records": _read_records(provider, secret or {}, name)}}


@app.post("/writeRecord")
def _op_write_record(body: dict):
    body = body or {}
    name, bad = _op_domain(body)
    if bad:
        return bad
    aid, bad2 = _op_account(body)
    if bad2:
        return bad2
    return _records_endpoint(aid, name, body)


@app.post("/checkAvailability")
def _op_check_availability(body: dict):
    return _availability(body or {})


#: the canonical op surface, registered as endpoints with the threadpool wrapper on purpose: these
#: are the calls OTHER apps and agents make, and they are the ones that must never stall the process.
for _path, _fn in (("/listAccounts", _op_list_accounts), ("/listDomains", _op_list_domains),
                   ("/getDomain", _op_get_domain), ("/whois", _op_whois),
                   ("/listRecords", _op_list_records), ("/writeRecord", _op_write_record),
                   ("/checkAvailability", _op_check_availability)):
    app.post(_path)(_op_sync(_fn))

OPS = {"listAccounts": _op_list_accounts, "listDomains": _op_list_domains,
       "getDomain": _op_get_domain, "whois": _op_whois, "listRecords": _op_list_records,
       "writeRecord": _op_write_record, "checkAvailability": _op_check_availability}
# ---- internal fixture ----
#: the internal test bench's in-memory zone (never a real domain)
_FIXTURE: dict = {"records": [{"type": "A", "name": "@", "content": "203.0.113.10",
                              "ttl": 3600}]}
_FIXTURE_DIR = Path(__file__).parent / "static" / "fixture"


@app.post("/internal/jobs/ping")
def internal_job_ping(steps: int = 4):
    """A trivial job, for verifying the job machinery and the progress stream end to end.

    Internal on purpose: it exercises the engine (queue → worker → progress → events → result) with
    something that cannot touch anything, which is exactly what a self-check should do.
    """
    def run(progress, params):
        n = max(1, min(20, int(params.get("steps") or 4)))
        for i in range(n):
            time.sleep(0.4)
            progress(int((i + 1) * 100 / n), f"צעד {i + 1} מתוך {n}")
        return {"steps": n}
    job = webengine.submit("ping", run, {"steps": steps}, title="בדיקת מנוע העבודות")
    return {"ok": True, "job": job["id"]}


@app.get("/internal/fixture/panel")
def fixture_panel(section: str = "dns"):
    return FileResponse(_FIXTURE_DIR / "panel.html")


@app.get("/internal/fixture/records")
def fixture_records(domain: str = "example.co.il"):
    return {"domain": domain, "records": _FIXTURE["records"]}


@app.post("/internal/fixture/records")
async def fixture_add(request: Request):
    body = await _json_body(request)
    rec = {"type": (body.get("type") or "A").upper(), "name": body.get("name") or "@",
           "content": (body.get("content") or "").strip(), "ttl": int(body.get("ttl") or 3600)}
    _FIXTURE["records"] = [r for r in _FIXTURE["records"] if not (
        r["type"] == rec["type"] and r["name"] == rec["name"])] + [rec]
    return {"ok": True, "records": _FIXTURE["records"]}


@app.delete("/internal/fixture/records")
def fixture_delete(domain: str = "example.co.il", content: str = ""):
    _FIXTURE["records"] = [r for r in _FIXTURE["records"] if r["content"] != content]
    return {"ok": True, "records": _FIXTURE["records"]}



@app.post("/internal/browser/selftest")
def api_browser_selftest():
    """Run the whole translation layer against the fixture panel, through the REAL browser.

    Steps: open the panel → read the table → add a record → verify it is in the table → delete it →
    verify it is gone. Returns the intent trace and the locators the run LEARNED, which is exactly
    what a real panel run produces.
    """
    import browser_ops
    if not browser_session.available().get("available"):
        return _err("הדפדפן של הלשכה אינו זמין", 503)
    if not browser_session.available().get("available"):
        return _err("הדפדפן של הלשכה אינו זמין כרגע", 503)
    s = browser_session.shared()
    origin = os.environ.get("DOMAINS_FIXTURE_URL", "http://domains:8980/internal/fixture/panel")
    editor = browser_ops.ZoneEditor(s, origin, learned={})
    stamp = str(int(time.time()))
    out: dict = {"origin": origin, "steps": {}, "learned": {}, "plan": {}}
    try:
        out["plan"] = {op: browser_ops.ops_for(op, {"name": "www", "type": "TXT",
                                                    "content": "x", "ttl": 300})
                       for op in ("list_records", "write_record", "delete_record")}
        s.open(origin)
        before = editor.records("example.co.il")
        out["steps"]["read"] = {"ok": True, "records": [r.get("content") for r in before]}
        created = editor.add_record("example.co.il",
                                    {"type": "TXT", "name": "bina-selftest", "content": f"ok-{stamp}",
                                     "ttl": 300})
        out["steps"]["write"] = {"ok": True, **{k: created.get(k) for k in ("rows", "added_rows")},
                                 "record": created.get("record")}
        deleted = editor.delete_record("example.co.il", {"type": "TXT", "content": f"ok-{stamp}"})
        out["steps"]["delete"] = deleted
        after = editor.records("example.co.il")
        out["steps"]["verify_gone"] = {"ok": not any(r.get("content") == f"ok-{stamp}"
                                                     for r in after)}
        out["learned"] = editor.learned
        out["ok"] = all(step.get("ok") for step in out["steps"].values())
        out["trace"] = editor.trace
        registry.event(None, "browser_selftest",
                       "בדיקת שכבת ההמרה לדפדפן עברה" if out["ok"] else "בדיקת שכבת ההמרה נכשלה",
                       {"ok": out["ok"]})
    except browser_session.SessionError as e:
        out.update({"ok": False, "state": e.state, "error": e.message, "detail": e.detail,
                    "trace": editor.trace, "learned": editor.learned})
    except Exception as e:                                   # noqa: BLE001
        out.update({"ok": False, "state": "unknown_error", "error": f"{type(e).__name__}: {e}",
                    "trace": editor.trace})
    return out


# ── the panel as a SOURCE: domains and zones, read through the browser ───────────────────────────
@app.post("/api/portals/{portal}/domains")
def api_portal_domains(portal: str, sync: int = 0):
    """Read the account's domains from the PANEL. `?sync=1` also mirrors them into the watch list."""
    res = _json(portal_mod.read_domains, portal)
    if isinstance(res, JSONResponse):
        return res
    if not res.get("ok"):
        return res
    for d in res["domains"]:
        d["known"] = bool(registry.get(d["name"]))
    if sync:
        added, updated = [], []
        for d in res["domains"]:
            existing = registry.get(d["name"])
            registry.upsert(d["name"], provider="portal", account=None, watched=True,
                            expiry=(whoisq.parse_date(d.get("expiry_iso")) or None),
                            nameservers=d.get("nameservers") or [], status="מהפורטל")
            (updated if existing else added).append(d["name"])
            d["known"] = True
        res.update({"synced": {"added": added, "updated": updated}})
        registry.event(None, "portal_sync", "רשימת הדומיינים סונכרנה מהפורטל",
                       {"added": added, "count": len(res["domains"])})
    return res


@app.post("/api/portals/{portal}/zone")
async def api_portal_zone(portal: str, request: Request):
    """Read ONE domain's zone from the panel's own editor."""
    body = await _json_body(request)
    domain = (body or {}).get("domain")
    if not domain:
        return _err("חסר domain")
    return await run_in_threadpool(_json, portal_mod.read_zone, portal, _norm_name(domain))




# ── the UI ───────────────────────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    """Relative URLs only: the console embeds this at /a/domains/ and injects `<base href>`."""
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
def _startup() -> None:
    registry.init()
    webengine.init()
    webengine.start_workers(2)
    log.info("domains up — %s watched, %s accounts", len(registry.list_domains()),
             len(accounts.vault_list()[0] or []))
    start_watch()
