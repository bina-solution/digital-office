"""domains.providers — one canonical op set over registrars and DNS hosts that agree on nothing.

The office's rule for every provider app (drive, mail, git, and now domains) is that the CALLER never
learns which provider is behind an account. That is harder here than anywhere else, because the
providers genuinely differ in kind, not just in spelling:

  * **Cloudflare** — one scoped API token; every zone operation goes through a zone id you must
    resolve first; the registrar side is account-scoped and its `/registrar/domains` list is
    deprecated with an end-of-life date, so expiry is taken from the registry (WHOIS), which is both
    authoritative and provider-independent.
  * **GoDaddy** — a key:secret pair or a PAT, a hard 60 requests/minute per credential, and a
    `PUT /v1/domains/{d}/records` that REPLACES THE WHOLE ZONE. That last one is not a footnote: this
    adapter never issues it. Creates go through the append (`PATCH`), updates and deletes through the
    per-name/per-type routes.
  * **Internic** — the registrar this office actually uses, and it publishes **no API at all**
    (checked 2026-09-23: no docs, no OpenAPI, a Laravel portal behind a WAF). Pretending otherwise
    would mean shipping a scraper against the owner's own password. So it is a provider whose
    capabilities are HONEST: it can be watched (registry WHOIS on port 43, no credentials) and it
    cannot be written to, and the UI says exactly that instead of offering a button that fails.

Capability differences are declared per provider (`can.write_dns`, `can.list_zones`, `can.renew`) and
the API refuses an op the connected provider cannot do, with a sentence naming what to do instead —
never a 500 from an endpoint that was never going to exist.
"""
from __future__ import annotations

import json
import logging
import re

import requests

import dnsq
import whois as whoisq

log = logging.getLogger("domains.providers")
TIMEOUT = 25


class DomainError(Exception):
    """One failure in the two languages a caller needs: what to do, and what the provider said."""

    def __init__(self, he_message: str, status: int = 502, *, detail: str | None = None,
                 provider_error=None, kind: str = "provider", refusal: dict | None = None):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status
        self.detail = detail
        self.provider_error = provider_error
        self.kind = kind
        #: When the failure is a REFUSAL that already knows its own title/why/how (a capability the
        #: source cannot do), the whole thing travels with the exception — so a refusal raised inside
        #: a background job reaches the screen with the same words as one raised on the spot.
        self.refusal = refusal or None

    def body(self) -> dict:
        out = {"error": self.he_message, "kind": self.kind, "status": self.status}
        if self.refusal:
            out = {**self.refusal, **out}
        if self.detail:
            out["detail"] = self.detail
        if self.provider_error is not None:
            out["provider_error"] = self.provider_error
        return out


def _http_error(status: int, payload, provider: str) -> DomainError:
    """One renderer for every provider's error shape — Cloudflare wraps everything in
    `{success:false, errors:[{code,message}]}`, GoDaddy returns a bare `{code,message}` and a 422 with
    a field map, and a 403 from either is a scope problem whose fix differs per provider."""
    msg = ""
    if isinstance(payload, dict):
        if isinstance(payload.get("errors"), list):
            parts = []
            for e in payload["errors"]:
                if isinstance(e, dict):
                    parts.append(str(e.get("message") or e.get("code") or ""))
                else:
                    parts.append(str(e))
            msg = " · ".join(p for p in parts if p)
        msg = msg or str(payload.get("message") or payload.get("error") or "")
    elif isinstance(payload, str):
        msg = payload.strip()[:300]
    if status == 401:
        he = f"{provider}: האימות נכשל — הטוקן/המפתח שגוי או שפג תוקפו."
    elif status == 403:
        he = (f"{provider}: אין הרשאה לפעולה הזו. בדוק את היקף הטוקן "
              f"(Cloudflare: Zone:DNS:Edit + Zone:Read; GoDaddy: domains.domain:read / dns:update).")
    elif status == 404:
        he = f"{provider}: לא נמצא — האזור או הרשומה אינם קיימים, או שאין לחשבון גישה אליהם."
    elif status == 422:
        he = f"{provider}: הנתונים לא עברו ולידציה."
    elif status == 429:
        he = f"{provider}: חריגה ממכסת הקריאות (GoDaddy: 60 בדקות) — נסה שוב בעוד דקה."
    else:
        he = f"{provider}: שגיאה מהספק (HTTP {status})"
    if msg:
        he = f"{he} ({msg[:200]})"
    return DomainError(he, status=status if status < 500 else 502, detail=msg or None,
                       provider_error=payload)


def norm_record(raw: dict, provider: str) -> dict:
    """Provider record → the office's one record shape {id, type, name, content, ttl, proxied, prio}."""
    if provider == "cloudflare":
        return {"id": raw.get("id"), "type": raw.get("type"), "name": raw.get("name"),
                "content": raw.get("content"), "ttl": raw.get("ttl"),
                "proxied": bool(raw.get("proxied")), "priority": raw.get("priority"),
                "provider": provider}
    # GoDaddy has no record ids and splits priority out of the content
    return {"id": f"{raw.get('type')}/{raw.get('name')}", "type": raw.get("type"),
            "name": raw.get("name"), "content": raw.get("data"), "ttl": raw.get("ttl"),
            "priority": raw.get("priority"), "proxied": None, "provider": provider}


def norm_domain(raw: dict, provider: str) -> dict:
    if provider == "cloudflare":
        return {"name": raw.get("name"), "status": raw.get("status"),
                "nameservers": raw.get("name_servers") or [], "registrar": None,
                "expiry": None, "auto_renew": None, "provider": provider}
    return {"name": raw.get("domain"), "status": raw.get("status"),
            "nameservers": ((raw.get("nameServers") or [None])[0:2] if raw.get("nameServers")
                            else []),
            "registrar": "GoDaddy",
            "expiry": whoisq.parse_date(raw.get("expires")), "auto_renew": raw.get("renewAuto"),
            "provider": provider}


# ── the adapters ─────────────────────────────────────────────────────────────────────────────────
class BaseAdapter:
    provider = "base"
    read_only = False

    def __init__(self, secret: dict):
        self.secret = secret or {}
        self.s = requests.Session()
        self.s.headers.update({"accept": "application/json",
                               "user-agent": "BinaOfficeDomains/1.0"})

    # every adapter implements what it can; the ones it cannot raise a NAMED refusal
    def whoami(self) -> dict:
        raise self._unsupported("whoami")

    def list_domains(self, limit: int = 100) -> list[dict]:
        raise self._unsupported("listDomains")

    def get_domain(self, domain: str) -> dict:
        raise self._unsupported("getDomain")

    def list_records(self, domain: str) -> list[dict]:
        raise self._unsupported("listRecords")

    def create_record(self, domain: str, rec: dict) -> dict:
        raise self._unsupported("createRecord")

    def update_record(self, domain: str, rec: dict) -> dict:
        raise self._unsupported("updateRecord")

    def delete_record(self, domain: str, rec: dict) -> dict:
        raise self._unsupported("deleteRecord")

    def check_availability(self, domain: str) -> dict:
        raise self._unsupported("checkAvailability")

    def _unsupported(self, op: str) -> DomainError:
        return DomainError(
            f"הספק {self.provider} אינו תומך בפעולה {op}. "
            f"{'הוא לקריאה בלבד (מעקב רישום).' if self.read_only else ''}",
            status=409, kind="unsupported")


class CloudflareAdapter(BaseAdapter):
    provider = "cloudflare"
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, secret: dict):
        super().__init__(secret)
        token = (self.secret.get("token") or "").strip()
        if not token:
            raise DomainError("חסר טוקן API של Cloudflare", status=400, kind="input")
        self.s.headers["authorization"] = f"Bearer {token}"
        self.account_id = (self.secret.get("account_id") or "").strip()

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.s.request(method, f"{self.BASE}{path}", timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise DomainError("לא ניתן להגיע ל-Cloudflare", detail=str(e))
        try:
            payload = r.json()
        except ValueError:
            payload = r.text[:300]
        if r.status_code >= 300 or (isinstance(payload, dict) and payload.get("success") is False):
            raise _http_error(r.status_code, payload, "Cloudflare")
        return payload.get("result") if isinstance(payload, dict) else {}

    def whoami(self) -> dict:
        verify = self._call("GET", "/user/tokens/verify")
        zones = self._call("GET", "/zones", params={"per_page": 5})
        return {"login": f"Cloudflare ({verify.get('status', 'unknown')})",
                "scopes": verify.get("policies") or None,
                "capabilities": {"write_dns": True, "list_zones": True, "registrar": bool(
                    self.account_id), "renew": False},
                "zones_sample": [z.get("name") for z in (zones or [])]}

    def _zone_id(self, domain: str) -> str:
        zones = self._call("GET", "/zones", params={"name": domain})
        if not zones:
            raise DomainError(f"‏{domain} אינו אזור בחשבון Cloudflare הזה", status=404)
        return zones[0]["id"]

    def list_domains(self, limit: int = 100) -> list[dict]:
        zones = self._call("GET", "/zones", params={"per_page": min(50, limit)})
        return [norm_domain(z, "cloudflare") for z in (zones or [])]

    def get_domain(self, domain: str) -> dict:
        zones = self._call("GET", "/zones", params={"name": domain})
        if not zones:
            raise DomainError(f"‏{domain} אינו אזור בחשבון הזה", status=404)
        return norm_domain(zones[0], "cloudflare")

    def list_records(self, domain: str) -> list[dict]:
        zid = self._zone_id(domain)
        out, page = [], 1
        while page <= 10:
            res = self._call("GET", f"/zones/{zid}/dns_records",
                             params={"per_page": 100, "page": page})
            out += [norm_record(r, "cloudflare") for r in (res or [])]
            if not res or len(res) < 100:
                break
            page += 1
        return out

    def _payload(self, rec: dict) -> dict:
        body = {"type": (rec.get("type") or "A").upper(), "name": rec.get("name"),
                "content": rec.get("content"), "ttl": int(rec.get("ttl") or 1)}
        if rec.get("proxied") is not None and body["type"] in ("A", "AAAA", "CNAME"):
            body["proxied"] = bool(rec["proxied"])
        if rec.get("priority") is not None:
            body["priority"] = int(rec["priority"])
        return {k: v for k, v in body.items() if v not in (None, "")}

    def create_record(self, domain: str, rec: dict) -> dict:
        zid = self._zone_id(domain)
        return norm_record(self._call("POST", f"/zones/{zid}/dns_records",
                                      json=self._payload(rec)), "cloudflare")

    def update_record(self, domain: str, rec: dict) -> dict:
        zid = self._zone_id(domain)
        rid = rec.get("id") or self._find_record(zid, rec)
        return norm_record(self._call("PATCH", f"/zones/{zid}/dns_records/{rid}",
                                      json=self._payload(rec)), "cloudflare")

    def delete_record(self, domain: str, rec: dict) -> dict:
        zid = self._zone_id(domain)
        rid = rec.get("id") or self._find_record(zid, rec)
        res = self._call("DELETE", f"/zones/{zid}/dns_records/{rid}")
        return {"deleted": True, "id": (res or {}).get("id") or rid}

    def _find_record(self, zid: str, rec: dict) -> str:
        """A record addressed by name+type+content (what a human types) → its provider id. The UI
        hands back ids it was given, but the op surface accepts a name, and resolving it HERE means
        a caller cannot accidentally edit the wrong record by guessing an id."""
        wanted = (rec.get("name") or "").lower()
        res = self._call("GET", f"/zones/{zid}/dns_records",
                         params={"type": (rec.get("type") or "").upper(), "per_page": 100})
        for r in res or []:
            if (r.get("name") or "").lower() == wanted and \
                    (rec.get("content") in (None, "", r.get("content"))):
                return r["id"]
        raise DomainError("לא נמצאה רשומה כזו באזור", status=404)

    def check_availability(self, domain: str) -> dict:
        """Cloudflare's registrar search needs an account id; without one, answer from the registry
        (which is what "is it taken" actually means) and say so."""
        if not self.account_id:
            return _registry_availability(domain, note="ל-Cloudflare לא הוגדר account_id")
        res = self._call("GET", f"/accounts/{self.account_id}/registrar/domain-search",
                         params={"q": domain})
        for d in (res.get("domains") or []):
            if d.get("name") == domain:
                return {"domain": domain, "available": bool(d.get("available")),
                        "price": d.get("price"), "currency": d.get("currency"),
                        "source": "cloudflare"}
        return {"domain": domain, "available": None, "source": "cloudflare",
                "note": "לא התקבלה תשובה לזמינות"}


class GoDaddyAdapter(BaseAdapter):
    provider = "godaddy"
    BASE = "https://api.godaddy.com"

    def __init__(self, secret: dict):
        super().__init__(secret)
        key, sec, pat = ((self.secret.get(k) or "").strip()
                         for k in ("key", "secret", "token"))
        if pat:
            self.s.headers["authorization"] = f"Bearer {pat}"
        elif key and sec:
            self.s.headers["authorization"] = f"sso-key {key}:{sec}"
        else:
            raise DomainError("חסרים מפתח וסוד של GoDaddy (או PAT)", status=400, kind="input")
        self.s.headers["accept"] = "application/json"
        if self.secret.get("shopper_id"):
            self.s.headers["X-Shopper-Id"] = self.secret["shopper_id"]
        if self.secret.get("ote"):
            self.BASE = "https://api.ote-godaddy.com"

    def _call(self, method: str, path: str, **kw) -> object:
        try:
            r = self.s.request(method, f"{self.BASE}{path}", timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise DomainError("לא ניתן להגיע ל-GoDaddy", detail=str(e))
        if r.status_code == 204 or not r.content:
            return {}
        try:
            payload = r.json()
        except ValueError:
            payload = r.text[:300]
        if r.status_code >= 300:
            raise _http_error(r.status_code, payload, "GoDaddy")
        return payload

    def whoami(self) -> dict:
        domains = self._call("GET", "/v1/domains", params={"limit": 5})
        return {"login": "GoDaddy",
                "capabilities": {"write_dns": True, "list_zones": True, "registrar": True,
                                 "renew": True},
                "domains_sample": [d.get("domain") for d in (domains or [])]}

    def list_domains(self, limit: int = 100) -> list[dict]:
        out, marker = [], None
        for _ in range(10):
            params = {"limit": min(100, limit), "includes": "nameServers"}
            if marker:
                params["marker"] = marker
            page = self._call("GET", "/v1/domains", params=params) or []
            out += [norm_domain(d, "godaddy") for d in page]
            marker = page[-1].get("domain") if page else None
            if not page or len(page) < params["limit"] or len(out) >= limit:
                break
        return out[:limit]

    def get_domain(self, domain: str) -> dict:
        raw = self._call("GET", f"/v1/domains/{domain}",
                         params={"includes": "nameServers"}) or {}
        out = norm_domain(raw, "godaddy")
        out.update({"locked": raw.get("locked"), "privacy": raw.get("privacy"),
                    "expiration_protected": raw.get("expirationProtected"),
                    "auto_renew": raw.get("renewAuto")})
        return out

    def list_records(self, domain: str) -> list[dict]:
        return [norm_record(r, "godaddy") for r in (self._call("GET", f"/v1/domains/{domain}/records") or [])]

    def create_record(self, domain: str, rec: dict) -> dict:
        """PATCH **appends**. `PUT /v1/domains/{d}/records` is never used here on purpose: it replaces
        the entire zone, so one mistaken call deletes every record the business depends on — mail
        included."""
        body = [{"type": (rec.get("type") or "A").upper(), "name": rec.get("name"),
                 "data": rec.get("content"), "ttl": int(rec.get("ttl") or 3600)}]
        if rec.get("priority") is not None:
            body[0]["priority"] = int(rec["priority"])
        self._call("PATCH", f"/v1/domains/{domain}/records", json=body)
        return {"created": True, "record": norm_record(body[0], "godaddy")}

    def update_record(self, domain: str, rec: dict) -> dict:
        rtype = (rec.get("type") or "A").upper()
        name = rec.get("name") or "@"
        body = [{"data": rec.get("content"), "ttl": int(rec.get("ttl") or 3600)}]
        if rec.get("priority") is not None:
            body[0]["priority"] = int(rec["priority"])
        self._call("PUT", f"/v1/domains/{domain}/records/{rtype}/{name}", json=body)
        return {"updated": True, "record": norm_record({**body[0], "type": rtype, "name": name},
                                                       "godaddy")}

    def delete_record(self, domain: str, rec: dict) -> dict:
        rtype = (rec.get("type") or "A").upper()
        name = rec.get("name") or "@"
        self._call("DELETE", f"/v1/domains/{domain}/records/{rtype}/{name}")
        return {"deleted": True, "type": rtype, "name": name}

    def check_availability(self, domain: str) -> dict:
        res = self._call("GET", "/v1/domains/available", params={"domain": domain,
                                                                "checkType": "FAST"}) or {}
        return {"domain": domain, "available": res.get("available"),
                "price": (res.get("price") or 0) / 1_000_000 if res.get("price") else None,
                "currency": res.get("currency"), "source": "godaddy",
                "definitive": res.get("definitive")}


class RegistryAdapter(BaseAdapter):
    """The office's own registrar, modelled HONESTLY.

    Internic publishes no API (verified 2026-09-23), so this provider can watch a domain and nothing
    else. That is not a gap to be papered over with a scraper against the owner's password: it is a
    real capability boundary, and the app states it — `write_dns: false` means the UI never offers a
    record editor for these domains, and every write op refuses with a sentence that names the two
    ways forward (connect the zone's actual DNS host, or manage it in Internic's own panel).
    """
    provider = "registry"
    read_only = True

    def whoami(self) -> dict:
        return {"login": "רישום (WHOIS/RDAP)",
                "scopes": None,
                "capabilities": {"write_dns": False, "list_zones": False, "registrar": True,
                                 "renew": False, "watch": True}}

    def list_domains(self, limit: int = 100) -> list[dict]:
        """A registry has no "list my domains" for a customer — only the office's own watched list
        can answer that, and this returns it rather than pretending to ask somebody."""
        import registry as store
        return [{"name": d["name"], "expiry": d["expiry"], "status": d["status"],
                 "nameservers": d["nameservers"], "registrar": d["registrar"],
                 "provider": "registry"} for d in store.list_domains()][:limit]

    def get_domain(self, domain: str) -> dict:
        info = whoisq.lookup(domain)
        if not info.get("found"):
            raise DomainError(f"‏{domain} אינו רשום", status=404)
        return {"name": domain, "expiry": info.get("expiry"), "registered": info.get("registered"),
                "status": info.get("status"), "registrar": info.get("registrar"),
                "nameservers": info.get("nameservers") or [], "source": info.get("source"),
                "provider": "registry"}

    def list_records(self, domain: str) -> list[dict]:
        """Not the zone — the WORLD's view of it. For a provider we cannot read, the public DNS
        answer is the only honest one, and it is also the answer that matters."""
        snap = dnsq.snapshot(domain)
        out = []
        for rtype, values in (snap.get("records") or {}).items():
            for v in values:
                out.append({"id": f"{rtype}/{v}", "type": rtype, "name": domain,
                            "content": v, "ttl": None, "source": "dns", "read_only": True,
                            "provider": "registry"})
        return out

    def check_availability(self, domain: str) -> dict:
        return _registry_availability(domain)


def _registry_availability(domain: str, note: str = "") -> dict:
    try:
        info = whoisq.lookup(domain)
    except whoisq.WhoisError as e:
        return {"domain": domain, "available": None, "source": "registry", "note": e.message}
    return {"domain": domain, "available": not info.get("found"), "source": "registry",
            "expiry": info.get("expiry"), "registrar": info.get("registrar"),
            "note": note or "לפי הרישום הציבורי (WHOIS/RDAP)"}



class PleskAdapter(BaseAdapter):
    """Plesk Obsidian's REST API — the panel that actually holds this office's zones.

    `ns1/ns2.sitesdepot.com` are not a mystery: they are a Plesk Obsidian 18.0.80 server run by
    InterVision (the InterSpace/Internic group — see apps/domains/AGENT.md for the evidence), and
    Plesk has had a documented REST API for years. Verified live on 2026-09-23: `/api/v2/domains`
    answers `403 {"code":0,"message":"Access to API is disabled for <IP>"}` — the API is ENABLED and
    the caller is refused BY IP. So this adapter is not speculative: it is the shortest path from
    "no automation" to "full DNS automation" for the domains this business already owns, and it needs
    exactly two things from the provider (an API key, and our egress IP on their allowlist).

    The refusal message names the IP to allowlist, and this adapter SURFACES it rather than
    paraphrasing: "access disabled for 79.177.165.212" is the difference between a support ticket
    that gets answered and one that says "the API does not work".
    """
    provider = "plesk"
    DEFAULT_BASE = "https://sitesdepot.com/api/v2"

    def __init__(self, secret: dict):
        super().__init__(secret)
        key = (self.secret.get("token") or self.secret.get("key") or "").strip()
        if not key:
            raise DomainError("חסר מפתח API של Plesk", status=400, kind="input")
        self.s.headers["X-API-Key"] = key
        self.base = (self.secret.get("base") or self.DEFAULT_BASE).rstrip("/")

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.s.request(method, f"{self.base}{path}", timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise DomainError("לא ניתן להגיע ל-Plesk", detail=str(e))
        payload = {}
        if r.content:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text[:300]
        if r.status_code >= 300:
            raise self._error(r.status_code, payload)
        return payload

    @staticmethod
    def _error(status: int, payload) -> DomainError:
        msg = (payload or {}).get("message") if isinstance(payload, dict) else str(payload)
        msg = msg or f"HTTP {status}"
        ip = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", msg)
        if status == 403 and "disabled for" in msg.lower():
            return DomainError(
                "ה-API של Plesk מופעל אבל חסום לכתובת ה-IP של הלשכה"
                + (f" ({ip.group(1)})" if ip else "") + ".",
                status=403,
                detail=(f"בקש מהספק (InterVision / sitesdepot) להוסיף את הכתובת "
                        f"{ip.group(1) if ip else 'של הלשכה'} לרשימת ההרשאות של ה-API, "
                        f"ולהוציא מפתח API. ההודעה מהשרת: {msg}"),
                provider_error=payload)
        if status == 401:
            raise DomainError("מפתח ה-API של Plesk נדחה — בדוק אותו מול הפאנל.", status=401,
                              provider_error=payload)
        return _http_error(status, payload, "Plesk")

    def whoami(self) -> dict:
        info = self._call("GET", "/server")
        domains = self._call("GET", "/domains")
        return {"login": (info or {}).get("hostname") or "Plesk",
                "capabilities": {"write_dns": True, "list_zones": True, "registrar": False,
                                 "renew": False},
                "domains_sample": [d.get("name") for d in (domains or [])[:5]]}

    def list_domains(self, limit: int = 100) -> list[dict]:
        rows = self._call("GET", "/domains") or []
        return [{"name": d.get("name"), "status": d.get("status"), "id": d.get("id"),
                 "nameservers": [], "registrar": None, "expiry": None, "provider": "plesk"}
                for d in rows[:limit]]

    def _domain_id(self, domain: str) -> int | None:
        for d in self._call("GET", "/domains") or []:
            if (d.get("name") or "").lower() == domain.lower():
                return d.get("id")
        return None

    def list_records(self, domain: str) -> list[dict]:
        rows = self._call("GET", "/dns/records", params={"domain": domain}) or []
        return [{"id": r.get("id"), "type": r.get("type"), "name": r.get("host"),
                 "content": r.get("value"), "ttl": r.get("ttl"), "provider": "plesk"}
                for r in rows]

    def create_record(self, domain: str, rec: dict) -> dict:
        body = {"host": rec.get("name") or "", "type": (rec.get("type") or "A").upper(),
                "value": rec.get("content"), "ttl": int(rec.get("ttl") or 3600)}
        did = self._domain_id(domain)
        if did is not None:
            body["domain_id"] = did
        # The write body is the ONE part of this adapter that has not been exercised against the real
        # panel (the API refuses us by IP before any write can run). Plesk answers a shape mistake
        # with a field-level error, which `_error` renders verbatim — so the first real call either
        # works or names the field, and it never fails silently.
        return self._call("POST", "/dns/records", json=body)

    def update_record(self, domain: str, rec: dict) -> dict:
        if not rec.get("id"):
            raise DomainError("עדכון רשומה ב-Plesk צריך מזהה רשומה (id)", status=400, kind="input")
        body = {"host": rec.get("name") or "", "type": (rec.get("type") or "A").upper(),
                "value": rec.get("content"), "ttl": int(rec.get("ttl") or 3600)}
        return self._call("PUT", f"/dns/records/{rec['id']}", json=body)

    def delete_record(self, domain: str, rec: dict) -> dict:
        if not rec.get("id"):
            raise DomainError("מחיקת רשומה ב-Plesk צריכה מזהה רשומה (id)", status=400,
                              kind="input")
        self._call("DELETE", f"/dns/records/{rec['id']}")
        return {"deleted": True, "id": rec["id"]}


class PortalAdapter(BaseAdapter):
    """A provider whose only door is its own website — driven through the office's browser.

    This is the honest shape for Internic (InterSpace Ltd): no API, no documented endpoint, a
    Laravel panel behind an Imperva WAF whose login form is not even served to a non-JS client
    (verified 2026-09-23). What it CAN do is exactly what the owner can do by hand, and the app is
    built so that the difference is visible: reads are safe and run; writes refuse until a human has
    watched that exact script version perform the action once (portal.py).

    The session it uses is the office's own Chromium — the owner logs in once and nothing about their
    credentials, cookies or screenshots ever leaves the office
    (ai/context/browser-session-connection.md).
    """
    provider = "portal"
    portal_id = "internic"

    def whoami(self) -> dict:
        import portal as portal_mod
        st = portal_mod.state(self.portal_id)
        return {"login": st.get("title") or "פורטל הרשם",
                "capabilities": {"write_dns": False, "list_zones": True, "registrar": True,
                                 "renew": False, "via_browser": True,
                                 "authenticated": bool(st.get("authenticated"))},
                "state": st.get("state"), "reason": st.get("reason")}

    def list_domains(self, limit: int = 100) -> list[dict]:
        """From the registry (WHOIS): a portal shows the same registrations, and the registry's copy
        needs no login and cannot be broken by a redesign."""
        return RegistryAdapter(self.secret).list_domains(limit)

    def get_domain(self, domain: str) -> dict:
        return RegistryAdapter(self.secret).get_domain(domain)

    def list_records(self, domain: str) -> list[dict]:
        return RegistryAdapter(self.secret).list_records(domain)

    def write_record(self, domain: str, rec: dict) -> dict:
        import portal as portal_mod
        res = portal_mod.run(self.portal_id, "write_record",
                             {"domain": domain, "type": rec.get("type"), "name": rec.get("name"),
                              "value": rec.get("content"), "ttl": rec.get("ttl")})
        if not res.get("ok"):
            raise DomainError(res.get("error") or "הפעולה בפורטל נכשלה",
                              status=409 if res.get("state") == "needs_verification" else 502,
                              detail=res.get("how") or res.get("why"), kind="portal")
        return res

    def check_availability(self, domain: str) -> dict:
        return _registry_availability(domain)


ADAPTERS = {"cloudflare": CloudflareAdapter, "godaddy": GoDaddyAdapter,
            "plesk": PleskAdapter, "portal": PortalAdapter, "registry": RegistryAdapter}

PROVIDER_OF = {
    "domain_cloudflare_token": "cloudflare",
    "domain_godaddy_key": "godaddy",
    "domain_godaddy_pat": "godaddy",
    "domain_registry_whois": "registry",
    "domain_plesk_key": "plesk",
    "domain_portal_session": "portal",
}

PROVIDERS = [
    {
        "id": "cloudflare", "name": "Cloudflare", "icon": "shield", "access": "api",
        "reads": "ה-zone עצמה (הרשומות) דרך ה-API, ונתוני הרישום דרך הרישום הציבורי",
        "description": "DNS מהיר עם API מסודר. מתאים לניהול רשומות אוטומטי ולתעבורה.",
        "capabilities": {"write_dns": True, "list_zones": True},
        "auth_methods": [{
            "id": "token", "label": "API Token (מומלץ)", "protocol": "domain_cloudflare_token",
            "needs": ["token"], "optional": ["account_id"], "recommended": True,
            "can": "לקרוא אזורים, לקרוא ולשנות רשומות DNS, ולבדוק זמינות דומיין.",
            "explain": "יוצרים Token בהרשאות Zone:Read ו-DNS:Edit. אפשר להגביל אותו לאזורים "
                       "ולכתובות IP. Account ID נדרש רק לבדיקת זמינות דרך הרשם של Cloudflare.",
            "help_url": "https://dash.cloudflare.com/profile/api-tokens",
        }],
    },
    {
        "id": "godaddy", "name": "GoDaddy", "icon": "globe", "access": "api",
        "reads": "ה-zone, התוקף והחידוש האוטומטי ישירות מה-API של הרשם",
        "description": "רשם ואחסון DNS. כולל נתוני רישום (תוקף, חידוש אוטומטי, שרתי שמות).",
        "capabilities": {"write_dns": True, "list_zones": True, "registrar": True},
        "auth_methods": [
            {"id": "pat", "label": "Personal Access Token (מומלץ)", "protocol": "domain_godaddy_pat",
             "needs": ["token"], "optional": ["shopper_id"], "recommended": True,
             "can": "לקרוא דומיינים ורשומות, ולעדכן רשומות.",
             "explain": "נוצר ב-GoDaddy Developer Portal עם הרשאות domains.domain:read ו-dns:update.",
             "help_url": "https://developer.godaddy.com/keys"},
            {"id": "sso_key", "label": "מפתח וסוד (sso-key)", "protocol": "domain_godaddy_key",
             "needs": ["key", "secret"], "optional": ["shopper_id"],
             "can": "אותו דבר, בשיטה הוותיקה (v1).",
             "explain": "מתאים לחשבונות שעוד עובדים עם המפתח הישן.", "help_url": ""},
        ],
    },
    {
        "id": "plesk", "name": "Plesk (InterVision / sitesdepot)", "icon": "server", "access": "api",
        "reads": "האזור עצמו דרך ה-API של Plesk — זה השרת שמחזיק בפועל את הרשומות של הדומיינים "
                 "האלה (ns1/ns2.sitesdepot.com).",
        "description": "שרת ה-DNS האמיתי של הדומיינים האלה. ה-API פעיל אך חסום לפי כתובת IP.",
        "capabilities": {"write_dns": True, "list_zones": True, "registrar": False},
        "auth_methods": [{
            "id": "api_key", "label": "מפתח API של Plesk (מומלץ)", "protocol": "domain_plesk_key",
            "needs": ["token"], "optional": ["base"], "recommended": True,
            "can": "לקרוא דומיינים ורשומות DNS, ולעדכן רשומות.",
            "explain": "שני דברים מהספק: (1) מפתח API לפאנל, (2) הוספת כתובת ה-IP של הלשכה "
                       "לרשימת ההרשאות של ה-API. השרת כבר עונה — הוא מסרב רק לפי IP, והתשובה "
                       "עצמה אומרת איזו כתובת צריך להתיר.",
            "help_url": "",
        }],
    },
    {
        "id": "portal", "name": "פורטל הרשם (דרך הדפדפן של הלשכה)", "icon": "monitor",
        "access": "browser",
        "reads": "מה שאדם רואה בפורטל — הלשכה נוהגת בדפדפן המחובר של הבעלים, בלי סיסמאות.",
        "description": "לרשם אין API בכלל. מתחברים פעם אחת בדפדפן של הלשכה, ומכאן זה עובד — "
                       "באותו סשן, בלי שהסיסמה נשמרת בשום מקום.",
        "capabilities": {"write_dns": False, "list_zones": True, "registrar": True,
                         "via_browser": True},
        "auth_methods": [{
            "id": "session", "label": "סשן בדפדפן של הלשכה", "protocol": "domain_portal_session",
            "needs": [], "recommended": True,
            "can": "לקרוא את מה שהפורטל מציג, ולפעול בו — בכפוף לאישור אנושי לפני כתיבה.",
            "explain": "פותחים את תצוגת הדפדפן של הלשכה ומתחברים כמו בכל דפדפן. הסיסמה לא נשמרת "
                       "בוולט ולא נשלחת לשום מקום; הלשכה פשוט ממשיכה מאותו סשן, בתוך הלשכה.",
            "help_url": "/a/browser42/",
        }],
    },
    {
        "id": "registry", "name": "רישום ציבורי — Internic וכל רשם אחר", "icon": "link",
        "access": "registry", "always_on": True,
        "reads": "התוקף, סטטוס הנעילה ושרתי השמות מהרישום הציבורי (WHOIS בפורט 43) — בלי סיסמה "
                 "ובלי חשבון. את הרשומות עצמן הוא מציג כפי שה-DNS הציבורי מחזיר אותן; כתיבה "
                 "דורשת את מי שמחזיק בפועל בשרתי השמות.",
        "description": "מעקב אחר הדומיין מול הרישום הציבורי — תוקף, סטטוס ושרתי שמות, בלי API.",
        "capabilities": {"write_dns": False, "list_zones": False, "registrar": True},
        "auth_methods": [{
            "id": "registry", "label": "מעקב בלבד (בלי סיסמה)", "protocol": "domain_registry_whois",
            "needs": [], "recommended": True,
            "can": "לקרוא תוקף, סטטוס, סטטוס נעילה ושרתי שמות מהרישום; להציג את ה-DNS שהעולם רואה.",
            "explain": "אינטרניק (Internic) אינה מפרסמת API. לכן הלשכה קוראת את מה שהרישום של "
                       ".co.il מפרסם לכולם (WHOIS בפורט 43, בלי סיסמה) ומתריעה לפני שהדומיין פג. "
                       "כתיבת רשומות נעשית אצל מי שמחזיק בפועל בשרתי השמות — אפשר לחבר אותו כאן.",
            "help_url": "",
        }],
    },
]


def adapter_for(provider: str, secret: dict) -> BaseAdapter:
    cls = ADAPTERS.get(provider)
    if not cls:
        raise DomainError(f"ספק לא מוכר: {provider}", status=400, kind="input")
    return cls(secret)


def dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)[:2000]


# ── the spec-driven adapters ─────────────────────────────────────────────────────────────────────
# Most DNS hosts differ only in URLs and in where their JSON keeps a value. Writing one class per
# provider is how a catalogue grows five entries and then stops, so the common case is DATA: a
# spec says where to get a token, which paths to call, and how to map the answer into the office's
# shapes. Hand-written adapters stay for the providers that need real behaviour (Cloudflare's
# zone-id indirection, GoDaddy's whole-zone PUT trap, Plesk's IP refusal).
#
# A spec'd provider is verified the moment an account is connected — the connect wizard calls
# `whoami()` before storing anything (§4b of the service contract), so "untested" never means
# "unverified in production": it means the first real token is the test, and a wrong path shows that
# provider's own error instead of a silent empty list.
SPECS: dict[str, dict] = {
    "porkbun": {
        "name": "Porkbun", "icon": "globe", "access": "api",
        "base": "https://api.porkbun.com/api/json/v3",
        "auth": {"headers": {"X-API-Key": "{key}", "X-Secret-API-Key": "{secret}"}},
        "needs": ["key", "secret"],
        "reads": "דומיינים, תוקף, רשומות DNS וזמינות — דרך ה-API של Porkbun.",
        "help_url": "https://porkbun.com/account/api",
        "ops": {
            "whoami": {"method": "POST", "path": "/domain/listAll", "items": "$.domains",
                       "map": {"name": "domain"}},
            "list_domains": {"method": "POST", "path": "/domain/listAll", "items": "$.domains",
                             "map": {"name": "domain", "expiry": "expireDate",
                                     "auto_renew": "autoRenew", "status": "status"}},
            "list_records": {"method": "POST", "path": "/dns/retrieve/{domain}",
                             "items": "$.records",
                             "map": {"id": "id", "type": "type", "name": "name",
                                     "content": "content", "ttl": "ttl", "priority": "prio"}},
            "create_record": {"method": "POST", "path": "/dns/create/{domain}",
                              "body": {"name": "{name}", "type": "{type}", "content": "{content}",
                                       "ttl": "{ttl}"}},
            "update_record": {"method": "POST", "path": "/dns/edit/{domain}/{id}",
                              "body": {"name": "{name}", "type": "{type}", "content": "{content}",
                                       "ttl": "{ttl}"}},
            "delete_record": {"method": "POST", "path": "/dns/delete/{domain}/{id}"},
            "check_availability": {"method": "POST", "path": "/domain/checkDomain/{domain}",
                                   "map": {"available": "avail"}},
        },
        "notes": ("Porkbun מחזיר SUCCESS גם כשהדומיין אינו מוצב אצל שרתי השמות שלהם — לכן הזרימה "
                  "הזו קוראת את הרשומות חזרה אחרי כל כתיבה, ולא מסתפקת בתשובת ההצלחה."),
    },
    "digitalocean": {
        "name": "DigitalOcean", "icon": "server", "access": "api",
        "base": "https://api.digitalocean.com/v2",
        "auth": {"headers": {"Authorization": "Bearer {token}"}},
        "needs": ["token"],
        "reads": "אזורי DNS ורשומות — דרך ה-API של DigitalOcean.",
        "help_url": "https://cloud.digitalocean.com/account/api/tokens",
        "ops": {
            "whoami": {"method": "GET", "path": "/domains", "items": "$.domains",
                       "map": {"name": "name"}},
            "list_domains": {"method": "GET", "path": "/domains", "items": "$.domains",
                             "map": {"name": "name", "ttl": "ttl"}},
            "list_records": {"method": "GET", "path": "/domains/{domain}/records", "items": "$.domain_records",
                             "map": {"id": "id", "type": "type", "name": "name",
                                     "content": "data", "ttl": "ttl", "priority": "priority"}},
            "create_record": {"method": "POST", "path": "/domains/{domain}/records",
                              "body": {"type": "{type}", "name": "{name}", "data": "{content}",
                                       "ttl": "{ttl}"}},
            "update_record": {"method": "PUT", "path": "/domains/{domain}/records/{id}",
                              "body": {"type": "{type}", "name": "{name}", "data": "{content}",
                                       "ttl": "{ttl}"}},
            "delete_record": {"method": "DELETE", "path": "/domains/{domain}/records/{id}"},
        },
    },
    "gandi": {
        "name": "Gandi LiveDNS", "icon": "globe", "access": "api",
        "base": "https://api.gandi.net/v5/livedns",
        "auth": {"headers": {"Authorization": "Bearer {token}"}},
        "needs": ["token"],
        "reads": "אזורי LiveDNS ורשומות — דרך ה-API של Gandi.",
        "help_url": "https://account.gandi.net/en/users/_/security",
        "ops": {
            "whoami": {"method": "GET", "path": "/domains", "items": "$", "map": {"name": "fqdn"}},
            "list_domains": {"method": "GET", "path": "/domains", "items": "$",
                             "map": {"name": "fqdn"}},
            "list_records": {"method": "GET", "path": "/domains/{domain}/records", "items": "$",
                             "map": {"type": "rrset_type", "name": "rrset_name",
                                     "content": "rrset_values", "ttl": "rrset_ttl"}},
            "create_record": {"method": "POST", "path": "/domains/{domain}/records/{name}/{type}",
                              "body": {"rrset_values": ["{content}"], "rrset_ttl": "{ttl}"}},
            "update_record": {"method": "PUT", "path": "/domains/{domain}/records/{name}/{type}",
                              "body": {"rrset_values": ["{content}"], "rrset_ttl": "{ttl}"}},
            "delete_record": {"method": "DELETE", "path": "/domains/{domain}/records/{name}/{type}"},
        },
        "notes": ("Gandi עובד ב-rrsets: רשומה = (שם, סוג) עם רשימת ערכים, ולכן „עדכון” כאן מחליף "
                  "את כל הערכים של אותו שם וסוג — הפעולה מוצהרת כך ולא מוסתרת."),
    },
    "hetzner": {
        "name": "Hetzner DNS", "icon": "server", "access": "api",
        "base": "https://dns.hetzner.com/api/v1",
        "auth": {"headers": {"Auth-API-Token": "{token}"}},
        "needs": ["token"],
        "reads": "אזורי DNS ורשומות — דרך ה-API של Hetzner.",
        "help_url": "https://dns.hetzner.com/settings/api-token",
        "ops": {
            "whoami": {"method": "GET", "path": "/zones", "items": "$.zones", "map": {"name": "name"}},
            "list_domains": {"method": "GET", "path": "/zones", "items": "$.zones",
                             "map": {"name": "name", "status": "status"}},
            "list_records": {"method": "GET", "path": "/records", "items": "$.records",
                             "params": {"zone_id": "{zone_id}"},
                             "map": {"id": "id", "type": "type", "name": "name",
                                     "content": "value", "ttl": "ttl"}},
            "create_record": {"method": "POST", "path": "/records",
                              "body": {"zone_id": "{zone_id}", "type": "{type}", "name": "{name}",
                                       "value": "{content}", "ttl": "{ttl}"}},
            "update_record": {"method": "PUT", "path": "/records/{id}",
                              "body": {"zone_id": "{zone_id}", "type": "{type}", "name": "{name}",
                                       "value": "{content}", "ttl": "{ttl}"}},
            "delete_record": {"method": "DELETE", "path": "/records/{id}"},
        },
        "notes": "Hetzner ממען רשומות לפי zone_id, ולכן האזור נפתר לפני כל פעולה.",
    },
}


def _dig(payload, path: str):
    """A tiny JSON path: `$.a.b`, `$.a`, `$`. Deliberately not jsonpath — the specs above need
    exactly one shape of navigation, and a real path library would be a dependency for a dot."""
    if path in ("$", ""):
        return payload
    cur = payload
    for part in path.lstrip("$").strip(".").split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class SpecAdapter(BaseAdapter):
    """One adapter for every provider whose API is "URL + JSON". Behaviour lives in the spec."""

    def __init__(self, spec: dict, secret: dict):
        super().__init__(secret)
        self.spec = spec
        self.provider = spec["id"]
        headers = {}
        for k, v in (spec.get("auth", {}).get("headers") or {}).items():
            headers[k] = _fill(v, {**secret, "token": secret.get("token") or secret.get("key") or ""})
        if not any(headers.values()):
            raise DomainError(f"חסרים פרטי התחברות ל-{spec['name']}", status=400, kind="input")
        self.s.headers.update(headers)
        self.base = spec["base"].rstrip("/")

    def _call(self, op: str, domain: str = "", params: dict | None = None) -> object:
        spec = (self.spec.get("ops") or {}).get(op)
        if not spec:
            raise self._unsupported(op)
        path = spec["path"].format(domain=domain, **(params or {}))
        kwargs = {}
        if spec.get("params"):
            kwargs["params"] = {k: _fill(str(v), {**self.secret, "domain": domain, **(params or {})})
                                for k, v in spec["params"].items()}
        if spec.get("body"):
            kwargs["json"] = {k: _fill(v, {**self.secret, "domain": domain, **(params or {})})
                              for k, v in spec["body"].items()}
        try:
            r = self.s.request(spec["method"], f"{self.base}{path}", timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise DomainError(f"לא ניתן להגיע ל-{self.spec['name']}",
                              detail=str(e))
        payload = {}
        if r.content:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text[:300]
        if r.status_code >= 300:
            raise _http_error(r.status_code, payload, self.spec["name"])
        if isinstance(payload, dict) and payload.get("status") == "ERROR":
            raise DomainError(f"{self.spec['name']}: {payload.get('message') or 'שגיאה'}",
                              detail=dumps(payload))
        return payload

    def _items(self, op: str, domain: str = "", params: dict | None = None) -> list[dict]:
        spec = (self.spec.get("ops") or {}).get(op) or {}
        payload = self._call(op, domain, params)
        items = _dig(payload, spec.get("items", "$")) if spec.get("items") else payload
        if isinstance(items, dict):
            items = [items]
        return [i for i in (items or []) if isinstance(i, dict)]

    def _map(self, op: str, raw: dict, extra: dict | None = None) -> dict:
        m = ((self.spec.get("ops") or {}).get(op) or {}).get("map") or {}
        out = {"provider": self.provider}
        for target, source in m.items():
            out[target] = raw.get(source)
        if isinstance(out.get("content"), list):
            out["content"] = " ".join(str(x) for x in out["content"])
        if out.get("expiry") and not isinstance(out["expiry"], int):
            out["expiry"] = whoisq.parse_date(str(out["expiry"]))
        return {**out, **(extra or {})}

    def whoami(self) -> dict:
        rows = self._items("whoami")
        return {"login": f"{self.spec['name']} ({len(rows)} אזורים)",
                "capabilities": {"write_dns": True, "list_zones": True,
                                 "registrar": "registrar" in (self.spec.get("ops") or {}),
                                 "renew": False, "spec_driven": True},
                "domains_sample": [self._map("whoami", r).get("name") for r in rows[:5]]}

    def list_domains(self, limit: int = 100) -> list[dict]:
        return [self._map("list_domains", r) for r in self._items("list_domains")][:limit]

    def get_domain(self, domain: str) -> dict:
        for d in self.list_domains(200):
            if (d.get("name") or "").lower() == domain.lower():
                return d
        raise DomainError(f"‏{domain} אינו אזור בחשבון {self.spec['name']}", status=404)

    def list_records(self, domain: str) -> list[dict]:
        params = {}
        if "{zone_id}" in str(self.spec.get("ops", {}).get("list_records", {}).get("params", {})):
            params["zone_id"] = self._zone_id(domain)
        return [self._map("list_records", r, {"zone_id": params.get("zone_id")})
                for r in self._items("list_records", domain, params)]

    def _zone_id(self, domain: str) -> str:
        for raw in self._items("list_domains"):
            if (raw.get("name") or "").lower() == domain.lower():
                return str(raw.get("id") or raw.get("zone_id") or "")
        raise DomainError(f"‏{domain} אינו אזור בחשבון {self.spec['name']}", status=404)

    def _write(self, op: str, domain: str, rec: dict) -> dict:
        params = {"id": rec.get("id"), "name": rec.get("name") or "@",
                  "type": (rec.get("type") or "").upper(), "content": rec.get("content"),
                  "ttl": int(rec.get("ttl") or 3600)}
        if "{zone_id}" in str(self.spec.get("ops", {}).get(op, {})):
            params["zone_id"] = self._zone_id(domain)
        payload = self._call(op, domain, params)
        return {"ok": True, "provider": self.provider, "op": op,
                "result": payload if isinstance(payload, (dict, list)) else str(payload)}

    def create_record(self, domain: str, rec: dict) -> dict:
        return self._write("create_record", domain, rec)

    def update_record(self, domain: str, rec: dict) -> dict:
        if "{id}" in str(self.spec.get("ops", {}).get("update_record", {})) and not rec.get("id"):
            raise DomainError("עדכון רשומה דורש מזהה רשומה (id)", status=400, kind="input")
        return self._write("update_record", domain, rec)

    def delete_record(self, domain: str, rec: dict) -> dict:
        return self._write("delete_record", domain, rec)

    def check_availability(self, domain: str) -> dict:
        if "check_availability" not in (self.spec.get("ops") or {}):
            return _registry_availability(domain, note=f"ל-{self.spec['name']} אין בדיקת זמינות")
        payload = self._call("check_availability", domain)
        mapped = self._map("check_availability", payload if isinstance(payload, dict) else {})
        return {"domain": domain, "available": mapped.get("available"),
                "source": self.provider, "raw": dumps(payload)}


def _fill(template: str, values: dict) -> str:
    out = str(template)
    for k, v in values.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out


for _pid, _spec in SPECS.items():
    _spec = {**_spec, "id": _pid}
    SPECS[_pid] = _spec
    ADAPTERS[_pid] = (lambda spec: (lambda secret: SpecAdapter(spec, secret)))(_spec)
    _protocol = f"domain_{_pid}_key"
    PROVIDER_OF[_protocol] = _pid
    PROVIDERS.append({
        "id": _pid, "name": _spec["name"], "icon": _spec.get("icon", "globe"),
        "access": "api", "reads": _spec.get("reads", ""),
        "description": _spec.get("notes", f"ניהול DNS דרך ה-API של {_spec['name']}."),
        "capabilities": {"write_dns": True, "list_zones": True},
        "auth_methods": [{
            "id": "api_key", "label": f"מפתח API של {_spec['name']}", "protocol": _protocol,
            "needs": list(_spec.get("needs") or ["token"]), "recommended": True,
            "can": "לקרוא אזורים ורשומות, ולעדכן רשומות.",
            "explain": f"הדבק את פרטי ה-API מ-{_spec['name']}. החיבור מאומת מול הספק לפני שנשמר.",
            "help_url": _spec.get("help_url", ""),
        }],
    })


# ── the operation matrix: what the office can DO, per provider, and why not when it cannot ───────
# This is the app's answer to "give me one API for domains". A domain is registered somewhere, its
# zone is hosted somewhere, and the two are often different companies — so "does it support X" has
# no single answer, and the honest design is a MATRIX plus a refusal that names the missing piece
# (a capability, a credential, or the provider itself). Anything else is a UI that offers a button
# which fails later, which is the failure this whole app exists to avoid.
#
# Each op declares: label, what it needs (`read`/`write`/`money`/`human`), and per-provider support.
DOMAIN_OPS: list[dict] = [
    {"id": "listDomains", "label": "רשימת הדומיינים", "kind": "read",
     "he": "מה בבעלות העסק ומה התוקף", "support": "all"},
    {"id": "getDomain", "label": "פרטי דומיין", "kind": "read",
     "he": "תוקף, רשם, סטטוס נעילה, שרתי שמות", "support": "all"},
    {"id": "checkAvailability", "label": "בדיקת זמינות", "kind": "read",
     "he": "האם שם פנוי, ולפעמים גם המחיר", "support": {"godaddy": True, "porkbun": True,
                                                          "cloudflare": True, "registry": True}},
    {"id": "listRecords", "label": "קריאת רשומות ה-DNS", "kind": "read",
     "he": "האזור כפי שהוא אצל מי שמארח אותו", "support": "all"},
    {"id": "createRecord", "label": "הוספת רשומת DNS", "kind": "write",
     "he": "רשומה חדשה באזור", "support": {"cloudflare": True, "godaddy": True, "plesk": True,
                                             "porkbun": True, "digitalocean": True, "gandi": True,
                                             "hetzner": True, "portal": "browser"}},
    {"id": "updateRecord", "label": "עדכון רשומת DNS", "kind": "write",
     "he": "שינוי רשומה קיימת", "support": {"cloudflare": True, "godaddy": True, "plesk": True,
                                             "porkbun": True, "digitalocean": True, "gandi": True,
                                             "hetzner": True, "portal": "browser"}},
    {"id": "deleteRecord", "label": "מחיקת רשומת DNS", "kind": "write",
     "he": "הסרת רשומה", "support": {"cloudflare": True, "godaddy": True, "plesk": True,
                                      "porkbun": True, "digitalocean": True, "gandi": True,
                                      "hetzner": True, "portal": "browser"}},
    {"id": "setNameservers", "label": "שינוי שרתי שמות", "kind": "write",
     "he": "העברת ניהול ה-DNS לספק אחר (למשל Cloudflare)",
     "support": {"godaddy": True, "porkbun": True, "portal": "browser"}},
    {"id": "setAutoRenew", "label": "חידוש אוטומטי", "kind": "write",
     "he": "הדלקה/כיבוי של חידוש אוטומטי אצל הרשם",
     "support": {"godaddy": True, "porkbun": True, "portal": "browser"}},
    {"id": "setLock", "label": "נעילת העברה", "kind": "write",
     "he": "Transfer Lock — מונע העברה בטעות או בכוונה",
     "support": {"godaddy": True, "portal": "browser"}},
    {"id": "renewDomain", "label": "חידוש הדומיין", "kind": "money",
     "he": "חידוש לשנה נוספת — פעולה בתשלום, ולכן היא עוברת דרך אישור אנושי",
     "support": {"godaddy": True, "porkbun": True, "portal": "browser"}},
    {"id": "registerDomain", "label": "קניית דומיין חדש", "kind": "money",
     "he": "רישום דומיין חדש — בתשלום, ואישור אנושי לפני החיוב",
     "support": {"godaddy": True, "porkbun": True, "portal": "browser"}},
    {"id": "transferDomain", "label": "העברת דומיין", "kind": "money",
     "he": "העברה בין רשמים (דורש קוד העברה והסרת נעילה)",
     "support": {"godaddy": True, "porkbun": True}},
    {"id": "getAuthCode", "label": "קוד העברה (Auth Code)", "kind": "read",
     "he": "הקוד שדרוש כדי להעביר את הדומיין לרשם אחר",
     "support": {"portal": "browser"}},
    {"id": "dnssec", "label": "DNSSEC", "kind": "write",
     "he": "חתימת האזור — תלוי במארח ה-DNS", "support": {}},
]


def op_support(op_id: str, provider: str, api_ok: bool = True) -> dict:
    """Can `provider` do `op_id` — and if not, WHAT is missing.

    Three different "no"s, deliberately distinguished, because they have three different fixes:
    the provider has no such feature (use another provider), the provider has it but needs a
    credential we do not hold (connect it), or it needs a human (money / irreversible).
    """
    op = next((o for o in DOMAIN_OPS if o["id"] == op_id), None)
    if not op:
        return {"supported": False, "reason": f"פעולה לא מוכרת: {op_id}"}
    support = op.get("support")
    if support == "all":
        return {"supported": True, "how": "api" if provider != "portal" else "browser"}
    entry = (support or {}).get(provider)
    if entry is True:
        if not api_ok:
            return {"supported": False, "needs": "connection",
                    "reason": f"ל-{provider} יש את הפעולה הזו, אבל החשבון אינו מחובר כאן."}
        return {"supported": True, "how": "api", "kind": op["kind"]}
    if entry == "browser":
        return {"supported": True, "how": "browser", "kind": op["kind"],
                "reason": "מבוצע דרך הדפדפן המחובר של הלשכה (אין API לרשם הזה).",
                "needs": "human" if op["kind"] in ("money",) else None}
    if provider == "registry":
        return {"supported": False, "needs": "other_provider",
                "reason": ("מהרישום הציבורי אפשר לקרוא תוקף וסטטוס, אבל לא לשנות דבר. "
                           "כדי לפעול — חבר את מי שמחזיק באזור או ברשומת הרישום.")}
    return {"supported": False, "needs": "other_provider",
            "reason": f"ל-{provider} אין את הפעולה הזו. אפשר לחבר ספק אחר שמחזיק באזור."}
