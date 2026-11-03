"""netparse — the pure parsers of the security app: no I/O, no clock, each one a function of bytes or text.

Everything the sensor and the app read from the outside world is parsed here, so every parser is
testable on a fixture (tests/selftest.py) and none of them can block, write or reach the network:

  conntrack_line(text)   one line of `conntrack -E -o timestamp,extended` → a flow event
  dns_answer(payload)    one DNS response (UDP payload) → the name asked and the addresses answered
  client_hello_sni(data) the first bytes of a TLS connection → the server name the client asked for
  ipv4_packet(buf)       one IPv4 packet (cooked capture) → protocol, addresses, ports, payload
  clf_line(text)         one traefik access-log line, common-log format OR json → a request record
  sshd_message(text)     one sshd journal message → (verdict, address, user, key fingerprint)
  authentik_event(text)  one authentik server log line → a sign-in event
  BPF_DNS_SNI            the kernel filter that hands the sniffer only DNS answers and TLS ClientHellos
"""
from __future__ import annotations

import ipaddress
import json
import re
import struct
from datetime import datetime, timezone

# ── conntrack ────────────────────────────────────────────────────────────────────────────────────
_CT_TS = re.compile(r"^\s*\[(\d+(?:\.\d+)?)\]\s*")
_CT_KIND = re.compile(r"\[(NEW|UPDATE|DESTROY)\]")
_CT_KV = re.compile(r"(src|dst|sport|dport|packets|bytes)=(\S+)")
_CT_PROTOS = ("tcp", "udp", "icmp", "icmpv6", "sctp", "udplite", "dccp", "gre")


def conntrack_line(line: str) -> dict | None:
    """`[1729485600.123456]  [NEW] ipv4 2 tcp 6 120 SYN_SENT src=A dst=B sport=1 dport=443 [UNREPLIED] src=B dst=C …`

    The first src/dst/sport/dport are the ORIGINAL direction (who opened it); the second set is the
    reply as the kernel expects it — after NAT, so the reply's dst is the address the outside world
    saw. packets/bytes appear only when the kernel counts them (nf_conntrack_acct=1)."""
    m = _CT_TS.match(line)
    ts = float(m.group(1)) if m else None
    k = _CT_KIND.search(line)
    if not k:
        return None
    proto = None
    for tok in line[k.end():].split():
        if tok in _CT_PROTOS:
            proto = tok
            break
    orig: dict = {}
    reply: dict = {}
    for key, val in _CT_KV.findall(line):
        side = orig if key not in orig else reply
        if key in side:
            continue
        side[key] = val
    if "src" not in orig or "dst" not in orig:
        return None
    out = {
        "ts": ts,
        "kind": k.group(1),
        "proto": proto or "?",
        "src": orig.get("src"),
        "dst": orig.get("dst"),
        "sport": _int(orig.get("sport")),
        "dport": _int(orig.get("dport")),
        "nat_src": reply.get("dst"),          # what the far end saw as the source (after SNAT)
        "packets_out": _int(orig.get("packets")),
        "bytes_out": _int(orig.get("bytes")),
        "packets_in": _int(reply.get("packets")),
        "bytes_in": _int(reply.get("bytes")),
    }
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── IPv4 packet (cooked AF_PACKET capture: the buffer starts at the IP header) ──────────────────
def ipv4_packet(buf: bytes) -> dict | None:
    if len(buf) < 20 or buf[0] >> 4 != 4:
        return None
    ihl = (buf[0] & 0x0F) * 4
    if ihl < 20 or len(buf) < ihl:
        return None
    proto = buf[9]
    src = ".".join(str(b) for b in buf[12:16])
    dst = ".".join(str(b) for b in buf[16:20])
    seg = buf[ihl:]
    if proto == 17 and len(seg) >= 8:
        sport, dport = struct.unpack_from(">HH", seg, 0)
        return {"proto": "udp", "src": src, "dst": dst, "sport": sport, "dport": dport, "payload": seg[8:]}
    if proto == 6 and len(seg) >= 20:
        sport, dport = struct.unpack_from(">HH", seg, 0)
        thl = (seg[12] >> 4) * 4
        if thl < 20 or len(seg) < thl:
            return None
        return {"proto": "tcp", "src": src, "dst": dst, "sport": sport, "dport": dport, "payload": seg[thl:]}
    return {"proto": str(proto), "src": src, "dst": dst, "sport": None, "dport": None, "payload": b""}


# ── DNS ──────────────────────────────────────────────────────────────────────────────────────────
def _dns_name(msg: bytes, off: int, depth: int = 0):
    labels = []
    jumped = False
    end = off
    guard = 0
    while True:
        guard += 1
        if guard > 128 or off >= len(msg):
            return None, end
        ln = msg[off]
        if ln == 0:
            off += 1
            if not jumped:
                end = off
            break
        if ln & 0xC0 == 0xC0:
            if off + 1 >= len(msg) or depth > 16:
                return None, end
            ptr = ((ln & 0x3F) << 8) | msg[off + 1]
            if not jumped:
                end = off + 2
            jumped = True
            off = ptr
            depth += 1
            continue
        off += 1
        if off + ln > len(msg):
            return None, end
        labels.append(msg[off:off + ln].decode("ascii", "replace").lower())
        off += ln
    return ".".join(labels), end


def dns_answer(payload: bytes) -> dict | None:
    """A DNS RESPONSE → {id, name, qtype, rcode, ips[], cnames[], ttl}. Queries and junk → None."""
    if len(payload) < 12:
        return None
    txid, flags, qd, an, _ns, _ar = struct.unpack_from(">HHHHHH", payload, 0)
    if not flags & 0x8000 or qd != 1:
        return None
    rcode = flags & 0x000F
    name, off = _dns_name(payload, 12)
    if not name or off + 4 > len(payload):
        return None
    qtype = struct.unpack_from(">H", payload, off)[0]
    off += 4
    ips: list = []
    cnames: list = []
    ttl_min = None
    for _ in range(min(an, 64)):
        _rname, off = _dns_name(payload, off)
        if off + 10 > len(payload):
            break
        rtype, _rclass, ttl, rdlen = struct.unpack_from(">HHIH", payload, off)
        off += 10
        rdata = payload[off:off + rdlen]
        rd_off = off
        off += rdlen
        if len(rdata) < rdlen:
            break
        if rtype == 1 and rdlen == 4:
            ips.append(".".join(str(b) for b in rdata))
        elif rtype == 28 and rdlen == 16:
            ips.append(str(ipaddress.IPv6Address(rdata)))
        elif rtype == 5:
            cname, _ = _dns_name(payload, rd_off)
            if cname:
                cnames.append(cname)
        else:
            continue
        ttl_min = ttl if ttl_min is None else min(ttl_min, ttl)
    return {"id": txid, "name": name, "qtype": qtype, "rcode": rcode, "ips": ips, "cnames": cnames,
            "ttl": ttl_min}


# ── TLS ClientHello → SNI ────────────────────────────────────────────────────────────────────────
def client_hello_sni(data: bytes) -> str | None:
    try:
        if len(data) < 9 or data[0] != 0x16 or data[5] != 0x01:
            return None
        p = 9                       # record header (5) + handshake type (1) + length (3)
        p += 2 + 32                 # client_version + random
        sid = data[p]
        p += 1 + sid
        cs = struct.unpack_from(">H", data, p)[0]
        p += 2 + cs
        comp = data[p]
        p += 1 + comp
        ext_total = struct.unpack_from(">H", data, p)[0]
        p += 2
        end = min(len(data), p + ext_total)
        while p + 4 <= end:
            etype, elen = struct.unpack_from(">HH", data, p)
            p += 4
            if etype == 0x0000:
                q = p + 2           # server_name_list length
                while q + 3 <= p + elen and q + 3 <= len(data):
                    ntype = data[q]
                    nlen = struct.unpack_from(">H", data, q + 1)[0]
                    q += 3
                    if ntype == 0 and q + nlen <= len(data):
                        name = data[q:q + nlen].decode("ascii", "replace").lower()
                        return name if _HOSTNAME.match(name) else None
                    q += nlen
                return None
            p += elen
    except (IndexError, struct.error):
        return None
    return None


_HOSTNAME = re.compile(r"^[a-z0-9_]([a-z0-9_.-]{0,251}[a-z0-9_])?\Z")

# ── the kernel filter: UDP from port 53, or a TCP segment to 443 whose payload opens a ClientHello ──
# A cooked (SOCK_DGRAM) AF_PACKET socket hands the filter packets that start at the IP header. Every
# other packet — the office's own HTTP between containers, the link's WireGuard, the edge's
# traffic — stays in the kernel, so the sniffer costs nothing on a busy box. (opcode, jt, jf, k)
BPF_DNS_SNI = [
    (0x30, 0, 0, 9),            # 0  ldb [9]               ip protocol
    (0x15, 0, 5, 17),           # 1  jeq #17  →2 : →7      udp?
    (0x28, 0, 0, 6),            # 2  ldh [6]               flags + fragment offset
    (0x45, 19, 0, 0x1FFF),      # 3  jset #0x1fff → drop   a fragment carries no header
    (0xB1, 0, 0, 0),            # 4  ldxb 4*([0]&0xf)      x = ip header length
    (0x48, 0, 0, 0),            # 5  ldh [x+0]             udp source port
    (0x15, 15, 16, 53),         # 6  jeq #53  → accept : drop
    (0x15, 0, 15, 6),           # 7  jeq #6   →8 : drop    tcp?
    (0x28, 0, 0, 6),            # 8  ldh [6]
    (0x45, 13, 0, 0x1FFF),      # 9  jset #0x1fff → drop
    (0xB1, 0, 0, 0),            # 10 ldxb 4*([0]&0xf)
    (0x48, 0, 0, 2),            # 11 ldh [x+2]             tcp destination port
    (0x15, 0, 10, 443),         # 12 jeq #443 →13 : drop
    (0x50, 0, 0, 12),           # 13 ldb [x+12]            data offset
    (0x54, 0, 0, 0xF0),         # 14 and #0xf0
    (0x74, 0, 0, 2),            # 15 rsh #2                = tcp header length
    (0x0C, 0, 0, 0),            # 16 add x
    (0x07, 0, 0, 0),            # 17 tax                   x = ip + tcp header length
    (0x50, 0, 0, 0),            # 18 ldb [x+0]             first payload byte
    (0x15, 0, 3, 0x16),         # 19 jeq #0x16 →20 : drop  a TLS handshake record
    (0x50, 0, 0, 5),            # 20 ldb [x+5]             handshake type
    (0x15, 0, 1, 1),            # 21 jeq #1 → accept : drop ClientHello
    (0x06, 0, 0, 0x40000),      # 22 accept (up to 256 KiB)
    (0x06, 0, 0, 0),            # 23 drop
]


def bpf_run(prog, pkt: bytes) -> int:
    """A classic-BPF interpreter for the instructions BPF_DNS_SNI uses — the self-test runs the very
    program the kernel gets against real packets, so a wrong jump offset fails here, not on a server."""
    a = x = 0
    pc = 0
    n = len(prog)
    while pc < n:
        code, jt, jf, k = prog[pc]
        pc += 1
        try:
            if code == 0x30:
                a = pkt[k]
            elif code == 0x28:
                a = struct.unpack_from(">H", pkt, k)[0]
            elif code == 0x20:
                a = struct.unpack_from(">I", pkt, k)[0]
            elif code == 0x50:
                a = pkt[x + k]
            elif code == 0x48:
                a = struct.unpack_from(">H", pkt, x + k)[0]
            elif code == 0xB1:
                x = 4 * (pkt[k] & 0x0F)
            elif code == 0x15:
                pc += jt if a == k else jf
            elif code == 0x45:
                pc += jt if a & k else jf
            elif code == 0x54:
                a &= k
            elif code == 0x74:
                a >>= k
            elif code == 0x0C:
                a = (a + x) & 0xFFFFFFFF
            elif code == 0x07:
                x = a
            elif code == 0x06:
                return k
            else:
                raise ValueError(f"opcode {code:#x} not in the interpreter")
        except (IndexError, struct.error):
            return 0                # the kernel returns 0 on a load past the packet's end
    return 0


# ── traefik access log ───────────────────────────────────────────────────────────────────────────
_CLF = re.compile(
    r'^(?P<ip>\S+)\s+-\s+(?P<user>\S+)\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>[^"]*?)\s+(?P<proto>[^"]+)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\d+|-)\s+'
    r'"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)"\s+'
    r'(?P<rcount>\d+)\s+"(?P<router>[^"]*)"\s+"(?P<svcurl>[^"]*)"\s+'
    r'(?P<dur>\d+)ms\s*$'
)


def clf_line(line: str) -> dict | None:
    """A traefik access-log line → {ts, ip, method, path, status, bytes, ms, ua, referer, router, host, user}.

    Reads both shapes traefik writes: the default common-log format (what every office runs today)
    and `--accesslog.format=json` (RequestHost and kept headers). `ts` is epoch seconds."""
    line = line.strip()
    if not line:
        return None
    if line[0] == "{":
        try:
            d = json.loads(line)
        except ValueError:
            return None
        if "ClientHost" not in d:
            return None
        ts = _iso_ts(d.get("StartUTC") or d.get("time"))
        return {
            "ts": ts, "ip": d.get("ClientHost") or "", "method": d.get("RequestMethod") or "",
            "path": (d.get("RequestPath") or "")[:400], "status": int(d.get("DownstreamStatus") or 0),
            "bytes": int(d.get("DownstreamContentSize") or 0), "ms": int((d.get("Duration") or 0) / 1e6),
            "ua": (d.get("request_User-Agent") or "")[:200], "referer": (d.get("request_Referer") or "")[:200],
            "router": d.get("RouterName") or "", "host": (d.get("RequestHost") or "").lower(),
            "user": d.get("request_X-Authentik-Username") or "",
        }
    m = _CLF.match(line)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("ts"), "%d/%b/%Y:%H:%M:%S %z").timestamp()
    except ValueError:
        return None
    user = m.group("user")
    return {
        "ts": ts, "ip": m.group("ip"), "method": m.group("method"), "path": m.group("path")[:400],
        "status": int(m.group("status")), "bytes": 0 if m.group("bytes") == "-" else int(m.group("bytes")),
        "ms": int(m.group("dur")), "ua": m.group("ua")[:200], "referer": m.group("referer")[:200],
        "router": m.group("router") if m.group("router") != "-" else "", "host": "",
        "user": "" if user == "-" else user,
    }


def _iso_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def docker_ts(prefix: str) -> float | None:
    """The RFC 3339 nano timestamp docker puts in front of a log line → epoch seconds."""
    try:
        base, _, frac = prefix.rstrip("Z").partition(".")
        t = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        return t + (float("0." + frac[:6]) if frac else 0.0)
    except ValueError:
        return None


# ── sshd ─────────────────────────────────────────────────────────────────────────────────────────
_SSH_RULES = [
    ("ok", re.compile(r"^Accepted (?P<how>\S+) for (?P<user>\S+) from (?P<ip>\S+) port \d+(?: ssh2(?:: (?P<keytype>\S+) (?P<fp>SHA256:\S+))?)?")),
    ("fail", re.compile(r"^Invalid user (?P<user>\S*) from (?P<ip>\S+) port \d+")),
    ("fail", re.compile(r"^Failed (?P<how>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+")),
    ("fail", re.compile(r"^Connection closed by (?:authenticating|invalid) user (?P<user>\S*) (?P<ip>\S+) port \d+ \[preauth\]")),
    ("fail", re.compile(r"^Disconnected from (?:authenticating|invalid) user (?P<user>\S*) (?P<ip>\S+) port \d+ \[preauth\]")),
    ("fail", re.compile(r"^banner exchange: Connection from (?P<ip>\S+) port \d+: invalid format")),
    ("fail", re.compile(r"^Unable to negotiate with (?P<ip>\S+) port \d+")),
    ("probe", re.compile(r"^Connection closed by (?P<ip>\S+) port \d+ \[preauth\]")),
    ("probe", re.compile(r"^Connection closed by (?P<ip>\S+) port \d+$")),
]


def sshd_message(msg: str) -> dict | None:
    for verdict, rx in _SSH_RULES:
        m = rx.match(msg.strip())
        if m:
            g = m.groupdict()
            ip = g.get("ip") or ""
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return None
            return {"verdict": verdict, "ip": ip, "user": g.get("user") or "", "how": g.get("how") or "",
                    "fp": g.get("fp") or ""}
    return None


# ── authentik ────────────────────────────────────────────────────────────────────────────────────
AUTH_ACTIONS = ("login", "login_failed", "logout", "suspicious_request")


def authentik_event(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{") or '"action"' not in line:
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    action = d.get("action")
    if action not in AUTH_ACTIONS:
        return None
    user = d.get("user") or {}
    ctx = d.get("context") or {}
    username = user.get("username") if isinstance(user, dict) else ""
    if not username and isinstance(ctx, dict):
        username = ctx.get("username") or ""
    return {"ts": _iso_ts(d.get("timestamp")), "action": action, "ip": d.get("client_ip") or "",
            "user": username or "", "how": (ctx.get("auth_method") if isinstance(ctx, dict) else "") or ""}


# ── forward-auth (r030-002) ──────────────────────────────────────────────────────────────────────
# Its own lines, one per event, the name and the address and never a password
# (platform-base/forward-auth/handlers.go, setup.go): `forward-auth: signed in: user="…" ip="…"`.
# Go's %q quotes both, so a value is a quoted string with backslash escapes.
_FA_EVENTS = (
    ("signed in:", "login", "password"),
    ("sign-in failed:", "login_failed", "password"),
    ("sign-in refused,", "login_failed", "blocked"),
    ("signed out:", "logout", ""),
    ("first-run setup done:", "login", "setup"),
    ("first-run setup refused,", "login_failed", "setup"),
)
_FA_FIELD = re.compile(r'\b(user|owner|ip)="((?:[^"\\]|\\.)*)"')


def forward_auth_event(line: str) -> dict | None:
    i = line.find("forward-auth: ")
    if i < 0:
        return None
    rest = line[i + len("forward-auth: "):]
    hit = next((e for e in _FA_EVENTS if rest.startswith(e[0])), None)
    if not hit:
        return None
    f = {k: v.replace('\\"', '"').replace("\\\\", "\\") for k, v in _FA_FIELD.findall(rest)}
    ip = f.get("ip") or ""
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    # no timestamp of its own here: the log's prefix is the container's local clock, and the caller
    # has the engine's own (docker's) for the line
    return {"ts": None, "action": hit[1], "ip": ip, "user": f.get("user") or f.get("owner") or "",
            "how": hit[2]}


# ── address classes ──────────────────────────────────────────────────────────────────────────────
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.version == 4 and a in _CGNAT:
        return False
    return a.is_global
