"""security — «אבטחה»: the one place an office (and the owner, for the whole herd) sees and controls what it
exposes and what it calls.

  inbound    every request to every public and private app, by address, place and network (the edge's
             log), every sign-in (the identity provider, the machine's sshd) and every request another
             office made through the link door
  outbound   every connection the machine and its containers open, by destination, name and app
  defence    the built-in fail2ban (jails.py) enforced in the kernel by the sensor (sensor.py), the
             owner's allow and block lists, observe → enforce
  machine    processor, memory, disk and containers (hostinfo.py — what the machine app showed)
  herd       the same for every linked office, through the link (herd.py)

Every route is behind the office's sign-in (the compiler emits it: routing auth sso). A request that
crossed a link (`X-Dgo-Office`, written by the serving door) may read, and may change nothing here
unless this office says so (`SECURITY_REMOTE_CONTROL=1`): a peer never writes another office's
defences by default (the rule G85 holds for the link's own declaration).
"""
from __future__ import annotations

import ipaddress
import json
import os
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import netparse as np
from dockerapi import Docker, DockerError, container_addresses
from edge import Routers, Tail
from geo import Geo
from herd import Herd
from hostinfo import HostInfo
from jails import Jails, ban_seconds
from store import Store, day_of

DATA = os.environ.get("SECURITY_DATA", "/data")
SENSOR = os.environ.get("SENSOR_DIR", "/sensor")
REGISTRY = os.environ.get("SECURITY_REGISTRY", "/registry")
OFFICE = os.environ.get("DGO_OFFICE_ID") or os.environ.get("DEPLOYMENT_NAME") or "office"
EDGE_CONTAINER = os.environ.get("SECURITY_EDGE_CONTAINER", "")
# The sign-in service whose log is read: the office's one switch, DGO_IDENTITY — the value the edge's
# middleware reads — names it (r030-002); SECURITY_AUTH_CONTAINER, when set, still wins.
AUTH_CONTAINER = os.environ.get("SECURITY_AUTH_CONTAINER") or (
    ("forward-auth-" if os.environ.get("DGO_IDENTITY") == "forward-auth" else "authentik-server-")
    + (os.environ.get("DEPLOYMENT_NAME") or "bina-deployment"))
# The LAN door's own sign-in (apps/lan-console, lan-signin): the same lines, from its own log.
LAN_AUTH_CONTAINER = os.environ.get("SECURITY_LAN_AUTH_CONTAINER") or (
    "lan-signin-" + (os.environ.get("DEPLOYMENT_NAME") or "bina-deployment"))
NOTIFY_URL = os.environ.get("NOTIFICATIONS_URL", "").rstrip("/")
DOOR_SOURCE = os.environ.get("SECURITY_DOOR_SOURCE", "")
LINK_SOURCE = os.environ.get("SECURITY_LINK_SOURCE", "")
REMOTE_CONTROL = os.environ.get("SECURITY_REMOTE_CONTROL", "0") == "1"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

store = Store(os.path.join(DATA, "security.db"))
geo = Geo(os.path.join(DATA, "geo"), os.environ.get("SECURITY_GEO", "city"))
docker = Docker(os.environ.get("DOCKER_SOCK", "/var/run/docker.sock"))
routers = Routers(docker, REGISTRY)
herd = Herd(REGISTRY)
host = HostInfo(docker, DATA, SENSOR)
STOP = threading.Event()
hits_q: "queue.Queue[dict]" = queue.Queue(maxsize=200000)
notices_q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
HEALTH: dict = {"sensor": {}, "door": {"ok": None, "error": ""}, "notify": {"ok": None, "error": ""}, "started": time.time()}
TAILS: dict = {}


# ── trust: who is never banned ───────────────────────────────────────────────────────────────────
class Trust:
    def __init__(self):
        self.own: set = set()
        self.herd: set = set()
        self.signed: set = set()
        self.allow_nets: list = []
        # what an address that is not on the internet IS — read from the engine and the registry, so a
        # row never says «unknown place» about this very machine (on the Mac every browser request
        # arrives through the engine's port forward, as the bridge's gateway address)
        self.gateways: set = set()
        self.containers: dict = {}
        self.offices: dict = {}
        self.at = 0.0

    def refresh(self) -> None:
        facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
        own = set()
        for it in facts.get("interfaces") or []:
            for a in it.get("addrs") or []:
                own.add(a.split("/")[0])
        herd_ips = set()
        for o in herd.offices().values():
            if o.get("address"):
                herd_ips.add(o["address"])
        for item in (link_items() or []):
            for key in ("endpoint", "via", "peer"):
                v = ((item.get("tunnel") or {}).get(key)) or item.get(key)
                if isinstance(v, str):
                    herd_ips.add(v.split(":")[0])
        nets = []
        for r in store.rules("allow"):
            try:
                nets.append(ipaddress.ip_network(r["value"], strict=False))
            except ValueError:
                pass
        self.own, self.herd, self.allow_nets = own, herd_ips, nets
        self.signed = store.trusted_signins(30)
        try:
            gws = {cfg["Gateway"] for net in (docker.get_json("/networks") or [])
                   for cfg in ((net.get("IPAM") or {}).get("Config") or []) if cfg.get("Gateway")}
            self.gateways, self.containers = gws, container_addresses(docker.containers())
        except (DockerError, OSError, ValueError, TypeError):
            pass                                   # the engine blinked: keep the last good answer
        self.offices = {o["address"]: o.get("label") or o["office"] for o in herd.offices().values() if o.get("address")}
        self.at = time.time()

    def label(self, ip: str) -> str:
        """A Hebrew name for an address that is not a stranger on the internet; '' for one that is."""
        if ip in self.offices:
            return "לשכה מקושרת · " + self.offices[ip]
        if ip in self.gateways:
            return "המחשב הזה, דרך המנוע"
        if ip in self.containers:
            return "אפליקציה של הלשכה · " + self.containers[ip]["name"]
        if ip in self.own:
            return "המחשב הזה"
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return ""
        if a.is_loopback:
            return "המחשב הזה"
        if a.is_multicast:
            return "שידור ברשת המקומית"            # mDNS and its kin: nobody outside hears it
        if a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10"):
            return "רשת הספק (CGNAT)"
        if not np.is_public(ip):
            return "הרשת הפנימית"
        return ""

    def why(self, ip: str) -> str:
        """'' when the address may be judged; otherwise the reason it never is."""
        if not np.is_public(ip):
            return "private"
        if ip in self.own:
            return "own"
        if ip in self.herd:
            return "herd"
        if ip in self.signed:
            return "signed-in"
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return "invalid"
        if any(a in n for n in self.allow_nets if n.version == a.version):
            return "allowed"
        return ""


trust = Trust()
jails = Jails(allow=lambda ip: bool(trust.why(ip)))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def said(e: urllib.error.HTTPError, who: str) -> str:
    """What a service SAID when it refused — its own words off the error's body (an HTTPError is a
    response), in a sentence a person reads; never the exception's class name (it was «HTTPError»)."""
    words = ""
    try:
        raw = e.read() or b""
        d = json.loads(raw) if raw[:1] in (b"{", b"[") else {}
        if isinstance(d, dict):
            words = d.get("message") or d.get("error") or d.get("detail") or ""
    except (OSError, ValueError):
        words = ""
    return f"{who} ענה בשגיאה" + (f": {str(words)[:160]}" if words else "")


def write_json(path, doc) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(tmp, path)


_link_cache = (0.0, None)


def link_items():
    global _link_cache
    if not LINK_SOURCE:
        return []
    at, items = _link_cache
    if items is not None and time.time() - at < 60:
        return items
    try:
        with urllib.request.urlopen(LINK_SOURCE, timeout=5) as r:      # noqa: S310 — the office network
            items = (json.loads(r.read() or b"{}") or {}).get("items") or []
    except urllib.error.HTTPError as e:
        HEALTH["links"] = {"ok": False, "error": said(e, "שירות הקישור")}
        items = items or []
    except (urllib.error.URLError, OSError, ValueError):
        items = items or []                                            # the link app is not here: no links
    else:
        HEALTH["links"] = {"ok": True, "error": ""}
    _link_cache = (time.time(), items)
    return items


def mode() -> str:
    return store.get("mode", "observe")


def notify(title: str, body: str, level: str = "info", source_id: str = "") -> None:
    if not NOTIFY_URL:
        return
    try:
        notices_q.put_nowait({"source": "security", "title": title, "body": body, "level": level,
                              "source_id": source_id or title, "meta": {"office": OFFICE}})
    except queue.Full:
        pass


# ── collectors ───────────────────────────────────────────────────────────────────────────────────
def on_edge_line(ts: float, line: str) -> bool:
    r = np.clf_line(line)
    if not r or not r.get("ip"):
        return False
    c = routers.classify(r.get("router") or "")
    r["ts"] = r.get("ts") or ts
    r.update(kind=c["kind"], app=c["app"], office=c["office"], src="edge")
    try:
        hits_q.put_nowait(r)
    except queue.Full:
        pass
    return True


def on_auth_line(ts: float, line: str) -> bool:
    e = np.authentik_event(line) or np.forward_auth_event(line)
    if not e or not e.get("ip"):
        return False
    e["ts"] = e.get("ts") or ts
    verdict = {"login": "ok", "login_failed": "fail", "logout": "out", "suspicious_request": "fail"}[e["action"]]
    store.add_signins([{"ts": e["ts"], "ip": e["ip"], "src": "sso", "verdict": verdict, "user": e.get("user") or "",
                        "how": e.get("how") or ""}], geo)
    jails.feed_auth(e)
    if verdict == "ok":
        trust.signed.add(e["ip"])
    return True


def cursor(name):
    return (lambda: store.get(f"cursor:{name}", 0)), (lambda v: store.put(f"cursor:{name}", v))


def _exists(name: str) -> bool:
    try:
        return bool(docker.inspect(name))
    except Exception:                                      # noqa: BLE001 — absent is the common answer
        return False


def follow_lan_signin() -> None:
    """The LAN door's sign-in (lan-signin), only where this office has one — a container that is not
    there would only read as a broken stream — and from the moment it appears, not only at this app's
    start: the door is often made after this app is up (Tail itself copes with a recreate)."""
    if "auth-lan" in TAILS or not LAN_AUTH_CONTAINER or not _exists(LAN_AUTH_CONTAINER):
        return
    g, p = cursor("auth-lan")
    t = Tail(docker, LAN_AUTH_CONTAINER, g, p, on_auth_line, "auth-lan")
    TAILS["auth-lan"] = t
    t.start()


def start_tails() -> None:
    follow_lan_signin()
    for name, cname, fn in (("edge", EDGE_CONTAINER, on_edge_line), ("auth", AUTH_CONTAINER, on_auth_line)):
        if not cname:
            continue
        g, p = cursor(name)
        t = Tail(docker, cname, g, p, fn, name)
        TAILS[name] = t
        t.start()


_known_countries: set = set()


def ingest_hits() -> None:
    batch = []
    try:
        while len(batch) < 5000:
            batch.append(hits_q.get_nowait())
    except queue.Empty:
        pass
    if not batch:
        return
    store.add_hits(batch, geo)
    for h in batch:
        jails.feed_hit(h)
    # a country never seen before on what is behind the sign-in is worth a line to the owner
    if not _known_countries:
        _known_countries.update(r["cc"] for r in store.q(
            "SELECT DISTINCT a.cc FROM hit_day d JOIN addr a ON a.ip=d.ip WHERE d.kind IN ('private','remote','auth') AND a.cc!=''"))
        _known_countries.add("")
    for h in batch:
        if h.get("kind") in ("private", "remote", "auth") and h.get("status", 0) < 400:
            row = store.one("SELECT cc FROM addr WHERE ip=?", (h["ip"],))
            cc = (row or {}).get("cc") or ""
            if cc and cc not in _known_countries:
                _known_countries.add(cc)
                title = f"כניסה ממדינה חדשה: {cc}"
                store.event("country", "warn", title, f"{h['ip']} → {h.get('app')}", h["ip"])
                notify(title, f"הכתובת {h['ip']} פתחה את {h.get('app') or 'הלשכה'} מ־{cc} — מדינה שלא נראתה קודם בכניסה ללשכה.",
                       "warning", f"country:{cc}")


def ingest_spool() -> None:
    d = os.path.join(SENSOR, "spool")
    try:
        files = sorted(os.listdir(d))
    except OSError:
        return
    flows, names, signins = [], [], []
    for f in files[:200]:
        p = os.path.join(d, f)
        doc = read_json(p)
        try:
            os.unlink(p)
        except OSError:
            pass
        if not doc:
            continue
        flows.extend(doc.get("flows") or [])
        store.add_vol(doc.get("vol") or [], float(doc.get("at") or time.time()))
        for n in doc.get("names") or []:
            names.append({"ip": n["ip"], "name": n["name"], "via": "dns", "first": n["first"], "last": n["last"], "n": n["n"]})
        for n in doc.get("sni") or []:
            names.append({"ip": n["ip"], "name": n["name"], "via": "tls", "first": n["first"], "last": n["last"], "n": n["n"]})
        for a in doc.get("auth") or []:
            signins.append({"ts": a.get("ts") or time.time(), "ip": a["ip"], "src": "ssh", "verdict": a["verdict"],
                            "user": a.get("user") or "", "how": a.get("how") or "", "fp": a.get("fp") or ""})
            jails.feed_ssh(a)
            if a.get("verdict") == "ok":
                trust.signed.add(a["ip"])
    if flows:
        # name each flow's app NOW, seconds after it happened: an address names a container only until
        # that container is recreated (outbound: its source; inbound: the app it reached)
        who = _who({f["src"] if f.get("dir") == "out" else f["dst"] for f in flows})
        for f in flows:
            name = who.get(f["src"] if f.get("dir") == "out" else f["dst"])
            f["who"] = name if name and name != (f["src"] if f.get("dir") == "out" else f["dst"]) else None
    store.add_flows(flows, geo)
    store.add_names(names)
    store.add_signins(signins, geo)


def ingest_door() -> None:
    """Every request another office made through this office's link door (dgo-extend's access log)."""
    if not DOOR_SOURCE:
        return
    since = store.get("cursor:door", 0)
    try:
        with urllib.request.urlopen(f"{DOOR_SOURCE}?since={since}", timeout=5) as r:   # noqa: S310
            doc = json.loads(r.read() or b"{}")
        HEALTH["door"] = {"ok": True, "error": ""}
    except urllib.error.HTTPError as e:
        HEALTH["door"] = {"ok": False, "error": said(e, "יומן הדלת")}
        return
    except (urllib.error.URLError, OSError, ValueError):
        HEALTH["door"] = {"ok": False, "error": "אין תשובה מיומן הדלת"}
        return
    rows = doc.get("items") or []
    hits = []
    last = since
    for it in rows:
        ts = float(it.get("ts") or 0)
        last = max(last, ts)
        hits.append({"ts": ts, "ip": it.get("peer_ip") or it.get("office") or "", "kind": "link", "app": it.get("app") or "",
                     "office": it.get("office") or "", "host": it.get("host") or "", "method": it.get("method") or "",
                     "path": (it.get("path") or "")[:400], "status": int(it.get("status") or 0), "bytes": int(it.get("bytes_out") or 0),
                     "ms": int(it.get("ms") or 0), "ua": "", "user": it.get("user") or "", "router": "", "src": "door"})
    if hits:
        store.add_hits(hits, None)
        store.put("cursor:door", last)


def decide() -> None:
    now = time.time()
    m = mode()
    for d in jails.decide(now):
        if trust.why(d["ip"]):
            continue
        current = store.one("SELECT active, mode FROM ban WHERE ip=?", (d["ip"],))
        if current and current["active"] and current["mode"] == m:
            continue
        seconds = ban_seconds(store.offences(d["ip"]) + 1)
        b = store.ban(d["ip"], d["jail"], d["reason"], seconds, m, "jail")
        place = store.one("SELECT cc, org FROM addr WHERE ip=?", (d["ip"],)) or {}
        hours = round(seconds / 3600, 1)
        if m == "enforce":
            title = f"נחסם {d['ip']}"
            body = f"{JAIL_HE.get(d['jail'], d['jail'])}: {d['reason']}. חסום ל־{hours} שעות (עבירה מס׳ {b['offences']}). {place.get('cc') or ''} {place.get('org') or ''}".strip()
            store.event("ban", "warn", title, body, d["ip"], d["jail"])
            notify(title, body, "warning", f"ban:{d['ip']}")
        else:
            title = f"היה נחסם: {d['ip']}"
            body = f"{JAIL_HE.get(d['jail'], d['jail'])}: {d['reason']}. מצב צפייה — לא נחסם בפועל."
            store.event("would-ban", "info", title, body, d["ip"], d["jail"])
    for r in store.expire_bans():
        store.event("unban", "info", f"החסימה של {r['ip']} הסתיימה", "", r["ip"], r["jail"])
    write_desired()


JAIL_HE = {"scan": "סריקה", "auth": "כניסות שנכשלו", "sshd": "SSH", "manual": "ידני"}


def write_desired() -> None:
    now = time.time()
    m = mode()
    bans = [{"ip": b["ip"], "until": b["until"]} for b in store.active_bans() if b["mode"] == "enforce" and (not b["until"] or b["until"] > now)]
    blocks = [{"ip": r["value"], "until": r["until"]} for r in store.rules("block")]
    try:
        os.makedirs(SENSOR, exist_ok=True)
        write_json(os.path.join(SENSOR, "desired.json"), {"at": now, "mode": m, "bans": bans, "blocks": blocks})
    except OSError:
        pass


def sender() -> None:
    while not STOP.is_set():
        try:
            n = notices_q.get(timeout=2)
        except queue.Empty:
            continue
        try:
            req = urllib.request.Request(f"{NOTIFY_URL}/api/notifications", data=json.dumps(n).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()                  # noqa: S310
            HEALTH["notify"] = {"ok": True, "error": ""}
        except urllib.error.HTTPError as e:
            HEALTH["notify"] = {"ok": False, "error": said(e, "שירות ההתראות")}
        except (urllib.error.URLError, OSError, ValueError):
            HEALTH["notify"] = {"ok": False, "error": "אין תשובה משירות ההתראות"}


_PTR_TRIED: dict = {}


def reverse_names() -> None:
    """Name the public destinations nobody named. A connection made to a bare address (an SSH to a
    server, the clock's NTP) carries no DNS answer and no TLS name, and the outbound list said
    «ללא שם» for every one of them. Their reverse name (PTR) is asked once a day per address — the
    question itself goes out through this machine's resolver, and is listed like every other call —
    and stored with a zero count, so a name the traffic itself carried always ranks first."""
    since = time.time() - 24 * 3600
    rows = store.q("SELECT f.dst ip FROM flow f LEFT JOIN name n ON n.ip=f.dst WHERE f.dir='out' AND f.last>=? "
                   "AND n.ip IS NULL GROUP BY f.dst ORDER BY SUM(f.n) DESC LIMIT 60", (since,))
    now = time.time()
    todo = [r["ip"] for r in rows if np.is_public(r["ip"]) and now - _PTR_TRIED.get(r["ip"], 0) > 24 * 3600][:20]
    if not todo:
        return
    for ip in todo:
        _PTR_TRIED[ip] = now
    found = []
    # not `with`: leaving that block waits for every lookup, and a resolver that never answers would hold
    # this pass forever; a lookup that outlives its four seconds finishes on its own thread and is dropped
    pool = ThreadPoolExecutor(max_workers=4)
    futs = {ip: pool.submit(socket.gethostbyaddr, ip) for ip in todo}
    for ip, fut in futs.items():
        try:
            name = (fut.result(timeout=4)[0] or "").rstrip(".").lower()
        except (OSError, FutureTimeout):
            continue
        if name and name != ip:
            found.append({"ip": ip, "name": name, "via": "ptr", "first": now, "last": now, "n": 0})
    pool.shutdown(wait=False, cancel_futures=True)
    store.add_names(found)


def loop(name: str, every: float, fn) -> None:
    def run():
        while not STOP.is_set():
            t0 = time.time()
            try:
                fn()
            except Exception as e:                                         # noqa: BLE001 — one bad pass must not end the loop
                store.event("fault", "error", f"{name}: {type(e).__name__}", str(e)[:400])
            STOP.wait(max(0.5, every - (time.time() - t0)))
    threading.Thread(target=run, daemon=True, name=name).start()


def sensor_watch() -> None:
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    age = time.time() - (facts.get("at") or 0)
    was = HEALTH["sensor"].get("ok")
    ok = age < 120
    HEALTH["sensor"] = {"ok": ok, "age_s": int(age) if facts else None}
    if was is True and not ok:
        store.event("sensor", "error", "החיישן לא כותב", f"facts.json לא עודכן {int(age)} שניות")
        notify("החיישן של האבטחה הפסיק לעבוד", "החיישן לא כתב כבר יותר משתי דקות: אין מעקב יציאות ואין אכיפת חסימות.", "error", "sensor-down")


def boot() -> None:
    if store.get("mode") is None:
        store.put("mode", "observe")
        store.put("learning_until", time.time() + 24 * 3600)
        store.event("mode", "info", "האבטחה הופעלה במצב צפייה", "לומדת את התנועה הרגילה; חסימות נרשמות ולא נאכפות עד שהבעלים עובר לאכיפה.")
    routers.refresh()
    trust.refresh()
    write_desired()
    start_tails()
    # (no thread of its own for the location database: the `geo` loop below runs at once, and a second
    #  start beside it downloaded every edition twice on each restart)
    threading.Thread(target=sender, daemon=True, name="notify").start()
    loop("ingest", 2, lambda: (ingest_hits(), ingest_spool()))
    loop("decide", 10, decide)
    loop("door", 10, ingest_door)
    loop("routers", 60, lambda: (routers.refresh(), follow_lan_signin()))
    loop("trust", 30, trust.refresh)
    loop("host", 10, host.tick)
    loop("sensor", 15, sensor_watch)
    loop("retention", 3600, store.retention)
    loop("geo", 6 * 3600, geo.refresh)
    loop("geo-fill", 300, lambda: store.geo_backfill(geo))
    loop("ptr", 120, reverse_names)
    loop("addrs", 5, remember_addrs)


# ── HTTP ─────────────────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="security", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def _startup() -> None:
    boot()


def actor(req: Request) -> str:
    return req.headers.get("x-authentik-username") or "?"


def guard_write(req: Request) -> None:
    if req.headers.get("x-dgo-office") and not REMOTE_CONTROL:
        raise HTTPException(403, {"error": "remote-write", "message": "לשכה מקושרת יכולה לראות את האבטחה כאן ולא לשנות אותה. השינוי נעשה במסך של הלשכה הזאת."})


def window(hours: float) -> float:
    return time.time() - max(0.1, min(float(hours), 24 * 120)) * 3600


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


@app.get("/api/summary")
def summary(hours: float = 24):
    since = window(hours)
    day0 = day_of(since)
    k = store.one("SELECT COUNT(DISTINCT d.ip) addrs, SUM(d.n) requests, SUM(d.fails) fails, "
                  # an internal address has no country (cc ''): it is not «one more country»
                  "COUNT(DISTINCT NULLIF(a.cc,'')) countries FROM hit_day d LEFT JOIN addr a ON a.ip=d.ip "
                  "WHERE d.day>=? AND d.last>=?",
                  (day0, since)) or {}
    kinds = {r["kind"]: r["n"] for r in store.q("SELECT kind, SUM(n) n FROM hit_day WHERE day>=? AND last>=? GROUP BY kind", (day0, since))}
    out = store.one("SELECT COUNT(DISTINCT dst) dests, SUM(n) conns FROM flow WHERE dir='out' AND last>=?", (since,)) or {}
    sig = {r["verdict"]: r["n"] for r in store.q("SELECT verdict, COUNT(*) n FROM signin WHERE ts>=? GROUP BY verdict", (since,))}
    bans = store.active_bans()
    top_c = store.q("SELECT a.cc, COUNT(DISTINCT d.ip) addrs, SUM(d.n) n FROM hit_day d JOIN addr a ON a.ip=d.ip "
                    "WHERE d.day>=? AND d.last>=? AND a.cc!='' GROUP BY a.cc ORDER BY n DESC LIMIT 8", (day0, since))
    top_a = store.q("SELECT app, kind, office, COUNT(DISTINCT ip) addrs, SUM(n) n FROM hit_day WHERE day>=? AND last>=? "
                    "GROUP BY app, kind, office ORDER BY n DESC LIMIT 10", (day0, since))
    for r in top_a:
        r["title"] = routers.title(r["app"], r["office"]) if r["app"] else ""
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    return {"office": OFFICE, "at": time.time(), "hours": hours, "mode": mode(),
            "kpi": {"requests": k.get("requests") or 0, "addrs": k.get("addrs") or 0, "countries": k.get("countries") or 0,
                    "fails": k.get("fails") or 0, "kinds": kinds, "out_dests": out.get("dests") or 0, "out_conns": out.get("conns") or 0,
                    "signin_ok": sig.get("ok", 0), "signin_fail": sig.get("fail", 0),
                    "bans": sum(1 for b in bans if b["mode"] == "enforce"), "would_ban": sum(1 for b in bans if b["mode"] != "enforce"),
                    "watching": len(jails.watching(time.time()))},
            "top": {"countries": top_c, "apps": top_a},
            "health": {"edge": TAILS["edge"].health if "edge" in TAILS else {"ok": None, "error": "no edge container declared"},
                       "auth": TAILS["auth"].health if "auth" in TAILS else {"ok": None, "error": "no sign-in container declared"},
                       **({"auth_lan": TAILS["auth-lan"].health} if "auth-lan" in TAILS else {}),
                       "sensor": HEALTH["sensor"], "sensor_parts": (facts.get("health") or {}),
                       "geo": geo.status, "door": HEALTH["door"], "notify": HEALTH["notify"]},
            "host": {"hostname": facts.get("hostname") or "", "kernel": facts.get("kernel") or ""}}


def _state(ip: str, banned: dict) -> str:
    b = banned.get(ip)
    if b:
        return "banned" if b["mode"] == "enforce" else "would"
    why = trust.why(ip)
    return {"signed-in": "trusted", "allowed": "allowed", "herd": "herd", "own": "own"}.get(why, "seen")


@app.get("/api/inbound")
def inbound(hours: float = 24, kind: str = "", q: str = "", limit: int = 1000):
    since = window(hours)
    args = [day_of(since), since]
    where = "d.day>=? AND d.last>=?"
    if kind:
        where += " AND d.kind=?"
        args.append(kind)
    rows = store.q(f"SELECT d.ip, SUM(d.n) n, SUM(d.fails) fails, MIN(d.first) first, MAX(d.last) last, "
                   f"GROUP_CONCAT(DISTINCT d.kind) kinds, GROUP_CONCAT(DISTINCT d.app || '|' || d.office) apps, "
                   f"a.cc, a.city, a.org, a.asn, a.users FROM hit_day d LEFT JOIN addr a ON a.ip=d.ip WHERE {where} "
                   f"GROUP BY d.ip ORDER BY n DESC LIMIT ?", (*args, max(1, min(limit, 5000))))
    banned = {b["ip"]: b for b in store.active_bans()}
    out = []
    ql = q.lower().strip()
    for r in rows:
        apps = []
        for pair in (r.pop("apps") or "").split(","):
            app_id, _, office = pair.partition("|")
            if app_id:
                apps.append({"app": app_id, "office": office, "title": routers.title(app_id, office)})
        r["apps"] = apps
        r["kinds"] = sorted(set((r.get("kinds") or "").split(",")) - {""})
        r["users"] = json.loads(r.get("users") or "[]")
        r["state"] = _state(r["ip"], banned)
        r["local"] = trust.label(r["ip"])
        if ql and ql not in json.dumps(r, ensure_ascii=False).lower():
            continue
        out.append(r)
    return {"hours": hours, "rows": out}


@app.get("/api/inbound/{ip}")
def inbound_one(ip: str):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, {"error": "ip", "message": "כתובת לא תקינה"})
    addr = store.one("SELECT * FROM addr WHERE ip=?", (ip,)) or {"ip": ip}
    addr["users"] = json.loads(addr.get("users") or "[]")
    addr["local"] = trust.label(ip)
    hits = store.q("SELECT ts, kind, app, office, host, method, path, status, bytes, ms, ua, user, src FROM hit WHERE ip=? "
                   "ORDER BY ts DESC LIMIT 300", (ip,))
    for h in hits:
        h["title"] = routers.title(h["app"], h["office"]) if h["app"] else ""
    days = store.q("SELECT day, app, kind, office, n, fails FROM hit_day WHERE ip=? ORDER BY day DESC LIMIT 200", (ip,))
    signins = store.q("SELECT ts, src, verdict, user, how, fp FROM signin WHERE ip=? ORDER BY ts DESC LIMIT 100", (ip,))
    flows = store.q("SELECT day, dir, src, dst, port, proto, n, last FROM flow WHERE src=? OR dst=? ORDER BY last DESC LIMIT 100", (ip, ip))
    ban = store.one("SELECT * FROM ban WHERE ip=?", (ip,))
    log = store.q("SELECT * FROM ban_log WHERE ip=? ORDER BY ts DESC LIMIT 50", (ip,))
    return {"addr": addr, "trust": trust.why(ip), "ban": ban, "ban_log": log, "hits": hits, "days": days,
            "signins": signins, "flows": flows}


# WHO HELD AN ADDRESS, for the last quarter of an hour. A connection is reported when it ENDS, and a
# short-lived container (a `docker run --rm`, a build step, a one-off job) is often gone by then: its
# calls showed as a bare address — or, worse, under whichever app had that address before it. So the
# engine's map is read every five seconds and kept; a container with no compose name is named by its
# image, which is what says what it was.
_RECENT: dict = {}
_RECENT_LOCK = threading.Lock()


def remember_addrs() -> dict:
    try:
        cs = docker.containers()
    except DockerError:
        return {}
    now = time.time()
    addrs = container_addresses(cs)
    images = {}
    for c in cs:
        labels = c.get("Labels") or {}
        if not labels.get("com.docker.compose.service"):
            image = (c.get("Image") or "").split("@")[0].rsplit("/", 1)[-1].split(":")[0]
            for net in ((c.get("NetworkSettings") or {}).get("Networks") or {}).values():
                if net.get("IPAddress") and image:
                    images[net["IPAddress"]] = image
    with _RECENT_LOCK:
        for ip, a in addrs.items():
            _RECENT[ip] = (images.get(ip) or a["name"], now)
        for ip in [k for k, v in _RECENT.items() if now - v[1] > 900]:
            _RECENT.pop(ip, None)
    return addrs


def _who(ips) -> dict:
    """container address → app (the compose service, or the image of a one-off), from the engine and the
    last quarter hour of it; the machine itself → host."""
    remember_addrs()
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    own = {a.split("/")[0] for it in (facts.get("interfaces") or []) for a in (it.get("addrs") or [])}
    out = {}
    with _RECENT_LOCK:
        recent = dict(_RECENT)
    for ip in ips:
        if ip in recent:
            out[ip] = recent[ip][0]
        elif ip in own:
            out[ip] = "@host"
        else:
            out[ip] = ip
    return out


@app.get("/api/outbound")
def outbound(hours: float = 24, q: str = "", limit: int = 1000):
    since = window(hours)
    rows = store.q("SELECT dst, SUM(n) n, SUM(bytes_out) bytes_out, SUM(bytes_in) bytes_in, MIN(first) first, MAX(last) last, "
                   "GROUP_CONCAT(DISTINCT src) srcs, GROUP_CONCAT(DISTINCT port || '/' || proto) ports, "
                   "GROUP_CONCAT(DISTINCT src || '|' || COALESCE(who, '')) pairs "
                   "FROM flow WHERE dir='out' AND last>=? GROUP BY dst ORDER BY n DESC LIMIT ?", (since, max(1, min(limit, 5000))))
    names = store.names_for([r["dst"] for r in rows])
    srcs = set()
    for r in rows:
        r["srcs"] = sorted(set((r.get("srcs") or "").split(",")) - {""})
        srcs.update(r["srcs"])
    who_now = _who(srcs)
    # the app named when the flow was ingested wins; a row from before that column is named now
    for r in rows:
        named = set()
        for pair in (r.pop("pairs") or "").split(","):
            src, _, w = pair.partition("|")
            if src:
                named.add(w or who_now.get(src, src))
        r["_apps"] = named
    who = {}
    geo_rows = {}
    ips = [r["dst"] for r in rows]
    for i in range(0, len(ips), 400):
        chunk = ips[i:i + 400]
        for g in store.q(f"SELECT ip, cc, city, org, asn, lat, lon FROM addr WHERE ip IN ({','.join('?' * len(chunk))})", chunk):
            geo_rows[g["ip"]] = g
    blocked = {r["value"] for r in store.rules("block")}
    # the VOLUME, from the sensor's kernel counters (per address and day): what conntrack alone cannot say
    vols = store.vol_for(ips, day_of(since))
    ql = q.lower().strip()
    out = []
    for r in rows:
        v = vols.get(r["dst"])
        if v:
            r["bytes_out"], r["bytes_in"] = v["bout"], v["bin"]
        r["names"] = (names.get(r["dst"]) or [])[:4]
        r["apps"] = sorted(r.pop("_apps", None) or {who.get(s, s) for s in r["srcs"]})
        r["ports"] = sorted(set((r.get("ports") or "").split(",")) - {""})
        g = geo_rows.get(r["dst"]) or {}
        r.update({"cc": g.get("cc") or "", "city": g.get("city") or "", "org": g.get("org") or "", "asn": g.get("asn")})
        r["local"] = trust.label(r["dst"])
        r["state"] = "blocked" if r["dst"] in blocked else "seen"
        if ql and ql not in json.dumps(r, ensure_ascii=False).lower():
            continue
        out.append(r)
    inbound_flows = store.q("SELECT dst port_owner, port, proto, COUNT(DISTINCT src) addrs, SUM(n) n, MAX(last) last FROM flow "
                            "WHERE dir='in' AND last>=? GROUP BY port, proto ORDER BY n DESC LIMIT 50", (since,))
    return {"hours": hours, "rows": out, "inbound_ports": inbound_flows}


@app.get("/api/outbound/{ip}")
def outbound_one(ip: str):
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(400, {"error": "ip", "message": "כתובת לא תקינה"})
    flows = store.q("SELECT day, src, port, proto, n, bytes_out, bytes_in, first, last, who FROM flow WHERE dir='out' AND dst=? "
                    "ORDER BY last DESC LIMIT 300", (ip,))
    who = _who({f["src"] for f in flows if not f.get("who")})
    for f in flows:
        f["app"] = f.pop("who", None) or who.get(f["src"], f["src"])
    names = store.q("SELECT name, via, first, last, n FROM name WHERE ip=? ORDER BY n DESC LIMIT 20", (ip,))
    addr = store.one("SELECT * FROM addr WHERE ip=?", (ip,)) or {"ip": ip}
    blocked = store.one("SELECT * FROM rule WHERE kind='block' AND value=?", (ip,))
    return {"addr": addr, "names": names, "flows": flows, "blocked": blocked}


@app.get("/api/map")
def map_points(hours: float = 24):
    since = window(hours)
    day0 = day_of(since)
    banned = {b["ip"]: b for b in store.active_bans()}
    inbound_rows = store.q("SELECT d.ip, SUM(d.n) n, SUM(d.fails) fails, GROUP_CONCAT(DISTINCT d.kind) kinds, a.cc, a.city, a.lat, a.lon "
                           "FROM hit_day d JOIN addr a ON a.ip=d.ip WHERE d.day>=? AND d.last>=? AND a.lat IS NOT NULL "
                           "GROUP BY d.ip", (day0, since))
    pins: dict = {}
    for r in inbound_rows:
        key = ("in", round(r["lat"], 1), round(r["lon"], 1))
        p = pins.setdefault(key, {"dir": "in", "lat": r["lat"], "lon": r["lon"], "cc": r["cc"], "city": r["city"], "n": 0, "fails": 0,
                                  "ips": 0, "banned": 0, "private": 0, "public": 0})
        p["n"] += r["n"] or 0
        p["fails"] += r["fails"] or 0
        p["ips"] += 1
        kinds = r.get("kinds") or ""
        p["private"] += 1 if ("private" in kinds or "remote" in kinds or "auth" in kinds) else 0
        p["public"] += 1 if ("public" in kinds or "none" in kinds or "door" in kinds) else 0
        p["banned"] += 1 if r["ip"] in banned else 0
    out_rows = store.q("SELECT f.dst, SUM(f.n) n, a.cc, a.city, a.lat, a.lon FROM flow f JOIN addr a ON a.ip=f.dst "
                       "WHERE f.dir='out' AND f.last>=? AND a.lat IS NOT NULL GROUP BY f.dst", (since,))
    names = store.names_for([r["dst"] for r in out_rows])
    for r in out_rows:
        key = ("out", round(r["lat"], 1), round(r["lon"], 1))
        p = pins.setdefault(key, {"dir": "out", "lat": r["lat"], "lon": r["lon"], "cc": r["cc"], "city": r["city"], "n": 0, "ips": 0, "names": []})
        p["n"] += r["n"] or 0
        p["ips"] += 1
        for nm in (names.get(r["dst"]) or [])[:1]:
            if len(p["names"]) < 6:
                p["names"].append(nm)
    return {"hours": hours, "office": OFFICE, "me": whereami(), "pins": sorted(pins.values(), key=lambda p: -p["n"])[:1500],
            "attribution": "IP geolocation by DB-IP (db-ip.com), CC BY 4.0"}


def whereami() -> dict | None:
    """The office on its own map: its public address (an interface that has one, else what STUN said),
    placed by the same database as everyone else."""
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    pub = facts.get("public_ip") or ""
    if not pub:
        for it in facts.get("interfaces") or []:
            for a in it.get("addrs") or []:
                if np.is_public(a.split("/")[0]):
                    pub = a.split("/")[0]
                    break
    if not pub:
        return None
    g = geo.lookup(pub) or {}
    if g.get("lat") is None:
        return {"ip": pub, "lat": None, "lon": None, "cc": g.get("cc") or "", "city": ""}
    return {"ip": pub, "lat": g["lat"], "lon": g["lon"], "cc": g.get("cc") or "", "city": g.get("city") or "", "org": g.get("org") or ""}


@app.get("/api/signins")
def signins(hours: float = 168, limit: int = 500):
    since = window(hours)
    rows = store.q("SELECT s.ts, s.ip, s.src, s.verdict, s.user, s.how, s.fp, a.cc, a.city, a.org FROM signin s "
                   "LEFT JOIN addr a ON a.ip=s.ip WHERE s.ts>=? ORDER BY s.ts DESC LIMIT ?", (since, max(1, min(limit, 5000))))
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    keys = {k["fp"]: k for k in (facts.get("ssh_keys") or [])}
    for r in rows:
        k = keys.get(r.get("fp") or "")
        r["key_label"] = (k or {}).get("comment") or ""
    by_key = store.q("SELECT fp, COUNT(*) n, COUNT(DISTINCT ip) addrs, MAX(ts) last FROM signin WHERE src='ssh' AND verdict='ok' "
                     "AND ts>=? GROUP BY fp ORDER BY n DESC", (since,))
    for r in by_key:
        k = keys.get(r["fp"] or "")
        r["label"] = (k or {}).get("comment") or ""
        r["type"] = (k or {}).get("type") or ""
        r["authorized"] = bool(k)
    return {"hours": hours, "rows": rows, "keys": by_key, "authorized": list(keys.values())}


@app.get("/api/links")
def links(hours: float = 24):
    since = window(hours)
    served = store.q("SELECT office, app, user, COUNT(*) n, SUM(CASE WHEN status>=400 THEN 1 ELSE 0 END) fails, MAX(ts) last, "
                     "SUM(bytes) bytes FROM hit WHERE src='door' AND ts>=? GROUP BY office, app, user ORDER BY n DESC", (since,))
    for r in served:
        r["title"] = routers.title(r["app"])
    used = store.q("SELECT office, app, COUNT(*) n, COUNT(DISTINCT ip) addrs, SUM(fails) fails, MAX(last) last FROM "
                   "(SELECT office, app, ip, n, fails, last FROM hit_day WHERE kind='remote' AND day>=? AND last>=?) GROUP BY office, app "
                   "ORDER BY n DESC", (day_of(since), since))
    for r in used:
        r["title"] = routers.title(r["app"], r["office"])
    recent = store.q("SELECT ts, office, app, user, method, path, status, ms, bytes FROM hit WHERE src='door' AND ts>=? "
                     "ORDER BY ts DESC LIMIT 300", (since,))
    for r in recent:
        r["title"] = routers.title(r["app"])
    return {"hours": hours, "served": served, "used": used, "recent": recent, "door": HEALTH["door"],
            "offices": {o: v["label"] for o, v in herd.offices().items()}}


@app.get("/api/bans")
def bans():
    now = time.time()
    active = store.active_bans()
    watching = jails.watching(now)
    for w in watching:
        w["trust"] = trust.why(w["ip"])
    hist = store.q("SELECT l.*, a.cc, a.org FROM ban_log l LEFT JOIN addr a ON a.ip=l.ip ORDER BY l.ts DESC LIMIT 300")
    applied = read_json(os.path.join(SENSOR, "applied.json"), {}) or {}
    return {"mode": mode(), "active": active, "watching": watching, "history": hist, "applied": applied,
            "jails": {k: {**v, "enabled": jails.enabled.get(k, True)} for k, v in jails.rules.items()},
            "learning_until": store.get("learning_until", 0)}


@app.post("/api/bans")
async def ban_add(req: Request):
    guard_write(req)
    body = await req.json()
    ip = str(body.get("ip") or "").strip()
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        raise HTTPException(400, {"error": "ip", "message": "כתובת לא תקינה"})
    why = trust.why(ip)
    if why in ("private", "own"):
        raise HTTPException(409, {"error": "trusted", "message": "זו כתובת של הלשכה עצמה או של הרשת הפרטית — לא חוסמים אותה."})
    minutes = int(body.get("minutes") or 0)
    reason = str(body.get("reason") or "חסימה ידנית")[:200]
    b = store.ban(ip, "manual", reason, minutes * 60, "enforce" if mode() == "enforce" else mode(), actor(req))
    store.event("ban", "warn", f"נחסם ידנית: {ip}", reason, ip, "manual")
    write_desired()
    return {"ok": True, "ban": b, "trust_note": why}


@app.delete("/api/bans/{ip}")
def ban_drop(ip: str, req: Request):
    guard_write(req)
    ok = store.unban(ip, actor(req), "ידני")
    if ok:
        store.event("unban", "info", f"החסימה של {ip} הוסרה", f"על ידי {actor(req)}", ip)
    write_desired()
    return {"ok": ok}


@app.get("/api/rules")
def rules():
    return {"allow": store.rules("allow"), "block": store.rules("block")}


@app.post("/api/rules")
async def rule_add(req: Request):
    guard_write(req)
    body = await req.json()
    kind = body.get("kind")
    value = str(body.get("value") or "").strip()
    if kind not in ("allow", "block"):
        raise HTTPException(400, {"error": "kind", "message": "סוג כלל לא מוכר"})
    try:
        value = str(ipaddress.ip_network(value, strict=False)) if kind == "allow" else str(ipaddress.ip_address(value))
    except ValueError:
        raise HTTPException(400, {"error": "value", "message": "כתובת או טווח לא תקינים"})
    if kind == "block" and not np.is_public(value):
        raise HTTPException(409, {"error": "private", "message": "חוסמים יציאה רק ליעד ציבורי."})
    minutes = int(body.get("minutes") or 0)
    store.set_rule(kind, value, str(body.get("note") or "")[:200], time.time() + minutes * 60 if minutes else 0, actor(req))
    store.event("rule", "info", f"{'הותרה' if kind == 'allow' else 'נחסמה יציאה ל'} {value}", str(body.get("note") or ""), value)
    if kind == "allow":
        try:
            store.unban(value, actor(req), "הותרה")
        except Exception:                                              # noqa: BLE001
            pass
    trust.refresh()
    write_desired()
    return {"ok": True}


@app.delete("/api/rules/{kind}/{value:path}")
def rule_drop(kind: str, value: str, req: Request):
    guard_write(req)
    ok = store.drop_rule(kind, value)
    trust.refresh()
    write_desired()
    return {"ok": ok}


@app.get("/api/settings")
def settings():
    return {"mode": mode(), "remote_control": REMOTE_CONTROL, "office": OFFICE, "geo": geo.status,
            "learning_until": store.get("learning_until", 0)}


@app.put("/api/settings")
async def settings_put(req: Request):
    guard_write(req)
    body = await req.json()
    m = body.get("mode")
    if m not in ("observe", "enforce"):
        raise HTTPException(400, {"error": "mode", "message": "מצב לא מוכר"})
    prev = mode()
    store.put("mode", m)
    if prev != m:
        # the bans that were only recorded become real (or the real ones stand down) at the next write
        with store.lock:
            store.db.execute("UPDATE ban SET mode=? WHERE active=1", (m,))
            store.db.commit()
        store.event("mode", "warn" if m == "enforce" else "info",
                    "האבטחה עברה לאכיפה" if m == "enforce" else "האבטחה עברה לצפייה", f"על ידי {actor(req)}")
    write_desired()
    return {"ok": True, "mode": m}


@app.get("/api/network")
def network():
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    applied = read_json(os.path.join(SENSOR, "applied.json"), {}) or {}
    published = {}
    try:
        for c in docker.containers():
            name = (c.get("Labels") or {}).get("com.docker.compose.service") or (c.get("Names") or ["?"])[0].lstrip("/")
            for p in c.get("Ports") or []:
                if p.get("PublicPort"):
                    published.setdefault((p.get("Type"), p.get("PublicPort")), set()).add(name)
    except DockerError:
        pass
    # one door, said once: a port open on 0.0.0.0 AND on :: is one row (it was every port twice)
    merged, seen = [], {}
    for row in facts.get("listen") or []:
        row["apps"] = sorted(published.get((row["proto"], row["port"]), set()))
        key = (row.get("proto"), row.get("port"), row.get("scope"), tuple(row["apps"]))
        if row.get("addr") in ("0.0.0.0", "::") and key in seen and seen[key].get("addr") in ("0.0.0.0", "::"):
            seen[key]["addr"] = "0.0.0.0 · ::"
            continue
        seen[key] = row
        merged.append(row)
    facts["listen"] = merged
    # a bridge's name is its network's (`br-1cb7e0fd3f54` is the office network), the id one line below
    bridges = {"docker0": "bridge"}
    try:
        for net in docker.get_json("/networks") or []:
            if net.get("Driver") == "bridge" and net.get("Id"):
                bridges["br-" + net["Id"][:12]] = net.get("Name") or ""
    except (DockerError, OSError, ValueError, TypeError):
        pass
    return {"facts": facts, "applied": applied, "office": OFFICE, "bridges": bridges}


@app.get("/api/host/overview")
def host_overview(containers: int = 1):
    facts = read_json(os.path.join(SENSOR, "facts.json"), {}) or {}
    return host.overview(hostname=facts.get("hostname") or "", with_containers=bool(containers))


@app.get("/api/herd")
def herd_view(hours: float = 24):
    rows = herd.each("security", f"/api/summary?hours={hours}")
    return {"office": OFFICE, "self": summary(hours), "offices": rows}


@app.get("/api/events")
def events(hours: float = 168, limit: int = 300):
    return {"rows": store.q("SELECT * FROM event WHERE ts>=? ORDER BY ts DESC LIMIT ?", (window(hours), max(1, min(limit, 2000))))}


@app.get("/timeline/spans")
def spans(hours: float | None = None, since: float | None = None):
    """The office timeline's lane «אבטחה» (contributed as SPAN_SOURCE_SECURITY): bans as spans (running
    while they hold), requests through the link door, new countries, faults. `?hours=` for the window,
    `?since=<ms>` for what changed."""
    t0 = (since / 1000.0) if since else window(hours or 24)
    out = []
    for b in store.q("SELECT ip, jail, reason, since, until, mode, active FROM ban WHERE since>=? OR active=1 ORDER BY since DESC LIMIT 1000", (t0,)):
        end = None if b["active"] and (not b["until"] or b["until"] > time.time()) else (b["until"] or b["since"])
        out.append({"id": f"ban:{b['ip']}:{int(b['since'])}", "svc": "חסימות", "svcid": b["ip"],
                    "label": f"{b['ip']} · {JAIL_HE.get(b['jail'], b['jail'])}", "s": int(b["since"] * 1000),
                    "e": int(end * 1000) if end else None,
                    "status": ("running" if b["mode"] == "enforce" else "waiting") if end is None else "success",
                    "meta": {"reason": b["reason"], "mode": b["mode"], "office": OFFICE}})
    for h in store.q("SELECT ts, office, app, user, method, path, status, ms FROM hit WHERE src='door' AND ts>=? ORDER BY ts DESC LIMIT 1500", (t0,)):
        out.append({"id": f"door:{int(h['ts'] * 1e6)}", "svc": f"קישור · {h['office']}", "svcid": h["office"],
                    "label": f"{h['app']} {h['method']} {h['path'][:60]}", "s": int(h["ts"] * 1000), "e": int(h["ts"] * 1000 + (h["ms"] or 1)),
                    "status": "error" if h["status"] >= 500 else ("canceled" if h["status"] >= 400 else "success"),
                    "meta": {"office": h["office"], "app": h["app"], "user": h["user"], "code": h["status"]}})
    for e in store.q("SELECT ts, kind, level, title, detail, ip FROM event WHERE ts>=? AND kind IN ('country','sensor','fault','mode') ORDER BY ts DESC LIMIT 300", (t0,)):
        out.append({"id": f"ev:{e['kind']}:{int(e['ts'] * 1000)}", "svc": "אירועי אבטחה", "svcid": e["kind"], "label": e["title"],
                    "s": int(e["ts"] * 1000), "e": int(e["ts"] * 1000) + 1,
                    "status": "error" if e["level"] == "error" else ("waiting" if e["level"] == "warn" else "success"),
                    "meta": {"detail": e["detail"], "ip": e["ip"]}})
    return {"spans": out, "reachable": True, "total": len(out)}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def page(path: str):
    """A view opened at its path (G83: the console frames `/a/security/<view>/<arg>`) is the page,
    which moves the path into its hash. Declared last, so every API answers first; an unknown
    `api/…` stays a JSON 404."""
    if path.startswith(("api/", "static/")):
        return JSONResponse({"error": "not-found", "message": "לא נמצא"}, status_code=404)
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


@app.exception_handler(HTTPException)
async def _http_error(_req: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": "error", "message": str(exc.detail)}
    return JSONResponse(detail, status_code=exc.status_code)
