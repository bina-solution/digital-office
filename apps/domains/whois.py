"""domains.whois — what the REGISTRY says, with no credentials at all.

This is the layer that makes the app useful before anybody connects an API, and it is why the office's
own registrar (Internic, which publishes no API whatsoever — verified 2026-09-23) is still a
first-class citizen here:

  * `.co.il` and the other `.il` namespaces are served by ISOC-IL's WHOIS on **port 43**, and their
    own policy keeps the **expiry date, the nameservers and the managing registrar** public (the 2026
    policy update removed contact details, not those). No key, no account, no rate agreement.
  * everywhere else, RDAP is the modern replacement for WHOIS and IANA publishes the bootstrap file
    that says which server answers for which TLD, so the same code covers the rest of the world.

One rule is honoured everywhere in this file: **WHOIS is a shared public service**. Its own banner
forbids high-volume automated querying, so the office asks only about domains it has declared it
watches, at most a few times a day (registry.due_for_whois), and never in a loop over a TLD.
"""
from __future__ import annotations

import json
import logging
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

log = logging.getLogger("domains.whois")

ISOC_WHOIS = ("whois.isoc.org.il", 43)
IANA_WHOIS = ("whois.iana.org", 43)
RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
TIMEOUT = 15
_bootstrap_cache: dict = {"at": 0, "data": None}


class WhoisError(Exception):
    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


# ── port 43 ──────────────────────────────────────────────────────────────────────────────────────
def query(server: str, port: int, domain: str, timeout: int = TIMEOUT) -> str:
    try:
        with socket.create_connection((server, port), timeout=timeout) as s:
            s.sendall((domain + "\r\n").encode("ascii", "ignore"))
            chunks = []
            while True:
                data = s.recv(4096)
                if not data:
                    break
                chunks.append(data)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as e:
        raise WhoisError(f"לא ניתן לשאול את {server}", detail=str(e)) from e


def _referral(text: str) -> str | None:
    m = re.search(r"(?im)^\s*(?:refer|whois server|registrar whois server)\s*:\s*(\S+)", text)
    return m.group(1).strip() if m else None


# ── the parsers ──────────────────────────────────────────────────────────────────────────────────
DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%Y.%m.%d", "%d/%m/%Y",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%d-%b-%Y")


def parse_date(raw: str | None) -> int | None:
    """The registry's own spelling → epoch. `06-02-2028` is day-month-year in the `.il` registry, and
    reading it as month-day silently turns an expiry into a different day — which for a date whose
    whole purpose is "renew before this" is the one mistake that matters."""
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", text)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        try:
            return int(datetime(y, mo, d, tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    return None


def parse_isoc(text: str) -> dict:
    """ISOC-IL's answer → the office's shape. Field names come from the registry's own output:
    `validity: 06-02-2028`, `status: Transfer Locked`, `nameservers:` with an indented list."""
    out: dict = {"raw_len": len(text or ""), "nameservers": []}
    if not text or "not found" in text.lower() or "no entries found" in text.lower():
        out["found"] = False
        return out
    out["found"] = True

    def field(*names):
        for n in names:
            m = re.search(rf"(?im)^\s*{n}\s*:\s*(.+?)\s*$", text)
            if m:
                return m.group(1).strip()
        return None

    out["expiry"] = parse_date(field("validity", "expiry date", "expiration date", "renewal date"))
    out["registered"] = parse_date(field("assigned", "creation date", "registered"))
    out["status"] = field("status")
    out["registrar"] = field("registrar", "registrar name", "sponsoring registrar")
    out["domain"] = field("domain", "domain name")
    ns_block = re.search(r"(?ims)^\s*nameservers?\s*:\s*\n?((?:\s+\S+.*\n?)+)", text)
    if ns_block:
        out["nameservers"] = [l.strip().split()[0].lower()
                              for l in ns_block.group(1).splitlines() if l.strip()]
    if not out["nameservers"]:
        out["nameservers"] = [m.group(1).lower().rstrip(".")
                              for m in re.finditer(r"(?im)^\s*nserver\s*:\s*(\S+)", text)]
    return out


def parse_key_value(text: str) -> dict:
    """A generic WHOIS answer → the same shape. Registries disagree about everything except that
    `Key: value` lines exist, so this is what covers the TLDs nobody here has met yet."""
    out: dict = {"nameservers": [], "found": "no match" not in (text or "").lower()}
    fields = {}
    for line in (text or "").splitlines():
        if ":" in line and not line.startswith((" ", "\t", "%", "#")):
            k, _, v = line.partition(":")
            fields.setdefault(k.strip().lower(), v.strip())
    for k in ("registrar", "sponsoring registrar", "registrar name"):
        if fields.get(k):
            out["registrar"] = fields[k]
            break
    for k in ("registry expiry date", "expiry date", "expiration date", "paid-till", "renewal date",
              "registrar registration expiration date"):
        if fields.get(k):
            out["expiry"] = parse_date(fields[k])
            break
    for k in ("creation date", "created", "registered on", "registered"):
        if fields.get(k):
            out["registered"] = parse_date(fields[k])
            break
    out["status"] = fields.get("domain status") or fields.get("status")
    out["nameservers"] = sorted({v.strip().lower().rstrip(".")
                                 for k, v in fields.items() if k == "nserver" and v})
    return out


def lookup(domain: str) -> dict:
    """Ask the right registry about one domain. Never raises for "not found" — that is an answer."""
    domain = domain.strip().lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]{3,253}", domain):
        raise WhoisError("שם דומיין לא תקין")
    if domain.endswith(".il"):
        text = query(*ISOC_WHOIS, domain)
        parsed = parse_isoc(text)
        parsed.update({"source": "whois.isoc.org.il", "whois": text[:4000]})
        return parsed
    # everything else: ask IANA who is authoritative, then that server (and one referral hop)
    try:
        iana = query(*IANA_WHOIS, domain.split(".")[-1])
        server = _referral(iana)
    except WhoisError:
        server = None
    text = ""
    if server:
        try:
            text = query(server, 43, domain)
            hop = _referral(text)
            if hop and hop != server and "Registrar WHOIS Server" in text:
                text = query(hop, 43, domain) or text
        except WhoisError:
            text = ""
    if not text:
        rdap = rdap_lookup(domain)
        if rdap:
            return rdap
        raise WhoisError("לא הצלחתי לקבל מידע על הדומיין מהרשם")
    parsed = parse_key_value(text)
    parsed.update({"source": f"whois:{server}", "whois": text[:4000]})
    return parsed


# ── RDAP (the JSON successor, for the TLDs that have it) ─────────────────────────────────────────
def _rdap_base(tld: str) -> str | None:
    if _bootstrap_cache["data"] is None or time.time() - _bootstrap_cache["at"] > 86400:
        try:
            r = requests.get(RDAP_BOOTSTRAP, timeout=TIMEOUT)
            r.raise_for_status()
            _bootstrap_cache.update({"at": time.time(), "data": r.json()})
        except (requests.RequestException, ValueError):
            return None
    data = _bootstrap_cache["data"] or {}
    for services in data.get("services", []):
        if len(services) >= 2 and tld in services[0]:
            urls = services[1]
            return urls[0] if urls else None
    return None


def rdap_lookup(domain: str) -> dict | None:
    base = _rdap_base(domain.rsplit(".", 1)[-1])
    if not base:
        return None
    try:
        r = requests.get(f"{base.rstrip('/')}/domain/{quote(domain)}", timeout=TIMEOUT,
                         headers={"accept": "application/rdap+json"})
        if r.status_code == 404:
            return {"found": False, "source": "rdap", "nameservers": []}
        r.raise_for_status()
        d = r.json()
    except (requests.RequestException, ValueError):
        return None
    out = {"found": True, "source": f"rdap:{base}", "nameservers": []}
    for ev in d.get("events", []) or []:
        action = (ev.get("eventAction") or "").lower()
        if action in ("expiration", "expiry"):
            out["expiry"] = parse_date(ev.get("eventDate"))
        elif action in ("registration", "registered"):
            out["registered"] = parse_date(ev.get("eventDate"))
    for ent in d.get("entities", []) or []:
        if "registrar" in (ent.get("roles") or []):
            for item in ent.get("vcardArray", [[], []])[1]:
                if item and item[0] == "fn":
                    out["registrar"] = item[3]
    out["nameservers"] = sorted({(n.get("ldhName") or "").lower().rstrip(".")
                                 for n in d.get("nameservers", []) or []} - {""})
    out["status"] = ", ".join(d.get("status", []) or []) or None
    out["rdap"] = json.dumps(d)[:3000]
    return out
