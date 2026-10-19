"""sites.checks.uptime — the one check that runs every minute, and it must not be clever.

An uptime probe answers one question: did the site answer a real HTTP request, from OUTSIDE, just
now. So it is a plain GET over the public hostname — not a TCP connect, not a container inspect, not
"is the process running". Every one of those cheaper signals stays green while the site serves a 502,
and the owner's phone is the thing that then tells them.

"Up" is `status < 400` after following redirects, so a site that redirects http→https and answers
200 is up, and a site answering 500 is not. The reason a check failed is recorded verbatim: the
difference between "DNS does not resolve", "the certificate is expired" and "the origin returned
500" is the entire value of the log.
"""
from __future__ import annotations

from . import http as H


def probe(site: dict, url: str | None = None, timeout: int = 20) -> dict:
    hosts = [h for h in (site.get("hosts") or []) if h]
    target = url or (f"https://{hosts[0]}/" if hosts else "")
    if not target:
        return {"ok": False, "url": "", "error": "לא הוגדר דומיין לאתר", "status": None, "ms": None}
    r = H.fetch(target, timeout=timeout, follow=True)
    if not r.get("ok"):
        return {"ok": False, "url": target, "error": r.get("error"), "status": None,
                "ms": r.get("ms"), "chain": r.get("chain") or []}
    return {"ok": (r.get("status") or 0) < 400, "url": target, "status": r.get("status"),
            "ms": r.get("ms"), "bytes": r.get("bytes"),
            "redirects": max(0, len(r.get("chain") or []) - 1),
            "error": None if (r.get("status") or 0) < 400 else f"האתר החזיר {r.get('status')}"}


def probe_host(site: dict, host: str, timeout: int = 15) -> dict:
    scheme = "https" if "." in host else "http"
    out = probe(site, url=f"{scheme}://{host}/", timeout=timeout)
    out["host"] = host
    return out


def reason(sample: dict) -> str:
    if sample.get("ok"):
        return ""
    return sample.get("error") or f"האתר לא ענה (HTTP {sample.get('status')})"
