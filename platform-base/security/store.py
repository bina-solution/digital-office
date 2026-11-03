"""store — the security app's memory: one SQLite file in the app's volume, one lock, WAL.

What is kept, and for how long
  hit       every request that reached the edge (and every link-door request), raw, 3 days
  hit_day   the same, per (day, address, app, kind): 120 days — what the maps and tables read
  addr      one row per address ever seen: first/last, place, network, who signed in from it
  flow      outbound and inbound connections per (day, source, destination, port, protocol): 60 days
  name      what a destination is called (DNS answers, TLS server names): 60 days
  signin    sign-ins at the identity provider and on the machine's sshd: 120 days
  ban       the bans in force and those that ended (offences counted per address)
  rule      the owner's lists: always-allow, outbound blocks
  event     what the app decided or noticed (a ban, a new country, a sensor fault): 120 days
  kv        settings and cursors
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS hit(ts REAL, ip TEXT, kind TEXT, app TEXT, office TEXT, host TEXT, method TEXT,
  path TEXT, status INT, bytes INT, ms INT, ua TEXT, user TEXT, router TEXT, src TEXT);
CREATE INDEX IF NOT EXISTS hit_ts ON hit(ts);
CREATE INDEX IF NOT EXISTS hit_ip ON hit(ip, ts);
CREATE TABLE IF NOT EXISTS hit_day(day TEXT, ip TEXT, app TEXT, kind TEXT, office TEXT, n INT, fails INT,
  bytes INT, first REAL, last REAL, users TEXT, PRIMARY KEY(day, ip, app, kind, office));
CREATE INDEX IF NOT EXISTS hit_day_last ON hit_day(last);
CREATE TABLE IF NOT EXISTS addr(ip TEXT PRIMARY KEY, first REAL, last REAL, cc TEXT, city TEXT, lat REAL, lon REAL,
  asn INT, org TEXT, users TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS flow(day TEXT, dir TEXT, src TEXT, dst TEXT, port INT, proto TEXT, first REAL, last REAL,
  n INT, bytes_out INT, bytes_in INT, PRIMARY KEY(day, dir, src, dst, port, proto));
CREATE INDEX IF NOT EXISTS flow_last ON flow(last);
CREATE INDEX IF NOT EXISTS flow_dst ON flow(dst);
CREATE TABLE IF NOT EXISTS name(ip TEXT, name TEXT, via TEXT, first REAL, last REAL, n INT, PRIMARY KEY(ip, name));
CREATE TABLE IF NOT EXISTS vol(day TEXT, ip TEXT, bout INT, bin INT, pout INT, pin INT, last REAL, PRIMARY KEY(day, ip));
CREATE INDEX IF NOT EXISTS vol_last ON vol(last);
CREATE TABLE IF NOT EXISTS signin(ts REAL, ip TEXT, src TEXT, verdict TEXT, user TEXT, how TEXT, fp TEXT);
CREATE INDEX IF NOT EXISTS signin_ts ON signin(ts);
CREATE INDEX IF NOT EXISTS signin_ip ON signin(ip, ts);
CREATE TABLE IF NOT EXISTS ban(ip TEXT PRIMARY KEY, jail TEXT, reason TEXT, since REAL, until REAL, offences INT,
  mode TEXT, by TEXT, active INT);
CREATE TABLE IF NOT EXISTS ban_log(ts REAL, ip TEXT, jail TEXT, action TEXT, reason TEXT, until REAL, mode TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS rule(kind TEXT, value TEXT, note TEXT, since REAL, until REAL, by TEXT, PRIMARY KEY(kind, value));
CREATE TABLE IF NOT EXISTS event(ts REAL, kind TEXT, level TEXT, title TEXT, detail TEXT, ip TEXT, ref TEXT);
CREATE INDEX IF NOT EXISTS event_ts ON event(ts);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""

RETENTION = {"hit": 3, "hit_day": 120, "flow": 60, "vol": 60, "name": 60, "signin": 120, "event": 120, "ban_log": 365}


def day_of(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts or time.time()))


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            # `who`: the app a flow belonged to, named WHEN IT HAPPENED. Named at read time from the
            # container's address, a recreated container's reused address handed one app's traffic to
            # another (the GeoIP download showed as «computers», 2026-10-21).
            if "who" not in {r[1] for r in self.db.execute("PRAGMA table_info(flow)")}:
                self.db.execute("ALTER TABLE flow ADD COLUMN who TEXT")
            self.db.commit()

    # ── small helpers ────────────────────────────────────────────────────────────────────────────
    def q(self, sql: str, args=()) -> list:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()):
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def get(self, k: str, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        if not r:
            return default
        try:
            return json.loads(r["v"])
        except ValueError:
            return default

    def put(self, k: str, v) -> None:
        with self.lock:
            self.db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
            self.db.commit()

    # ── inbound ──────────────────────────────────────────────────────────────────────────────────
    def add_hits(self, hits: list, geo=None) -> None:
        if not hits:
            return
        with self.lock:
            cur = self.db.cursor()
            cur.executemany(
                "INSERT INTO hit(ts,ip,kind,app,office,host,method,path,status,bytes,ms,ua,user,router,src) "
                "VALUES(:ts,:ip,:kind,:app,:office,:host,:method,:path,:status,:bytes,:ms,:ua,:user,:router,:src)",
                [{**{"office": "", "host": "", "ua": "", "user": "", "router": "", "src": "edge", "bytes": 0, "ms": 0}, **h}
                 for h in hits])
            for h in hits:
                fail = 1 if int(h.get("status") or 0) >= 400 else 0
                users = json.dumps([h["user"]]) if h.get("user") else "[]"
                cur.execute(
                    "INSERT INTO hit_day(day,ip,app,kind,office,n,fails,bytes,first,last,users) VALUES(?,?,?,?,?,1,?,?,?,?,?) "
                    "ON CONFLICT(day,ip,app,kind,office) DO UPDATE SET n=n+1, fails=fails+excluded.fails, "
                    "bytes=bytes+excluded.bytes, last=MAX(last,excluded.last), first=MIN(first,excluded.first), "
                    "users=CASE WHEN excluded.users!='[]' AND instr(users, json_extract(excluded.users,'$[0]'))=0 "
                    "THEN json_insert(users,'$[#]',json_extract(excluded.users,'$[0]')) ELSE users END",
                    (day_of(h["ts"]), h["ip"], h.get("app") or "", h.get("kind") or "", h.get("office") or "", fail,
                     int(h.get("bytes") or 0), h["ts"], h["ts"], users))
                self._addr(cur, h["ip"], h["ts"], geo, h.get("user"))
            self.db.commit()

    def _addr(self, cur, ip: str, ts: float, geo, user=None) -> None:
        row = cur.execute("SELECT ip, users, cc FROM addr WHERE ip=?", (ip,)).fetchone()
        if row:
            if user and user not in (row["users"] or ""):
                users = json.loads(row["users"] or "[]")
                users.append(user)
                cur.execute("UPDATE addr SET last=MAX(last,?), users=? WHERE ip=?", (ts, json.dumps(users[-8:]), ip))
            else:
                cur.execute("UPDATE addr SET last=MAX(last,?) WHERE ip=?", (ts, ip))
            if row["cc"] is None and geo is not None:
                self._geo_fill(cur, ip, geo)
            return
        cur.execute("INSERT INTO addr(ip,first,last,users) VALUES(?,?,?,?)", (ip, ts, ts, json.dumps([user] if user else [])))
        if geo is not None:
            self._geo_fill(cur, ip, geo)

    def geo_backfill(self, geo, limit: int = 2000) -> int:
        """Place the addresses written while no location database was loaded (`cc` still NULL).

        `_addr` places a row when its address is seen AGAIN, so one that came once — most of what the edge's
        log is read back at a first start, before the database is downloaded — never got a place: on vps1's
        first hour 150 of 203 addresses read «לא ידוע» in the network view (2026-11-01). Returns how many
        were placed; none while there is still no database (the next pass tries again)."""
        with self.lock:
            cur = self.db.cursor()
            done = 0
            for r in cur.execute("SELECT ip FROM addr WHERE cc IS NULL LIMIT ?", (limit,)).fetchall():
                if not self._geo_fill(cur, r["ip"], geo):
                    break
                done += 1
            self.db.commit()
        return done

    @staticmethod
    def _geo_fill(cur, ip: str, geo) -> bool:
        """Place one row; False (and the row left unplaced) while no PLACE database is loaded. Only the ASN
        one is a lookup with no `cc`: writing that as '' would mark the address placed — as nowhere — for
        good, through the six hours until the city edition is fetched again (the second reader of DGO-1115)."""
        g = geo.lookup(ip) if geo else {}
        if g is None or (geo and "cc" not in g):
            return False
        cur.execute("UPDATE addr SET cc=?, city=?, lat=?, lon=?, asn=?, org=? WHERE ip=?",
                    (g.get("cc") or "", g.get("city") or "", g.get("lat"), g.get("lon"), g.get("asn"), g.get("org") or "", ip))
        return True

    # ── sign-ins ─────────────────────────────────────────────────────────────────────────────────
    def add_signins(self, rows: list, geo=None) -> None:
        if not rows:
            return
        with self.lock:
            cur = self.db.cursor()
            cur.executemany("INSERT INTO signin(ts,ip,src,verdict,user,how,fp) VALUES(:ts,:ip,:src,:verdict,:user,:how,:fp)",
                            [{"how": "", "fp": "", "user": "", **r} for r in rows])
            for r in rows:
                if r.get("ip"):
                    self._addr(cur, r["ip"], r["ts"], geo, r.get("user") if r.get("verdict") == "ok" else None)
            self.db.commit()

    def trusted_signins(self, days: int = 30) -> set:
        rows = self.q("SELECT DISTINCT ip FROM signin WHERE verdict='ok' AND ts > ?", (time.time() - days * 86400,))
        return {r["ip"] for r in rows}

    # ── outbound ─────────────────────────────────────────────────────────────────────────────────
    def add_flows(self, flows: list, geo=None) -> None:
        if not flows:
            return
        with self.lock:
            cur = self.db.cursor()
            for f in flows:
                cur.execute(
                    "INSERT INTO flow(day,dir,src,dst,port,proto,first,last,n,bytes_out,bytes_in,who) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(day,dir,src,dst,port,proto) DO UPDATE SET n=n+excluded.n, last=MAX(last,excluded.last), "
                    "bytes_out=bytes_out+excluded.bytes_out, bytes_in=bytes_in+excluded.bytes_in, "
                    "who=COALESCE(excluded.who, who)",
                    (day_of(f["first"]), f["dir"], f["src"], f["dst"], int(f.get("dport") or 0), f.get("proto") or "?",
                     f["first"], f["last"], int(f.get("n") or 0), int(f.get("bytes_out") or 0), int(f.get("bytes_in") or 0),
                     f.get("who")))
                other = f["dst"] if f["dir"] == "out" else f["src"]
                self._addr(cur, other, f["last"], geo)
            self.db.commit()

    def add_vol(self, rows: list, at: float) -> None:
        """Bytes and packets per public address and day, as the sensor's kernel counters grew."""
        if not rows:
            return
        day = day_of(at)
        with self.lock:
            cur = self.db.cursor()
            for r in rows:
                cur.execute(
                    "INSERT INTO vol(day,ip,bout,bin,pout,pin,last) VALUES(?,?,?,?,?,?,?) ON CONFLICT(day,ip) DO UPDATE SET "
                    "bout=bout+excluded.bout, bin=bin+excluded.bin, pout=pout+excluded.pout, pin=pin+excluded.pin, "
                    "last=MAX(last,excluded.last)",
                    (day, r["ip"], int(r.get("out") or 0), int(r.get("in") or 0), int(r.get("pout") or 0),
                     int(r.get("pin") or 0), at))
            self.db.commit()

    def vol_for(self, ips, day0: str) -> dict:
        """{address: {bout, bin}} summed from `day0` on."""
        ips = [i for i in set(ips) if i]
        out: dict = {}
        for i in range(0, len(ips), 400):
            chunk = ips[i:i + 400]
            for r in self.q(f"SELECT ip, SUM(bout) bout, SUM(bin) bin FROM vol WHERE day>=? AND ip IN ({','.join('?' * len(chunk))}) "
                            "GROUP BY ip", (day0, *chunk)):
                out[r["ip"]] = {"bout": r["bout"] or 0, "bin": r["bin"] or 0}
        return out

    def add_names(self, names: list) -> None:
        if not names:
            return
        with self.lock:
            cur = self.db.cursor()
            for n in names:
                cur.execute(
                    "INSERT INTO name(ip,name,via,first,last,n) VALUES(?,?,?,?,?,?) ON CONFLICT(ip,name) DO UPDATE SET "
                    "last=MAX(last,excluded.last), n=n+excluded.n",
                    (n["ip"], n["name"], n.get("via") or "dns", n["first"], n["last"], int(n.get("n") or 1)))
            self.db.commit()

    def names_for(self, ips) -> dict:
        ips = [i for i in set(ips) if i]
        out: dict = {}
        for i in range(0, len(ips), 400):
            chunk = ips[i:i + 400]
            rows = self.q(f"SELECT ip, name, n, via FROM name WHERE ip IN ({','.join('?' * len(chunk))}) ORDER BY n DESC", chunk)
            for r in rows:
                out.setdefault(r["ip"], []).append(r["name"])
        return out

    # ── bans and rules ───────────────────────────────────────────────────────────────────────────
    def ban(self, ip: str, jail: str, reason: str, seconds: int, mode: str, by: str) -> dict:
        now = time.time()
        with self.lock:
            prev = self.db.execute("SELECT offences FROM ban WHERE ip=?", (ip,)).fetchone()
            offences = (prev["offences"] if prev else 0) + 1
            until = now + seconds if seconds else 0
            self.db.execute(
                "INSERT INTO ban(ip,jail,reason,since,until,offences,mode,by,active) VALUES(?,?,?,?,?,?,?,?,1) "
                "ON CONFLICT(ip) DO UPDATE SET jail=excluded.jail, reason=excluded.reason, since=excluded.since, "
                "until=excluded.until, offences=excluded.offences, mode=excluded.mode, by=excluded.by, active=1",
                (ip, jail, reason, now, until, offences, mode, by))
            self.db.execute("INSERT INTO ban_log(ts,ip,jail,action,reason,until,mode,by) VALUES(?,?,?,?,?,?,?,?)",
                            (now, ip, jail, "ban", reason, until, mode, by))
            self.db.commit()
        return {"ip": ip, "jail": jail, "until": until, "offences": offences, "mode": mode}

    def offences(self, ip: str) -> int:
        r = self.one("SELECT offences FROM ban WHERE ip=?", (ip,))
        return r["offences"] if r else 0

    def unban(self, ip: str, by: str, why: str = "") -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE ban SET active=0, until=? WHERE ip=? AND active=1", (time.time(), ip))
            if cur.rowcount:
                self.db.execute("INSERT INTO ban_log(ts,ip,jail,action,reason,until,mode,by) VALUES(?,?,'','unban',?,0,'',?)",
                                (time.time(), ip, why, by))
            self.db.commit()
            return cur.rowcount > 0

    def expire_bans(self) -> list:
        now = time.time()
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT ip, jail FROM ban WHERE active=1 AND until>0 AND until<=?", (now,)).fetchall()]
            for r in rows:
                self.db.execute("UPDATE ban SET active=0 WHERE ip=?", (r["ip"],))
                self.db.execute("INSERT INTO ban_log(ts,ip,jail,action,reason,until,mode,by) VALUES(?,?,?,'expire','',0,'','clock')",
                                (now, r["ip"], r["jail"]))
            self.db.commit()
        return rows

    def active_bans(self) -> list:
        return self.q("SELECT b.*, a.cc, a.city, a.org FROM ban b LEFT JOIN addr a ON a.ip=b.ip "
                      "WHERE b.active=1 ORDER BY b.since DESC")

    def rules(self, kind: str | None = None) -> list:
        now = time.time()
        if kind:
            return self.q("SELECT * FROM rule WHERE kind=? AND (until=0 OR until>?) ORDER BY since DESC", (kind, now))
        return self.q("SELECT * FROM rule WHERE until=0 OR until>? ORDER BY since DESC", (now,))

    def set_rule(self, kind: str, value: str, note: str, until: float, by: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO rule(kind,value,note,since,until,by) VALUES(?,?,?,?,?,?) ON CONFLICT(kind,value) "
                            "DO UPDATE SET note=excluded.note, since=excluded.since, until=excluded.until, by=excluded.by",
                            (kind, value, note, time.time(), until, by))
            self.db.commit()

    def drop_rule(self, kind: str, value: str) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM rule WHERE kind=? AND value=?", (kind, value))
            self.db.commit()
            return cur.rowcount > 0

    # ── events ───────────────────────────────────────────────────────────────────────────────────
    def event(self, kind: str, level: str, title: str, detail: str = "", ip: str = "", ref: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO event(ts,kind,level,title,detail,ip,ref) VALUES(?,?,?,?,?,?,?)",
                            (time.time(), kind, level, title, detail[:600], ip, ref))
            self.db.commit()

    # ── retention ────────────────────────────────────────────────────────────────────────────────
    def retention(self) -> dict:
        now = time.time()
        out = {}
        with self.lock:
            for table, days in RETENTION.items():
                col = {"hit_day": "last", "flow": "last", "vol": "last", "name": "last", "ban_log": "ts"}.get(table, "ts")
                cur = self.db.execute(f"DELETE FROM {table} WHERE {col} < ?", (now - days * 86400,))
                out[table] = cur.rowcount
            self.db.execute("DELETE FROM addr WHERE last < ? AND ip NOT IN (SELECT ip FROM ban)", (now - 180 * 86400,))
            self.db.commit()
        return out


def ip_key(ip: str):
    try:
        return ipaddress.ip_address(ip)
    except ValueError:
        return None
