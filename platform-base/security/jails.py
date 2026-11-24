"""jails — the built-in fail2ban: evidence in, decisions out. No I/O; the app owns storage and the sensor
owns the kernel, so every rule here is a function of what it was fed and the clock it was given.

Three jails, each the industry's answer to one attack that reaches an office:

  scan   an address that collects failures (400/401/403/404/405) on what the office exposes without a
         sign-in — a public site, the link door, a host nobody routes — or asks for a path only a
         scanner asks for (/.env, /.git/, /wp-login.php …). The owner's own 404s inside his apps do not
         count: requests behind the sign-in are his.
  auth   failed sign-ins at the identity provider.
  sshd   failed SSH logins and pre-auth disconnects on the machine itself.

A decision bans for an hour, four times longer on every repeat (1 h, 4 h, 16 h, 2.7 d, then 7 days),
like fail2ban's `bantime.increment`. An address the office trusts (`allow`) is never decided against:
private ranges, the office's own addresses, the other offices of the herd, anyone who signed in
successfully, and what the owner allowed by hand.
"""
from __future__ import annotations

import re
from collections import deque

PROBE_PATHS = re.compile(
    r"(?i)(^/\.env|/\.git/|/\.svn/|/\.hg/|/\.aws/|/\.ssh/|/\.vscode/|/\.DS_Store|/wp-(login|admin|includes|content)|"
    r"/xmlrpc\.php|/phpmyadmin|/pma/|/myadmin|/cgi-bin/|/HNAP1|/boaform|/GponForm|/setup\.cgi|"
    r"/vendor/phpunit|/actuator|/server-status|/owa/|/autodiscover/|/solr/|/etc/passwd|\.\./\.\./|"
    r"/manager/html|/druid/|/telescope|/_ignition|/\.well-known/security\.txt\.bak|/config\.(json|php|yml)$|"
    r"/backup\.(zip|tar|sql)|/dump\.sql|/shell\b|/eval-stdin\.php|/cgi-mod/|/remote/login|/sslvpn)")
FAIL_STATUS = frozenset({400, 401, 403, 404, 405, 444})
SCAN_KINDS = frozenset({"none", "public", "door"})
#: A 404 on one of these is NOT a scan, and the list is deliberately this short (DGO-1597). A bare `/`
#: and the favicon are what every browser, every uptime checker and every search engine asks for on a
#: hostname it has never seen; nobody learned anything from the 404. Measured 2026-11-09 on Exampleu: four
#: AWS Oregon addresses (93.184.216.20, 93.184.216.21, 93.184.216.22, 93.184.216.23) each collected 20-24
#: `GET /` 404s on a name nobody routes, and the scan jail (12 failures in 10 minutes) would have banned
#: all four for asking a question the internet asks by itself. A 404 on any other path still counts: that
#: is somebody reading the answers.
INNOCENT_404 = frozenset({"/", "/favicon.ico", "/favicon.png", "/favicon.svg", "/apple-touch-icon.png",
                          "/apple-touch-icon-precomposed.png"})
#: …and this one is not even the caller's doing: the edge answers Let's Encrypt's validation from its own
#: router, and a 404 there is a certificate that has not been renewed yet. Only a 404 is forgiven, and a
#: path that walks up (`/…/../.env`) is not an ACME path at all — the second reader's point: an exemption
#: a scanner can hide behind is worse than none, and `edge.classify` already gives these their own kind,
#: which the jail does not count anyway.
NOT_OURS_PREFIXES = ("/.well-known/acme-challenge/",)

DEFAULT_RULES = {
    "scan": {"window": 600, "fails": 12, "probes": 3},
    "auth": {"window": 900, "fails": 5},
    "sshd": {"window": 600, "fails": 5},
}
BAN_BASE = 3600
BAN_MAX = 7 * 86400


def ban_seconds(offences: int) -> int:
    return int(min(BAN_BASE * (4 ** max(0, offences - 1)), BAN_MAX))


class Jails:
    def __init__(self, allow=lambda ip: False, rules: dict | None = None):
        self.allow = allow
        self.rules = {k: dict(v) for k, v in (rules or DEFAULT_RULES).items()}
        self.enabled = {k: True for k in self.rules}
        self._fails: dict = {}       # ip -> deque[ts]
        self._probes: dict = {}      # ip -> deque[(ts, path)]
        self._auth: dict = {}        # ip -> deque[(ts, user)]
        self._ssh: dict = {}         # ip -> deque[(ts, user)]

    # ── evidence ────────────────────────────────────────────────────────────────────────────────
    def feed_hit(self, h: dict) -> None:
        ip = h.get("ip") or ""
        if not ip or self.allow(ip):
            return
        ts = h.get("ts") or 0
        path = h.get("path") or ""
        if PROBE_PATHS.search(path):
            self._probes.setdefault(ip, deque(maxlen=64)).append((ts, path[:120]))
        status = int(h.get("status") or 0)
        # A 404 that answers «is anything here?» on a host nobody routes is the internet asking, not a
        # scan (DGO-1597); Let's Encrypt's validation is not even the caller's question. Everything else
        # on those kinds is evidence, exactly as before.
        bare = path.split("?", 1)[0]
        innocent = (status == 404 and bare in INNOCENT_404) or (
            status == 404 and bare.startswith(NOT_OURS_PREFIXES) and ".." not in bare)
        if h.get("kind") in SCAN_KINDS and status in FAIL_STATUS and not innocent:
            self._fails.setdefault(ip, deque(maxlen=256)).append(ts)

    def feed_auth(self, e: dict) -> None:
        ip = e.get("ip") or ""
        if e.get("action") != "login_failed" or not ip or self.allow(ip):
            return
        self._auth.setdefault(ip, deque(maxlen=64)).append((e.get("ts") or 0, e.get("user") or ""))

    def feed_ssh(self, e: dict) -> None:
        ip = e.get("ip") or ""
        if e.get("verdict") != "fail" or not ip or self.allow(ip):
            return
        self._ssh.setdefault(ip, deque(maxlen=64)).append((e.get("ts") or 0, e.get("user") or ""))

    # ── decisions ───────────────────────────────────────────────────────────────────────────────
    def decide(self, now: float) -> list:
        out = []
        r = self.rules
        if self.enabled.get("scan"):
            w = r["scan"]["window"]
            for ip in list(set(self._fails) | set(self._probes)):
                fails = [t for t in self._fails.get(ip, ()) if now - t <= w]
                probes = [(t, p) for t, p in self._probes.get(ip, ()) if now - t <= w]
                if self.allow(ip):
                    self._fails.pop(ip, None)
                    self._probes.pop(ip, None)
                    continue
                if len(fails) >= r["scan"]["fails"] or len(probes) >= r["scan"]["probes"]:
                    sample = ", ".join(sorted({p for _, p in probes})[:3])
                    out.append({"ip": ip, "jail": "scan", "count": max(len(fails), len(probes)),
                                "reason": f"{len(fails)} failures, {len(probes)} probe paths" + (f": {sample}" if sample else "")})
                    self._fails.pop(ip, None)
                    self._probes.pop(ip, None)
        for name, store in (("auth", self._auth), ("sshd", self._ssh)):
            if not self.enabled.get(name):
                continue
            w = r[name]["window"]
            for ip in list(store):
                recent = [(t, u) for t, u in store[ip] if now - t <= w]
                if self.allow(ip):
                    store.pop(ip, None)
                    continue
                if len(recent) >= r[name]["fails"]:
                    users = sorted({u for _, u in recent if u})[:3]
                    out.append({"ip": ip, "jail": name, "count": len(recent),
                                "reason": f"{len(recent)} failed sign-ins" + (f" as {', '.join(users)}" if users else "")})
                    store.pop(ip, None)
        self._trim(now)
        return out

    def _trim(self, now: float) -> None:
        horizon = max(v["window"] for v in self.rules.values()) * 2
        for store in (self._fails, self._probes, self._auth, self._ssh):
            for ip in list(store):
                q = store[ip]
                while q and (now - (q[0][0] if isinstance(q[0], tuple) else q[0])) > horizon:
                    q.popleft()
                if not q:
                    store.pop(ip, None)

    def watching(self, now: float) -> list:
        """Addresses with evidence that has not reached a decision yet — the screen's «במעקב»."""
        rows = []
        for ip in set(self._fails) | set(self._probes) | set(self._auth) | set(self._ssh):
            rows.append({"ip": ip,
                         "fails": len([t for t in self._fails.get(ip, ()) if now - t <= self.rules["scan"]["window"]]),
                         "probes": len([1 for t, _ in self._probes.get(ip, ()) if now - t <= self.rules["scan"]["window"]]),
                         "auth": len([1 for t, _ in self._auth.get(ip, ()) if now - t <= self.rules["auth"]["window"]]),
                         "ssh": len([1 for t, _ in self._ssh.get(ip, ()) if now - t <= self.rules["sshd"]["window"]])})
        return [r for r in rows if r["fails"] or r["probes"] or r["auth"] or r["ssh"]]
