"""sites.checks.http — the one HTTP client the checks share, and the TLS facts they need.

The site's own answer is the only evidence any check here may use: no check may conclude anything
from the office's config, and none of them trusts the last run. Two details are worth stating
because they are the difference between a useful scan and a decorative one:

* **redirects are walked by hand.** `requests`' automatic following hides the chain, and the chain
  is the finding ("http:// never reaches https://", "www and the apex serve two different sites").
* **a certificate is inspected even when it does not verify.** `verified: false` and "the handshake
  failed" are different failures with different fixes, and only an unverified retry can tell them
  apart — the retry is never used to fetch content.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from datetime import datetime, timezone

import requests

UA = "BinaOfficeSites/1.0 (+digital office site checks)"
DEFAULT_TIMEOUT = 20
MAX_HOPS = 6


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"})
    return s


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT, follow: bool = True,
          session_: requests.Session | None = None) -> dict:
    """GET a URL, recording the redirect chain, the final response and the wall time.

    Never raises for an HTTP status — a 404 is an answer. Raises nothing at all, in fact: the error
    is returned in `error`, because every caller here is a checker whose job is to report.
    """
    s = session_ or session()
    chain: list[dict] = []
    started = time.time()
    try:
        for _ in range(MAX_HOPS):
            r = s.get(url, timeout=timeout, allow_redirects=False, verify=True)
            chain.append({"url": url, "status": r.status_code,
                          "location": r.headers.get("location")})
            if follow and r.is_redirect and r.headers.get("location"):
                url = requests.compat.urljoin(url, r.headers["location"])
                continue
            body = r.content[:400_000] if r.status_code < 400 or r.status_code == 404 else b""
            return {"ok": True, "url": url, "status": r.status_code,
                    "headers": {k.lower(): v for k, v in r.headers.items()},
                    "raw_headers": dict(r.headers), "text": _decode(body, r),
                    "bytes": len(r.content), "chain": chain,
                    "ms": int((time.time() - started) * 1000), "error": None,
                    "final_url": r.url}
        return {"ok": False, "error": "too many redirects", "chain": chain, "status": None,
                "ms": int((time.time() - started) * 1000), "headers": {}, "text": ""}
    except requests.RequestException as e:
        return {"ok": False, "error": _err(e), "error_kind": type(e).__name__, "chain": chain,
                "status": None, "ms": int((time.time() - started) * 1000), "headers": {}, "text": ""}


def _decode(body: bytes, r: requests.Response) -> str:
    """Bytes → text, and the encoding is NOT taken on trust.

    `requests` falls back to ISO-8859-1 for any `text/*` response whose Content-Type carries no
    charset — and a static file server very often sends exactly `Content-Type: text/html`. Taking that
    default turns every Hebrew page into mojibake, and the SEO check then reports titles nobody can
    read. So: the header's charset if it names one, else the page's own `<meta charset>`, else UTF-8,
    which is what every site this office runs actually is.
    """
    enc = (r.encoding or "").lower()
    if not enc or enc in ("iso-8859-1", "latin-1", "ascii"):
        m = re.search(rb"""charset=["']?([A-Za-z0-9_:-]+)""", body[:4096])
        enc = m.group(1).decode("ascii", "replace").lower() if m else "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except (LookupError, TypeError):
        return body.decode("utf-8", errors="replace")


def _err(e: Exception) -> str:
    """A sentence the owner can act on. `requests` says 'HTTPSConnectionPool(host=…, port=443): Max
    retries exceeded … SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] …')' — every
    word true and none of it a next step."""
    text = str(e)
    if "CERTIFICATE_VERIFY_FAILED" in text or "SSLCertVerificationError" in text:
        return "אישור ה-TLS אינו תקף (פג תוקף / שם לא תואם / שרשרת חסרה)"
    if "Name or service not known" in text or "getaddrinfo" in text:
        return "השם אינו נפתר ב-DNS"
    if "Connection refused" in text:
        return "החיבור נדחה — אין שירות בפורט"
    if "timed out" in text or "Timeout" in text:
        return "השרת לא ענה בזמן"
    if "SSLError" in text:
        return "כשל ב-TLS"
    return text.split("(")[0][:200] or type(e).__name__


def tls_info(host: str, port: int = 443, timeout: int = 12) -> dict:
    """The certificate and the negotiated protocol/cipher, as a real client would see them.

    Verified first. If verification fails, ONE unverified handshake is made to read the certificate
    so the finding can say WHAT is wrong (expired? wrong name? self-signed? incomplete chain?)
    instead of only that something is.
    """
    out = {"host": host, "port": port, "verified": False, "ok": False, "error": None,
           "protocol": None, "cipher": None, "cert": None, "days_left": None}
    for verify in (True, False):
        ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ss:
                    der = ss.getpeercert()
                    out.update({
                        "ok": True, "verified": verify,
                        "protocol": ss.version(), "cipher": (ss.cipher() or [None])[0],
                        "cert": _cert_summary(der),
                    })
                    try:
                        ts = ssl.cert_time_to_seconds(der.get("notAfter", ""))
                        out["days_left"] = int((ts - time.time()) / 86400)
                    except (ValueError, TypeError):
                        pass
                    return out
        except ssl.SSLCertVerificationError as e:
            out["error"] = _verify_reason(e)
            continue
        except (ssl.SSLError, socket.timeout, OSError) as e:
            out["error"] = _err(e)
            return out
    return out


def _verify_reason(e: ssl.SSLCertVerificationError) -> str:
    text = str(e)
    if "certificate has expired" in text:
        return "האישור פג תוקף"
    if "Hostname mismatch" in text or "doesn't match" in text:
        return "האישור אינו מכסה את השם הזה"
    if "self-signed" in text or "self signed" in text:
        return "האישור חתום עצמית"
    if "unable to get local issuer" in text:
        return "שרשרת האישורים חסרה (לא ניתן לאמת מול רשות)"
    return "אישור TLS לא תקף"


def _cert_summary(der) -> dict | None:
    if not der:
        return None
    subject = {k: v for pair in der.get("subject", ()) for k, v in pair}
    issuer = {k: v for pair in der.get("issuer", ()) for k, v in pair}
    sans = [v for t, v in der.get("subjectAltName", ()) if t == "DNS"]
    return {"subject": subject, "issuer": issuer, "not_before": der.get("notBefore"),
            "not_after": der.get("notAfter"), "sans": sans[:40],
            "issuer_cn": issuer.get("commonName"), "subject_cn": subject.get("commonName")}


def resolve(host: str) -> dict:
    """A/AAAA records, from the office's own resolver — what DNS says, not what the site claims."""
    import socket as _s
    out = {"host": host, "a": [], "aaaa": [], "error": None}
    try:
        for fam, key in ((_s.AF_INET, "a"), (_s.AF_INET6, "aaaa")):
            try:
                out[key] = sorted({ai[4][0] for ai in _s.getaddrinfo(host, None, fam)})
            except _s.gaierror:
                pass
    except OSError as e:
        out["error"] = _err(e)
    return out


def http_date(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")


def finding(code: str, severity: str, title: str, detail: str = "", fix: str = "",
            url: str = "") -> dict:
    return {"code": code, "severity": severity, "title": title, "detail": detail, "fix": fix,
            "url": url}
