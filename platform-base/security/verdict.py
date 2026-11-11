"""verdict — the screen's first answer: who the traffic is, whether anything got in, what the internet
tried, who signed in, and every door into the machine (DGO-1646).

WHY IT EXISTS. On 2026-11-09 the owner opened «אבטחה» on a brand-new office and read «22,298 requests,
791 addresses, 62 countries, 4,055 successful sign-ins». He was its only user. Measured from these same
tables (DGO-1645):
  - 41% of the requests were his own clicks; the rest were internet scanners, every one sent to the
    sign-in, and 0 answered by a private app;
  - the «sign-ins» were the office's own machines polling each other over SSH.
The numbers were right, and the screen said none of that. This module says it, before any count.

WHO IS WHO comes from the same rule the bans use (Trust.why in app.py):
  - «you»: an address that signed in, or is allowed, and any address in the same /24 (IPv4) or /64 (IPv6)
    as one that signed in through the office's sign-in. A phone that changes network inside its carrier
    keeps its session, and must not turn the screen red;
  - «the office»: the machine itself, its containers, the private ranges and the linked offices;
  - «the internet»: everyone else.

WHAT «GOT IN» MEANS, AND WHAT IT CHECKED. A private, remote or link app answered an internet address with
a 2xx, or switched it to a websocket (101). The raw requests are kept 3 days. The proof therefore counts
the requests it actually checked, in the same window, and says how many hours that window covers.

SIGN-INS ARE NEVER ONE NUMBER (the second reader's blockers, 2026-11-09):
  - people: sign-ins through the office's sign-in (SSO). A failed one is a person's typo only when it
    comes from your side; a stranger's failure is a stranger's. A sign-out is neither;
  - our machines: an SSH sign-in with a NAMED key, or from the office's own side;
  - in through SSH: any other SSH success — a stranger's password, an unnamed key. That turns the verdict
    red, and Trust.why's «signed-in» cannot hide it, because it counts SSH successes too.
"""
from __future__ import annotations

import ipaddress
import re
import time

from jails import PROBE_PATHS

#: a request that hunts for a secret or a known weak spot, also where the narrower jail rule does not
#: look (`/api/.env`, `/v1/.env`, `/.git/HEAD`)
SECRETS = re.compile(r"(?i)/\.env|/\.git(?:/|$)|/xmlrpc\.php|/wp-(?:login|admin|includes|content)|/config\.(?:json|php|ya?ml)$")
#: raw requests (`hit`) are kept this long: the proof and the kinds cover at most this much
RAW_HOURS = 72
#: a new office is «learning» for its first two weeks: the internet finds it and sweeps it
LEARNING_DAYS = 14


def side(why: str) -> str:
    """Trust.why's reason, as one of the three sides the screen shows."""
    if why in ("signed-in", "allowed"):
        return "you"
    if why in ("private", "own", "herd"):
        return "office"
    return "internet"


def near(ip: str, nets: set) -> bool:
    """Is `ip` in the same /24 (IPv4) or /64 (IPv6) as one of `nets`?"""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return ipaddress.ip_network(f"{ip}/{24 if a.version == 4 else 64}", strict=False) in nets


def kind_of(h: dict) -> str:
    """What one internet request was, in the screen's words (the keys the screen names)."""
    path = (h.get("path") or "").split("?", 1)[0]
    if SECRETS.search(path) or PROBE_PATHS.search(path):
        return "secrets"
    k = h.get("kind") or ""
    if k in ("private", "remote", "auth", "link"):
        return "signin"
    if k == "public":
        return "public:" + (h.get("app") or "")
    if k == "door":
        return "door"
    return "bare"


def compute(store, why, facts: dict, hours: float, now: float | None = None, mode: str = "observe",
            would_ban: int = 0, proxy: str | None = None) -> dict:
    """The verdict for the last `hours`. `why(ip)` is Trust.why, `facts` the sensor's facts.json, `proxy`
    the docker door's state as app.proxy_check() measured it ("closed" / "open" / None unknown)."""
    now = now or time.time()
    since = now - hours * 3600
    day0 = time.strftime("%Y-%m-%d", time.gmtime(since))
    # the networks of the addresses that signed in through the office's sign-in in 30 days: a session is
    # the owner's when its address is one of them, or a neighbour inside the same /24 or /64
    sso_nets = set()
    for r in store.q("SELECT DISTINCT ip FROM signin WHERE src='sso' AND verdict='ok' AND ts>=?", (now - 30 * 86400,)):
        try:
            a = ipaddress.ip_address(r["ip"])
            sso_nets.add(ipaddress.ip_network(f"{r['ip']}/{24 if a.version == 4 else 64}", strict=False))
        except ValueError:
            pass
    sides = {}

    def side_of(ip: str) -> str:
        if ip not in sides:
            s = side(why(ip))
            sides[ip] = "you" if s == "internet" and near(ip, sso_nets) else s
        return sides[ip]

    # ── who: the whole window, from the per-day table the rest of the screen counts with ──────────────
    who = {s: {"requests": 0, "addrs": 0} for s in ("you", "office", "internet")}
    countries = set()
    for r in store.q("SELECT d.ip, SUM(d.n) n, a.cc FROM hit_day d LEFT JOIN addr a ON a.ip=d.ip "
                     "WHERE d.day>=? AND d.last>=? GROUP BY d.ip", (day0, since)):
        s = side_of(r["ip"])
        who[s]["requests"] += int(r["n"] or 0)
        who[s]["addrs"] += 1
        if s == "internet" and r.get("cc"):
            countries.add(r["cc"])
    who["internet"]["countries"] = len(countries)

    # ── the proof and what the internet tried: the raw requests, at most RAW_HOURS back ──────────────
    raw_since = max(since, now - RAW_HOURS * 3600)
    got_in, checked, got_ips, tried = 0, 0, set(), {}
    for h in store.q("SELECT ip, kind, app, path, status FROM hit WHERE ts>=?", (raw_since,)):
        if side_of(h["ip"]) != "internet":
            continue
        checked += 1
        status = int(h.get("status") or 0)
        inside = h.get("kind") in ("private", "remote", "link") and (200 <= status < 300 or status == 101)
        if inside:
            got_in += 1
            got_ips.add(h["ip"])
        k = kind_of(h)
        t = tried.setdefault(k, {"key": k, "requests": 0, "ips": set(), "ok": 0, "in": 0, "missing": 0})
        t["requests"] += 1
        t["ips"].add(h["ip"])
        t["ok"] += 1 if 200 <= status < 300 else 0
        t["in"] += 1 if inside else 0
        t["missing"] += 1 if status == 404 else 0

    # ── sign-ins: people, our machines, in through SSH, strangers — never one number ─────────────────
    named = {k.get("fp") for k in (facts.get("ssh_keys") or []) if (k.get("comment") or "").strip()}
    people = {"ok": 0, "typo": 0}
    machines = {"ok": 0, "fail": 0, "addrs": set()}
    ssh_in = {"ok": 0, "addrs": set()}
    strangers = {"attempts": 0, "addrs": set(), "sso_fail": 0}
    for r in store.q("SELECT ip, src, verdict, how, fp FROM signin WHERE ts>=?", (since,)):
        s = side_of(r["ip"])
        if r["src"] == "sso":
            if r["verdict"] == "ok":
                people["ok"] += 1
            elif r["verdict"] == "fail":
                if s == "internet":
                    strangers["sso_fail"] += 1
                    strangers["addrs"].add(r["ip"])
                else:
                    people["typo"] += 1
            continue                                       # a sign-out ("out") is neither
        if r["verdict"] == "ok":
            ours = (r.get("fp") or "") in named or s == "office" or \
                (r.get("how") == "password" and near(r["ip"], sso_nets))
            if ours:
                machines["ok"] += 1
                machines["addrs"].add(r["ip"])
            else:
                ssh_in["ok"] += 1
                ssh_in["addrs"].add(r["ip"])
        elif s == "internet":
            strangers["attempts"] += 1
            strangers["addrs"].add(r["ip"])
        else:
            machines["fail"] += 1
    if strangers["attempts"]:
        tried["ssh"] = {"key": "ssh", "requests": strangers["attempts"], "ips": set(strangers["addrs"]),
                        "ok": 0, "in": 0, "missing": 0}

    # ── the machine itself: the provider's hand and the console ──────────────────────────────────────
    host = {"exec": 0, "file-write": 0, "file-read": 0, "password": 0, "keys": 0, "freeze": 0, "console": 0}
    last_exec = ""
    for r in store.q("SELECT ts, kind, op, detail FROM host_event WHERE ts>=? ORDER BY ts", (since,)):
        if r["kind"] == "console":
            host["console"] += 1
        elif r["op"] in host:
            host[r["op"]] += 1
            if r["op"] == "exec":
                last_exec = r["detail"] or last_exec

    # ── the doors. A door this sensor does not watch says «not measured», never «0» ──────────────────
    listen = facts.get("listen") or []
    open_ports = {(x.get("proto"), x.get("port")) for x in listen if x.get("scope") == "all"}
    v6_global = any(":" in a.split("/")[0] and not a.lower().startswith("fe80")
                    for it in (facts.get("interfaces") or []) for a in (it.get("addrs") or []))
    v6_listen = any(x.get("scope") == "all" and ":" in str(x.get("addr")) for x in listen)
    keys = facts.get("ssh_keys")                           # None: the keys file could not be read
    unnamed = sum(1 for k in (keys or []) if not (k.get("comment") or "").strip())
    fence = facts.get("closed_fence")                      # "present" / "absent" / "error" / None (old sensor)
    drops = facts.get("closed_drops")
    agent = facts.get("provider_agent")                    # True / False / None (not measured)
    provider_acts = host["exec"] + host["file-write"] + host["password"] + host["keys"]
    web_bad = got_in > 0
    doors = [
        {"key": "web", "state": "bad" if web_bad else "ok", "open": bool({("tcp", 80), ("tcp", 443)} & open_ports),
         "n": got_in},
        {"key": "ssh", "state": "bad" if ssh_in["ok"] else ("info" if keys is None else ("warn" if unnamed else "ok")),
         "open": ("tcp", 22) in open_ports, "measured": keys is not None, "n": len(keys or []), "unnamed": unnamed,
         "in": ssh_in["ok"]},
        {"key": "media", "state": "info", "open": ("udp", 10000) in open_ports},
        {"key": "ipv6", "state": "info" if fence is None else ("ok" if not v6_global or fence == "present" else "warn"),
         "open": v6_global and v6_listen, "measured": fence is not None},
        {"key": "closed", "state": {"present": "ok", "absent": "warn"}.get(fence or "", "info"),
         "n": drops, "measured": fence in ("present", "absent"), "fence": fence},
        {"key": "docker", "state": {"closed": "ok", "open": "bad"}.get(proxy or "", "info"), "value": proxy},
        {"key": "provider", "state": "info" if agent is None else ("warn" if provider_acts else "ok"),
         "measured": agent is not None, "agent": agent, "n": host["exec"], "files": host["file-write"],
         "last": last_exec[:200]},
        {"key": "console", "state": "info" if "login" not in set(facts.get("watch") or []) else
         ("warn" if host["console"] else "ok"), "measured": "login" in set(facts.get("watch") or []), "n": host["console"]},
    ]

    # ── the age of the office: «learning» while the internet is still finding it ─────────────────────
    first = store.one("SELECT MIN(first) t FROM hit_day") or {}
    age_days = (now - float(first.get("t") or now)) / 86400

    needs = []
    if mode != "enforce" and would_ban:
        needs.append({"key": "enforce", "n": would_ban})
    if ssh_in["ok"]:
        needs.append({"key": "ssh-in", "n": ssh_in["ok"], "addrs": len(ssh_in["addrs"])})
    if agent and provider_acts:
        needs.append({"key": "provider", "n": provider_acts})
    if unnamed:
        needs.append({"key": "keys", "n": unnamed})
    if proxy == "open":
        needs.append({"key": "docker"})

    bad = web_bad or ssh_in["ok"] or any(d["state"] == "bad" for d in doors)
    return {
        "at": now, "hours": hours, "raw_hours": round((now - raw_since) / 3600, 1),
        "state": "needs" if bad else ("learning" if age_days < LEARNING_DAYS else "calm"),
        "got_in": got_in, "got_in_addrs": len(got_ips), "checked": checked,
        "age_days": round(age_days, 1), "learning_days": LEARNING_DAYS,
        "who": who,
        "tried": sorted(({"key": t["key"], "requests": t["requests"], "addrs": len(t["ips"]), "ok": t["ok"],
                          "in": t["in"], "missing": t["missing"]} for t in tried.values()), key=lambda t: -t["requests"]),
        "signins": {"people": people,
                    "machines": {"ok": machines["ok"], "fail": machines["fail"], "addrs": len(machines["addrs"])},
                    "ssh_in": {"ok": ssh_in["ok"], "addrs": len(ssh_in["addrs"])},
                    "strangers": {"attempts": strangers["attempts"], "addrs": len(strangers["addrs"]),
                                  "sso_fail": strangers["sso_fail"]}},
        "doors": doors, "needs": needs,
    }
