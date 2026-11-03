#!/usr/bin/env python3
"""platform.manager.framecheck — may the console show this app INSIDE itself? Asked on enable and update (#63).

Why this exists
---------------
A window on an app that forbids being framed stays EMPTY: the browser draws its own grey page and tells the
page that framed it nothing (FPG, 2026-10-28: the services window). The console now asks at the click
(`/api/frame-check`, platform-base/console/app.py) and opens a tab instead of a dead window. This module asks
the same question EARLIER — when an app is switched on (app-management `_apply`) and when a rebuilt image
replaces a running one (`bbox update`, scripts/app-update.sh) — so the office learns it from the change that
caused it, not from a person staring at a blank window.

The verdict is the console's, verbatim (`frame_verdict` / `_csp_allows` below are copied from it, so the two
can never judge one answer differently): CSP `frame-ancestors`, when present, wins (browsers then ignore
X-Frame-Options) and must allow the console's origin — `'none'` never does, `'self'` only for the app's own
origin; otherwise X-Frame-Options DENY refuses, and SAMEORIGIN refuses unless the app IS the console's origin.

What is asked, and how it is judged (`targets`)
-----------------------------------------------
Only the routing entries the console FRAMES are enforced:
  * `external`  — a module with `external: true`: the shell frames the app on its own public host, so the
                  answer of that host is judged against the console's origin (cross-origin);
  * `embedded`  — a module with an alias that is not `embed: false`: the shell frames `/a/<alias>/`, which the
                  console PROXIES from the module's internal base (`module.url`, or the variable `url_env`
                  names) and passes the app's headers through — so that answer is judged as the console's own
                  origin (SAMEORIGIN and `'self'` pass there; DENY and `'none'` do not).
An app that opens in a TAB by design (`embed: false` and not external, or no module at all) is asked too and
the answer is RECORDED — a desktop window shows the console's tab card for it since #63 — but it is never
refused: a tab is exactly what its manifest asked for.

Fail-open, like the console: no answer, a timeout, a TLS/DNS failure, an answer of 400 or more, or a redirect
to ANOTHER origin (a sign-in page — the browser would judge that page, not the app) is `unknown` and passes.
Only addresses of this office are asked (the console's domain and the names under it, or a bare compose
service name that only resolves inside the office network); the body is never read.

The setting — FRAME_GATE in the office's .env (no code to change)
-----------------------------------------------------------------
  warn    (default) the verdict is recorded (data/platform/frame-checks.json, per app and version), logged, and
          returned to the caller; nothing is stopped.
  refuse  an enforced target that refuses makes the change fail with one sentence naming the header and the fix:
            · enable — the app is switched off again through the plane's own disable path (state, compile,
              containers, automations) — but ONLY when it was not enabled before this call: a re-apply never
              takes down an app that was already running;
            · update — the previous image is put back (the same path as an update that never gets healthy).
  off     nothing is asked or recorded.
`refuse` is a setting, not the default, on purpose: AGENTS.md rule 8 — a stricter contract lands as warn first,
and turns refuse only after a mechanical survey of every enabled app (`framecheck.py survey`).

Stdlib only: it runs on the host (`bbox update`) and inside app-management (which mounts the checkout at the
same path), and neither needs anything installed for it.

    python3 platform/manager/framecheck.py --selftest
    python3 platform/manager/framecheck.py check <app|service> [--phase enable|update] [--was-enabled] [--json]
    python3 platform/manager/framecheck.py survey [--json]       # every enabled app, nothing recorded
    python3 platform/manager/framecheck.py verdict <url>         # one address, judged against the console

Exit codes of `check`: 0 keep (ok / unknown / warn / off), 3 the gate refuses (FRAME_GATE=refuse), 2 usage.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit

#: the checkout this layer lives in — the host's, or the same path mounted into app-management
REPO = Path(__file__).resolve().parents[2]
MODES = ("off", "warn", "refuse")
DEFAULT_MODE = "warn"
RECORD = Path("data") / "platform" / "frame-checks.json"
TIMEOUT = float(os.environ.get("FRAMECHECK_TIMEOUT", "6"))
REFUSE_EXIT = 3


# ── the console's verdict, verbatim (platform-base/console/app.py, #63) ─────────────────────────────────────────
def _csp_allows(policy, console_origin, app_origin):
    """None when the policy says nothing about framing, else (allowed, the directive as written)."""
    for part in policy.split(";"):
        bits = part.strip().split()
        if not bits or bits[0].lower() != "frame-ancestors":
            continue
        srcs = [s for s in bits[1:]]
        said = "frame-ancestors " + " ".join(srcs)
        c = urlparse(console_origin)
        for s in srcs:
            low = s.lower()
            if low == "'none'":
                return False, said
            if low == "'self'":
                if console_origin == app_origin:
                    return True, said
                continue
            if low == "*":
                return True, said
            if low.endswith(":") and "/" not in low:              # a scheme source: `https:`
                if c.scheme == low[:-1]:
                    return True, said
                continue
            anyport = low.endswith(":*")
            src = low[:-2] if anyport else low
            src = src if "://" in src else f"{c.scheme}://{src}"
            sp = urlparse(src)
            if sp.scheme != c.scheme:
                continue
            host = sp.hostname or ""
            ch = c.hostname or ""
            if host.startswith("*."):
                if not ch.endswith(host[1:]):
                    continue
            elif host != ch:
                continue
            try:
                port = sp.port or {"http": 80, "https": 443}.get(sp.scheme)
            except ValueError:
                continue
            cport = c.port or {"http": 80, "https": 443}.get(c.scheme)
            if anyport or port == cport:
                return True, said
        return False, said
    return None


def frame_verdict(headers, console_origin, app_origin):
    """("ok" | "refused", why) for an app's response headers, as a browser judges them."""
    csp = [v for k, v in headers.items() if k.lower() == "content-security-policy"]
    for policy in csp:
        for one in policy.split(","):                   # several policies folded into one header
            got = _csp_allows(one, console_origin, app_origin)
            if got is not None and not got[0]:
                return "refused", "Content-Security-Policy: " + got[1]
    if any(_csp_allows(p, console_origin, app_origin) is not None for pol in csp for p in pol.split(",")):
        return "ok", ""
    xfo = next((v for k, v in headers.items() if k.lower() == "x-frame-options"), "").strip()
    first = xfo.split(",")[0].strip().upper()
    if first == "DENY":
        return "refused", "X-Frame-Options: " + xfo
    if first == "SAMEORIGIN" and console_origin != app_origin:
        return "refused", "X-Frame-Options: " + xfo
    return "ok", ""


# ── the office's own facts: .env, the console's origin, an app's addresses ──────────────────────────────────────
def env_value(name, repo=None, _depth=0):
    """One value of the office's configuration: the process environment, else the checkout's .env, with
    `${OTHER}` / `${OTHER:-default}` expanded the way compose does (the production file spells
    DEPLOYMENT_DOMAIN as `${COMPANY_SLUG}.${COMPANY_BASE_DOMAIN}`). "" when absent — never a guess."""
    if not name:
        return ""
    v = (os.environ.get(name) or "").strip()
    if not v:
        try:
            with open(Path(repo or REPO) / ".env", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(name + "="):
                        v = line[len(name) + 1:].strip().strip('"').strip("'")
                        break
        except OSError:
            v = ""
    if "${" in v and _depth < 5:
        v = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}",
                   lambda m: env_value(m.group(1), repo, _depth + 1) or (m.group(2) or ""), v)
    return v.strip()


def mode(repo=None):
    """FRAME_GATE: off | warn | refuse. Anything else reads as the default, warn (and says so)."""
    v = env_value("FRAME_GATE", repo).lower()
    return v if v in MODES else DEFAULT_MODE


def _is_localhost(v):
    h = re.sub(r"^https?://", "", v).split("/", 1)[0].rsplit(":", 1)[0].lower()
    return h == "localhost" or h.endswith(".localhost")


def _origin(value, proto_env="", repo=None):
    """`host[:port]` or a URL -> `scheme://host[:port]`; "" when it is not a browser address."""
    v = (value or "").strip()
    if not v:
        return ""
    if not v.startswith(("http://", "https://")):
        proto = env_value(proto_env, repo) if proto_env else ""
        if proto not in ("http", "https"):
            proto = "http" if _is_localhost(v) else "https"
        v = f"{proto}://{v}"
    u = urlsplit(v)
    return f"{u.scheme}://{u.netloc}" if u.netloc else ""


def console_origin(repo=None):
    """The origin the console is opened at — CONSOLE_BASE_URL (+ AUTH_PROTOCOL), else console.<domain>."""
    v = env_value("CONSOLE_BASE_URL", repo)
    if not v:
        dom = env_value("DEPLOYMENT_DOMAIN", repo) or env_value("COMPANY_BASE_DOMAIN", repo)
        v = f"console.{dom}" if dom else ""
    return _origin(v, "AUTH_PROTOCOL", repo)


def office_domain(console):
    """console.<domain> -> <domain> (the console's own rule, `_office_domain`); None for an address."""
    host = (urlsplit(console).hostname or "").lower()
    if not host or re.fullmatch(r"[0-9.]+|[0-9a-f:]+", host):
        return None
    return host.split(".", 1)[1] if "." in host else host


def base_url_env(app_id):
    """machine -> MACHINE_BASE_URL (the compiler's convention, reconcile.base_url_env)."""
    return app_id.upper().replace("-", "_") + "_BASE_URL"


def public_origin(app_id, host, base_env, repo=None):
    """Where an app's UI is reachable from a browser — app-management's `_public_origin`, the same order:
    the entry's own base-url variable -> <APP>_BASE_URL -> <host>.<DEPLOYMENT_DOMAIN> -> <host>.localhost."""
    for name in (base_env, base_url_env(app_id)):
        v = env_value(name, repo) if name else ""
        if v:
            return _origin(v, "", repo).rstrip("/")
    dom = env_value("DEPLOYMENT_DOMAIN", repo) or env_value("COMPANY_BASE_DOMAIN", repo)
    if dom and dom != "localhost":
        return f"https://{host}.{dom}"
    return f"http://{host}.localhost"


def targets(app_id, manifest, repo=None):
    """[{kind, url, enforced}] — every address of this app the console shows, and how it shows it."""
    out = []
    routing = [r for r in (manifest.get("routing") or []) if isinstance(r, dict)]
    with_module = [r for r in routing if r.get("module")]
    for r in with_module:
        m = r["module"] if isinstance(r["module"], dict) else {}
        sso_env = (r.get("sso") or {}).get("base_url_env")
        alias = m.get("alias")
        if m.get("external") and r.get("host"):
            # the host the shell frames (reconcile.external_origin): the app's own host variable
            var = sso_env or m.get("url_env") or base_url_env(app_id)
            val = env_value(var, repo)
            host = val.split("//", 1)[-1].split("/", 1)[0]
            if host and "." in host.split(":")[0]:
                origin = _origin(val, app_id.upper().replace("-", "_") + "_PROTOCOL", repo)
            else:
                origin = public_origin(app_id, r["host"], sso_env, repo)
            out.append({"kind": "external", "url": origin.rstrip("/") + "/", "enforced": True})
        elif alias and m.get("embed", True) is not False:
            base = env_value(m.get("url_env"), repo) or (m.get("url") or "")
            if base:
                out.append({"kind": "embedded", "url": base.rstrip("/") + "/", "enforced": True,
                            "alias": alias})
        elif r.get("host"):
            path = (m.get("url") or "").strip()
            origin = public_origin(app_id, r["host"], sso_env, repo)
            url = path if path.startswith(("http://", "https://")) else origin + "/" + path.lstrip("/")
            out.append({"kind": "tab", "url": url, "enforced": False})
    if not with_module and routing and routing[0].get("host"):
        r = routing[0]
        origin = public_origin(app_id, r["host"], (r.get("sso") or {}).get("base_url_env"), repo)
        out.append({"kind": "tab", "url": origin + "/", "enforced": False})
    return out


# ── asking: the answer's headers, never its body ────────────────────────────────────────────────────────────────
def _connect_map():
    """FRAMECHECK_CONNECT_TO="suffix=addr,…" — tests only: dial `addr` for hosts ending in `suffix`
    (curl's --connect-to); the Host header and the origin judged stay the URL's own."""
    out = []
    for part in (os.environ.get("FRAMECHECK_CONNECT_TO") or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out.append((k.strip().lower(), v.strip()))
    return out


def ask(url, timeout=None, hops=5):
    """(status, {header: value}, landed origin) of the first answer from the URL's OWN origin.

    Redirects are followed only while they stay on that origin; a redirect to another origin is returned
    as it is (its Location's origin as the landed one) and the caller calls it unknown. Duplicate headers
    are folded with ", " as the console's HTTP client folds them (frame_verdict splits folded policies)."""
    timeout = TIMEOUT if timeout is None else timeout
    start = urlsplit(url)
    home = f"{start.scheme}://{start.netloc}"
    for _ in range(hops + 1):
        u = urlsplit(url)
        host, port = u.hostname or "", u.port
        dial = host
        for suffix, addr in _connect_map():
            if host == suffix or host.endswith("." + suffix):
                dial = addr
        if u.scheme == "https":
            conn = http.client.HTTPSConnection(dial, port or 443, timeout=timeout,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(dial, port or 80, timeout=timeout)
        try:
            conn.putrequest("GET", (u.path or "/") + (("?" + u.query) if u.query else ""), skip_host=True,
                            skip_accept_encoding=True)
            conn.putheader("Host", u.netloc)
            conn.putheader("Accept", "text/html")
            conn.putheader("Sec-Fetch-Dest", "iframe")
            conn.putheader("User-Agent", "dgo-framecheck/1")
            conn.endheaders()
            r = conn.getresponse()
            folded = {}
            for k, v in r.getheaders():
                key = next((x for x in folded if x.lower() == k.lower()), k)
                folded[key] = (folded[key] + ", " + v) if key in folded else v
            status = r.status
        finally:
            conn.close()                                   # the body is never read
        loc = next((v for k, v in folded.items() if k.lower() == "location"), "")
        if status in (301, 302, 303, 307, 308) and loc:
            nxt = urljoin(url, loc)
            n = urlsplit(nxt)
            if f"{n.scheme}://{n.netloc}" != home:
                return status, folded, f"{n.scheme}://{n.netloc}"
            url = nxt
            continue
        return status, folded, home
    return status, folded, home


def _in_office(host, domain, kind):
    host = (host or "").lower()
    if not host:
        return False
    if kind == "embedded" and "." not in host:
        return True                       # a compose service name: it resolves inside the office network only
    return bool(domain) and (host == domain or host.endswith("." + domain))


def judge(target, console, domain, asker=None):
    """One target -> {kind, url, enforced, verdict: ok|refused|unknown, why, status}."""
    asker = asker or ask
    out = dict(target, verdict="unknown", why="", status=None)
    u = urlsplit(target["url"])
    if u.scheme not in ("http", "https") or not _in_office(u.hostname, domain, target["kind"]):
        out["why"] = "not an address of this office — not asked"
        return out
    if not console:
        out["why"] = "the console's address is not known here (CONSOLE_BASE_URL / DEPLOYMENT_DOMAIN)"
        return out
    try:
        status, headers, landed = asker(target["url"])
    except (OSError, http.client.HTTPException, ssl.SSLError, socket.timeout, ValueError) as e:
        out["why"] = f"no answer ({type(e).__name__})"
        return out
    out["status"] = status
    home = f"{u.scheme}://{u.netloc}"
    if landed != home:
        out["why"] = f"answered by {landed} (a sign-in or a redirect), not by the app — not judged"
        return out
    if status >= 400:
        out["why"] = f"answered {status} — not a page to judge"
        return out
    # an embedded app is framed THROUGH the console's proxy: the browser sees the console's own origin
    app_origin = console if target["kind"] == "embedded" else home
    verdict, why = frame_verdict(headers, console, app_origin)
    out.update(verdict=verdict, why=why)
    return out


# ── the gate: ask, record, decide ───────────────────────────────────────────────────────────────────────────────
def manifest_of(name, repo=None):
    """(app id, manifest) for an app id or one of its compose services; (None, None) when neither."""
    root = Path(repo or REPO)
    for base in ("apps", "platform-base"):
        p = root / base / name / "app.json"
        if p.is_file():
            try:
                return name, json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return name, None
    for base in ("apps", "platform-base"):
        for p in sorted((root / base).glob("*/app.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            compose = p.parent / ((m.get("compose") or "docker-compose.yml") if isinstance(m.get("compose"), str)
                                  else "docker-compose.yml")
            if name in _compose_services(compose):
                return m.get("id") or p.parent.name, m
    return None, None


def _compose_services(path):
    """Top-level service names of a compose file, without a YAML parser (two-space keys under `services:`)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return set()
    names, inside = set(), False
    for line in text.splitlines():
        if re.match(r"^services:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*(#.*)?$", line) if inside else None
        if m:
            names.add(m.group(1))
    return names


def check(app_id, manifest, phase="enable", repo=None, was_enabled=False, asker=None, gate_mode=None):
    """Ask every target of one app and decide. Returns the result (never raises for an app's answer):
    {app, version, phase, mode, console, at, targets, verdict, refuse, sentence}."""
    gate_mode = gate_mode or mode(repo)
    console = console_origin(repo)
    title = ((manifest or {}).get("title") or {})
    name = (title.get("en") or title.get("he") or app_id) if isinstance(title, dict) else str(title or app_id)
    res = {"app": app_id, "version": (manifest or {}).get("version"), "phase": phase, "mode": gate_mode,
           "console": console, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "targets": [], "verdict": "none", "refuse": False, "sentence": ""}
    if gate_mode == "off" or not manifest:
        return res
    domain = office_domain(console) if console else None
    res["targets"] = [judge(t, console, domain, asker) for t in targets(app_id, manifest, repo)]
    enforced = [t for t in res["targets"] if t["enforced"]]
    res["verdict"] = ("refused" if any(t["verdict"] == "refused" for t in enforced)
                      else "ok" if enforced and all(t["verdict"] == "ok" for t in enforced)
                      else "unknown" if enforced else "none")
    bad = next((t for t in enforced if t["verdict"] == "refused"), None)
    if bad:
        fix = (f"The fix is in the app: answer `Content-Security-Policy: frame-ancestors 'self' {console}` "
               f"and send no X-Frame-Options.")
        if gate_mode == "refuse" and (phase == "update" or not was_enabled):
            undo = "it was switched off again" if phase == "enable" else "the previous image was put back"
            res["refuse"] = True
            res["sentence"] = (f"«{name}» forbids being shown inside the office console ({bad['why']}) — {undo}. "
                               + fix)
        else:
            why_kept = ("FRAME_GATE=refuse, but it was already running before this change, so it was kept"
                        if gate_mode == "refuse" else "FRAME_GATE=warn: kept")
            res["sentence"] = (f"«{name}» forbids being shown inside the office console ({bad['why']}) — "
                               f"{why_kept}. " + fix)
    return res


def record(res, repo=None):
    """Keep the latest verdict per app (data/platform/frame-checks.json). A failed write never fails a change."""
    path = Path(repo or REPO) / RECORD
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        doc[res["app"]] = dict(res, targets=[dict(t, url=_shown(t["url"])) for t in res["targets"]])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _shown(url):
    """An address as it may be printed or recorded: never with a user or password in it."""
    u = urlsplit(url)
    return u._replace(netloc=u.netloc.rsplit("@", 1)[-1]).geturl() if "@" in u.netloc else url


def lines(res):
    """One line per target, for a log or a terminal."""
    out = []
    for t in res["targets"]:
        tail = f" — {t['why']}" if t["why"] else ""
        role = "" if t["enforced"] else " (opens in a tab: recorded, never refused)"
        out.append(f"frame-check {res['app']} [{t['kind']}] {_shown(t['url'])} -> {t['verdict']}{tail}{role}")
    if res["sentence"]:
        out.append(("REFUSED: " if res["refuse"] else "warning: ") + res["sentence"])
    return out


def gate(app_id, manifest, phase="enable", was_enabled=False, repo=None, asker=None):
    """What the enable/update hooks call: check, record, log. Returns the result (`refuse` decides)."""
    res = check(app_id, manifest, phase, repo, was_enabled, asker)
    if res["mode"] != "off" and res["targets"]:
        record(res, repo)
        for line in lines(res):
            print(line, flush=True)
    return res


# ── the selftest: a case table, no network ──────────────────────────────────────────────────────────────────────
def selftest():
    fails = []
    C, A = "https://console.office.test", "https://app.office.test"

    def eq(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    verdicts = [
        ("no header", {}, A, "ok"),
        ("XFO DENY", {"X-Frame-Options": "DENY"}, A, "refused"),
        ("XFO deny, lower case", {"x-frame-options": "deny"}, A, "refused"),
        ("XFO SAMEORIGIN, another origin", {"X-Frame-Options": "SAMEORIGIN"}, A, "refused"),
        ("XFO SAMEORIGIN, the console's own origin", {"X-Frame-Options": "SAMEORIGIN"}, C, "ok"),
        ("XFO ALLOW-FROM (obsolete, ignored)", {"X-Frame-Options": "ALLOW-FROM https://x"}, A, "ok"),
        ("CSP 'none'", {"Content-Security-Policy": "frame-ancestors 'none'"}, A, "refused"),
        ("CSP 'self', another origin", {"Content-Security-Policy": "frame-ancestors 'self'"}, A, "refused"),
        ("CSP 'self', same origin", {"Content-Security-Policy": "frame-ancestors 'self'"}, C, "ok"),
        ("CSP names the console, XFO DENY ignored",
         {"Content-Security-Policy": f"default-src 'self'; frame-ancestors 'self' {C}", "X-Frame-Options": "DENY"},
         A, "ok"),
        ("CSP wildcard host", {"Content-Security-Policy": "frame-ancestors https://*.office.test"}, A, "ok"),
        ("CSP scheme source https:", {"Content-Security-Policy": "frame-ancestors https:"}, A, "ok"),
        ("CSP scheme source http: for an https console", {"Content-Security-Policy": "frame-ancestors http:"}, A,
         "refused"),
        ("CSP host without scheme", {"Content-Security-Policy": "frame-ancestors console.office.test"}, A, "ok"),
        ("CSP another port", {"Content-Security-Policy": "frame-ancestors https://console.office.test:8443"}, A,
         "refused"),
        ("CSP any port", {"Content-Security-Policy": "frame-ancestors https://console.office.test:*"}, A, "ok"),
        ("CSP *", {"Content-Security-Policy": "frame-ancestors *"}, A, "ok"),
        ("CSP without frame-ancestors leaves XFO in charge",
         {"Content-Security-Policy": "default-src 'self'", "X-Frame-Options": "DENY"}, A, "refused"),
        ("two policies folded, one refuses",
         {"Content-Security-Policy": f"frame-ancestors {C}, frame-ancestors 'none'"}, A, "refused"),
    ]
    for name, headers, origin, want in verdicts:
        eq("verdict: " + name, frame_verdict(headers, C, origin)[0], want)
    eq("verdict: the refusing header is named", frame_verdict({"X-Frame-Options": "DENY"}, C, A)[1],
       "X-Frame-Options: DENY")
    eq("an address is never shown with its user and password", _shown("http://u:CHANGE_ME@svc:80/x"), "http://svc:80/x")

    # targets, from manifests alone (the environment gives the addresses)
    saved = {k: os.environ.get(k) for k in ("DEPLOYMENT_DOMAIN", "CONSOLE_BASE_URL", "AUTH_PROTOCOL",
                                             "PLANE_BASE_URL", "FRAME_GATE", "NOTES_BASE_URL")}
    try:
        os.environ.update(DEPLOYMENT_DOMAIN="office.test", CONSOLE_BASE_URL="console.office.test",
                          AUTH_PROTOCOL="https", PLANE_BASE_URL="plane.office.test")
        os.environ.pop("NOTES_BASE_URL", None)
        nowhere = Path(os.devnull).parent / "framecheck-no-such-repo"
        ext = {"routing": [{"host": "plane", "module": {"external": True, "alias": "plane", "url": "http://plane:80"}}]}
        emb = {"routing": [{"host": "notes", "module": {"alias": "notes", "url": "http://notes:8080"}}]}
        tab = {"routing": [{"host": "notes", "module": {"embed": False}}]}
        bare = {"routing": [{"host": "notes"}]}
        eq("targets: external = its own public host", targets("plane", ext, nowhere),
           [{"kind": "external", "url": "https://plane.office.test/", "enforced": True}])
        eq("targets: embedded = the proxy's internal base",
           [(t["kind"], t["url"], t["enforced"]) for t in targets("notes", emb, nowhere)],
           [("embedded", "http://notes:8080/", True)])
        eq("targets: embed:false = a tab, never enforced", targets("notes", tab, nowhere),
           [{"kind": "tab", "url": "https://notes.office.test/", "enforced": False}])
        eq("targets: no module = a tab", targets("notes", bare, nowhere),
           [{"kind": "tab", "url": "https://notes.office.test/", "enforced": False}])
        eq("targets: no routing = nothing to ask", targets("x", {}, nowhere), [])
        eq("console origin", console_origin(nowhere), "https://console.office.test")
        eq("office domain", office_domain("https://console.office.test"), "office.test")

        for raw, want in (("", "warn"), ("refuse", "refuse"), ("REFUSE", "refuse"), ("off", "off"),
                          ("nonsense", "warn")):
            os.environ["FRAME_GATE"] = raw
            eq(f"mode {raw!r}", mode(nowhere), want)

        asked = []

        def fake(answer):
            def asker(url):
                asked.append(url)
                return answer(url)
            return asker
        deny = fake(lambda url: (200, {"X-Frame-Options": "DENY"}, "https://plane.office.test"))
        os.environ["FRAME_GATE"] = "refuse"
        r = check("plane", ext, "enable", nowhere, was_enabled=False, asker=deny)
        eq("refuse: a first enable is refused", (r["verdict"], r["refuse"]), ("refused", True))
        eq("refuse: the sentence names the header and the fix",
           ("X-Frame-Options: DENY" in r["sentence"], "frame-ancestors 'self' https://console.office.test"
            in r["sentence"]), (True, True))
        r = check("plane", ext, "enable", nowhere, was_enabled=True, asker=deny)
        eq("refuse: an app that was already running is kept", (r["verdict"], r["refuse"]), ("refused", False))
        r = check("plane", ext, "update", nowhere, was_enabled=True, asker=deny)
        eq("refuse: an update is refused (the previous image goes back)", r["refuse"], True)
        r = check("notes", tab, "enable", nowhere, asker=fake(lambda url: (200, {"X-Frame-Options": "DENY"},
                                                                            "https://notes.office.test")))
        eq("refuse: a tab app is recorded, never refused",
           (r["targets"][0]["verdict"], r["verdict"], r["refuse"]), ("refused", "none", False))
        r = check("notes", emb, "enable", nowhere,
                  asker=fake(lambda url: (200, {"X-Frame-Options": "SAMEORIGIN"}, "http://notes:8080")))
        eq("embedded: SAMEORIGIN passes through the console's proxy", (r["verdict"], r["refuse"]), ("ok", False))
        r = check("plane", ext, "enable", nowhere,
                  asker=fake(lambda url: (302, {"Location": "https://auth.office.test/x"}, "https://auth.office.test")))
        eq("a sign-in redirect is unknown and passes", (r["verdict"], r["refuse"]), ("unknown", False))

        def boom(url):
            raise ConnectionRefusedError("down")
        r = check("plane", ext, "enable", nowhere, asker=boom)
        eq("no answer is unknown and passes", (r["verdict"], r["refuse"]), ("unknown", False))
        os.environ["FRAME_GATE"] = "warn"
        r = check("plane", ext, "enable", nowhere, asker=deny)
        eq("warn: recorded refused, nothing refused", (r["verdict"], r["refuse"], bool(r["sentence"])),
           ("refused", False, True))
        os.environ["FRAME_GATE"] = "off"
        n = len(asked)
        r = check("plane", ext, "enable", nowhere, asker=deny)
        eq("off: nothing asked", (len(asked) - n, r["targets"]), (0, []))
        os.environ["FRAME_GATE"] = "refuse"
        os.environ["PLANE_BASE_URL"] = "plane.elsewhere.test"
        n = len(asked)
        r = check("plane", ext, "enable", nowhere, asker=deny)
        eq("an address outside the office is never asked", (len(asked) - n, r["verdict"], r["refuse"]),
           (0, "unknown", False))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return fails


def _enabled_apps(repo):
    """App ids the state file calls enabled — a plain read (no YAML parser): `  <id>:` then `state: enabled`
    or `enabled: true` in its block. Used by `survey` only."""
    try:
        text = (Path(repo) / "platform.state.yaml").read_text(encoding="utf-8")
    except OSError:
        return []
    out, cur, inside = [], None, False
    for line in text.splitlines():
        if re.match(r"^apps:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m:
            cur = m.group(1)
            if re.search(r"\benabled\b(?!:)|state:\s*enabled|enabled:\s*true", m.group(2)):
                out.append(cur)
            continue
        if cur and re.search(r"^\s+(state:\s*enabled|enabled:\s*true)\s*$", line):
            out.append(cur)
    return sorted(set(out))


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    if args[0] == "--selftest":
        fails = selftest()
        for f in fails:
            print("FAIL", f)
        print("framecheck selftest: " + ("PASS" if not fails else f"{len(fails)} FAILED"))
        return 1 if fails else 0
    repo = REPO
    if "--repo" in args:
        i = args.index("--repo")
        repo = Path(args[i + 1])
        del args[i:i + 2]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args[0] == "verdict" and len(args) == 2:
        console = console_origin(repo)
        t = judge({"kind": "external", "url": args[1], "enforced": True}, console, office_domain(console))
        print(json.dumps(t, ensure_ascii=False) if as_json else f"{args[1]} -> {t['verdict']} {t['why']}".rstrip())
        return 0
    if args[0] == "survey":
        rows = []
        for aid in _enabled_apps(repo):
            _, m = manifest_of(aid, repo)
            if m:
                res = check(aid, m, "survey", repo, was_enabled=True, gate_mode="warn")
                rows.append(res)
                if not as_json:
                    for line in lines(res):
                        print(line)
        if as_json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if args[0] == "check" and len(args) >= 2:
        phase = "enable"
        if "--phase" in args:
            phase = args[args.index("--phase") + 1]
        was = "--was-enabled" in args
        aid, m = manifest_of(args[1], repo)
        if not aid or not m:
            print(f"frame-check {args[1]}: not an app (or one of its services) of this office — nothing to judge")
            return 0
        res = gate(aid, m, phase, was, repo)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif res["mode"] == "off":
            print(f"frame-check {aid}: FRAME_GATE=off — not asked")
        elif not res["targets"]:
            print(f"frame-check {aid}: nothing the console shows — nothing to judge")
        return REFUSE_EXIT if res["refuse"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
