#!/usr/bin/env python3
"""security-sensor — the office's eyes and hands on its own machine. One process in the HOST's network
namespace, with exactly two capabilities (NET_ADMIN for the kernel's tables, NET_RAW for the sniffer),
no published port and no listener of any kind: it reads the kernel and writes files, and the security
app reads those files. Nothing on the network can talk to it.

What it watches
  connections   every connection the kernel tracks (`conntrack -E`): who opened it, to where, on
                which port — the outbound map, and inbound that never touches the edge (SSH, mail,
                the link's UDP).
  names         the DNS answers the machine receives and the server name of every TLS connection it
                opens — so an address on the map reads `api.github.com`, not `93.184.216.21`. A kernel
                filter (netparse.BPF_DNS_SNI) hands it those packets and nothing else.
  sign-ins      the machine's sshd, from its journal (accepted keys by fingerprint, failures).
  facts         interfaces, routes, the gateway, every listening socket, the router behind the
                gateway (its web page, its open ports, UPnP port forwards when the router speaks it).

What it does
  enforce       one nftables table of its own, `inet dgo_security`: a ban set dropped at the very
                first hook (prerouting, priority -300 — before docker's NAT, before ufw, before the
                edge) and a block set for outbound destinations. Bans carry their own timeout in the
                kernel, so a crashed app cannot leave anyone banned for ever. The table is built in
                one nft transaction and never deleted while running: there is no instant in which a
                rule that should hold does not (the link firewall learned that, cyc-203).

Files (SENSOR_DIR, a volume shared with the app)
  desired.json  ← the app: {mode: observe|enforce, bans: [{ip, until}], blocks: [{ip, until}]}
  applied.json  → what the kernel holds now, and its drop counters
  facts.json    → the machine's network facts, every 30 s
  spool/*.json  → batches of flows, names and sign-ins, every 5 s; the app consumes and deletes them
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from xml.etree import ElementTree

import netparse as np

SENSOR_DIR = os.environ.get("SENSOR_DIR", "/sensor")
JOURNAL_DIR = os.environ.get("SENSOR_JOURNAL_DIR", "/host/journal")
SSH_DIR = os.environ.get("SENSOR_SSH_DIR", "/host/ssh")
ROUTER_HINTS = [x.strip() for x in os.environ.get("SECURITY_ROUTER_HINTS", "").split(",") if x.strip()]
FLUSH_EVERY = 5
FACTS_EVERY = 30
ROUTER_EVERY = 300
NFT_EVERY = 2
TABLE = "inet dgo_security"
STOP = threading.Event()


def log(msg: str) -> None:
    print(f"[sensor] {msg}", flush=True)


def write_json(path: str, doc) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ── nftables ─────────────────────────────────────────────────────────────────────────────────────
def _ban_ok(ip: str) -> str | None:
    """An address the kernel may hold: public, unicast, written canonically. Anything else is dropped
    here so that a malformed or hostile value can never reach the nft script."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None
    return str(a) if np.is_public(str(a)) else None


def nft_script(desired: dict, now: float) -> str:
    enforce = (desired or {}).get("mode") == "enforce"
    lines = [
        f"add table {TABLE}",
        f"add set {TABLE} ban4 {{ type ipv4_addr; flags timeout; }}",
        f"add set {TABLE} ban6 {{ type ipv6_addr; flags timeout; }}",
        f"add set {TABLE} block4 {{ type ipv4_addr; flags timeout; }}",
        f"add set {TABLE} block6 {{ type ipv6_addr; flags timeout; }}",
        f"add chain {TABLE} guard_in {{ type filter hook prerouting priority -300; policy accept; }}",
        f"add chain {TABLE} guard_fwd {{ type filter hook forward priority -300; policy accept; }}",
        f"add chain {TABLE} guard_out {{ type filter hook output priority -300; policy accept; }}",
        f"flush chain {TABLE} guard_in",
        f"flush chain {TABLE} guard_fwd",
        f"flush chain {TABLE} guard_out",
        f"add rule {TABLE} guard_in ip saddr @ban4 counter drop",
        f"add rule {TABLE} guard_in ip6 saddr @ban6 counter drop",
        f"add rule {TABLE} guard_fwd ip daddr @block4 counter drop",
        f"add rule {TABLE} guard_fwd ip6 daddr @block6 counter drop",
        f"add rule {TABLE} guard_out ip daddr @block4 counter drop",
        f"add rule {TABLE} guard_out ip6 daddr @block6 counter drop",
        f"flush set {TABLE} ban4",
        f"flush set {TABLE} ban6",
        f"flush set {TABLE} block4",
        f"flush set {TABLE} block6",
    ]
    if enforce:
        for key, setname in (("bans", "ban"), ("blocks", "block")):
            v4, v6 = [], []
            for item in (desired.get(key) or []):
                ip = _ban_ok(item.get("ip"))
                if not ip:
                    continue
                until = float(item.get("until") or 0)
                if until and until <= now:
                    continue
                el = f"{ip} timeout {max(1, int(until - now))}s" if until else ip
                (v6 if ":" in ip else v4).append(el)
            for fam, items in (("4", v4), ("6", v6)):
                for i in range(0, len(items), 400):
                    lines.append(f"add element {TABLE} {setname}{fam} {{ {', '.join(items[i:i + 400])} }}")
    return "\n".join(lines) + "\n"


# ── volume: bytes per public address, counted in the kernel ─────────────────────────────────────
# conntrack's byte counters are a host-wide switch (net.netfilter.nf_conntrack_acct) that a container
# may not flip, and the screen said «we see connections, not volumes». So the volume is counted in this
# sensor's OWN table: four dynamic sets — out and in, IPv4 and IPv6 — one element per public address,
# each element with its own counter, refreshed by one rule per direction. It is applied as a SEPARATE
# script: were it refused (an old kernel, an old nft), the ban rules are untouched — enforcement never
# depends on accounting. An element nobody talked to for two hours expires by itself.
_NOT_PUBLIC4 = ("{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, "
                "192.168.0.0/16, 224.0.0.0/3 }")
_NOT_PUBLIC6 = "{ ::1/128, ::ffff:0:0/96, fc00::/7, fe80::/10, ff00::/8 }"
VOL_SETS = ("vol_out4", "vol_in4", "vol_out6", "vol_in6")
VOL_EVERY = 30


def vol_script() -> str:
    lines = [f"add table {TABLE}"]
    for name in VOL_SETS:
        typ = "ipv6_addr" if name.endswith("6") else "ipv4_addr"
        lines.append(f"add set {TABLE} {name} {{ type {typ}; size 65536; flags dynamic,timeout; timeout 2h; }}")
    lines += [
        # after every NAT (postrouting 300): the destination is the real one, from the host and from any app
        f"add chain {TABLE} vol_post {{ type filter hook postrouting priority 300; policy accept; }}",
        # right after the ban chain (prerouting -300): what a banned address sends is not volume, it is dropped
        f"add chain {TABLE} vol_pre {{ type filter hook prerouting priority -290; policy accept; }}",
        f"flush chain {TABLE} vol_post",
        f"flush chain {TABLE} vol_pre",
        f"add rule {TABLE} vol_post ip daddr != {_NOT_PUBLIC4} update @vol_out4 {{ ip daddr counter }}",
        f"add rule {TABLE} vol_post ip6 daddr != {_NOT_PUBLIC6} update @vol_out6 {{ ip6 daddr counter }}",
        f"add rule {TABLE} vol_pre ip saddr != {_NOT_PUBLIC4} update @vol_in4 {{ ip saddr counter }}",
        f"add rule {TABLE} vol_pre ip6 saddr != {_NOT_PUBLIC6} update @vol_in6 {{ ip6 saddr counter }}",
    ]
    return "\n".join(lines) + "\n"


def vol_elements(doc: dict) -> dict:
    """`nft -j list set` → {address: (packets, bytes)}; an element without a counter is skipped."""
    out = {}
    for item in (doc or {}).get("nftables", []):
        s = item.get("set") if isinstance(item, dict) else None
        if not s:
            continue
        for el in s.get("elem") or []:
            e = el.get("elem") if isinstance(el, dict) else None
            if not isinstance(e, dict) or not isinstance(e.get("val"), str):
                continue
            c = e.get("counter") or {}
            out[e["val"]] = (int(c.get("packets") or 0), int(c.get("bytes") or 0))
    return out


class Volume:
    """Reads the counters and hands on what grew since the last reading. The last reading is kept on
    disk: the sets outlive this process, so after a restart a delta counted from zero would report every
    byte a second time."""

    def __init__(self):
        self.ok = None
        self.error = ""
        self.addrs = 0
        self.applied = 0.0
        self.prev_path = os.path.join(SENSOR_DIR, "vol-prev.json")
        prev = read_json(self.prev_path, {}) or {}
        self.prev = {k: tuple(v) for k, v in prev.items() if isinstance(v, list) and len(v) == 2}

    def ensure(self, now: float) -> None:
        if self.ok and now - self.applied < 600:
            return
        try:
            r = subprocess.run(["nft", "-f", "-"], input=vol_script().encode(), capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.ok, self.error = False, f"{type(e).__name__}: {e}"[:300]
            return
        if r.returncode != 0:
            self.ok, self.error = False, r.stderr.decode(errors="replace").strip()[:300]
            return
        self.ok, self.error, self.applied = True, "", now

    def read(self) -> list:
        readings = {}
        for name in VOL_SETS:
            try:
                r = subprocess.run(["nft", "-j", "list", "set", "inet", "dgo_security", name], capture_output=True, timeout=10)
                readings[name] = vol_elements(json.loads(r.stdout or b"{}"))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                continue
        return self.step(readings)

    def step(self, readings: dict) -> list:
        """{set: {address: (packets, bytes)}} → the growth since the last reading, one row per address."""
        rows: dict = {}
        seen: dict = {}
        for name, els in readings.items():
            direction = "out" if "_out" in name else "in"
            for ip, (pk, by) in els.items():
                key = f"{name}|{ip}"
                seen[key] = (pk, by)
                ppk, pby = self.prev.get(key, (0, 0))
                if by < pby or pk < ppk:              # the element expired and came back: its counter restarted
                    ppk, pby = 0, 0
                if by > pby:
                    row = rows.setdefault(ip, {"ip": ip, "out": 0, "in": 0, "pout": 0, "pin": 0})
                    row[direction] += by - pby
                    row["p" + direction] += pk - ppk
        self.prev, self.addrs = seen, len({k.split("|", 1)[1] for k in seen})
        write_json(self.prev_path, {k: list(v) for k, v in seen.items()})
        return list(rows.values())


class Nft:
    def __init__(self):
        self.ok = None
        self.error = ""
        self.applied_hash = None
        self.last_apply = 0.0

    def reconcile(self, now: float) -> None:
        desired = read_json(os.path.join(SENSOR_DIR, "desired.json"), {}) or {}
        script = nft_script(desired, now)
        h = hashlib.sha256(json.dumps(desired, sort_keys=True).encode()).hexdigest()
        # re-apply when the wish changed, and once a minute regardless (a timeout the app shortened,
        # a table somebody flushed by hand)
        if h == self.applied_hash and now - self.last_apply < 60:
            return
        try:
            r = subprocess.run(["nft", "-f", "-"], input=script.encode(), capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.ok, self.error = False, f"{type(e).__name__}: {e}"
            return
        if r.returncode != 0:
            self.ok, self.error = False, r.stderr.decode(errors="replace").strip()[:400]
            log(f"nft refused the script: {self.error}")
            return
        self.ok, self.error = True, ""
        self.applied_hash, self.last_apply = h, now
        mode = desired.get("mode") or "observe"
        bans = len(desired.get("bans") or []) if mode == "enforce" else 0
        blocks = len(desired.get("blocks") or []) if mode == "enforce" else 0
        write_json(os.path.join(SENSOR_DIR, "applied.json"),
                   {"at": now, "ok": True, "mode": mode, "bans": bans, "blocks": blocks, "counters": self.counters()})

    def counters(self) -> dict:
        out = {}
        try:
            r = subprocess.run(["nft", "-j", "list", "table", "inet", "dgo_security"], capture_output=True, timeout=10)
            doc = json.loads(r.stdout or b"{}")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return out
        for item in doc.get("nftables", []):
            rule = item.get("rule")
            if not rule:
                continue
            setname = None
            pk = by = 0
            for ex in rule.get("expr", []):
                m = ex.get("match")
                if m and isinstance(m.get("right"), str) and m["right"].startswith("@"):
                    setname = m["right"][1:]
                c = ex.get("counter")
                if c:
                    pk, by = c.get("packets", 0), c.get("bytes", 0)
            if setname:
                key = f"{rule.get('chain')}:{setname}"
                out[key] = {"packets": pk, "bytes": by}
        return out


# ── local addresses ──────────────────────────────────────────────────────────────────────────────
class Local:
    """The machine's own addresses and the subnets behind it (docker bridges): what makes a flow
    "ours going out" or "someone coming in"."""

    def __init__(self):
        self.addrs: set = set()
        self.nets: list = []
        self.ifaces: list = []
        self.refresh()

    def refresh(self) -> None:
        try:
            r = subprocess.run(["ip", "-j", "addr"], capture_output=True, timeout=10)
            doc = json.loads(r.stdout or b"[]")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        addrs, nets, ifaces = set(), [], []
        for it in doc:
            entry = {"name": it.get("ifname"), "state": it.get("operstate"), "mac": it.get("address"), "addrs": []}
            for a in it.get("addr_info", []):
                local = a.get("local")
                if not local:
                    continue
                addrs.add(local)
                entry["addrs"].append(f"{local}/{a.get('prefixlen')}")
                try:
                    net = ipaddress.ip_network(f"{local}/{a.get('prefixlen')}", strict=False)
                    if not net.is_loopback:
                        nets.append(net)
                except ValueError:
                    pass
            ifaces.append(entry)
        self.addrs, self.nets, self.ifaces = addrs, nets, ifaces

    def is_local(self, ip: str) -> bool:
        if ip in self.addrs:
            return True
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a in n for n in self.nets if n.version == a.version)


# ── the collector: connections, names, sign-ins ──────────────────────────────────────────────────
class Collector:
    def __init__(self, local: Local):
        self.local = local
        self.lock = threading.Lock()
        self.flows: dict = {}
        self.names: dict = {}
        self.sni: dict = {}
        self.auth: list = []
        self.health = {"conntrack": {"ok": None, "error": "", "events": 0},
                       "sniffer": {"ok": None, "error": "", "packets": 0},
                       "journal": {"ok": None, "error": "", "lines": 0}}
        self._seen_dns: dict = {}

    # conntrack ───────────────────────────────────────────────────────────────────────────────────
    def conntrack_loop(self) -> None:
        h = self.health["conntrack"]
        while not STOP.is_set():
            try:
                p = subprocess.Popen(["conntrack", "-E", "-e", "NEW,DESTROY", "-o", "timestamp,extended"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            except OSError as e:
                h.update(ok=False, error=f"conntrack: {e}")
                STOP.wait(60)
                continue
            h.update(ok=True, error="")
            for line in p.stdout:
                if STOP.is_set():
                    break
                ev = np.conntrack_line(line)
                if ev:
                    h["events"] += 1
                    self._flow(ev)
            err = (p.stderr.read() or "").strip() if p.stderr else ""
            p.wait()
            h.update(ok=False, error=(err or f"conntrack exited {p.returncode}")[:300])
            STOP.wait(10)

    def _flow(self, ev: dict) -> None:
        src, dst = ev["src"], ev["dst"]
        if np.is_public(dst) and self.local.is_local(src):
            direction, key_ip = "out", dst
        elif np.is_public(src) and self.local.is_local(dst):
            direction, key_ip = "in", src
        else:
            return
        key = (direction, src, dst, ev.get("dport") or 0, ev.get("proto") or "?")
        ts = ev.get("ts") or time.time()
        with self.lock:
            f = self.flows.get(key)
            if not f:
                f = self.flows[key] = {"dir": direction, "src": src, "dst": dst, "dport": ev.get("dport") or 0,
                                       "proto": ev.get("proto") or "?", "first": ts, "last": ts, "n": 0,
                                       "bytes_out": 0, "bytes_in": 0}
            if ev["kind"] == "NEW":
                f["n"] += 1
            f["last"] = max(f["last"], ts)
            f["bytes_out"] += ev.get("bytes_out") or 0
            f["bytes_in"] += ev.get("bytes_in") or 0

    # sniffer ─────────────────────────────────────────────────────────────────────────────────────
    def sniff_loop(self) -> None:
        h = self.health["sniffer"]
        while not STOP.is_set():
            try:
                s = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0800))
                self._attach_filter(s)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                s.settimeout(1.0)
            except (OSError, AttributeError) as e:
                h.update(ok=False, error=f"packet socket: {e}")
                STOP.wait(60)
                continue
            h.update(ok=True, error="")
            try:
                while not STOP.is_set():
                    try:
                        buf = s.recv(65535)
                    except socket.timeout:
                        continue
                    h["packets"] += 1
                    self._packet(buf)
            except OSError as e:
                h.update(ok=False, error=f"recv: {e}")
            finally:
                s.close()
            STOP.wait(5)

    @staticmethod
    def _attach_filter(s: socket.socket) -> None:
        class SockFilter(ctypes.Structure):
            _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]

        class SockFprog(ctypes.Structure):
            _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(SockFilter))]

        prog = np.BPF_DNS_SNI
        arr = (SockFilter * len(prog))(*[SockFilter(*ins) for ins in prog])
        fprog = SockFprog(len(prog), ctypes.cast(arr, ctypes.POINTER(SockFilter)))
        # SO_ATTACH_FILTER: the kernel copies the program during this call; `arr` is alive until we return
        s.setsockopt(socket.SOL_SOCKET, 26, bytes(fprog))

    def _packet(self, buf: bytes) -> None:
        p = np.ipv4_packet(buf)
        if not p:
            return
        now = time.time()
        if p["proto"] == "udp" and p["sport"] == 53:
            a = np.dns_answer(p["payload"])
            if not a or not a["ips"]:
                return
            # one answer is seen on several interfaces (veth, bridge, uplink) — keep the copy addressed
            # to the most specific querier (a container's address beats the host's after NAT)
            sig = (a["id"], a["name"], tuple(a["ips"]))
            prev = self._seen_dns.get(sig)
            querier = p["dst"]
            if prev and now - prev[0] < 3 and (self.local.is_local(prev[1]) and not querier.startswith("172.")):
                return
            self._seen_dns[sig] = (now, querier)
            if len(self._seen_dns) > 5000:
                self._seen_dns = {k: v for k, v in self._seen_dns.items() if now - v[0] < 10}
            with self.lock:
                for ip in a["ips"]:
                    key = (a["name"], ip, querier)
                    n = self.names.get(key)
                    if n:
                        n["last"], n["n"] = now, n["n"] + 1
                    else:
                        self.names[key] = {"name": a["name"], "ip": ip, "querier": querier, "resolver": p["src"],
                                           "cnames": a["cnames"][:4], "ttl": a["ttl"], "first": now, "last": now, "n": 1}
        elif p["proto"] == "tcp" and p["dport"] == 443:
            name = np.client_hello_sni(p["payload"])
            if not name:
                return
            with self.lock:
                key = (name, p["dst"], p["src"])
                n = self.sni.get(key)
                if n:
                    n["last"], n["n"] = now, n["n"] + 1
                else:
                    self.sni[key] = {"name": name, "ip": p["dst"], "src": p["src"], "first": now, "last": now, "n": 1}

    # journal ─────────────────────────────────────────────────────────────────────────────────────
    def journal_loop(self) -> None:
        h = self.health["journal"]
        if not os.path.isdir(JOURNAL_DIR) or not os.listdir(JOURNAL_DIR):
            h.update(ok=False, error="no journal on this machine")
            return
        while not STOP.is_set():
            try:
                p = subprocess.Popen(["journalctl", "-D", JOURNAL_DIR, "-f", "-n", "0", "-o", "json",
                                      "SYSLOG_IDENTIFIER=sshd", "+", "SYSLOG_IDENTIFIER=sshd-session"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            except OSError as e:
                h.update(ok=False, error=f"journalctl: {e}")
                STOP.wait(120)
                continue
            h.update(ok=True, error="")
            for line in p.stdout:
                if STOP.is_set():
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                msg = d.get("MESSAGE")
                if not isinstance(msg, str):
                    continue
                h["lines"] += 1
                ev = np.sshd_message(msg)
                if ev:
                    try:
                        ev["ts"] = int(d.get("__REALTIME_TIMESTAMP") or 0) / 1e6 or time.time()
                    except ValueError:
                        ev["ts"] = time.time()
                    with self.lock:
                        self.auth.append(ev)
                        if len(self.auth) > 20000:
                            self.auth = self.auth[-10000:]
            err = (p.stderr.read() or "").strip() if p.stderr else ""
            p.wait()
            h.update(ok=False, error=(err or f"journalctl exited {p.returncode}")[:300])
            STOP.wait(30)

    # the spool ───────────────────────────────────────────────────────────────────────────────────
    def drain(self) -> dict | None:
        with self.lock:
            batch = {"flows": list(self.flows.values()), "names": list(self.names.values()),
                     "sni": list(self.sni.values()), "auth": self.auth}
            self.flows, self.names, self.sni, self.auth = {}, {}, {}, []
        if not any(batch.values()):
            return None
        batch["at"] = time.time()
        return batch


# ── facts ────────────────────────────────────────────────────────────────────────────────────────
def default_gateway() -> str:
    try:
        with open("/proc/net/route", encoding="ascii") as fh:
            for line in fh.readlines()[1:]:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<L", int(parts[2], 16)))
    except OSError:
        pass
    return ""


def listening() -> list:
    out = []
    seen = set()
    for fname, proto in (("tcp", "tcp"), ("tcp6", "tcp"), ("udp", "udp"), ("udp6", "udp")):
        try:
            with open(f"/proc/net/{fname}", encoding="ascii") as fh:
                rows = fh.readlines()[1:]
        except OSError:
            continue
        for row in rows:
            p = row.split()
            if len(p) < 4:
                continue
            local, rem, st = p[1], p[2], p[3]
            if proto == "tcp" and st != "0A":
                continue
            if proto == "udp" and not rem.endswith(":0000"):
                continue
            hexip, hexport = local.split(":")
            port = int(hexport, 16)
            if len(hexip) == 8:
                ip = socket.inet_ntoa(struct.pack("<L", int(hexip, 16)))
            else:
                raw = bytes.fromhex(hexip)
                ip = str(ipaddress.IPv6Address(b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))))
            key = (proto, ip, port)
            if key in seen:
                continue
            seen.add(key)
            out.append({"proto": proto, "addr": ip, "port": port,
                        "scope": "all" if ip in ("0.0.0.0", "::") else ("loopback" if ip.startswith("127.") or ip == "::1" else "address")})
    return sorted(out, key=lambda r: (r["scope"] != "all", r["port"]))


def ssh_keys() -> list:
    out = []
    path = os.path.join(SSH_DIR, "authorized_keys")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2 or line.lstrip().startswith("#"):
            continue
        # options may precede the key type; find the first token that looks like a key type
        for i, tok in enumerate(parts):
            if tok.startswith(("ssh-", "ecdsa-", "sk-")) and i + 1 < len(parts):
                try:
                    blob = base64.b64decode(parts[i + 1])
                except ValueError:
                    break
                fp = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
                out.append({"type": tok, "fp": fp, "comment": " ".join(parts[i + 2:])[:80],
                            "options": i > 0})
                break
    return out


def conntrack_stats() -> dict:
    def rd(p):
        try:
            with open(p, encoding="ascii") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None
    return {"count": rd("/proc/sys/net/netfilter/nf_conntrack_count"),
            "max": rd("/proc/sys/net/netfilter/nf_conntrack_max"),
            "acct": rd("/proc/sys/net/netfilter/nf_conntrack_acct")}


# ── the router behind the gateway ────────────────────────────────────────────────────────────────
_TITLE = re.compile(rb"<title[^>]*>([^<]{0,120})</title>", re.I)
_MGMT_PORTS = (21, 22, 23, 53, 80, 443, 1900, 5000, 7547, 8080, 8443, 49152, 49000, 52869, 37215)


def _http_peek(url: str, limit: int = 65536) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "dgo-security/1"})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:   # noqa: S310 — a fixed private address
            body = r.read(limit)
            return {"status": r.status, "server": r.headers.get("Server", ""), "url": r.geturl(),
                    "title": (_TITLE.search(body).group(1).decode("utf-8", "replace").strip() if _TITLE.search(body) else "")}
    except urllib.error.HTTPError as e:
        # a management page that refuses (401 for a password, 403) still says who it is: its server and its title
        body = e.read(limit) or b""
        m = _TITLE.search(body)
        return {"status": e.code, "server": e.headers.get("Server", "") if e.headers else "", "url": url,
                "title": m.group(1).decode("utf-8", "replace").strip() if m else ""}
    except (urllib.error.URLError, OSError, ValueError):                  # a router answers in many ways
        return {"error": "אין תשובה מדף הניהול"}


def _safe_xml(raw: bytes):
    if len(raw) > 131072 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return None
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def upnp(ip: str) -> dict | None:
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 93.184.216.22:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.5)
    location = ""
    try:
        s.sendto(msg, (ip, 1900))
        data, _ = s.recvfrom(4096)
        for line in data.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()
    except OSError:
        return None
    finally:
        s.close()
    if not location.startswith(f"http://{ip}"):
        return {"answered": True, "location": "", "note": "the description is not on the gateway"} if location else None
    try:
        with urllib.request.urlopen(location, timeout=4) as r:      # noqa: S310
            root = _safe_xml(r.read(131072))
    except urllib.error.HTTPError as e:
        e.read(4096)                                                 # the gateway's own refusal, drained
        return {"answered": True, "location": location, "status": e.code}
    except (urllib.error.URLError, OSError, ValueError):
        return {"answered": True, "location": location}
    if root is None:
        return {"answered": True, "location": location}
    dev = {}
    services = []
    for el in root.iter():
        t = _local(el.tag)
        if t in ("friendlyName", "manufacturer", "modelName", "modelNumber") and t not in dev:
            dev[t] = (el.text or "").strip()[:80]
        if t == "service":
            svc = {_local(c.tag): (c.text or "").strip() for c in el}
            services.append(svc)
    out = {"answered": True, "device": dev, "mappings": [], "external_ip": ""}
    base = location.split("/", 3)
    origin = "/".join(base[:3])
    for svc in services:
        st = svc.get("serviceType", "")
        if "WANIPConnection" in st or "WANPPPConnection" in st:
            ctl = svc.get("controlURL", "")
            url = ctl if ctl.startswith("http") else origin + ("" if ctl.startswith("/") else "/") + ctl
            ext = _soap(url, st, "GetExternalIPAddress", {})
            out["external_ip"] = (ext or {}).get("NewExternalIPAddress", "")
            for i in range(64):
                m = _soap(url, st, "GetGenericPortMappingEntry", {"NewPortMappingIndex": str(i)})
                if not m:
                    break
                out["mappings"].append({"external_port": m.get("NewExternalPort"), "protocol": m.get("NewProtocol"),
                                        "client": m.get("NewInternalClient"), "internal_port": m.get("NewInternalPort"),
                                        "enabled": m.get("NewEnabled"), "description": (m.get("NewPortMappingDescription") or "")[:60],
                                        "lease": m.get("NewLeaseDuration")})
            break
    return out


def _soap(url: str, st: str, action: str, args: dict) -> dict | None:
    body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{st}">' + "".join(f"<{k}>{v}</{k}>" for k, v in args.items()) +
            f'</u:{action}></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{st}#{action}"'})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:            # noqa: S310
            root = _safe_xml(r.read(65536))
    except urllib.error.HTTPError as e:
        # a SOAP fault is a 500 whose body names the UPnP error: 713/714 = past the last port mapping —
        # the normal end of the list; any other code means the gateway refused this question
        fault = e.read(65536) or b""
        code = re.search(rb"<errorCode>(\d+)</errorCode>", fault)
        if code and code.group(1) not in (b"713", b"714"):
            log(f"upnp {action}: the gateway answered UPnP error {code.group(1).decode()}")
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if root is None:
        return None
    for el in root.iter():
        if _local(el.tag) == f"{action}Response":
            return {_local(c.tag): (c.text or "").strip() for c in el}
    return None


def router_probe(gateway: str) -> dict:
    cands = []
    for ip in [gateway] + ROUTER_HINTS:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_private and ip not in cands:
            cands.append(ip)
    out = {"at": time.time(), "candidates": cands, "routers": []}
    for ip in cands:
        open_ports = []
        for port in _MGMT_PORTS:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.6)
            try:
                if s.connect_ex((ip, port)) == 0:
                    open_ports.append(port)
            except OSError:
                pass
            finally:
                s.close()
        if not open_ports:
            continue
        # WHICH router this is. The first hop of a machine that runs the office inside a VM (the Mac's
        # engine, Windows' WSL) is the VIRTUAL router of its host, not the box on the shelf; the one the
        # owner declared (SECURITY_ROUTER_HINTS) is the physical one behind it.
        r = {"ip": ip, "open": open_ports, "role": "gateway" if ip == gateway else "declared"}
        if 80 in open_ports:
            r["http"] = _http_peek(f"http://{ip}/")
        elif 443 in open_ports:
            r["http"] = {"note": "https only"}
        r["upnp"] = upnp(ip)
        out["routers"].append(r)
    return out


def netdev() -> dict:
    """The machine's interface counters (bytes in and out since boot), for the resource view's network line."""
    out = {}
    try:
        with open("/proc/net/dev", encoding="ascii") as fh:
            for line in fh.readlines()[2:]:
                name, _, rest = line.partition(":")
                f = rest.split()
                if len(f) >= 9:
                    out[name.strip()] = {"rx": int(f[0]), "tx": int(f[8])}
    except (OSError, ValueError):
        pass
    return out


STUN_SERVER = os.environ.get("SECURITY_STUN", "stun.cloudflare.com:3478")


def public_address() -> str:
    """This machine's address as the internet sees it — one STUN binding request (RFC 5389), the same
    question WebRTC and every NAT-traversing link ask. It places the office on its own map. One UDP
    packet each way, once an hour, to the server SECURITY_STUN names (empty: never asked)."""
    if not STUN_SERVER:
        return ""
    host, _, port = STUN_SERVER.rpartition(":")
    txid = os.urandom(12)
    req = struct.pack(">HHI", 0x0001, 0, 0x2112A442) + txid
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    try:
        s.sendto(req, (host, int(port or 3478)))
        data, _ = s.recvfrom(2048)
    except (OSError, ValueError):
        return ""
    finally:
        s.close()
    if len(data) < 20 or data[8:20] != txid:
        return ""
    p = 20
    while p + 4 <= len(data):
        atype, alen = struct.unpack_from(">HH", data, p)
        val = data[p + 4:p + 4 + alen]
        if atype in (0x0020, 0x0001) and len(val) >= 8 and val[1] == 0x01:
            raw = struct.unpack(">I", val[4:8])[0]
            if atype == 0x0020:
                raw ^= 0x2112A442
            return socket.inet_ntoa(struct.pack(">I", raw))
        p += 4 + alen + ((4 - alen % 4) % 4)
    return ""


# ── main ─────────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    os.makedirs(os.path.join(SENSOR_DIR, "spool"), exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    local = Local()
    col = Collector(local)
    nft = Nft()
    vol = Volume()
    for target in (col.conntrack_loop, col.sniff_loop, col.journal_loop):
        threading.Thread(target=target, daemon=True).start()
    log(f"watching: {len(local.addrs)} addresses, {len(local.nets)} networks; spool {SENSOR_DIR}/spool")
    last_flush = last_facts = last_router = last_nft = last_netdev = last_stun = last_vol = 0.0
    router = {}
    public_ip = ""
    seq = 0
    pending_vol: list = []
    while not STOP.is_set():
        now = time.time()
        if now - last_vol >= VOL_EVERY:
            last_vol = now
            try:
                vol.ensure(now)
                if vol.ok:
                    pending_vol.extend(vol.read())
            except Exception as e:                                   # noqa: BLE001 — accounting never takes the loop down
                vol.ok, vol.error = False, repr(e)[:300]
        if now - last_netdev >= 10:
            last_netdev = now
            write_json(os.path.join(SENSOR_DIR, "netdev.json"), {"at": now, "ifaces": netdev()})
        if now - last_stun >= 3600:
            last_stun = now
            public_ip = public_address() or public_ip
        if now - last_nft >= NFT_EVERY:
            last_nft = now
            try:
                nft.reconcile(now)
            except Exception as e:                                   # noqa: BLE001 — never take the loop down
                nft.ok, nft.error = False, repr(e)[:300]
        if now - last_flush >= FLUSH_EVERY:
            last_flush = now
            batch = col.drain()
            if pending_vol:
                batch = batch or {"flows": [], "names": [], "sni": [], "auth": [], "at": now}
                batch["vol"], pending_vol = pending_vol, []
            if batch:
                seq += 1
                write_json(os.path.join(SENSOR_DIR, "spool", f"{int(now * 1000)}-{seq:06d}.json"), batch)
            # a spool nobody reads must not fill the disk: keep the newest 2000 batches
            try:
                files = sorted(os.listdir(os.path.join(SENSOR_DIR, "spool")))
                for f in files[:-2000]:
                    os.unlink(os.path.join(SENSOR_DIR, "spool", f))
            except OSError:
                pass
        if now - last_router >= ROUTER_EVERY:
            last_router = now
            try:
                router = router_probe(default_gateway())
            except Exception as e:                                   # noqa: BLE001
                router = {"at": now, "error": repr(e)[:200]}
        if now - last_facts >= FACTS_EVERY:
            last_facts = now
            local.refresh()
            write_json(os.path.join(SENSOR_DIR, "facts.json"), {
                "at": now, "hostname": socket.gethostname(), "kernel": os.uname().release, "public_ip": public_ip,
                "interfaces": local.ifaces, "gateway": default_gateway(), "listen": listening(),
                "conntrack": conntrack_stats(), "ssh_keys": ssh_keys(), "router": router,
                "health": {**col.health, "nft": {"ok": nft.ok, "error": nft.error},
                           "volume": {"ok": vol.ok, "error": vol.error, "addrs": vol.addrs}},
            })
        STOP.wait(1)
    log("stopped (the ban table stays: every element carries its own timeout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
