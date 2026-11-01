"""sites.checks.security — is the SITE itself secure? (the machine it runs on is `computers`' job)

Scope, stated because a check that does not say what it does not look at is a check that gets
trusted for the wrong thing: this is the EXTERNAL posture — what any visitor on the internet can
see and reach. It does not read the site's source, does not log in, and does not exploit anything.
The questions are the ones that actually cost a small business its site:

  * is TLS valid today, and when does it expire (a cert that expires on a Sunday is an outage),
  * does plain http:// get upgraded,
  * are the browser's own protections switched on (HSTS, nosniff, frame policy, referrer policy),
  * is the server advertising its version,
  * is anything PRIVATE reachable — `.env`, `.git/config`, backups, listings, phpinfo, admin panels,
  * are cookies safe, is the page free of mixed content, does the server answer TRACE.

Every finding names its evidence and its fix, because "security: 3 warnings" has never fixed one.
"""
from __future__ import annotations

import re

from . import http as H

#: Paths whose reachability means a real leak, chosen for this office's stack (a git checkout
#: deployed by rsync, a Vite/Eleventy site, a WordPress-era leftover) — not a generic 10,000-line
#: wordlist, which would be a scan the owner cannot act on and a load on a site we own.
#:
#: (path, severity, title, signature). The SIGNATURE is what makes this check honest, and it is not
#: optional politeness: this office's live sites answer **200 with the homepage** for ANY unknown
#: path (a `try_files … /index.html` fallback), so "the path returned 200" is true of every path on
#: the internet — the first version of this check reported 13 leaks on a site that has none. A path
#: is exposed when its BODY is the thing it claims to be (`[core]` for a git config, `BEGIN …
#: PRIVATE KEY` for a key); where no signature is meaningful, it must at least differ from the
#: site's own not-found answer.
SENSITIVE_PATHS = [
    ("/.env", "error", "קובץ משתני הסביבה נגיש", r"(?m)^[A-Z][A-Z0-9_]{2,}="),
    ("/.git/config", "error", "מאגר הגיט של האתר נגיש", r"\[core\]"),
    ("/.git/HEAD", "error", "מאגר הגיט של האתר נגיש", r"^ref:\s+refs/"),
    ("/.svn/entries", "warn", "תיקיית SVN נגישה", r"(?m)^\d+\s*$"),
    ("/.DS_Store", "info", "קובץ Finder של macOS נגיש", r"Bud1"),
    ("/wp-config.php.bak", "error", "גיבוי קונפיגורציה של WordPress נגיש",
     r"DB_(NAME|PASSWORD|USER)"),
    ("/backup.zip", "error", "קובץ גיבוי נגיש", r"^PK"),
    ("/backup.sql", "error", "קובץ גיבוי נגיש", r"(?i)(INSERT INTO|CREATE TABLE|MySQL dump)"),
    ("/db.sql", "error", "קובץ גיבוי נגיש", r"(?i)(INSERT INTO|CREATE TABLE|MySQL dump)"),
    ("/phpinfo.php", "error", "phpinfo נגיש", r"(?i)(phpinfo\(\)|<title>\s*phpinfo)"),
    ("/server-status", "warn", "סטטוס השרת נגיש", r"(?i)(apache server status|server version)"),
    ("/docker-compose.yml", "error", "הגדרת הדוקר של האתר נגישה", r"(?m)^services:"),
    ("/site.meta.json", "info", "מטא-דאטה של האתר נגישה", r'"pattern"\s*:\s*"bina-site'),
    ("/package.json", "warn", "מניפסט הפרויקט נגיש", r'"name"\s*:'),
    ("/.ssh/id_rsa", "error", "מפתח פרטי נגיש", r"BEGIN [A-Z ]*PRIVATE KEY"),
    ("/admin/", "info", "עמוד ניהול נגיש (לוודא שהוא מוגן)", ""),
]

MIN_HSTS = 15552000            # six months — the floor the preload list and every guide agree on
CERT_WARN_DAYS = 30
CERT_ERROR_DAYS = 14


def run(site: dict, hosts: list[str] | None = None, deep: bool = True) -> dict:
    hosts = hosts or [h for h in (site.get("hosts") or []) if h]
    if not hosts:
        return {"check": "security", "state": "error", "summary": {"reason": "לא הוגדר שם אתר"},
                "findings": [H.finding("no_host", "error", "לא הוגדר דומיין לאתר",
                                       "לא ניתן לבדוק אבטחה של אתר בלי כתובת.",
                                       "הוסף דומיין לאתר.")]}
    host = hosts[0]
    findings: list[dict] = []
    summary: dict = {"host": host, "hosts": hosts}

    # ── TLS ─────────────────────────────────────────────────────────────────────────────────────
    tls = H.tls_info(host)
    summary["tls"] = {k: tls.get(k) for k in ("verified", "protocol", "cipher", "days_left",
                                              "error")}
    if tls.get("cert"):
        summary["tls"]["issuer"] = tls["cert"].get("issuer_cn")
        summary["tls"]["not_after"] = tls["cert"].get("not_after")
    if not tls.get("ok"):
        findings.append(H.finding(
            "tls_unreachable", "error", f"לא ניתן להשלים חיבור TLS ל-{host}",
            tls.get("error") or "החיבור נכשל.", "בדוק שהאתר פעיל ושה-TLS מוגדר בקצה."))
    elif not tls.get("verified"):
        findings.append(H.finding(
            "tls_untrusted", "error", "אישור ה-TLS אינו מאומת בדפדפן",
            f"הסיבה: {tls.get('error')}. האישור: {tls['cert'].get('subject_cn') if tls.get('cert') else '?'}",
            "חדש את האישור או תקן את השרשרת — דפדפנים יציגו אזהרה לכל גולש."))
    else:
        days = tls.get("days_left")
        findings.append(H.finding(
            "tls_valid", "ok", "אישור TLS תקף",
            f"מונפק על ידי {tls['cert'].get('issuer_cn')} · בתוקף עד {tls['cert'].get('not_after')}"
            + (f" · {days} ימים" if days is not None else "")))
        if days is not None and days <= CERT_ERROR_DAYS:
            findings.append(H.finding(
                "tls_expiring", "error", f"האישור פג בעוד {days} ימים",
                "חידוש אוטומטי לא עבד (ACME) או שהאישור ידני.",
                "חדש את האישור עכשיו, ובדוק שה-ACME של הקצה רץ."))
        elif days is not None and days <= CERT_WARN_DAYS:
            findings.append(H.finding(
                "tls_expiring_soon", "warn", f"האישור פג בעוד {days} ימים",
                "פחות מחודש.", "ודא שהחידוש האוטומטי של הקצה פעיל."))
    if tls.get("protocol") and tls["protocol"] in ("TLSv1", "TLSv1.1"):
        findings.append(H.finding("tls_old", "warn", f"הפרוטוקול הנתמך הוא {tls['protocol']}",
                                  "פרוטוקול מיושן ופגיע.",
                                  "אפשר TLS 1.2+ בלבד בקצה."))

    # ── HTTPS enforcement and the headers on the real page ───────────────────────────────────────
    https = H.fetch(f"https://{host}/")
    if not https.get("ok"):
        findings.append(H.finding("https_failed", "error", "האתר אינו עונה ב-HTTPS",
                                  https.get("error") or "", "בדוק את הקצה ואת הקונטיינר של האתר."))
        return _done(summary, findings)
    summary["status"] = https["status"]
    summary["ms"] = https["ms"]
    summary["server"] = https["headers"].get("server")
    h = https["headers"]

    plain = H.fetch(f"http://{host}/", follow=True)
    redirects_to_https = any((c.get("location") or "").startswith("https://")
                             for c in plain.get("chain") or [])
    summary["http_upgrade"] = bool(redirects_to_https)
    if not redirects_to_https:
        findings.append(H.finding(
            "no_https_redirect", "warn", "‏http:// אינו מופנה ל-https://",
            "הגולש נשאר בחיבור לא מוצפן, וכל מי שברשת יכול לקרוא אותו.",
            "הוסף הפניה 301 מ-http ל-https בקצה או בשרת."))

    hsts = h.get("strict-transport-security")
    summary["hsts"] = hsts
    if not hsts:
        findings.append(H.finding(
            "no_hsts", "warn", "חסר כותרת HSTS",
            "בלי Strict-Transport-Security הדפדפן ינסה שוב http בחיבור הבא.",
            "הוסף: Strict-Transport-Security: max-age=31536000; includeSubDomains"))
    else:
        m = re.search(r"max-age=(\d+)", hsts)
        if m and int(m.group(1)) < MIN_HSTS:
            findings.append(H.finding("weak_hsts", "warn", "HSTS עם תוקף קצר מדי",
                                      f"max-age={m.group(1)} (מומלץ ≥ {MIN_HSTS}).",
                                      "הגדל את max-age לשנה."))
        else:
            findings.append(H.finding("hsts_ok", "ok", "HSTS מוגדר", hsts))

    if h.get("x-content-type-options", "").lower() != "nosniff":
        findings.append(H.finding("no_nosniff", "warn", "חסר X-Content-Type-Options: nosniff",
                                  "הדפדפן עלול לפרש קובץ שהועלה כקוד.",
                                  "הוסף: X-Content-Type-Options: nosniff"))
    if not (h.get("x-frame-options") or "frame-ancestors" in (h.get("content-security-policy") or "")):
        findings.append(H.finding("no_frame_policy", "warn", "אין הגנה מפני שיבוץ האתר (clickjacking)",
                                  "לא הוגדר X-Frame-Options או frame-ancestors.",
                                  "הוסף: X-Frame-Options: SAMEORIGIN"))
    if not h.get("content-security-policy"):
        findings.append(H.finding("no_csp", "info", "לא הוגדר Content-Security-Policy",
                                  "CSP הוא שכבת ההגנה האחרונה מפני הזרקת סקריפטים.",
                                  "הוסף CSP מדורג (Report-Only תחילה) אחרי מיפוי המקורות."))
    if not h.get("referrer-policy"):
        findings.append(H.finding("no_referrer_policy", "info", "לא הוגדר Referrer-Policy",
                                  "כתובות פנימיות עלולות לדלוף לאתרים חיצוניים.",
                                  "הוסף: Referrer-Policy: strict-origin-when-cross-origin"))

    server = h.get("server") or ""
    if re.search(r"\d+\.\d+", server):
        findings.append(H.finding("server_version", "info", f"השרת מצהיר על גרסה ({server})",
                                  "חשיפת גרסה עוזרת לתוקף לבחור ניצול מתאים.",
                                  "הסתר את הגרסה (server_tokens off / הסתרת הכותרת בקצה)."))
    if h.get("x-powered-by"):
        findings.append(H.finding("powered_by", "info",
                                  f"השרת מצהיר על המנוע ({h['x-powered-by']})", "",
                                  "הסר את כותרת X-Powered-By."))

    # ── cookies on the entry page ───────────────────────────────────────────────────────────────
    bad_cookies = []
    for c in https.get("raw_headers", {}).get("Set-Cookie", []) if isinstance(
            https.get("raw_headers", {}).get("Set-Cookie"), list) else (
            [https["raw_headers"]["Set-Cookie"]] if https.get("raw_headers", {}).get("Set-Cookie")
            else []):
        low = c.lower()
        missing = [k for k in ("secure", "httponly") if k not in low]
        if missing:
            bad_cookies.append(f"{c.split('=')[0].strip()} (חסר: {', '.join(missing)})")
    if bad_cookies:
        findings.append(H.finding("cookie_flags", "warn", "עוגיות ללא דגלי אבטחה",
                                  "; ".join(bad_cookies[:5]),
                                  "הוסף Secure ו-HttpOnly לכל עוגייה."))
    summary["cookies"] = len(bad_cookies)

    # ── mixed content ───────────────────────────────────────────────────────────────────────────
    mixed = sorted(set(re.findall(r"""(?:src|href)=["'](http://[^"']+)["']""", https.get("text", ""))))
    mixed = [m for m in mixed if host not in m][:5]
    if mixed:
        findings.append(H.finding("mixed_content", "warn", "תוכן לא מוצפן בתוך עמוד HTTPS",
                                  ", ".join(mixed),
                                  "החלף את הכתובות ל-https או הורד את המשאב."))
    summary["mixed_content"] = len(mixed)

    # ── methods ─────────────────────────────────────────────────────────────────────────────────
    try:
        opt = H.session().request("OPTIONS", f"https://{host}/", timeout=15)
        allow = (opt.headers.get("allow") or "").upper()
        summary["allow"] = allow
        if "TRACE" in allow:
            findings.append(H.finding("trace_enabled", "error", "השרת מצהיר על TRACE",
                                      "TRACE מאפשר XST (גניבת עוגיות).",
                                      "השבת TRACE בשרת."))
    except Exception:                                        # noqa: BLE001
        pass

    # ── exposed paths (only when asked: it is the ONE noisy thing here) ──────────────────────────
    if deep:
        baseline = _not_found_baseline(host)
        summary["not_found"] = baseline
        exposed = []
        for path, sev, title, signature in SENSITIVE_PATHS:
            r = H.fetch(f"https://{host}{path}", timeout=12, follow=False)
            if not r.get("ok"):
                continue
            status = r.get("status")
            if status in (401, 403):
                if path in ("/admin/", "/server-status"):
                    findings.append(H.finding(f"protected:{path}", "ok", f"{path} מוגן",
                                              f"מחזיר {status}."))
                continue
            if status not in (200, 206) or not r.get("bytes"):
                continue
            body = r.get("text") or ""
            hit = bool(re.search(signature, body[:20000])) if signature else \
                not _same_as_not_found(r, baseline)
            if not hit:
                continue
            findings.append(H.finding(
                f"exposed:{path}", sev, title,
                f"{path} מחזיר {status} ({r.get('bytes')} בייט)"
                + (" ותוכנו תואם לקובץ אמיתי." if signature else " ושונה מדף ה„לא נמצא” של האתר."),
                "הסר את הקובץ מהאתר או חסום את הנתיב בשרת."))
            exposed.append(path)
        summary["exposed"] = exposed
        # directory listing on the root
        root = H.fetch(f"https://{host}/", timeout=15)
        if "Index of /" in (root.get("text") or "")[:4000]:
            findings.append(H.finding("dir_listing", "error", "השרת מציג רשימת קבצים",
                                      "autoindex פעיל — כל תוכן התיקייה קריא.",
                                      "השבת autoindex בשרת."))

    # ── the other hostnames this site answers on ────────────────────────────────────────────────
    for other in hosts[1:]:
        r = H.fetch(f"https://{other}/", timeout=15)
        summary.setdefault("alt_hosts", {})[other] = {
            "ok": r.get("ok"), "status": r.get("status"),
            "verified": (H.tls_info(other).get("verified") if "." in other else None),
            "error": r.get("error")}
        if not r.get("ok"):
            findings.append(H.finding(f"host_down:{other}", "warn", f"‏{other} אינו עונה",
                                      r.get("error") or "", "בדוק את ה-DNS ואת הקצה."))
    return _done(summary, findings)


def _not_found_baseline(host: str) -> dict:
    """What this site answers for a path that CANNOT exist. The control group of the path check.

    A site whose not-found answer is a 404 is easy; a site that answers 200 with its homepage for
    everything (this office has two) is the reason the baseline exists at all — without it, "any
    path answers 200" is a machine for producing false leaks.
    """
    probe = f"/bina-check-nonexistent-{abs(hash(host)) % 100000}"
    r = H.fetch(f"https://{host}{probe}", timeout=12, follow=False)
    return {"path": probe, "status": r.get("status"), "bytes": r.get("bytes"),
            "content_type": (r.get("headers") or {}).get("content-type"),
            "ok": bool(r.get("ok"))}


def _same_as_not_found(r: dict, baseline: dict) -> bool:
    """Is this response indistinguishable from the site's own not-found page?"""
    if not baseline.get("ok") or baseline.get("status") != r.get("status"):
        return False
    b, n = baseline.get("bytes") or 0, r.get("bytes") or 0
    if b and abs(n - b) <= max(64, b * 0.02):
        return True
    return False


def _done(summary: dict, findings: list[dict]) -> dict:
    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    summary.update({"errors": errors, "warnings": warns,
                    "checks": len(findings)})
    return {"check": "security", "summary": summary, "findings": findings,
            "state": "error" if errors else ("warn" if warns else "ok")}
