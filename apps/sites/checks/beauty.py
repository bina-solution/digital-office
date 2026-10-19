"""sites.checks.beauty — the owner's own beauty score, measured on the live site.

`beautiful-score` (github.com/solomonBoltin/beautiful) scores PIXELS with explicit formulas — so the
only honest input is a real render, and the only honest place to render is a container that has a
browser. That container is `sites-render` (see render_server.py) and this module is the client.

Two things make this more than a number:

  * **three viewports, never an average.** desktop/tablet/mobile are scored separately because a page
    that is composed on a laptop and cramped on a phone is a broken page, and averaging 90 and 48
    into "69" hides exactly the thing worth knowing. The run records the worst viewport's score as
    the site's score and names it.
  * **the DOM rules are findings, not footnotes.** When a page is rendered, `beautiful` also runs 44
    rules the DOM can answer — contrast under 4.5:1, a touch target under 24 px, a toggle that
    reveals nothing, text clipped by its box. They arrive inside `hints` marked `[error, mobile]`,
    and they are the half of the lint that is a defect rather than a taste, so each one becomes a
    finding with its own severity.
"""
from __future__ import annotations

import os
import re

import requests

from . import http as H

RENDER_URL = os.environ.get("SITES_RENDER_URL", "http://sites-render:8981").rstrip("/")
TIMEOUT = int(os.environ.get("SITES_RENDER_TIMEOUT", "300"))
DEFAULT_MIN = int(os.environ.get("SITES_BEAUTY_MIN", "70"))
VIEWPORTS = ("desktop", "tablet", "mobile")
_HINT_RULE = re.compile(r"^(?P<rule>[^\[\]]+?)\s*\[(?P<level>error|warning|note)[,\]]")


def run(site: dict, min_score: int | None = None, viewports: list[str] | None = None,
        mode: str = "ui") -> dict:
    hosts = [h for h in (site.get("hosts") or []) if h]
    if not hosts:
        return {"check": "beauty", "state": "error", "summary": {"reason": "לא הוגדר שם אתר"},
                "findings": [H.finding("no_host", "error", "לא הוגדר דומיין לאתר", "", "")]}
    url = f"https://{hosts[0]}/"
    min_score = int(min_score or (site.get("checks") or {}).get("beauty_min") or DEFAULT_MIN)
    viewports = viewports or list(VIEWPORTS)
    payload = {"url": url, "viewports": viewports, "mode": mode, "site": site["id"],
               "components": True}
    try:
        r = requests.post(f"{RENDER_URL}/score", json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        return _unavailable("שירות הרינדור אינו זמין")
    if r.status_code >= 300:
        try:
            detail = (r.json() or {}).get("error")
        except ValueError:
            detail = r.text[:200]
        if r.status_code == 503:
            return _unavailable(detail or "שירות הרינדור אינו מוכן")
        return {"check": "beauty", "state": "error",
                "summary": {"url": url, "error": detail},
                "findings": [H.finding("render_failed", "error", "הרינדור של האתר נכשל",
                                       detail or f"HTTP {r.status_code}",
                                       "בדוק שהאתר נטען בדפדפן ושאינו חוסם בוטים.")]}
    body = r.json() or {}
    pages = body.get("pages") or []
    findings: list[dict] = []
    scores: dict[str, int] = {}
    for p in pages:
        vp = p.get("viewport") or "?"
        score = p.get("score")
        if score is None:
            continue
        scores[vp] = score
        sev = "ok" if score >= min_score else ("warn" if score >= min_score - 20 else "error")
        detail = (f"ציון {score}/100 ב-{vp} (מודל {p.get('mode')}"
                  f"{', קלאסי ' + str(p.get('classic')) if p.get('classic') else ''}). "
                  f"{_weakest_factors(p.get('factors') or {})}")
        findings.append(H.finding(f"score:{vp}", sev, f"ציון יופי ב-{vp}: {score}", detail,
                                  "ראה ההצעות למטה — כל הצעה היא שינוי קונקרטי בעמוד.", url))
        for h in (p.get("hints") or [])[:12]:
            m = _HINT_RULE.match(h)
            if m:
                level = {"error": "error", "warning": "warn", "note": "info"}[m.group("level")]
                rule = m.group("rule").strip()
            else:
                level, rule = "info", (h.split(" (", 1)[0].strip() or "hint")
            findings.append(H.finding(f"rule:{rule}:{vp}", level, f"{rule} — {vp}",
                                      h, "", url))
        for pen in (p.get("penalties") or []):
            # A penalty arrives as a STRING in the pinned release ("overflow: …") and as an object
            # with `kind`/`detail` on the project's main branch. Both are handled because both are
            # real: the version installed here is the version the numbers came from, and a beauty
            # check that crashes on its own penalty list is worse than one that misses a nuance.
            if isinstance(pen, dict):
                kind = str(pen.get("kind") or "penalty")
                detail = str(pen.get("detail") or pen)
            else:
                kind = (str(pen).split(":", 1)[0].strip() or "penalty")[:40]
                detail = str(pen)
            findings.append(H.finding(f"penalty:{kind}:{vp}", "error",
                                      f"פגם: {kind} — {vp}", detail, "", url))
        comps = p.get("components") or []
        weak = sorted(comps, key=lambda c: c.get("score") or 100)[:5]
        for c in weak:
            if (c.get("score") or 100) < 60:
                findings.append(H.finding(f"component:{c.get('key')}:{vp}", "info",
                                          f"רכיב חלש: {c.get('key')} ({c.get('score')})",
                                          (c.get("hints") or [""])[0], "", url))
    if not scores:
        return {"check": "beauty", "state": "error",
                "summary": {"url": url, "error": "לא התקבל ציון מאף viewport"},
                "findings": [H.finding("no_score", "error", "לא התקבל ציון יופי",
                                       "הרינדור החזיר דפים בלי ציון.",
                                       "בדוק את לוג שירות הרינדור.")]}
    worst_vp = min(scores, key=lambda k: scores[k])
    summary = {"url": url, "scores": scores, "worst": scores[worst_vp], "worst_viewport": worst_vp,
               "min": min_score, "mode": body.get("mode"), "backend": body.get("backend"),
               "beautiful": body.get("beautiful"), "seconds": body.get("seconds"),
               "run": body.get("run"), "screenshots": body.get("screenshots") or [],
               "views": [{"viewport": p.get("viewport"), "score": p.get("score"),
                          "classic": p.get("classic"), "factors": p.get("factors"),
                          "screenshot": p.get("screenshot"),
                          "components": (p.get("components") or [])[:12]} for p in pages],
               "errors": sum(1 for f in findings if f["severity"] == "error"),
               "warnings": sum(1 for f in findings if f["severity"] == "warn")}
    state = ("error" if summary["errors"] else "warn" if summary["warnings"] else "ok")
    return {"check": "beauty", "summary": summary, "findings": findings, "state": state}


def _weakest_factors(factors: dict) -> str:
    if not factors:
        return ""
    weak = sorted(((k, v) for k, v in factors.items() if isinstance(v, (int, float))),
                  key=lambda kv: kv[1])[:3]
    return "הגורמים החלשים: " + ", ".join(f"{k} {v:.2f}" for k, v in weak)


def _unavailable(reason: str) -> dict:
    """Not a site finding at all — the RENDERER is down, and saying "the site got 0" would be a lie
    the owner would chase in the wrong place."""
    return {"check": "beauty", "state": "error", "summary": {"unavailable": reason},
            "findings": [H.finding("renderer_unavailable", "warn",
                                   "סריקת היופי לא רצה — שירות הרינדור אינו זמין", reason,
                                   "ודא שהקונטיינר sites-render בריא (docker logs sites-render).")]}
